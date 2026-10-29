import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class Installation(unittest.TestCase):
    def test_reinstall_preserves_existing_profile_and_selection(self):
        project=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            env=dict(os.environ,HOME=d,XDG_CONFIG_HOME=d+'/.config',XDG_STATE_HOME=d+'/.local/state')
            dms=Path(d)/'.config/dms'
            dms.mkdir(parents=True)
            settings=dms/'settings.json'
            settings.write_text(json.dumps({'barConfigs':[{'id':'default','enabled':True,
                'rightWidgets':['systemTray','controlCenterButton']}]})+'\n')
            command=['python3',str(project/'installer/install-user.py')]
            subprocess.run(command,env=env,check=True,stdout=subprocess.DEVNULL)
            profiles=Path(d)/'.config/raze-vpn/profiles'
            self.assertEqual(list(profiles.glob('*.json')), [])
            # An installed custom profile is user data, not part of the app update.
            custom=profiles/'my-custom-profile.json'
            custom.write_text('{"fixture":"test-only"}')
            selection=profiles.parent/'selection.json'
            selection.write_text('{"profile":"my-custom-profile"}')
            before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in profiles.glob('*.json')}
            subprocess.run(command,env=env,check=True,stdout=subprocess.DEVNULL)
            after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in profiles.glob('*.json')}
            self.assertEqual(before,after)
            self.assertEqual(selection.read_text(),'{"profile":"my-custom-profile"}')
            self.assertEqual(profiles.stat().st_mode&0o777,0o700)
            self.assertTrue((dms/'plugins/razeVpn/plugin.json').is_file())
            widgets=json.loads(settings.read_text())['barConfigs'][0]['rightWidgets']
            self.assertEqual(sum(item.get('id')=='razeVpn' for item in widgets if isinstance(item,dict)),1)
            self.assertEqual(widgets[-1],'controlCenterButton')


if __name__=='__main__':unittest.main()
