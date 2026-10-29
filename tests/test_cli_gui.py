from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cli


class GuiRouting(unittest.TestCase):
    def test_dux_uses_gtk_manager(self):
        with patch.object(cli, 'dux_running', return_value=True), \
             patch.object(cli.subprocess, 'call', return_value=0) as call:
            self.assertEqual(cli.open_gui('settings'), 0)
            self.assertEqual(call.call_args.args[0][-2:], ['--page', 'settings'])
            self.assertTrue(call.call_args.args[0][1].endswith('gui.py'))

    def test_noctalia_unavailable_falls_back_to_gtk(self):
        with patch.object(cli, 'dux_running', return_value=False), \
             patch.object(cli.shutil, 'which', return_value='/usr/bin/noctalia'), \
             patch.object(cli.subprocess, 'run') as run, \
             patch.object(cli.subprocess, 'call', return_value=0) as call:
            run.return_value.returncode = 1
            self.assertEqual(cli.open_gui(), 0)
            self.assertTrue(call.call_args.args[0][1].endswith('gui.py'))


if __name__ == '__main__':
    unittest.main()
