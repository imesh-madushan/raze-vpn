"""All writable data follows the current Linux account's XDG directories."""
import os
from pathlib import Path

APP = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'raze-vpn'
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'raze-vpn'
PROFILES = CONFIG / 'profiles'
HISTORY = CONFIG / 'backups'
LOGS = STATE / 'logs'
SELECTION = CONFIG / 'selection.json'
UNIT = 'raze-vpn.service'


def ensure():
    for directory in (CONFIG, STATE, PROFILES, HISTORY, LOGS):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)


def binary():
    import shutil
    found = shutil.which('sing-box')
    if not found:
        raise RuntimeError('sing-box is missing. Run setup.sh to install dependencies.')
    return found
