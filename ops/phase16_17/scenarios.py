#!/usr/bin/env python3
"""Bounded live TEST relationships; no Finance transaction or real customer effect."""
from test_lab import Lab,MARKER,ROOT,atomic
from datetime import datetime,timezone
import json
import sys

def prepare(lab,scenario):
    from workflow.automation.lifecycle import site_match,accepted_plan,site_fields,SITE_FIELDS
    ids=lab.state['scenarios'][scenario]['conversion'];account=ids['Accounts'];contact=ids['Contacts'];deal=ids['Deals']
    public=lab.state['public-'+scenario]['receipt']['request']
    address={'street':'123 TEST Avenue','unit':'Unit '+('2' if scenario=='B' else '1'),
        'city':'Montréal','province':'Quebec','postal_code':'H1A 1A1','country':'Canada'}
    sites=lab.lists('Service_Locations','id,Name,Linked_Account,Service_Location_Address,OptiBrain_Test,'+','.join(SITE_FIELDS.values()))
    decision=site_match(sites,account,address)
    if decision['decision']=='HUMAN':raise ValueError(decision['reason'])
    if decision['decision']=='REUSE':
        site=lab.crm('Service_Locations',decision['record']['id'])
        if site['id'] not in lab.ownership['records']:raise ValueError('Site reuse lacks TEST ownership')
    else:
        site=lab.create('site-'+scenario,'Service_Locations',{'Name':MARKER+' — Site '+('A' if scenario=='C' else scenario),
            'Linked_Account':{'id':account},'Primary_Contact':{'id':contact},**site_fields(address),'OptiBrain_Test':True})
    site_id=str(site['id'])
    lab.state['scenarios'][scenario]['site_id']=site_id;lab.save()
    if scenario=='C' and site_id!=lab.state['scenarios']['A']['site_id']:raise ValueError('Existing site not reused')
    lab.update('deal-site-'+scenario,'Deals',deal,{'Service_Location':{'id':site_id}})
    actual_deal=lab.crm('Deals',deal)
    plan=accepted_plan(public['service'],account_id=account,deal_id=deal,site_id=site_id)
    if plan['decision']!='PREPARE_INTERNAL':raise ValueError('Ambiguous accepted synthetic scope')
    # Explicit status-equivalent TEST acceptance. No Books transaction is created.
    lab.state['scenarios'][scenario]['estimate_equivalent']={'ownership':'TEST_ONLY','kind':'local status-equivalent','status':'accepted','financial_writes':0,'native_estimate_created':False}
    lab.save()
    existing=lab.lists('Services','id,Linked_Deal,Linked_Service_Location,Service_Type,OptiBrain_Test')
    services=[]
    for spec in plan['services']:
        matches=[r for r in existing if str((r.get('Linked_Deal') or {}).get('id'))==deal
            and str((r.get('Linked_Service_Location') or {}).get('id'))==site_id and r.get('Service_Type')==spec['type']]
        if len(matches)>1:raise ValueError('Duplicate service effects')
        if matches:
            service=lab.crm('Services',matches[0]['id'])
            if service['id'] not in lab.ownership['records']:raise ValueError('Service lacks TEST lineage')
        else:
            service=lab.create('service-'+scenario+'-'+spec['type'],'Services',{'Name':MARKER+' — '+scenario+' — '+spec['label'],
                'Linked_Deal':{'id':deal},'Linked_Service_Location':{'id':site_id},'Service_Type':spec['type'],
                'Service_Stage':'Ready for Scheduling','OptiBrain_Test':True})
        services.append(str(service['id']))
    account_folder=lab.state['workdrive_account']
    general=lab.folder('general-folder','General',account_folder)
    folder=lab.folder('site-folder-'+site_id,MARKER+' — Site '+('B' if scenario=='B' else 'A'),account_folder)
    contracts=lab.folder('contracts-folder-'+site_id,'Contracts',folder['id'])
    account_actual=lab.crm('Accounts',account)
    if account_actual.get('Main_Workdrive_Folder_ID')!=account_folder:
        lab.update('account-folder-link','Accounts',account,{'Main_Workdrive_Folder_ID':account_folder,
            'Main_Workdrive_Folder_URL':'https://workdrive.zoho.com/folder/'+account_folder})
    if site.get('Service_Location_Workdrive_Folder_ID')!=folder['id']:
        lab.update('site-folder-link-'+site_id,'Service_Locations',site_id,{'Service_Location_Workdrive_Folder_ID':folder['id'],
            'Service_Location_Workdrive_Folder_URL':'https://workdrive.zoho.com/folder/'+folder['id']})
    installations=lab.lists('Installations','id,Linked_Service,Installation_Status')
    matches=[r for r in installations if str((r.get('Linked_Service') or {}).get('id'))==services[0]]
    if len(matches)>1:raise ValueError('Duplicate Installation effects')
    if matches:
        installation=lab.crm('Installations',matches[0]['id'])
        if installation['id'] not in lab.ownership['records']:raise ValueError('Installation not owned')
    else:
        installation=lab.create('installation-'+scenario,'Installations',{'Name':MARKER+' — Installation '+scenario,
            'Linked_Service':{'id':services[0]},'Installation_Status':'Requested','OptiBrain_Test':True,
            'Instructions_Notes':MARKER+' — UNSCHEDULED. Human selects schedule and technician. No customer notification.'})
    existing_links=lab.lists('Installation_X_Services','id,Linked_Installation,Linked_Service')
    for identity in services:
        found=[r for r in existing_links if str((r.get('Linked_Installation') or {}).get('id'))==installation['id']
            and str((r.get('Linked_Service') or {}).get('id'))==identity]
        if len(found)>1:raise ValueError('Duplicate Installation-Service links')
        if not found:
            lab.create('installation-link-'+identity,'Installation_X_Services',{'Name':MARKER+' — '+scenario+' — '+identity,
                'Linked_Installation':{'id':str(installation['id'])},'Linked_Service':{'id':identity}})
    if 'schedule_task' not in lab.state['scenarios'][scenario]:
        task=lab.create('schedule-task-'+scenario,'Tasks',{'Subject':MARKER+' — Schedule Installation '+scenario,
            'What_Id':{'id':str(installation['id'])},'$se_module':'Installations','Who_Id':{'id':contact},
            'Status':'Not Started','Description':MARKER+' — Human scheduling, no external confirmation.',
            'Send_Notification_Email':False,'OptiBrain_Test':True})
        lab.state['scenarios'][scenario]['schedule_task']=str(task['id'])
    lab.state['scenarios'][scenario].update(service_ids=services,installation_id=str(installation['id']),
        workdrive={'account':account_folder,'general':general['id'],'site':folder['id'],'contracts':contracts['id']},
        accepted_plan=plan,contract={'state':'LOCAL_PREPARED_ONLY','provider_send':False,'provider_license':'API send unavailable','account_id':account,'contact_id':contact,'deal_id':deal,'site_id':site_id})
    lab.save()
    print('Scenario',scenario,'site',site_id,decision['decision'],'Services',len(services),'Installation',installation['id'],'WorkDrive verified',flush=True)

