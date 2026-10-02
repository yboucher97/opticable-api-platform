#!/usr/bin/env python3
"""Bounded synthetic text upload into owned TEST contract folders; no sharing."""
from test_lab import Lab,MARKER,ROOT,atomic
import json

VENDOR={'Accept':'application/vnd.api+json'}

def main():
    lab=Lab();evidence=[]
    for scenario in ['A','B','C']:
        s=lab.state['scenarios'][scenario];parent=s['workdrive']['contracts'];filename='OPTIBRAIN_TEST_PHASE16_'+scenario+'.txt'
        content=MARKER+'\nLOCAL CONTRACT PREPARATION ONLY\nScenario '+scenario+'\nAccount '+s['conversion']['Accounts']+'\nDeal '+s['conversion']['Deals']+'\nService Location '+s['site_id']+'\nSynthetic scope only. No real customer agreement, signature, work or financial obligation.\n'
        rows=lab.get('zohoapis','/workdrive/api/v1/files/'+parent+'/files',{'page[limit]':50},headers=VENDOR)['data']
        matches=[r for r in rows if r['attributes']['name']==filename]
        if len(matches)>1:raise ValueError('Duplicate WorkDrive file effects')
        if matches:
            actual=matches[0]
            if actual['id'] not in lab.ownership['records']:raise ValueError('Existing file requires independent lineage reconciliation')
        else:
            response=lab.call('workdrive-file-'+scenario,'workdrive.file.create','zohoapis','POST','/workdrive/api/v1/upload',
                {'parent_id':parent,'filename':filename,'content':content},headers=VENDOR,content_type='multipart/form-data')
            data=response.get('data',{}).get('data',[])
            if len(data)!=1:raise ValueError('Upload acknowledgment has no exact file')
            attrs=data[0].get('attributes',{});identity=str(data[0].get('id') or attrs.get('resource_id') or '')
            if not identity:raise ValueError('Upload resource ID missing')
            actual=lab.get('zohoapis','/workdrive/api/v1/files/'+identity,headers=VENDOR)['data']
            if actual['attributes']['name']!=filename or actual['attributes']['parent_id']!=parent:raise ValueError('Upload parent/name readback mismatch')
            lab.register('WorkDrive',identity,{'parent_id':parent,'action_id':lab.state['operations']['workdrive-file-'+scenario]['action_id'],'content_sha256':__import__('hashlib').sha256(content.encode()).hexdigest()})
            lab.verified('workdrive-file-'+scenario,identity,{'parent_id':parent,'filename':filename,'bytes':len(content.encode()),'external_shares':0})
        evidence.append({'scenario':scenario,'id':actual['id'],'parent_id':parent,'filename':filename,'external_shares':0})
        print('TEST file',scenario,'uploaded/read back in exact contract folder; no sharing',flush=True)
    atomic(ROOT/'workdrive-file-evidence.json',evidence)

if __name__=='__main__':main()
