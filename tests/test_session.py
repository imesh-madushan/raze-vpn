import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class Session(unittest.TestCase):
    def run_session(self, fail=False, interrupt=False, recover=False):
        source=Path(__file__).resolve().parents[1]/'src/session.py'
        spec=importlib.util.spec_from_file_location('vpn_session_under_test',source)
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);sysctl=root/'sysctl';runtime=root/'runtime'
            initial={'all':'0','default':'0','lo':'1','wlan0':'0'}
            for name,value in initial.items():
                (sysctl/name).mkdir(parents=True);(sysctl/name/'disable_ipv6').write_text(value)
            runtime.mkdir(mode=0o700)
            m.SYSCTL=sysctl;m.RUNTIME=runtime
            if recover:
                (runtime/'ipv6-state.json').write_text(json.dumps(initial))
                for p in sysctl.glob('*/disable_ipv6'):p.write_text('1')
            original_lstat=Path.lstat
            def lstat(p,*args,**kwargs):
                info=original_lstat(p,*args,**kwargs)
                return SimpleNamespace(st_mode=info.st_mode,st_uid=0) if p==runtime else info
            outer=self
            class Child:
                def __init__(self,args,**kwargs):
                    outer.assertIn('--reuid=1000',args)
                    outer.assertIn('--bounding-set=-all,+net_admin,+net_raw',args)
                    outer.assertEqual((sysctl/'all/disable_ipv6').read_text(),'1')
                    if fail:raise OSError('simulated startup failure')
                def poll(self):return None
                def send_signal(self,sig):outer.assertEqual(sig,signal.SIGTERM)
                def wait(self):
                    if interrupt:m.stop(signal.SIGTERM,None);return -signal.SIGTERM
                    return 0
                def terminate(self):pass
            args=['session','--restore'] if recover else ['session','config','sing-box','1000','1000']
            with patch.object(m.os,'geteuid',return_value=0),patch.object(Path,'lstat',lstat),patch.object(m.signal,'signal'),patch.object(m.subprocess,'Popen',Child),patch.object(sys,'argv',args):
                if fail:
                    with self.assertRaises(OSError):m.main()
                else:m.main()
            self.assertFalse((runtime/'ipv6-state.json').exists())
            for name,value in initial.items():self.assertEqual((sysctl/name/'disable_ipv6').read_text(),value)

    def test_restore_normal_exit(self):self.run_session()
    def test_restore_startup_failure(self):self.run_session(fail=True)
    def test_restore_on_termination(self):self.run_session(interrupt=True)
    def test_restore_stale_state_after_forced_exit(self):self.run_session(recover=True)


if __name__=='__main__':unittest.main()
