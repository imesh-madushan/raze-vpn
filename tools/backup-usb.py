#!/usr/bin/env python3
"""Copy the verified source project into a mounted drive's PROJECTS."""
import argparse
from datetime import datetime
import filecmp
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT=Path(__file__).resolve().parents[1]
ROOT_FILES=('README.md','LICENSE','VERSION','setup.sh','.gitignore')
EXTENSIONS={
    'src':{'.py','.json','.sh'},
    'plugin':{'.luau','.toml'},
    'dux-plugin':{'.qml','.json'},
    'installer':{'.py','.in','.policy'},
    'tests':{'.py'},
    'tools':{'.py'},
}


def source_files():
    """Production source only; never user profiles, logs or caches."""
    files=[PROJECT/name for name in ROOT_FILES if (PROJECT/name).is_file()]
    for folder,suffixes in EXTENSIONS.items():
        files+=[p for p in (PROJECT/folder).rglob('*') if p.is_file() and not p.is_symlink()
                and '__pycache__' not in p.parts and p.suffix in suffixes]
    return sorted(files)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mount',help='Mounted USB directory, as shown by the file manager')
    args=parser.parse_args()
    volume=Path(args.mount).expanduser().resolve()
    if not volume.is_mount() or volume in (Path('/'),Path.home()):
        sys.exit('The USB must be mounted. Refusing to write to an ordinary directory or system root.')
    destdir=volume/'PROJECTS';destdir.mkdir(exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    staging=destdir/('.raze-vpn-copy-'+stamp)
    target=destdir/'raze-vpn'
    try:
        staging.mkdir()
        for source in source_files():
            relative=source.relative_to(PROJECT)
            dest=staging/relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
            if not filecmp.cmp(source,dest,shallow=False):
                raise RuntimeError('Copy verification failed: '+str(relative))
        if target.exists():
            previous=destdir/('raze-vpn-previous-'+stamp)
            target.rename(previous)
            print('Previous project retained:',previous)
        staging.rename(target)
        subprocess.run(['sync','-f',str(target)],check=True)
    finally:
        if staging.exists():shutil.rmtree(staging)
    print('Copied and verified:',target)


if __name__=='__main__':main()
