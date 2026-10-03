#!/usr/bin/env python3
"""Read-only Phase21 delta proof; reuse sealed Phase20 native receipt."""
import json,os,sys
from pathlib import Path
from datetime import datetime,timezone
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'ops/phase16_17'))
from inventory import clients
settings,client,_=clients(REPO)
from workflow.automation.business_observation import NativeReader,collect_marketing
from workflow.automation.marketing_attribution import build_marketing
root=Path('/var/lib/optibrain/phase20-21');os.umask(0o077)
snapshot=collect_marketing(NativeReader(client,limit=40),json.loads((root/'native-recurring-snapshot.json').read_text()))
snapshot['observed_at']=datetime.now(timezone.utc).isoformat()
view=build_marketing(snapshot)
for name,value in [('native-marketing-snapshot.json',snapshot),('native-marketing-view.json',view)]:
 with (root/name).open('x') as f:json.dump(value,f,indent=2);f.write('\n')
summary={'schema':1,'at':snapshot['observed_at'],'native_delta_gets':snapshot['provider_reads'],
 'native_counts':{k:len(snapshot.get(k,[])) for k in ['leads','contacts','deals','finance_estimates','finance_invoices','books_invoices','customers']},
 'source_groups':len(view['groups']),'attribution_problems':view['problems'],'test_excluded':view['excluded'],
 'financial_writes':0,'advertising_mutations':0,'conversion_uploads':0,'customer_sends':0}
with (root/'native-marketing-validation.json').open('x') as f:json.dump(summary,f,indent=2);f.write('\n')
print(json.dumps(summary))
