"""Named private profiles with validated imports and atomic, backed-up edits."""
from contextlib import contextmanager
from datetime import datetime
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit, parse_qs, unquote
import uuid
from paths import APP, CONFIG, PROFILES, HISTORY, SELECTION, binary, ensure


def profile_path(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
        raise ValueError('Use 1–64 letters, numbers, underscores or hyphens for the profile name.')
    p = PROFILES / (name + '.json')
    if p.is_symlink():
        raise ValueError('Symlink profiles are not supported.')
    return p


@contextmanager
def lock():
    ensure()
    with (CONFIG / 'profiles.lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def names():
    ensure()
    return sorted(p.stem for p in PROFILES.glob('*.json') if not p.is_symlink() and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', p.stem))


def selected():
    candidates = names()
    try:
        choice = json.loads(SELECTION.read_text())['profile']
    except (OSError, ValueError, KeyError):
        choice = ''
    return choice if choice in candidates else (candidates[0] if candidates else '')


def load(name):
    return json.loads(profile_path(name).read_text())


def outbound(data):
    if not isinstance(data, dict) or not isinstance(data.get('outbounds'), list):
        raise ValueError('Expected a complete sing-box configuration object.')
    candidates = [o for o in data.get('outbounds', []) if o.get('type') == 'vless']
    if len(candidates) != 1:
        raise ValueError('Import requires exactly one VLESS outbound. Selector/subscription bundles are not supported.')
    return candidates[0]


def normalize(data):
    # Only the remote connection is imported. Routing stays managed and IPv4-only.
    o = copy.deepcopy(outbound(data))
    if not o.get('server') or not 1 <= int(o.get('server_port', 0)) <= 65535:
        raise ValueError('A valid server and port are required.')
    uuid.UUID(o.get('uuid', ''))
    if not o.get('tls', {}).get('enabled'):
        raise ValueError('This manager requires TLS-enabled VLESS profiles.')
    if o.get('transport', {}).get('type', 'tcp') not in ('tcp', 'ws'):
        raise ValueError('Supported transports are TCP and WebSocket.')
    o['tag'] = 'vpn'
    o.pop('detour', None)
    o.pop('bind_interface', None)
    o.pop('routing_mark', None)
    o['domain_resolver'] = 'dns-direct'
    result = json.loads((APP / 'template.json').read_text())
    result['outbounds'].insert(0, o)
    result['dns']['strategy'] = 'ipv4_only'
    return result


def parse(source):
    source = source.strip()
    if not source.startswith('vless://'):
        if source.startswith('{'):
            return normalize(json.loads(source))
        p = Path(source).expanduser()
        if p.stat().st_size > 1024 * 1024:
            raise ValueError('Profile files must be under 1 MiB.')
        return normalize(json.loads(p.read_text()))
    u = urlsplit(source)
    q = parse_qs(u.query, keep_blank_values=True)
    allowed = {'encryption', 'security', 'sni', 'fp', 'type', 'host', 'path', 'allowInsecure', 'insecure', 'alpn', 'flow'}
    if set(q) - allowed or any(len(v) != 1 for v in q.values()):
        raise ValueError('Unsupported or repeated link options. Import a complete sing-box JSON file instead.')
    get = lambda key, default='': q.get(key, [default])[0]
    if get('encryption', 'none') != 'none' or get('security', 'tls') != 'tls' or get('type', 'tcp') not in ('tcp', 'ws'):
        raise ValueError('VLESS links must use TLS over TCP or WebSocket. Reality/subscriptions are not supported.')
    if not u.hostname or u.password:
        raise ValueError('Missing server or invalid VLESS credentials.')
    insecure = get('allowInsecure', get('insecure', 'false')).lower()
    if insecure not in ('0', '1', 'true', 'false'):
        raise ValueError('Invalid TLS verification flag.')
    tls = {'enabled': True, 'server_name': get('sni') or u.hostname, 'insecure': insecure in ('1', 'true')}
    if get('fp'):
        tls['utls'] = {'enabled': True, 'fingerprint': get('fp')}
    if get('alpn'):
        tls['alpn'] = get('alpn').split(',')
    o = {'type': 'vless', 'server': u.hostname, 'server_port': u.port or 443,
         'uuid': str(uuid.UUID(unquote(u.username or ''))), 'tls': tls}
    if get('flow'):
        o['flow'] = get('flow')
    if get('type') == 'ws':
        o['transport'] = {'type': 'ws', 'path': get('path') or '/'}
        if get('host'):
            o['transport']['headers'] = {'Host': get('host')}
    return normalize({'outbounds': [o]})


def validate(data):
    fd, tmp = tempfile.mkstemp(dir=CONFIG, suffix='.json')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
        r = subprocess.run([binary(), 'check', '-c', tmp], text=True, capture_output=True, timeout=15)
        if r.returncode:
            raise ValueError('sing-box rejected the profile. Existing settings were not changed.')
    finally:
        Path(tmp).unlink(missing_ok=True)


def backup(name, reason):
    target = HISTORY / (name + '--' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '--' + reason + '.json')
    shutil.copy2(profile_path(name), target)
    target.chmod(0o600)


def managed_requirements(data):
    if not isinstance(data, dict) or not isinstance(data.get('dns'), dict) or data.get('dns', {}).get('strategy') != 'ipv4_only':
        raise ValueError('Keep dns.strategy set to ipv4_only.')
    tun = [i for i in data.get('inbounds', []) if i.get('type') == 'tun']
    socks = [i for i in data.get('inbounds', []) if i.get('type') == 'socks']
    if (len(tun) != 1 or tun[0].get('interface_name') != 'singtun0'
            or any(':' in a for a in tun[0].get('address', []))
            or not all(tun[0].get(k) is True for k in ('auto_route', 'auto_redirect', 'strict_route'))):
        raise ValueError('Keep one IPv4-only singtun0 inbound with auto_route, auto_redirect and strict_route enabled.')
    if not any(i.get('listen') == '127.0.0.1' and i.get('listen_port') == 10808 for i in socks):
        raise ValueError('Keep the diagnostic SOCKS listener at 127.0.0.1:10808.')
    if data.get('route', {}).get('final') != 'vpn' or data.get('route', {}).get('auto_detect_interface') is not True:
        raise ValueError('Keep route.final set to vpn and auto_detect_interface enabled.')
    if outbound(data).get('tag') != 'vpn':
        raise ValueError('Keep the VLESS outbound tag set to vpn.')


def save(name, data, new=False, raw=False):
    p = profile_path(name)
    if new and p.exists():
        raise ValueError('A profile with that name already exists.')
    if raw:
        managed_requirements(data)
    else:
        data = normalize(data)
    validate(data)
    if p.exists():
        backup(name, 'edit')
    atomic(p, data)
    if not selected():
        atomic(SELECTION, {'profile': name})
    return name


def details(name):
    o = outbound(load(name))
    return {'name': name, 'server': o['server'], 'port': str(o['server_port']),
            'sni': o.get('tls', {}).get('server_name', ''),
            'transport': o.get('transport', {}).get('type', 'tcp'),
            'ws_host': o.get('transport', {}).get('headers', {}).get('Host', ''),
            'ws_path': o.get('transport', {}).get('path', '/'),
            'tls_verify': not o.get('tls', {}).get('insecure', False), 'uuid': ''}


def json_details(name):
    data = profile_path(name).read_bytes()
    return {'name': name, 'content': data.decode(), 'revision': hashlib.sha256(data).hexdigest()}


def edit(name, values):
    d = load(name); o = outbound(d)
    allowed = {'name', 'server', 'port', 'sni', 'transport', 'ws_host', 'ws_path', 'tls_verify', 'uuid'}
    if set(values) - allowed or values.get('name', name) != name:
        raise ValueError('Unexpected profile settings.')
    for key in ('server', 'sni', 'ws_host'):
        if not isinstance(values[key], str) or not re.fullmatch(r'[A-Za-z0-9_.:\[\]-]{0,253}', values[key]):
            raise ValueError('Invalid ' + key)
    o['server'], o['server_port'] = values['server'], int(values['port'])
    o['tls']['server_name'] = values['sni']
    if not isinstance(values['tls_verify'], bool):
        raise ValueError('TLS verification must be on or off.')
    o['tls']['insecure'] = not values['tls_verify']
    if values.get('uuid'):
        o['uuid'] = str(uuid.UUID(values['uuid']))
    transport = values['transport']
    if transport not in ('tcp', 'ws'):
        raise ValueError('Transport must be TCP or WebSocket.')
    if transport == 'ws':
        if not values['ws_path'].startswith('/'):
            raise ValueError('WebSocket path must start with /.')
        if o.get('transport', {}).get('type') != 'ws':
            o['transport'] = {'type': 'ws'}
        o['transport']['path'] = values['ws_path']
        headers = o['transport'].setdefault('headers', {})
        headers.pop('Host', None); headers.pop('host', None)
        if values['ws_host']:
            headers['Host'] = values['ws_host']
    else:
        o.pop('transport', None)
    save(name, d, raw=True)


def manage(operation, name, value=None, active=''):
    with lock():
        if operation == 'add':
            save(name, parse(value), new=True)
        elif operation == 'select':
            load(name)
            atomic(SELECTION, {'profile': name})
        elif operation == 'duplicate':
            save(value, load(name), new=True)
        elif operation == 'delete':
            if name == active:
                raise ValueError('Disconnect this profile before deleting it.')
            if len(names()) <= 1:
                raise ValueError('Keep at least one profile; add another before deleting this one.')
            load(name); backup(name, 'delete'); profile_path(name).unlink()
            atomic(SELECTION, {'profile': selected()})
        elif operation == 'edit':
            edit(name, value)
        elif operation == 'edit-json':
            current = json_details(name)
            if current['revision'] != value.get('revision'):
                raise ValueError('Profile changed since the editor opened. Reopen it before saving.')
            try:
                data = json.loads(value['content'])
            except json.JSONDecodeError as exc:
                raise ValueError(f'Invalid JSON at line {exc.lineno}, column {exc.colno}. Profile unchanged.') from None
            save(name, data, raw=True)
        elif operation == 'rename':
            if name == active:
                raise ValueError('Disconnect this profile before renaming it.')
            was_selected = selected() == name
            save(value, load(name), new=True)
            backup(name, 'rename'); profile_path(name).unlink()
            if was_selected:
                atomic(SELECTION, {'profile': value})
        else:
            raise ValueError('Unknown profile operation.')
    return {'ok': True, 'message': 'Saved. Connection changes apply the next time you connect.'}
