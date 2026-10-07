#!/usr/bin/env python3
"""Manual exact technical request from a file; never prints credentials."""
from inventory import clients, ROOT
import json
from pathlib import Path
import sys

def main():
    request=json.loads(Path(sys.argv[1]).read_text())
    settings,_,cloudflare=clients()
    from workflow.github_api import GithubApiClient
    from workflow.automation.mutation_control import technical_admin_call
    client=GithubApiClient(settings.github) if request['provider']=='github' else cloudflare
    method=request.get('method','GET');body=request.get('body')
    if method=='GET':result=client.request(request['path'],params=request.get('query',{}))
    else:
        from workflow.automation.action_evidence import ActionEvidence
        audit=ActionEvidence('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
        aid=request.get('audit_action_id')
        with technical_admin_call(client,request['provider'],method,request['path'],body,audit=audit,action_id=aid):
            result=client.request(request['path'],method,body=body)
    output=ROOT/(request['receipt']+'.json')
    if '/' in request['receipt']:raise ValueError('Receipt name must be a basename')
    output.write_text(json.dumps(result,indent=2)+'\n')
    data=result['data']
    print(json.dumps({'http_status':result['status'],'saved':str(output),'number':data.get('number') if isinstance(data,dict) else None,'url':data.get('html_url') if isinstance(data,dict) else None}))

if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Technical request stopped: '+type(exc).__name__)
