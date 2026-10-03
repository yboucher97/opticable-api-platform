#!/usr/bin/env python3
"""Manually initiated GET-only delta audit; reuse current hourly native snapshot."""
import argparse, json, os, sys
from pathlib import Path
from datetime import datetime, timezone
from hashlib import sha256
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'ops/phase16_17'))
from inventory import clients


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--business',action='store_true');args=parser.parse_args()
    os.umask(0o077);root=Path('/var/lib/optibrain/phase22-23')
    settings,client,_=clients(REPO)
    from workflow.automation.business_observation import NativeReader
    from workflow.automation.measurement import audit_lineage, populations
    saved=Path('/var/lib/optibrain/lifecycle/business-observation.json')
    cached=json.loads(saved.read_text());snapshot=cached['snapshot']
    at=datetime.fromisoformat(cached['observed_at']);now=datetime.now(timezone.utc)
    if not 0<=(now-at).total_seconds()<7200:raise ValueError('Current native snapshot required')
    reader=NativeReader(client,limit=20)
    # Minimal fresh native fields missing from the previous reporting snapshot.
    snapshot['deals']=reader.crm('Deals','id,Deal_Name,Account_Name,Contact_Name,Stage,Amount,Currency,Closing_Date,Created_Time,Modified_Time,Service_Location,Next_Step,OptiBrain_Test,Lead_Source,First_Source,First_Medium,First_Campaign,Last_Source,Last_Medium,Last_Campaign')
    # Independently re-read three exact non-test financial objects; preserve all receipts privately.
    rows,_=populations(snapshot);checks=[]
    for kind in ('invoices','estimates'):
        for rid,old in list(rows[kind].items())[:3]:
            key='invoice' if kind=='invoices' else 'estimate'
            actual=reader.record('/books/v3/'+kind+'/'+rid,key,key+'_id',rid)
            fields=('customer_id','status','total','balance') if kind=='invoices' else ('customer_id','status','total')
            if any(str(actual.get(k))!=str(old.get(k)) for k in fields):raise ValueError('Financial snapshot changed; reconcile before totals')
            checks.append({'kind':kind,'id':rid,'compared_fields':list(fields),'consistent':True})
            if kind=='invoices':snapshot['books_invoices']=[actual if str(r['invoice_id'])==rid else r for r in snapshot['books_invoices']]
            else:snapshot['books_estimate_index'][rid]=actual
    if args.business:
        # Complete bounded collections or explicit unavailable; optional costs cannot authorize margin.
        snapshot['optional_reads']={}
        for name,path,key in [('payments','customerpayments','customerpayments'),('expenses','expenses','expenses')]:
            try:snapshot[name]=reader.listing('/books/v3/'+path,key);snapshot['optional_reads'][name]='PROVEN'
            except ValueError:snapshot[name]=[];snapshot['optional_reads'][name]='UNAVAILABLE'
    baseline=json.loads(Path('/etc/optibrain/protected-runtime-versions.json').read_text())
    protected={m:set(v['protected_versions']) for m,v in baseline['modules'].items()}
    audit=audit_lineage(snapshot,protected=protected)
    name='business' if args.business else 'measurement'
    receipt={'schema':1,'at':now.isoformat(),'source_observed_at':cached['observed_at'],
        'reused_snapshot_sha256':sha256(saved.read_bytes()).hexdigest(),'delta_gets':reader.reads,
        'financial_samples':checks,'coverage':audit['coverage'],'test_excluded':audit['excluded'],
        'provider_writes':0,'financial_writes':0,'advertising_changes':0,'natural_effect':'PENDING NATURAL EVENT'}
    if args.business:
        receipt['optional_read_states']=snapshot['optional_reads']
        receipt['cost_rows']=len(snapshot['expenses']);receipt['payment_rows']=len(snapshot['payments'])
        receipt['cost_allocation_fields']=sorted({k for r in snapshot['expenses'] for k in r if any(v in k for v in ('project','customer','invoice','deal','amount','date'))})
    for suffix,value in [('snapshot',snapshot),('lineage',audit),('receipt',receipt)]:
        with (root/(name+'-'+suffix+'.json')).open('x') as f:json.dump(value,f,indent=2);f.write('\n')
    print(json.dumps(receipt))


if __name__=='__main__':main()
