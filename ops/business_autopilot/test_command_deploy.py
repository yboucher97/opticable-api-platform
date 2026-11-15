from copy import deepcopy
from pathlib import Path
import sys
import unittest
import tempfile
import json
from hashlib import sha256
from serve_command_center import verify_source

sys.path.insert(0,str(Path(__file__).resolve().parent))
from command_center_deploy import plan,validate,render


class DeployTests(unittest.TestCase):
    def test_source_guard_rejects_tampering_extra_members_and_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'app.py';p.write_text('pinned source');p.chmod(0o644)
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'app.py':sha256(p.read_bytes()).hexdigest()}));manifest.chmod(0o644);expected=sha256(manifest.read_bytes()).hexdigest()
            self.assertEqual(verify_source(root,expected,require_root=False),1)
            p.write_text('changed')
            with self.assertRaises(ValueError):verify_source(root,expected,require_root=False)
            p.write_text('pinned source');(root/'extra.py').write_text('extra');(root/'extra.py').chmod(0o644)
            with self.assertRaises(ValueError):verify_source(root,expected,require_root=False)
            (root/'extra.py').unlink();p.unlink();p.symlink_to(manifest)
            with self.assertRaises(PermissionError):verify_source(root,expected,require_root=False)
    def test_exact_policy_is_owner_only_with_zero_cost_and_no_bypass(self):
        value=plan();self.assertEqual(len(validate(value)),64)
        self.assertEqual(value['access_application']['policies'][0]['include'],[{'email':{'email':'info@opticable.ca'}}])
        self.assertEqual(value['origin_template']['application']['member_roles'],{})
        self.assertFalse(value['access_application']['options_preflight_bypass'])
        self.assertEqual(value['maximum_incremental_cost']['amount'],0)

    def test_only_returned_identifier_slots_can_be_rendered(self):
        value=render(plan(),access_aud='a'*64,tunnel_uuid='11111111-2222-3333-4444-555555555555')
        self.assertEqual(value['origin_template']['application']['audience'],'a'*64)
        self.assertEqual(value['ingress_template']['ingress'][0]['originRequest']['access']['audTag'],['a'*64])
        self.assertEqual(value['dns_template']['content'],'11111111-2222-3333-4444-555555555555.cfargotunnel.com')
        self.assertIsNone(value['origin_template']['staging_public_key'])
        self.assertEqual(value['ingress_template']['ingress'][-1],{'service':'http_status:404'})
        for audience,tunnel in [('http://evil','11111111-2222-3333-4444-555555555555'),('a'*64,'../../evil')]:
            with self.assertRaises(ValueError):render(plan(),access_aud=audience,tunnel_uuid=tunnel)

    def test_permissive_policy_route_cost_and_identity_drift_fail_closed(self):
        for field,replacement in [('hostname','evil.test'),('maximum_incremental_cost',{'amount':1,'currency':'CAD'})]:
            p=plan();p[field]=replacement
            with self.assertRaises(ValueError):validate(p)
        p=plan();p['access_application']['policies'][0]['include']=[{'everyone':{}}]
        with self.assertRaises(ValueError):validate(p)
        p=plan();p['ingress_template']['ingress'][0]['originRequest']['access']['required']=False
        with self.assertRaises(ValueError):validate(p)

    def test_origin_write_parent_requires_enforced_profile_and_exact_sidecars(self):
        root=Path(__file__).resolve().parent;unit=(root/'optibrain-command-center.service').read_text();profile=(root/'optibrain-command-center.apparmor').read_text()
        self.assertIn('AppArmorProfile=optibrain-command-center-v1',unit)
        self.assertNotIn('AppArmorProfile=-',unit)
        self.assertNotIn('/automation/** rw',profile)
        for suffix in (' rwk,','-journal rw,','-wal rw,','-shm rwk,'):self.assertIn('phase12-autonomy.db'+suffix,profile)

    def test_tunnel_identity_uses_scoped_systemd_credentials_for_config_and_ca(self):
        unit=(Path(__file__).resolve().parent/'optibrain-command-tunnel.service').read_text()
        for field in ('DynamicUser=yes','LoadCredential=tunnel.json:','LoadCredential=ingress.json:','LoadCredential=origin-ca.pem:','--config %d/ingress.json'):self.assertIn(field,unit)
        self.assertEqual(plan()['ingress_template']['ingress'][0]['originRequest']['caPool'],'/run/credentials/optibrain-command-tunnel.service/origin-ca.pem')


if __name__=='__main__':unittest.main()
