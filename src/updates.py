"""Local-source updates: no invented release server or automatic git pulls."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from paths import STATE


def fingerprint(project):
    digest = hashlib.sha256()
    files = [project/'setup.sh', project/'VERSION']
    for folder in ('src', 'plugin', 'dux-plugin', 'installer'):
        files.extend(p for p in (project/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    for p in sorted(files):
        digest.update(str(p.relative_to(project)).encode()+b'\0'+p.read_bytes()+b'\0')
    return digest.hexdigest()


def status(source=None):
    try: installed=json.loads((STATE/'install.json').read_text())
    except (OSError, ValueError):installed={}
    project=Path(source or installed.get('source', Path.home()/'Projects/tools/raze-vpn')).expanduser().resolve()
    available=(project/'setup.sh').is_file() and (project/'VERSION').is_file()
    source_version=(project/'VERSION').read_text().strip() if available else ''
    return {'installed_version':installed.get('version','unknown'), 'source_version':source_version,
            'source':str(project), 'available':available,
            'update_available':available and fingerprint(project)!=installed.get('fingerprint')}


def launch():
    info=status()
    if not info['available']:
        raise RuntimeError('Project source is missing. Use vpn update /path/to/raze-vpn.')
    setup=str(Path(info['source'])/'setup.sh')
    if shutil.which('kitty'):args=['kitty','--title','raze VPN update','bash',setup]
    elif shutil.which('alacritty'):args=['alacritty','-e','bash',setup]
    elif shutil.which('xterm'):args=['xterm','-e','bash',setup]
    else:raise RuntimeError('No supported terminal found. Run vpn update in your terminal.')
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {'ok':True,'message':'Updater opened in a terminal. Profiles are preserved.'}
