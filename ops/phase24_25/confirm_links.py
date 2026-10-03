#!/usr/bin/env python3
"""Manual root recording of explicit owner choices; no provider transport."""
import argparse
from datetime import datetime,timezone
import hashlib,json,os,sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'apps/workflow-api'))
from workflow.automation.lifecycle_control import trusted_json
from workflow.automation.measurement import populations
from workflow.automation.finance_links import validate_confirmation,receipt_key,resolve_finance,recurring_reviews
from workflow.automation.recurring_lifecycle import bind_profile,identity
from workflow.automation.real_internal import atomic

ROOT=Path('/var/lib/optibrain/lifecycle')

def main():
 if os.geteuid()!=0:raise ValueError('Manual root execution required')
 os.umask(0o077)
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--check',action='store_true')
 args=p.parse_args();request=trusted_json(args.input,262144)
 snapshot=trusted_json(ROOT/'business-observation.json',16777216)['snapshot'];rows,_=populations(snapshot)
 target=ROOT/'finance-links.json';current=trusted_json(target,262144) if target.exists() else {'schema':1,'records':{}}
 if request.get('owner_confirmed') is not True or not request.get('owner_confirmation_reference'):
  raise ValueError('Actual owner confirmation reference required; candidates are not choices')
 incoming=request.get('records')
 if not isinstance(incoming,list) or not 0<len(incoming)<=250:raise ValueError('Bounded owner choice batch required')
 result=json.loads(json.dumps(current))
 for r in incoming:
  reviewed=validate_confirmation(r,rows);key=receipt_key(reviewed['kind'],reviewed['record_id'])
  if key in result['records'] and result['records'][key]!=reviewed:
   raise ValueError('Conflicting prior confirmation; explicit reconciliation required')
  result['records'][key]=reviewed
 rows['_finance_reviews']=result['records']
 for r in incoming:
  if r['kind']!='profiles' and resolve_finance(rows[r['kind']][r['record_id']],r['kind'],rows)['conflict']:
   raise ValueError('Owner choice conflicts with current native evidence')
 reviews=recurring_reviews(rows)
 for r in incoming:
  if r['kind']=='profiles':
   profile=rows['profiles'][r['record_id']]
   relation=bind_profile(profile,rows['customers'].get(r['customer_id'],{}),list(rows['services'].values()),rows['sites'],
    list(rows['finance_invoices'].values()),[i for i in rows['invoices'].values() if identity(i.get('recurring_invoice_id'))==r['record_id']],reviewed=reviews[r['record_id']])
   if relation['decision']!='LINKED':raise ValueError('Owner choice conflicts with native recurring evidence')
 if args.check:print(json.dumps({'state':'CHECK PASS','records':len(incoming),'provider_writes':0}));return
 receipt={'schema':1,'at':datetime.now(timezone.utc).isoformat(),'request_sha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),
  'owner_confirmation_reference':request['owner_confirmation_reference'],'keys':sorted(receipt_key(r['kind'],r['record_id']) for r in incoming),
  'source_mutations':0,'provider_writes':0}
 directory=ROOT/'finance-link-confirmations';directory.mkdir(mode=0o700,exist_ok=True)
 digest=receipt['request_sha256'];path=directory/(digest+'.json')
 if not path.exists():atomic(path,{'receipt':receipt,'records':incoming})
 atomic(target,result)
 print(json.dumps({'state':'RECORDED','records':len(incoming),'receipt':str(path),'provider_writes':0}))

if __name__=='__main__':main()
