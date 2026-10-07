"""Comparable bounded observations; no load generator or stress test."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import time
from urllib.request import Request, urlopen

from common import command, env_file, now


def baseline(manager_ms=None):
    env=env_file('/etc/opticable-workflow-api.env')
    headers={'X-API-Key':env[env.get('SITE_WORKFLOW_API_KEY_ENV','SITE_WORKFLOW_API_KEY')]}
    latency=[]
    for _ in range(5):
        started=time.monotonic()
        with urlopen(Request('http://127.0.0.1:8100/v1/system/health',headers=headers),timeout=15) as response:
            value=json.load(response)
        latency.append(round((time.monotonic()-started)*1000,3))
    usage=shutil.disk_usage('/');memory={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        k,v=line.split(':',1)
        if k in ('MemTotal','MemAvailable','SwapTotal','SwapFree'):memory[k]=int(v.strip().split()[0])*1024
    jobs={}
    for name in ('optibrain-backup','optibrain-phase2a-upload','opticable-lifecycle-internal',
                 'opticable-phase9-intake-receipts','opticable-phase10-service-events','opticable-phase12-test-runner'):
        raw=command(['systemctl','show',name+'.service','-p','ExecMainStartTimestampMonotonic',
                     '-p','ExecMainExitTimestampMonotonic','-p','Result'])
        data=dict(r.split('=',1) for r in raw.splitlines() if '=' in r)
        start=int(data.get('ExecMainStartTimestampMonotonic') or 0);end=int(data.get('ExecMainExitTimestampMonotonic') or 0)
        jobs[name]={'last_duration_ms':round((end-start)/1000,3) if end>=start and start else None,'result':data.get('Result')}
    providers=[]
    path=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        for job,at,raw in db.execute('SELECT job,recorded_at,summary_json FROM provider_usage ORDER BY id DESC LIMIT 30'):
            data=json.loads(raw)
            providers.append({'job':job,'at':at,'duration_ms':data.get('duration_ms'),
                              'calls':data.get('calls'),'status':data.get('status')})
    return {'schema':1,'at':now(),'source_sha':command(['git','-c','safe.directory=/opt/opticable-api-platform','-C','/opt/opticable-api-platform','rev-parse','HEAD']),
            'api_version':value['version'],'cpu_count':os.cpu_count(),'load_average':list(os.getloadavg()),
            'memory_bytes':memory,'disk_bytes':{'total':usage.total,'used':usage.used,'free':usage.free},
            'api_latency_ms':{'samples':latency,'median':statistics.median(latency),'max':max(latency)},
            'manager_render_ms':manager_ms,'manager_http_authenticated_ms':None,
            'manager_limit':'Owner Access session unavailable to automation; provider-free copied-state render measured separately',
            'scheduled_jobs':jobs,'provider_collector_samples':providers,'destructive_stress_tests':0}


def compare(before,after):
    rows={}
    measurements={'api_median_ms':(before['api_latency_ms']['median'],after['api_latency_ms']['median'],False),
        'manager_render_ms':(before.get('manager_render_ms'),after.get('manager_render_ms'),False),
        'free_disk_bytes':(before['disk_bytes']['free'],after['disk_bytes']['free'],True),
        'available_ram_bytes':(before['memory_bytes']['MemAvailable'],after['memory_bytes']['MemAvailable'],True)}
    if before.get('cpu_count') and after.get('cpu_count'):
        measurements['load_per_vcpu']=(before['load_average'][0]/before['cpu_count'],
                                        after['load_average'][0]/after['cpu_count'],False)
    for job in sorted(set(before.get('scheduled_jobs',{})) & set(after.get('scheduled_jobs',{}))):
        measurements['scheduled_'+job+'_ms']=(before['scheduled_jobs'][job]['last_duration_ms'],
                                               after['scheduled_jobs'][job]['last_duration_ms'],False)
    def latest(rows):
        result={}
        for row in rows:result.setdefault(row['job'],row.get('duration_ms'))
        return result
    first=latest(before.get('provider_collector_samples',[]));second=latest(after.get('provider_collector_samples',[]))
    for job in sorted(set(first)&set(second)):
        measurements['collector_'+job+'_ms']=(first[job],second[job],False)
    for name,(old,new,higher_better) in measurements.items():
        state='UNKNOWN';ratio=None
        if old is not None and new is not None and old>0:
            ratio=new/old;state='SIMILAR' if .85<=ratio<=1.15 else 'BETTER' if (ratio>1)==higher_better else 'WORSE'
        rows[name]={'before':old,'after':new,'ratio':ratio,'assessment':state}
    return {'schema':1,'at':now(),'measurements':rows,'threshold':'±15% similar; observational baseline, not workload-normalized capacity proof'}
