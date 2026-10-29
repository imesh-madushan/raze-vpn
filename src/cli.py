#!/usr/bin/env python3
"""Human-facing CLI; the panel uses controller.py's JSON API."""
import argparse
import getpass
import json
import shutil
import subprocess
import sys
from pathlib import Path
from paths import APP, ensure
import controller
import profiles
import updates


def dux_running():
    if not shutil.which('dms'):
        return False
    try:
        result = subprocess.run(['dms', 'ipc', 'call', 'plugins', 'list'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def open_gui(page='main'):
    # The Dux plugin and the GTK manager share this backend. The GTK window
    # also works on desktops without either shell running.
    if dux_running():
        return subprocess.call([sys.executable, str(APP / 'gui.py'), '--page', page])
    if shutil.which('noctalia'):
        action = 'panel-toggle' if page == 'main' else 'panel-open'
        result = subprocess.run(['noctalia', 'msg', action, 'raze/vpn:panel'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            if page == 'settings':
                subprocess.run(['noctalia', 'msg', 'plugin', 'raze/vpn:panel', 'all', 'settings'],
                               check=True)
            return 0
    return subprocess.call([sys.executable, str(APP / 'gui.py'), '--page', page])


def main():
    parser = argparse.ArgumentParser(description='raze VPN manager')
    parser.add_argument('command', nargs='?', default='gui', choices=['gui','status','start','stop','check','logs','list','add','select','duplicate','rename','delete','edit','edit-json','diagnose','update'])
    parser.add_argument('name', nargs='?')
    parser.add_argument('value', nargs='?')
    parser.add_argument('--check', action='store_true', help='Check for local-source updates without installing')
    parser.add_argument('--json', action='store_true', help='Print status as JSON')
    args = parser.parse_args()
    ensure()
    if args.command == 'gui':
        return open_gui()
    if args.command == 'update':
        info=updates.status(args.name)
        if args.check: print(json.dumps(info, indent=2));return 0
        if not info['available']:raise RuntimeError('Source missing. Use vpn update /path/to/project.')
        return subprocess.call(['bash',str(Path(info['source'])/'setup.sh')])
    if args.command == 'edit-json':
        import os,shlex,tempfile
        name=args.name or profiles.selected();data=profiles.json_details(name)
        fd,tmp=tempfile.mkstemp(suffix='.json');os.fchmod(fd,0o600)
        try:
            with os.fdopen(fd,'w') as f:f.write(data['content'])
            editor=shlex.split(os.environ.get('EDITOR','nano'))
            if not editor or subprocess.call(editor+[tmp]):raise RuntimeError('Editor canceled.')
            data['content']=Path(tmp).read_text()
            print(profiles.manage('edit-json',name,data)['message'])
        finally:Path(tmp).unlink(missing_ok=True)
        return 0
    if args.command == 'list':
        for name in profiles.names(): print(('* ' if name == profiles.selected() else '  ') + name)
    elif args.command in ('start','stop'):
        if args.command == 'start' and args.name: profiles.manage('select', args.name)
        print(controller.control(args.command)['message'])
    elif args.command == 'status':
        s = controller.snapshot()
        if args.json:
            print(json.dumps(s))
            return 0
        print(('Connected' if s['active'] else 'Disconnected') + ' · ' + s['machine'])
        print('Selected:', s['profile'] or '(none)')
        if s['active']: print('Connected profile:', s['active_profile'] or '(terminal session)')
        print('IPv6:', 'disabled' if s['ipv6_disabled'] else 'enabled')
    elif args.command == 'check': print(json.dumps(controller.check(), indent=2))
    elif args.command == 'logs': print(controller.logs_text())
    elif args.command == 'diagnose': return subprocess.call(['bash', str(APP / 'check-connectivity.sh')])
    elif args.command == 'edit':
        if args.name: profiles.manage('select', args.name)
        return open_gui('settings')
    else:
        if not args.name: parser.error('This command needs a profile name.')
        value = args.value
        if args.command == 'add':
            # Secret links are read without echo; never pass them on the command line.
            value = value or getpass.getpass('VLESS link or JSON file path: ')
        if args.command == 'delete' and input('Type ' + args.name + ' to delete it: ') != args.name:
            print('Canceled.'); return 0
        s = controller.snapshot()
        print(profiles.manage(args.command, args.name, value, active=s['active_profile'])['message'])
    return 0


if __name__ == '__main__':
    try: sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('VPN:', str(exc), file=sys.stderr);sys.exit(1)
