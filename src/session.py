#!/usr/bin/env python3
"""Root supervisor: save/restore IPv6 and run the network client without root."""
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys

SYSCTL = Path('/proc/sys/net/ipv6/conf')
RUNTIME = Path('/run/raze-vpn')
child = None
interrupted = False


def stop(signum, frame):
    global interrupted
    interrupted = True
    if child is not None and child.poll() is None:
        child.send_signal(signum)


def restore(saved):
    failures = []
    for name in sorted(saved, key=lambda n: (n not in ('all', 'default'), n)):
        if '/' in name or name in ('.', '..') or saved[name] not in ('0', '1'):
            raise RuntimeError('Invalid saved IPv6 state.')
        p = SYSCTL / name / 'disable_ipv6'
        if p.exists():
            try:
                p.write_text(saved[name])
            except OSError as exc:
                failures.append(str(exc))
    if failures:
        raise RuntimeError('Could not restore IPv6: ' + '; '.join(failures))
    print('Previous IPv6 settings restored.', flush=True)


def main():
    global child
    os.umask(0o077)
    if os.geteuid() != 0:
        sys.exit('Use the VPN panel or vpn start.')
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    info = RUNTIME.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        sys.exit('Unsafe VPN runtime directory.')
    fd = os.open(RUNTIME / 'session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('A VPN session is already running.')
        state = RUNTIME / 'ipv6-state.json'
        if state.exists():
            restore(json.loads(state.read_text()))
            state.unlink()
        if sys.argv[1:] == ['--restore']:
            return 0
        if len(sys.argv) != 5:
            sys.exit('Expected configuration, binary, user ID and group ID.')
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, stop)
        saved = {p.parent.name: p.read_text().strip() for p in SYSCTL.glob('*/disable_ipv6')}
        if not saved:
            sys.exit('Cannot read IPv6 settings; VPN was not started.')
        # This root-only recovery record also handles a previous forced termination.
        fd = os.open(state, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(saved, f)
            f.flush()
            os.fsync(f.fileno())
        status = 1
        try:
            for name in ('default', 'all'):
                (SYSCTL / name / 'disable_ipv6').write_text('1')
            print('IPv6 disabled for VPN session.', flush=True)
            if not interrupted:
                command = ['/usr/bin/setpriv', '--reuid=' + str(int(sys.argv[3])), '--regid=' + str(int(sys.argv[4])),
                           '--init-groups', '--inh-caps=+net_admin,+net_raw', '--ambient-caps=+net_admin,+net_raw',
                           '--bounding-set=-all,+net_admin,+net_raw', '--no-new-privs',
                           sys.argv[2], 'run', '-c', sys.argv[1]]
                child = subprocess.Popen(command, start_new_session=True)
                if interrupted:
                    child.terminate()
                status = child.wait()
        finally:
            restore(saved)
            state.unlink()
        return status if status >= 0 else 128 - status


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print('VPN session: ' + str(exc), file=sys.stderr)
        sys.exit(1)