def complete(lab,scenario):
    s=lab.state['scenarios'][scenario];identity=s['installation_id']
    if s.get('completion'):
        if lab.crm('Installations',identity)['Installation_Status']!='Completed' or any(lab.crm('Services',i)['Service_Stage']!='Active' for i in s['service_ids']):
            raise ValueError('Completed provider lifecycle drifted; reconciliation only')
        print('Completion replay',scenario,'read-only; no provider mutation',flush=True)
        return
    lab.update('schedule-'+scenario,'Installations',identity,{'Installation_Status':'Scheduled','Scheduled_Date':'2026-10-05T10:00:00-04:00',
        'Assigned_To':'OPTIBRAIN TEST TECHNICIAN','Instructions_Notes':MARKER+' — Human-selected TEST time, technician and access instructions.'},scope='crm.test.transition')
    lab.update('progress-'+scenario,'Installations',identity,{'Installation_Status':'In Progress'},scope='crm.test.transition')
    lab.update('complete-'+scenario,'Installations',identity,{'Installation_Status':'Completed','Completion_Notes':MARKER+' — Synthetic field completion; no actual work or billing.'},scope='crm.test.transition')
    for sid in s['service_ids']:lab.update('service-active-'+sid,'Services',sid,{'Service_Stage':'Active'})
    lab.update('schedule-task-complete-'+scenario,'Tasks',s['schedule_task'],{'Status':'Completed'})
    s['completion']={'status':'Completed','human_simulation':True,'billing_attention':'HUMAN Invoice only','support_eligibility':True,'review_send':False,'renewal_eligibility':'observe only; no fabricated expiry'};lab.save()
    print('Scenario',scenario,'installation completion, active Services and internal support/billing attention verified',flush=True)

def main():
    if len(sys.argv)!=3 or sys.argv[1] not in {'prepare','complete'} or sys.argv[2] not in {'A','B','C'}:raise ValueError('Explicit bounded scenario required')
    lab=Lab()
    (prepare if sys.argv[1]=='prepare' else complete)(lab,sys.argv[2])

if __name__=='__main__':main()
