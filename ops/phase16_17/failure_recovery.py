#!/usr/bin/env python3
"""Real TEST effects with injected lost acknowledgments; independent GET recovery."""
from test_lab import Lab,MARKER,ROOT,RUN,atomic
from datetime import datetime,timezone
import httpx,json,os

VENDOR={'Accept':'application/vnd.api+json'}

def main():
    lab=Lab();s=lab.state['scenarios']['A'];deal=s['conversion']['Deals'];parent=s['workdrive']['contracts']
    jobs=[('failure-crm-lost-ack','crm.internal.task','/crm/v8/Tasks',
        {'data':[{'Subject':MARKER+' — Recovery drill internal Task','What_Id':{'id':deal},'$se_module':'Deals',
            'Status':'Not Started','Description':MARKER+' — Injected lost acknowledgment; reconciliation only.',
            'Send_Notification_Email':False,'OptiBrain_Test':True}],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]},{}),
        ('failure-workdrive-lost-ack','workdrive.folder.create','/workdrive/api/v1/files',
         {'data':{'type':'files','attributes':{'name':MARKER+' — Recovery drill','parent_id':parent}}},VENDOR)]
    evidence=[]
    for key,scope,path,body,headers in jobs:
        if key not in lab.state['operations']:
            original=httpx.request;injected=[]
            def lose_ack(method,url,**kwargs):
                response=original(method,url,**kwargs)
                if method=='POST' and httpx.URL(url).path==path and response.is_success:
                    injected.append({'method':method,'path':path,'status':response.status_code,'response_digest':__import__('hashlib').sha256(response.content).hexdigest()})
                    atomic(ROOT/(key+'-transport.json'),injected)
                    raise httpx.ReadError('Intentional TEST-only lost acknowledgment after provider application')
                return response
            httpx.request=lose_ack
            try:
                lab.call(key,scope,'zohoapis','POST',path,body,headers=headers)
                raise ValueError('Failure injection did not execute')
            except Exception as exc:
                if type(exc).__name__!='ZohoWriteUnconfirmedError':raise
            finally:httpx.request=original
            if len(injected)!=1:raise ValueError('Expected exactly one TEST transport effect')
        op=lab.state['operations'][key]
        if path.endswith('/Tasks'):
            rows=lab.lists('Tasks','id,Subject,What_Id,$se_module,Description,OptiBrain_Test,Created_Time')
            matches=[r for r in rows if r.get('Subject')==body['data'][0]['Subject'] and str((r.get('What_Id') or {}).get('id'))==deal]
            if len(matches)!=1 or matches[0].get('OptiBrain_Test') is not True or matches[0].get('$se_module')!='Deals':raise ValueError('CRM recovery ambiguous')
            identity=matches[0]['id'];module='Tasks'
        else:
            rows=lab.get('zohoapis','/workdrive/api/v1/files/'+parent+'/files',{'page[limit]':50},headers=VENDOR)['data']
            matches=[r for r in rows if r.get('attributes',{}).get('name')==body['data']['attributes']['name'] and r['attributes']['parent_id']==parent]
            if len(matches)!=1:raise ValueError('WorkDrive recovery ambiguous')
            identity=matches[0]['id'];module='WorkDrive'
        lab.register(module,identity,{'reconciled_action_id':op['action_id'],'independent_provider_get':True})
        if op['state']!='verified':lab.verified(key,identity,{'independent_readback':True,'provider_effects':1,'resends':0,'failure':'lost acknowledgment'})
        from workflow.automation.lifecycle_control import LifecycleEffect
        with lab.journal.connect() as db:row=db.execute('SELECT envelope FROM lifecycle_intents WHERE action_id=?',(op['action_id'],)).fetchone()
        effect=LifecycleEffect(RUN+':'+key,json.loads(row[0]));claim=lab.remote.claim(effect)
        if claim.fresh:raise ValueError('Existing effect acquired a replay claim')
        evidence.append({'key':key,'module':module,'id':identity,'provider_effects':1,'duplicate_effects':0,'resends':0,'independent_recovery':True,'fresh_replay_claim':False})
        print(module,'lost-ack failure detected; independent GET recovered one effect; replay fenced',flush=True)
    atomic(ROOT/'failure-recovery-evidence.json',{'schema':1,'run':RUN,'failures':evidence,'duplicate_effects':0,'resends':0})

if __name__=='__main__':main()
