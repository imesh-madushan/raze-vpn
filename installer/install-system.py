#!/usr/bin/env python3
"""Install the fixed VPN control helper and its scoped Polkit action."""
from pathlib import Path
import datetime
import os
import pwd
import shutil
import sys
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent


def main():
    if os.geteuid() != 0:
        sys.exit('Run with pkexec or sudo.')
    uid = int(os.environ.get('PKEXEC_UID', os.environ.get('SUDO_UID', '-1')))
    if uid <= 0:
        sys.exit('Run from the account that will control the VPN.')
    user = pwd.getpwuid(uid)
    home = Path(user.pw_dir)
    template = (BASE / 'vpn-control.py.in').read_text()
    control = template.replace('@ACCOUNT@', repr(user.pw_name)).replace('@UID@', str(uid)).replace('@HOME@', repr(str(home))).replace('@GID@', str(user.pw_gid)).replace('@CONFIG@', repr(str(home / '.config/raze-vpn'))).replace('@BINARY@', repr('/usr/bin/sing-box'))
    session = (BASE.parent / 'src/session.py').read_text()
    policy = (BASE / 'dev.raze.vpn.control.policy').read_text()
    compile(control, 'vpn-control', 'exec')
    compile(session, 'vpn-session', 'exec')
    ET.fromstring(policy)
    targets = {
        Path('/usr/local/libexec/raze-vpn-control'): (control, 0o755),
        Path('/usr/local/libexec/raze-vpn-session.py'): (session, 0o644),
        Path('/usr/share/polkit-1/actions/dev.raze.vpn.control.policy'): (policy, 0o644),
    }
    if not Path('/usr/bin/sing-box').is_file():
        sys.exit('Install the sing-box package before installing system controls.')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    for dest, (content, mode) in targets.items():
        if dest.is_symlink():
            sys.exit('Refusing symlink destination: ' + str(dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.copy2(dest, dest.with_name(dest.name + '.bak-' + stamp))
        tmp = dest.with_name(dest.name + '.new-' + stamp)
        with tmp.open('x') as f:
            f.write(content)
        tmp.chmod(mode)
        os.chown(tmp, 0, 0)
        tmp.replace(dest)
        print('Installed:', dest)
    print('Control installed. No VPN connection or boot service was started.')


if __name__ == '__main__':
    main()
