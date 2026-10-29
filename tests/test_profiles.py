import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import profiles as p

LINK = 'vless://00000000-0000-4000-8000-000000000001@example.com:443?security=tls&type=ws&sni=example.com&host=example.com&path=%2Fvpn'


class Profiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        config, state = root / 'config', root / 'state'
        for d in [config, state, config/'profiles', config/'backups']:
            d.mkdir(parents=True, exist_ok=True)
        self.patch = patch.multiple(p, CONFIG=config, PROFILES=config/'profiles', HISTORY=config/'backups', SELECTION=config/'selection.json', ensure=lambda: None)
        self.patch.start()

    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()

    def add(self, name='work'):
        p.manage('add', name, LINK)

    def test_import_routes_ipv4_and_preserves_tls(self):
        self.add(); d = p.load('work')
        self.assertEqual(d['dns']['strategy'], 'ipv4_only')
        self.assertEqual(d['route']['final'], 'vpn')
        self.assertTrue(next(i for i in d['inbounds'] if i['type']=='tun')['auto_redirect'])
        self.assertFalse(p.outbound(d)['tls']['insecure'])
        self.assertEqual(p.outbound(d)['transport']['path'], '/vpn')
        self.assertEqual(p.profile_path('work').stat().st_mode & 0o777, 0o600)

    def test_duplicate_select_rename_delete_and_backups(self):
        self.add(); p.manage('duplicate','work','osg2')
        p.manage('select','osg2'); self.assertEqual(p.selected(),'osg2')
        p.manage('rename','osg2','remote'); self.assertEqual(p.selected(),'remote')
        p.manage('delete','remote'); self.assertEqual(p.names(),['work'])
        self.assertGreaterEqual(len(list(p.HISTORY.glob('*.json'))),2)

    def test_invalid_name_and_duplicate_do_not_overwrite(self):
        self.add(); original=p.load('work')
        for name in ['../escape', '', 'has space', 'x'*65]:
            with self.assertRaises(ValueError):p.manage('add',name,LINK)
        with self.assertRaises(ValueError): self.add()
        self.assertEqual(p.load('work'),original)

    def test_active_profile_cannot_be_deleted_or_renamed(self):
        self.add();p.manage('duplicate','work','osg2')
        for operation,value in [('delete',None),('rename','newname')]:
            with self.assertRaises(ValueError):p.manage(operation,'work',value,active='work')

    def test_last_profile_cannot_be_deleted(self):
        self.add()
        with self.assertRaises(ValueError): p.manage('delete','work')

    def test_edit_credentials_kept_when_blank_and_backup_created(self):
        self.add();original=p.outbound(p.load('work'))['uuid'];v=p.details('work')
        v.update(server='vpn.example.com',port='8443',tls_verify=False)
        p.manage('edit','work',v)
        o=p.outbound(p.load('work'));self.assertEqual(o['uuid'],original)
        self.assertTrue(o['tls']['insecure']);self.assertEqual(o['server_port'],8443)
        self.assertEqual(len(list(p.HISTORY.glob('*.json'))),1)

    def test_guided_transport_switches_between_tcp_and_websocket(self):
        self.add()
        values=p.details('work');values['transport']='tcp'
        p.manage('edit','work',values)
        self.assertNotIn('transport',p.outbound(p.load('work')))
        values=p.details('work');values.update(transport='ws',ws_host='vpn.example.com',ws_path='/new')
        p.manage('edit','work',values)
        self.assertEqual(p.outbound(p.load('work'))['transport']['path'],'/new')

    def test_invalid_edits_leave_original_unchanged(self):
        self.add();original=p.profile_path('work').read_bytes();v=p.details('work');v['port']='99999'
        with self.assertRaises(ValueError):p.manage('edit','work',v)
        self.assertEqual(p.profile_path('work').read_bytes(),original)

    def test_repeated_unknown_and_unsupported_link_options_rejected(self):
        for suffix in ['&type=tcp','&unknown=1']:
            with self.assertRaises(ValueError):p.parse(LINK+suffix)
        with self.assertRaises(ValueError):p.parse(LINK.replace('security=tls','security=reality'))

    def test_full_json_import_preserves_provider_tls(self):
        d=p.parse(LINK);p.outbound(d)['tls']['insecure']=True
        imported=p.parse(json.dumps(d))
        self.assertTrue(p.outbound(imported)['tls']['insecure'])

    def test_symlink_profile_rejected(self):
        self.add();p.profile_path('link').symlink_to(p.profile_path('work'))
        with self.assertRaises(ValueError):p.load('link')

    def test_json_edit_keeps_custom_settings_and_backs_up(self):
        self.add();value=p.json_details('work');d=json.loads(value['content']);d['log']['level']='warn'
        value['content']=json.dumps(d);p.manage('edit-json','work',value)
        self.assertEqual(p.load('work')['log']['level'],'warn')
        self.assertEqual(len(list(p.HISTORY.glob('*.json'))),1)

    def test_json_edit_rejects_invalid_text_and_stale_revision(self):
        self.add();value=p.json_details('work');original=p.profile_path('work').read_bytes()
        value['content']='{ invalid json'
        with self.assertRaises(ValueError):p.manage('edit-json','work',value)
        self.assertEqual(p.profile_path('work').read_bytes(),original)
        value=p.json_details('work');value['revision']='stale'
        with self.assertRaises(ValueError):p.manage('edit-json','work',value)

    def test_json_edit_cannot_disable_ipv4_policy(self):
        self.add();value=p.json_details('work');d=json.loads(value['content']);d['dns']['strategy']='prefer_ipv6'
        value['content']=json.dumps(d)
        with self.assertRaises(ValueError):p.manage('edit-json','work',value)


if __name__ == '__main__':unittest.main()
