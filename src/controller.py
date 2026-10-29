#!/usr/bin/env python3
"""Unprivileged CLI used by the native Noctalia VPN panel."""
import datetime
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess as sp
import sys
import tempfile
import time

from paths import APP, CONFIG, PROFILES, LOGS, UNIT, binary, ensure
import profiles
import updates
BASE = CONFIG
UNIT = 'raze-vpn.service'
HELPER = '/usr/local/libexec/raze-vpn-control'
CACHE = LOGS / 'ui-check.json'
PREFS = CONFIG / 'ui.json'
BAR_LABELS = ('icon', 'vpn', 'profile')


def run(args, **kwargs):
    return sp.run(args, text=True, capture_output=True, timeout=kwargs.pop('timeout', 8), **kwargs)


def unit_state():
    r = run(['systemctl', 'show', UNIT, '-p', 'ActiveState,MainPID,ActiveEnterTimestampMonotonic,InvocationID,Description'])
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or 'Cannot read VPN service state')
    return dict(line.split('=', 1) for line in r.stdout.splitlines() if '=' in line)


def ui_prefs(path=None):
    try:
        value = json.loads((path or PREFS).read_text()).get('bar_label')
    except (OSError, ValueError, AttributeError):
        value = None
    return {'bar_label': value if value in BAR_LABELS else 'vpn'}


def set_ui_prefs(req, path=None):
    value = req.get('bar_label') if isinstance(req, dict) else None
    if value not in BAR_LABELS:
        raise ValueError('Unknown top-bar label option.')
    write_private(path or PREFS, {'bar_label': value})
    return {'ok': True, 'bar_label': value, 'message': 'Top bar label updated.'}


def snapshot():
    s = unit_state()
    active = s.get('ActiveState') == 'active'
    tun = Path('/sys/class/net/singtun0').exists()
    ipv6 = Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').read_text().strip() == '1'
    invocation = s.get('InvocationID', '')
    result = {'active': active or tun, 'managed': active, 'tun': tun,
              'state': s.get('ActiveState', 'inactive'), 'ipv6_disabled': ipv6,
              'machine': socket.gethostname(), 'profile': profiles.selected(),
              'profiles': profiles.names(), 'active_profile': s.get('Description', '').removeprefix('VPN profile: ') if active else '',
              'installed': Path(HELPER).exists(), 'pid': s.get('MainPID', '0'),
              'invocation': invocation, 'check': None, 'bar_label': ui_prefs()['bar_label']}
    choice = result['active_profile'] if active else result['profile']
    if choice and choice in profiles.names():
        outbound = profiles.outbound(profiles.load(choice))
        result['server'] = f"{outbound['server']}:{outbound['server_port']}"
    else:
        result['server'] = 'No profile selected'
    result['uptime'] = max(0, int(time.monotonic() - int(s.get('ActiveEnterTimestampMonotonic', '0')) / 1e6)) if active else 0
    if CACHE.exists():
        check = json.loads(CACHE.read_text())
        if (time.time() - check.get('checked_at', 0) < 60
                and check.get('invocation') == invocation
                and check.get('active') == result['active']):
            result['check'] = check
    return result


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def check():
    before = snapshot()
    start = time.monotonic()
    r = run(['curl', '-4', '--noproxy', '*', '-sS', '--connect-timeout', '4', '--max-time', '6',
             'https://www.cloudflare.com/cdn-cgi/trace'], timeout=8)
    fields = dict(line.split('=', 1) for line in r.stdout.splitlines() if '=' in line)
    if r.returncode or not fields.get('ip'):
        r = run(['curl', '-4', '--noproxy', '*', '-sS', '--connect-timeout', '4', '--max-time', '6',
                 'https://api.ipify.org'], timeout=8)
        fields = {'ip': r.stdout.strip(), 'loc': ''}
    try:
        ipaddress.ip_address(fields.get('ip', ''))
        ok = r.returncode == 0
    except ValueError:
        ok = False
    ip_available = ok
    if not ok:
        # A blocked IP-discovery provider must not imply all HTTPS is broken.
        r = run(['curl', '-4', '--noproxy', '*', '-sS', '--connect-timeout', '4', '--max-time', '6',
                 '-o', '/dev/null', '-w', '%{http_code}', 'https://example.com'], timeout=8)
        ok = r.returncode == 0 and r.stdout.strip() == '200'
        fields = {'ip': '', 'loc': ''}
    after = snapshot()
    ok = ok and before['active'] == after['active'] and before['invocation'] == after['invocation']
    result = {'ok': ok, 'ip': fields.get('ip', ''), 'country': fields.get('loc', ''),
              'ip_available': ip_available and ok,
              'latency_ms': round((time.monotonic() - start) * 1000),
              'error': '' if ok else (r.stderr.strip() or 'Connection changed or HTTPS check failed'),
              'active': after['active'], 'invocation': after['invocation'], 'checked_at': time.time()}
    write_private(CACHE, result)
    return result


