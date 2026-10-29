import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import updates


class Updates(unittest.TestCase):
    def test_source_changes_detected_without_version_bump(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);project=root/'project';state=root/'state';project.mkdir();state.mkdir()
            (project/'VERSION').write_text('1.1.0');(project/'setup.sh').write_text('true')
            for name in ['src','plugin','installer']:(project/name).mkdir()
            (project/'src/code.py').write_text('first')
            stamp=updates.fingerprint(project)
            (state/'install.json').write_text(json.dumps({'source':str(project),'version':'1.1.0','fingerprint':stamp}))
            with patch.object(updates,'STATE',state):
                self.assertFalse(updates.status()['update_available'])
                (project/'src/code.py').write_text('second')
                self.assertTrue(updates.status()['update_available'])
                self.assertFalse(updates.status(root/'missing')['available'])

    def test_profile_and_log_changes_do_not_trigger_code_updates(self):
        project=Path(__file__).resolve().parents[1]
        stamp=updates.fingerprint(project)
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'profile.json').write_text('{"secret":"test"}')
            self.assertEqual(updates.fingerprint(project),stamp)


if __name__=='__main__':unittest.main()
