from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import controller


class UiPrefs(unittest.TestCase):
    def test_default_is_vpn_label(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(controller.ui_prefs(Path(d)/'ui.json'),{'bar_label':'vpn'})

    def test_round_trip_and_private_mode(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'sub'/'ui.json'
            for choice in ('icon','profile','vpn'):
                self.assertTrue(controller.set_ui_prefs({'bar_label':choice},path)['ok'])
                self.assertEqual(controller.ui_prefs(path)['bar_label'],choice)
            self.assertEqual(path.stat().st_mode&0o077,0)

    def test_invalid_values_rejected_and_corrupt_file_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ui.json'
            for bad in ({'bar_label':'huge'},{},None,'icon'):
                with self.assertRaises(ValueError):controller.set_ui_prefs(bad,path)
            path.write_text('{not json')
            self.assertEqual(controller.ui_prefs(path)['bar_label'],'vpn')


if __name__=='__main__':unittest.main()