def control(action):
    if not Path(HELPER).exists():
        raise RuntimeError('Install the VPN control helper first.')
    import auth_broker
    result = auth_broker.request([action] if action == 'stop' else [action, profiles.selected()])
    if result['returncode']:
        raise RuntimeError(result['stderr'].strip() or 'Authorization canceled or VPN operation failed')
    CACHE.unlink(missing_ok=True)
    if action in ('start', 'test'):
        time.sleep(0.8)
        if not snapshot()['active']:
            raise RuntimeError('VPN exited during startup. Open Logs for the cause.')
        # Independent worker: diagnostics survive the panel/chat closing.
        logs = LOGS; logs.mkdir(mode=0o700, exist_ok=True)
        log = logs / ('ui-session-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
        with log.open('w') as out:
            sp.Popen([sys.executable, str(Path(__file__).resolve()), 'session-worker'],
                     stdin=sp.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    return {'ok': True, 'message': result['stdout'].strip()}


def logs_text():
    journal = run(['journalctl', '-u', UNIT, '-n', '100', '--no-pager', '-o', 'short-iso'], timeout=10)
    chunks = ['raze VPN service\n' + (journal.stdout.strip() or journal.stderr.strip())]
    for name in ('sing-box-latest.log', 'latest.log'):
        p = LOGS / name
        if p.exists():
            chunks.append('\n' + str(p) + '\n' + '\n'.join(p.read_text(errors='replace').splitlines()[-45:]))
    return re.sub(r'\x1b\[[0-9;]*m', '', '\n'.join(chunks))[-24000:]


def read_request(filename):
    p = Path(filename)
    info = p.lstat()
    import stat
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1024 * 1024:
        raise ValueError('Requests must be private files owned by your account, under 1 MiB.')
    try:
        return json.loads(p.read_text())
    finally:
        p.unlink(missing_ok=True)


def session_worker():
    print('Started:', datetime.datetime.now().astimezone().isoformat(), flush=True)
    sp.run(['bash', str(APP / 'check-connectivity.sh')], check=False)
    print(logs_text(), flush=True)


def main():
    os.umask(0o077)
    ensure()
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if action == 'status': result = snapshot()
    elif action == 'check': result = check()
    elif action in ('start', 'stop', 'test'): result = control(action)
    elif action == 'restart':
        # Apply a newly selected profile: stop, then start (polkit keeps the authorization briefly).
        if snapshot()['active']: control('stop'); time.sleep(0.6)
        result = control('start')
    elif action == 'logs': print(logs_text()); return
    elif action == 'settings': result = profiles.details(profiles.selected())
    elif action == 'json-settings': result = profiles.json_details(profiles.selected())
    elif action == 'updates': result = updates.status()
    elif action == 'launch-update': result = updates.launch()
    elif action == 'profile-request':
        req = read_request(sys.argv[2]); current = snapshot()
        result = profiles.manage(req['operation'], req['name'], req.get('value'), active=current['active_profile'])
    elif action == 'save-settings':
        req = read_request(sys.argv[2])
        result = profiles.manage('edit', req['name'], req)
    elif action == 'set-ui': result = set_ui_prefs(read_request(sys.argv[2]))
    elif action == 'session-worker': session_worker(); return
    else: raise RuntimeError('Unknown command')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError, StopIteration, sp.TimeoutExpired) as exc:
        print(json.dumps({'ok': False, 'error': 'Invalid profile JSON or request.' if isinstance(exc, json.JSONDecodeError) else str(exc)}))
        sys.exit(1)
