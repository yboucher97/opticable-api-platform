"""Notification renewal stays bound, audited and finite; all provider calls are forbidden."""
import copy,json,sys,tempfile,time,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ops/rebuild'))
from common import RebuildError,atomic_json,digest,file_hash
from durable_migration import Control,profile_binding
import owner_notifications as n

class BudgetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.c=Control(self.root/'actions.db','budget-fixture');self.c.transition({'current_stage':'PREPARED','authority':'OLD'},'fixture')
  self.p={'version':1,'execution_id':self.c.run_id,'runtime':{}}
  self.owner=self.root/'actual-fixture-owner.txt';self.owner.write_text('FIXTURE_ONLY: explicit approval for one additional 16 owner-only migration incidents.');self.owner.chmod(0o600)
  self.baseline={}
  for i in range(16):
   ident='old-'+str(i);self.c.alert_intent(ident,'fixture');row={'state':'DELIVERED','incident':ident,'message_id':'fixture-'+str(i)}
   self.c.save_alert(ident,row);self.baseline[ident]=digest(row)
  self.patch=patch.object(n,'AUTHORIZATION_ROOT',self.root);self.patch.start()
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def configure(self,**changes):
  plan={'additional_incident_limit':16,'baseline_incident_hashes':dict(self.baseline),
   'approval_file':str(self.root/'renewal.json'),'expires_utc':datetime.fromtimestamp(time.time()+120,timezone.utc).isoformat()}
  plan.update(changes);self.p['runtime']['owner_notification_renewal']=plan;return plan
 def authorize(self):
  plan=self.p['runtime']['owner_notification_renewal'];now=datetime.now(timezone.utc);aid='fixture-budget-renewal'
  record=self.c.audit.envelope(aid,'migration.owner_notification_budget_renewal',{'type':'RECOVERY','identity':self.c.run_id},now,
   initiator='OWNER',trigger='FIXTURE_OWNER_APPROVAL',mutation=True,approval_required=True,
   authority_class='OWNER_ONLY_MIGRATION_NOTIFICATION_RENEWAL',automatic_rule='One exact fixture owner budget',
   rollback_capability='COMPENSATING_ACTION_ONLY',before_state={'count':16},proposed_state={'additional_limit':16},
   consequence='Only one fixture notification renewal',compensating_action='Revoke fixture receipt; preserve all synthetic history',
   exact_versions={'package_sha256':profile_binding(self.p)},reason='Isolated explicit owner budget fixture')
  self.c.audit.store.plan(record,now);self.c.audit.store.approve(aid,'FIXTURE_OWNER_APPROVAL',now,binding=self.c.canonical.approval_binding(record),expires_at=datetime.fromtimestamp(time.time()+120,timezone.utc).isoformat())
  self.c.audit.store.start(aid,now,authority_check=lambda:None)
  receipt={'approved':True,'execution_id':self.c.run_id,'package_sha256':profile_binding(self.p),'plan_sha256':digest(plan),
   'issued_epoch':time.time()-1,'expires_epoch':time.time()+60,'owner_authorization_file':str(self.owner),
   'owner_authorization_sha256':file_hash(self.owner),'owner_authorization_reference':'FIXTURE_OWNER_APPROVAL','action_id':aid}
  atomic_json(plan['approval_file'],receipt)
  self.c.audit.store.finish(aid,now,provider_success=True,actual_after={'receipt_sha256':file_hash(plan['approval_file'])},verified=True)
  return receipt
 def alter_receipt(self,**changes):
  f=Path(self.p['runtime']['owner_notification_renewal']['approval_file']);v=json.loads(f.read_text());v.update(changes);atomic_json(f,v)
 def test_legacy_guard_denies_seventeenth_without_allocating_or_sending(self):
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
  with self.c.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM migration_alerts').fetchone()[0],16)
 def test_existing_incident_still_deduplicates_at_limit(self):n.check_alert_budget(self.c,self.p,'old-0')
 def test_renewal_is_never_implicit(self):
  self.configure()
  with self.assertRaises((RebuildError,FileNotFoundError)):n.check_alert_budget(self.c,self.p,'new')
 def test_audited_renewal_allows_new_incident_preserving_all_old_rows(self):
  self.configure();self.authorize();n.check_alert_budget(self.c,self.p,'new')
  with self.c.connect() as db:rows={r[0]:json.loads(r[1]) for r in db.execute('SELECT incident,state_json FROM migration_alerts')}
  self.assertEqual({k:digest(v) for k,v in rows.items()},self.baseline)
 def test_single_renewal_cannot_exceed_16_additional_or_32_lifetime(self):
  self.configure();self.authorize()
  for i in range(16):self.c.alert_intent('new-'+str(i),'fixture')
  n.check_alert_budget(self.c,self.p,'new-0')
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'thirty-third')
 def test_expired_receipt_denied(self):
  self.configure();self.authorize();self.alter_receipt(issued_epoch=time.time()-20,expires_epoch=time.time()-1)
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_future_issue_denied(self):
  self.configure();self.authorize();self.alter_receipt(issued_epoch=time.time()+30)
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_package_change_denied(self):
  self.configure();self.authorize();self.p['unreviewed_change']=True
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_baseline_edit_or_unresolved_delivery_denied(self):
  self.configure();self.authorize();self.c.save_alert('old-0',{'state':'UNKNOWN'})
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_missing_baseline_denied(self):
  self.configure();self.authorize()
  with self.c.connect() as db:db.execute("DELETE FROM migration_alerts WHERE incident='old-0'")
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_owner_artifact_change_denied(self):
  self.configure();self.authorize();self.owner.write_text('NOT THE APPROVED FIXTURE')
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_unaudited_receipt_denied(self):
  self.configure();self.authorize();self.alter_receipt(action_id='not-audited')
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_limit_expansion_denied(self):
  self.configure(additional_incident_limit=17);self.authorize()
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_wrong_run_denied(self):
  self.configure();self.authorize();self.alter_receipt(execution_id='wrong')
  with self.assertRaises(RebuildError):n.check_alert_budget(self.c,self.p,'new')
 def test_notify_refuses_before_constructing_mail_or_allocating(self):
  policy=self.root/'policy.json';atomic_json(policy,{'recipient':n.OWNER,'account_id':n.ACCOUNT,
   'authority_reference':n.AUTHORITY_REFERENCE,'expires_epoch':time.time()+60,'code_sha256':file_hash(n.__file__),
   'report_reference':'/home/optibrain/optibrain-migration-progress-20261101.txt'})
  with patch.object(n,'Mail',side_effect=AssertionError('No provider allowed')) as mail:
   with self.assertRaises(RebuildError):n.notify(self.c,self.p,policy,'BLOCKED','new',mail_factory=mail)
   mail.assert_not_called()


class SourceFallbackTests(unittest.TestCase):
 def test_independent_OLD_alert_uses_its_actual_audited_execution_identity(self):
  import source_executor as source
  from types import SimpleNamespace
  cfg={'execution_id':'fixture-main','source':{'host':'OLD'},'target':{'host':'NEW'}}
  control=SimpleNamespace(run_id='fixture-main-old-supervisor',state=lambda:{'current_stage':'SOURCE_FROZEN'})
  def guarded(c,p,*args,**kwargs):
   self.assertEqual(c.run_id,p['execution_id'])
   self.assertEqual(args[1:3],('CRITICAL','fixture-critical'))
   self.assertEqual(kwargs['delays'],(0,))
   return {'state':'FIXTURE_ONLY_NO_PROVIDER'}
  with patch.object(source,'private',return_value=cfg),patch('durable_migration.Control',return_value=control),patch('owner_notifications.notify',side_effect=guarded):
   self.assertEqual(source.owner_alert('fixture-critical')['state'],'FIXTURE_ONLY_NO_PROVIDER')

if __name__=='__main__':unittest.main()
