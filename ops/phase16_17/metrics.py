#!/usr/bin/env python3
"""Exact root-reviewed native reporting exclusion; preserve report definitions."""
from test_lab import Lab,ROOT,RUN,atomic
import hashlib
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
import json

EDITABLE={'id','name','module','folder','show_row_count','show_detail_rows','show_wrap_text',
    'show_sub_totals','type','show_grand_total','aggregate_type','columns','joins','group_by',
    'aggregate_functions','date_filter','sort_by','sort_order','territory_filter','sub_reports','description'}
BOOLEAN_MODULES={'Leads','Contacts','Accounts','Deals','Services','Service_Locations','Tasks','Cases','Installations'}

def plan_call(lab,key,method,path,body,query=None):
    envelope=dict(service='zohoapis',method=method,path=path,body=body,headers={},content_type='application/json',query=query or {})
    path_plan=ROOT/'metric-exclusion-plan.json'
    plans=json.loads(path_plan.read_text()) if path_plan.exists() else {'schema':1,'run':RUN,'envelopes':{}}
    plans['envelopes'][digest(envelope)]={'envelope':envelope,'purpose':'TEST_ONLY exclusion; preserve all unrelated current settings'}
    atomic(path_plan,plans)
    return lab.call(key,'crm.config.test_exclusion',**envelope)

def main():
    lab=Lab()
    for module in ['Tasks','Cases','Installations']:
        fields=lab.get('zohoapis','/crm/v8/settings/fields',{'module':module})['fields']
        present=[f for f in fields if f['api_name']=='OptiBrain_Test']
        if not present:
            response=plan_call(lab,'metric-marker-'+module,'POST','/crm/v8/settings/fields',
                {'fields':[{'field_label':'OptiBrain Test','data_type':'boolean'}]},query={'module':module})
            fields=lab.get('zohoapis','/crm/v8/settings/fields',{'module':module})['fields']
            present=[f for f in fields if f['api_name']=='OptiBrain_Test']
            if len(present)!=1 or present[0]['data_type']!='boolean':raise ValueError('Native TEST marker not verified')
            lab.verified('metric-marker-'+module,present[0]['id'],{'module':module,'api_name':'OptiBrain_Test'})
        for identity,owned in list(lab.ownership['records'].items()):
            if owned['module']==module and owned['ownership']=='TEST_ONLY':
                actual=lab.crm(module,identity)
                if actual.get('OptiBrain_Test') is not True:lab.update('metric-mark-'+identity,module,identity,{'OptiBrain_Test':True})
        print('Native test marker',module,'verified',flush=True)
    reports=json.loads((ROOT/'report-definitions-before.json').read_text())
    verified=[]
    for original in reports:
        if original['module']['api_name'] not in BOOLEAN_MODULES:continue
        identity=original['id'];actual=lab.get('zohoapis','/crm/v8/Reports/'+identity)['Reports'][0]
        if 'OptiBrain_Test' not in json.dumps(actual.get('filters')):
            row={k:actual[k] for k in EDITABLE if k in actual}
            exclusion={'comparator':'not_equal','field':{'api_name':'OptiBrain_Test'},'value':True,'type':'value'}
            row['filters']={'group_operator':'and','group':[actual['filters'],exclusion]} if actual.get('filters') else exclusion
            response=plan_call(lab,'metric-report-'+identity,'PUT','/crm/v8/Reports',{'Reports':[row]})
            rows=response.get('data',{}).get('Reports',[])
            if len(rows)!=1 or rows[0].get('code')!='SUCCESS':raise ValueError('Report exclusion rejected')
            actual=lab.get('zohoapis','/crm/v8/Reports/'+identity)['Reports'][0]
            if 'OptiBrain_Test' not in json.dumps(actual.get('filters')):raise ValueError('Report exclusion readback missing')
            lab.verified('metric-report-'+identity,identity,{'module':original['module']['api_name'],'filters':actual['filters']})
        verified.append({'id':identity,'name':actual['name'],'module':original['module']['api_name'],'filters':actual['filters']})
        atomic(ROOT/'metric-reports-verified.json',verified)
        print('Native report excludes TEST_ONLY:',actual['name'],flush=True)
    titles={'Leads':'Last_Name','Contacts':'Last_Name','Accounts':'Account_Name','Deals':'Deal_Name',
        'Service_Locations':'Name','Services':'Name','Tasks':'Subject','Cases':'Subject','Installations':'Name'}
    views={}
    for module,title in titles.items():
        name='Opticable Live '+module.replace('_',' ')
        listed=lab.get('zohoapis','/crm/v8/settings/custom_views',{'module':module})['custom_views']
        found=[v for v in listed if v['name']==name]
        if not found:
            response=plan_call(lab,'metric-view-'+module,'POST','/crm/v8/settings/custom_views',
                {'custom_views':[{'name':name,'access_type':'public','criteria':{'comparator':'not_equal','field':{'api_name':'OptiBrain_Test'},'value':True},'fields':[{'api_name':title},{'api_name':'OptiBrain_Test'}]}]},query={'module':module})
            rows=response.get('data',{}).get('custom_views',[])
            if len(rows)!=1 or rows[0].get('code')!='SUCCESS':raise ValueError('Live view creation rejected')
            identity=str(rows[0]['details']['id'])
        else:
            if len(found)!=1:raise ValueError('Duplicate canonical Live view')
            identity=found[0]['id']
        actual=lab.get('zohoapis','/crm/v8/settings/custom_views/'+identity,{'module':module})['custom_views'][0]
        if actual.get('criteria',{}).get('value') is not True or actual['criteria'].get('comparator')!='not_equal':raise ValueError('Live view exclusion mismatch')
        if not found:lab.verified('metric-view-'+module,identity,{'module':module,'criteria':actual['criteria']})
        result=lab.get('zohoapis','/crm/v8/'+module,{'cvid':identity,'fields':'id,OptiBrain_Test','per_page':200})
        rows=result.get('data',[]) if isinstance(result,dict) else []
        owned={i for i,r in lab.ownership['records'].items() if r['module']==module and r['ownership']=='TEST_ONLY'}
        if any(r.get('OptiBrain_Test') is True or r['id'] in owned for r in rows):raise ValueError('Native Live view leaked TEST records')
        views[module]={'id':identity,'name':name,'test_records':0,'complete':not isinstance(result,dict) or not result.get('info',{}).get('more_records')}
        atomic(ROOT/'metric-views-verified.json',views)
        print('Native Live view',module,'TEST records = 0',flush=True)

if __name__=='__main__':main()
