#!/usr/bin/env python3
"""Install this project's application, profiles and native shell plugin."""
from pathlib import Path
import datetime
import json
import os
import shutil
import subprocess as sp
import sys
import tomllib

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / 'src'))
from paths import CONFIG, PROFILES, LOGS, SELECTION, ensure
import profiles
import updates


def install():
    if os.geteuid() == 0:
        sys.exit('Run setup.sh as your normal desktop account, not with sudo.')
    os.umask(0o077)
    ensure()
    app = Path.home() / '.local/share/raze-vpn/app'
    app.mkdir(parents=True, exist_ok=True, mode=0o700)
    for p in (PROJECT / 'src').iterdir():
        if p.is_file():
            shutil.copy2(p, app / p.name)
    plugin = Path.home() / '.local/share/noctalia/plugins/raze-vpn'
    shutil.copytree(PROJECT / 'plugin', plugin, dirs_exist_ok=True)
    if shutil.which('dms') or (Path.home() / '.config/dms').exists():
        dux = Path.home() / '.config/dms'
        dux_plugin = dux / 'plugins/razeVpn'
        dux_plugin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(PROJECT / 'dux-plugin', dux_plugin, dirs_exist_ok=True)
        settings = dux / 'settings.json'
        if settings.exists():
            data = json.loads(settings.read_text())
            changed = False
            for bar in data.get('barConfigs', []):
                if not bar.get('enabled', True):
                    continue
                widgets = bar.get('rightWidgets', [])
                if not any((item == 'razeVpn' or
                            isinstance(item, dict) and item.get('id') == 'razeVpn') for item in widgets):
                    index = next((i for i, item in enumerate(widgets) if
                                  item == 'controlCenterButton' or
                                  isinstance(item, dict) and item.get('id') == 'controlCenterButton'), len(widgets))
                    widgets.insert(index, {'id': 'razeVpn', 'enabled': True})
                    bar['rightWidgets'] = widgets
                    changed = True
            if changed:
                history = CONFIG / 'backups/dms'
                history.mkdir(parents=True, exist_ok=True)
                shutil.copy2(settings, history / ('settings-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.json'))
                temporary = settings.with_name('settings.vpn-new.json')
                temporary.write_text(json.dumps(data, indent=2) + '\n')
                os.replace(temporary, settings)
    localbin = Path.home() / '.local/bin'; localbin.mkdir(parents=True, exist_ok=True)
    command = localbin / 'vpn'
    if command.exists() and 'raze-vpn' not in command.read_text(errors='replace'):
        shutil.copy2(command, command.with_name('vpn.before-raze-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
    command.write_text('#!/usr/bin/env bash\nexec python3 "$HOME/.local/share/raze-vpn/app/cli.py" "$@"\n')
    command.chmod(0o700)
    config = Path.home() / '.config/noctalia/config.toml'
    if config.exists() and shutil.which('noctalia'):
        import re
        original = config.read_text(); data = tomllib.loads(original); content = original
        entries = data.get('bar', {}).get('default', {}).get('end', [])
        if 'raze_vpn' not in entries:
            entries.insert(entries.index('network') if 'network' in entries else len(entries), 'raze_vpn')
            start = content.index('[bar.default]'); end = content.find('\n[', start + 1)
            if end < 0: end = len(content)
            block = re.sub(r'^end\s*=.*$', 'end = ' + json.dumps(entries), content[start:end], count=1, flags=re.M)
            content = content[:start] + block + content[end:]
        if 'raze_vpn' not in data.get('widget', {}):
            content += '\n[widget.raze_vpn]\ntype = "raze/vpn:status"\ncapsule = true\ncapsule_fill = "surface_variant"\n'
        if content != original:
            history = CONFIG / 'backups/noctalia';history.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config, history / ('config-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.toml'))
            temp = config.with_name('config.vpn-new.toml');temp.write_text(content)
            sp.run(['noctalia', 'config', 'validate', str(temp)], check=True)
            os.replace(temp, config)
    print('Application:', app)
    if shutil.which('dms'):
        print('Dux plugin:', Path.home() / '.config/dms/plugins/razeVpn')
    print('Profiles:', PROFILES)
    print('Logs:', LOGS)
    # Written only after the complete system installation succeeds by setup.sh.
    if '--record' in sys.argv:
        from paths import STATE
        profiles.atomic(STATE / 'install.json', {'source':str(PROJECT),'version':(PROJECT/'VERSION').read_text().strip(),'fingerprint':updates.fingerprint(PROJECT)})


if __name__ == '__main__':
    install()
