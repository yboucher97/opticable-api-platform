#!/usr/bin/env python3
"""Manual bounded export/validation/reconciliation. No automatic receipt invention."""
import argparse,json,os,sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO/'apps/workflow-api'))
from workflow.automation.conversion_export import CONTROL,ROOT,build_plan,trusted_control,DataManager,ConversionClaims,export_one,reconcile
from workflow.automation.lifecycle_control import trusted_json
from workflow.automation.real_internal import atomic

def main():
 if os.geteuid()!=0:raise ValueError('Manual root execution required')
 os.umask(0o077)
 p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
 g.add_argument('--stop',action='store_true');g.add_argument('--check',action='store_true')
 g.add_argument('--validate',action='store_true');g.add_argument('--send-one',action='store_true');g.add_argument('--reconcile',action='store_true')
 p.add_argument('--event-key');p.add_argument('--request-id');a=p.parse_args()
 control=trusted_control()
 if a.stop:
  atomic(CONTROL,{**control,'enabled':False});print(json.dumps({'state':'STOPPED','other_scopes_changed':0}));return
 if not a.event_key or not __import__('re').fullmatch('[0-9a-f]{64}',a.event_key):raise ValueError('Root-held event identity required')
 event=trusted_json(ROOT/'events'/(a.event_key+'.json'),262144)
 cache=trusted_json(Path('/var/lib/optibrain/lifecycle/business-observation.json'),16777216)
 plan=build_plan(event,cache['snapshot'],control)
 if a.check:
  print(json.dumps({'state':'PLAN_CHECK_PASS','key':plan['key'],'kind':plan['kind'],'provider_calls':0,'uploads':0}));return
 sys.path.insert(0,str(REPO/'ops/phase16_17'))
 from inventory import clients
 from workflow.google_oauth import GoogleOAuthManager
 settings,_,_=clients(REPO);client=DataManager(GoogleOAuthManager(settings.google_oauth))
 if a.reconcile:
  if not a.request_id:raise ValueError('Provider request ID required')
  client.authorize(plan,live=False);result=reconcile(plan,client,a.request_id)
 else:
  from workflow.automation.remote_effects import RemoteEffects
  claims=ConversionClaims(RemoteEffects.root_store().client) if a.send_one else None
  result=export_one(plan,client,claims,live=a.send_one)
 atomic(ROOT/'receipts'/(plan['key']+'-'+result['state']+'.json'),result,immutable=True)
 print(json.dumps(result))

if __name__=='__main__':main()
