#!/usr/bin/env python3
"""Add live page evidence and unsent briefs to the existing acquisition lab."""
import json,os,sys,pwd
from datetime import datetime,timezone
from pathlib import Path
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO/'apps/workflow-api'))
ROOT=Path('/var/lib/optibrain/acquisition-intelligence');EVIDENCE=Path('/home/optibrain/phase28-29-evidence')

def main():
    if os.geteuid()!=0:raise ValueError('Manual private source assembly required')
    os.umask(0o077)
    from workflow.automation.acquisition_store import AcquisitionStore
    from workflow.automation.acquisition_ingest import ingest
    from workflow.automation.seo_intelligence import enrich
    inputs=json.loads((ROOT/'inputs.json').read_text());inputs['website']=json.loads((EVIDENCE/'website-raw.json').read_text());inputs['market_research']=json.loads((ROOT/'phase29-market-research.json').read_text())
    (ROOT/'inputs.json').write_text(json.dumps(inputs,ensure_ascii=False));(ROOT/'inputs.json').chmod(0o600)
    now=datetime.now(timezone.utc);store=AcquisitionStore(ROOT/'lab.sqlite');view=enrich(store,inputs,ingest(store,inputs,now=now),now=now)
    store.prune(now);view.update(store.summary(now));(ROOT/'phase29-lab.json').write_text(json.dumps(view,ensure_ascii=False))
    queue=EVIDENCE/'content-queue.json';queue.write_text(json.dumps(view['content_queue'],indent=2,ensure_ascii=False));queue.chmod(0o600)
    owner=pwd.getpwnam('optibrain');os.chown(queue,owner.pw_uid,owner.pw_gid)
    print(json.dumps({'counts':view['counts'],'snapshot_count':view['snapshots'],'daily_history':view['daily_history_rows'],'technical':{k:v for k,v in view['technical_seo'].items() if k not in ('issues','orphan_candidates')},'content':[(r['decision'],r['title'],r['score']) for r in view['content_queue'][:8]],'queue_count':len(view['content_queue']),'paid':len(view['paid_opportunities'])},ensure_ascii=False))

if __name__=='__main__':main()
