from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import controller


class Connectivity(unittest.TestCase):
    def test_ip_service_failure_does_not_hide_working_https(self):
        results=[SimpleNamespace(returncode=28,stdout='',stderr='timeout'),
                 SimpleNamespace(returncode=28,stdout='',stderr='timeout'),
                 SimpleNamespace(returncode=0,stdout='200',stderr='')]
        state={'active':True,'invocation':'same-service'}
        with patch.object(controller,'snapshot',return_value=state),patch.object(controller,'run',side_effect=results),patch.object(controller,'write_private'):
            result=controller.check()
        self.assertTrue(result['ok'])
        self.assertFalse(result['ip_available'])
        self.assertEqual(result['ip'],'')


if __name__=='__main__':unittest.main()
