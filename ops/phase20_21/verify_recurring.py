#!/usr/bin/env python3
"""Manually initiated bounded native GET proof; no financial or CRM writes."""
import json,os,sys
from pathlib import Path
from datetime import datetime,timezone
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'ops/phase16_17'))
from inventory import clients
settings,client,_=clients(REPO)
from workflow.automation.business_observation import NativeReader,collect_recurring
from workflow.automation.recurring_lifecycle import build_recurring
reader=NativeReader(client);snapshot=collect_recurring(reader);view=build_recurring(snapshot,now=datetime.now(timezone.utc))
root=Path('/var/lib/optibrain/phase20-21');os.umask(0o077)
for name,value in [('native-recurring-snapshot.json',snapshot),('native-recurring-view.json',view)]:
 with (root/name).open('x') as f:json.dump(value,f,indent=2);f.write('\n')
summary={'schema':1,'at':datetime.now(timezone.utc).isoformat(),'native_gets':reader.reads,'provider_writes':0,'books_profiles':view['books_profiles'],'active_books_profiles':sum(x.get('status')=='active' for x in snapshot['profiles']),'native_generated_invoices':sum(len(v) for v in snapshot['generated'].values()),'crm_recurring_services':view['recurring_services'],'linked_profiles':view['profiles_linked'],'unlinked_profiles':len(view['unlinked']),'financial_writes':0,'customer_sends':0,'protected_mutations':0,'relationship_basis':'native customer→Account and generated Invoice→profile verified;historical Service/Site linkage incomplete;no guesses','live_recurring_effect':'PENDING NATURAL EVENT'}
with (root/'native-recurring-validation.json').open('x') as f:json.dump(summary,f,indent=2);f.write('\n')
print(json.dumps(summary))
