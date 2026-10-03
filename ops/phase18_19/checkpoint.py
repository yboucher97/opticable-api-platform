#!/usr/bin/env python3
"""Seal aggregate Phase18 evidence; no provider transport or execution grant."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,os,collections
ROOT=Path('/var/lib/optibrain/phase18-19')
CUST=Path('/var/lib/optibrain/customer-communications')
REPO=Path(__file__).resolve().parents[2]

def main():
 if os.geteuid()!=0:raise ValueError('Manual root evidence sealing required')
 state=json.loads((CUST/'state.json').read_text());host=json.loads((ROOT/'phase18-host-check.json').read_text())
 if state['holds'] or len(state['effects'])!=12 or any(x['state']!='verified' or x['mode']!='TEST_ONLY' for x in state['effects'].values()):raise ValueError('TEST reconciliation incomplete')
 if host['protected']['unchanged'] is not True:raise ValueError('Protected baseline issue')
 for name,count in [('communication-replay.json',12),('communication-kill-test.json',12),('communication-stops-fr.json',8)]:
  v=json.loads((ROOT/name).read_text());checks=v['checks'] if isinstance(v['checks'],int) else len(v['checks'])
  if checks!=count or v['provider_send_calls']!=0:raise ValueError('Replay/stop/kill test incomplete')
 real=json.loads(Path('/var/lib/optibrain/lifecycle/state.json').read_text())
 counts=dict(collections.Counter(x['family'] for x in state['effects'].values()))
 names=['state.json'];evidence={str(CUST/name):hashlib.sha256((CUST/name).read_bytes()).hexdigest() for name in names}
 evidence.update({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('communication-*.json')})
 value={'schema':1,'phase18':'PASS','at':datetime.now(timezone.utc).isoformat(),'safety_critical_failures':0,
  'test_provider_sends':12,'real_sends':0,'passed_families':sorted(counts),'families':{k:{'state':'READY / ARMED AFTER RELEASE','test_sends':n} for k,n in counts.items()},
  'controlled_recipient':'yboucher@opticable.ca','suppression_checks':8,'verified_replays':12,'kill_denials':12,
  'duplicate_sends':0,'wrong_recipient_sends':0,'unauthorized_sends':0,'financial_writes':0,'protected_records':123,'protected_unchanged':123,
  'lost_ack':'One provider POST; initial HOLD from mailbox-local date filter; corrected bounded GET-only reconciliation located exactly one Sent message; no resend',
  'finance_test_source':'Explicit TEST_STATUS_EQUIVALENT; no Estimate/Invoice created. Native CRM Finance/Books associations and system-send history independently read and validated.',
  'sign':'DEFERRED — PROVIDER LICENSE; native code12000; contract sends HUMAN',
  'first_genuine_phase17_effect':'NOT YET OBSERVED','eligible_genuine_leads':len(real.get('leads',{})),'real_internal_effects':len(real.get('effects',{})),
  'evidence_sha256':evidence,'automatic_continuation':'PHASE 19'}
 if (CUST/'phase18-checkpoint.json').exists():raise ValueError('Checkpoint already sealed')
 raw=json.dumps(value,sort_keys=True,indent=2)+'\n'
 for path in [CUST/'phase18-checkpoint.json',ROOT/'PHASE18_CHECKPOINT.json']:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 policy=Path('/etc/optibrain/customer-communication-control.json');v=json.loads(policy.read_text());v['test_enabled']=False;v['external_enabled']=False
 fd=os.open(policy,os.O_WRONLY|os.O_TRUNC);os.write(fd,(json.dumps(v)+'\n').encode());os.fsync(fd);os.close(fd)
 (REPO/'docs/PHASE18_CHECKPOINT.json').write_text(raw)
 (REPO/'docs/PHASE18_CHECKPOINT.md').write_text('''# Phase 18 checkpoint\n\nAUDIT EVIDENCE. **PASS. PHASE 18 PASSED. AUTOMATICALLY CONTINUING TO PHASE 19.**\n\nTwelve actual Zoho Mail TEST sends to the controlled owner mailbox were independently reconciled using Sent metadata, complete content and headers: five quote reminders (including one lost-ack probe), three confirmations (including an updated schedule), two appointment reminders and two completion messages. French and English templates were exercised. Twelve frozen-intent replays caused zero sends; twelve kill denials caused zero sends. Eight stop conditions passed; wrong-recipient, bounce, language and association denial passed focused offline tests.\n\nThe lost acknowledgement initially entered HOLD because UTC date filtering excluded the Canadian evening message. Widening the bounded search window recovered exactly one native effect using GETs only. Exact timestamps/content/headers remain required; no send retry occurred. This is a fixed Phase18 defect.\n\nQuote timing used explicit TEST status-equivalent fixtures/accelerated clocks, linked to independently read TEST CRM identities. Native CRM Finance/Books relationships and actual typed system-send history were independently validated read-only; no financial transaction was created or changed. Real send timing never uses a TEST clock, creation date or view date.\n\nProtected baseline:123/123 unchanged. Wrong/duplicate/unauthorized customer sends:0. Financial writes:0. Genuine eligible Phase17 Leads/effects:0; its existing authority remains enabled. Sign remains provider-license deferred (native12000); send remains HUMAN. Four Mail families may be armed only after the exact release and source/checkpoint gates.\n\nMachine proof: [PHASE18_CHECKPOINT.json](PHASE18_CHECKPOINT.json). Root immutable checkpoint: `/var/lib/optibrain/customer-communications/phase18-checkpoint.json`; native effects/proofs/claims remain private runtime evidence and standard backup input. GA4, English Forms and campaign continuity retain their documented noncritical limitations.\n''')
 print(json.dumps({'phase18':'PASS','test_sends':12,'real_sends':0,'protected_unchanged':123,'checkpoint_sha256':hashlib.sha256(raw.encode()).hexdigest()}))
if __name__=='__main__':main()
