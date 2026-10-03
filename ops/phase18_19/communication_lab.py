#!/usr/bin/env python3
"""Controlled provider Mail tests with native TEST ownership and explicit clocks."""
from live_lab import lab,activate,ROOT,RUN,REPO,MARKER
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,sys,hashlib,os

def sender(instance):
    from workflow.automation import customer_send_control as control
    from workflow.automation.customer_delivery import RootSender
    from test_lab import atomic
    control.ROOT.mkdir(mode=0o700,exist_ok=True)
    if not (control.ROOT/'state.json').exists():RootSender.initialize()
    policy={'schema':1,'external_enabled':False,'test_enabled':True,'test_run':RUN,
        'test_scopes':sorted(control.SCOPES),'real_scopes':[],'activated_at':None,
        'expires_at':(datetime.now(timezone.utc)+timedelta(hours=4)).isoformat(),
        'source_hashes':{n:hashlib.sha256((REPO/'apps/workflow-api/workflow'/n).read_bytes()).hexdigest() for n in control.SOURCES},
        'phase18_checkpoint_sha256':None,'per_family_limit':10,'per_cycle_limit':4}
    atomic(control.CONTROL,policy)
    return RootSender(instance.client,lambda:None)

def build(instance,delivery,kind,language,*,clock=None,probe=False):
    from workflow.automation import customer_communications as domain
    from workflow.automation.customer_delivery import decorate
    p=instance.state['parents'];s=instance.state['scenarios'][language]
    contact=instance.crm('Contacts',p['contact_id']);account=instance.crm('Accounts',p['account_id'])
    site=instance.crm('Service_Locations',p['site_id']);deal=instance.crm('Deals',s['deal_id'])
    visit=instance.crm('Installations',s['installation_id'])
    for record in [contact,account,site,deal,visit]:
        if record.get('OptiBrain_Test') is not True or record['id'] not in instance.ownership['records']:
            raise ValueError('Independent native TEST ownership unavailable')
    real_now=datetime.now(timezone.utc);now=clock or real_now;at=now.isoformat()
    ids={'contact_id':contact['id'],'account_id':account['id'],'deal_id':deal['id'],'site_id':site['id']}
    proof={'mode':'TEST_ONLY','test_run':RUN,'lineage_verified':True,'protected':False,**ids,
        'contact_email':contact.get('Email'),'contact_account_id':str((contact.get('Account_Name') or {}).get('id')),
        'deal_account_id':str((deal.get('Account_Name') or {}).get('id')),
        'deal_contact_id':str((deal.get('Contact_Name') or {}).get('id')),
        'deal_site_id':str((deal.get('Service_Location') or {}).get('id')),
        'site_account_id':str((site.get('Linked_Account') or {}).get('id')),
        'contact_version':contact['Modified_Time'],'deal_version':deal['Modified_Time'],'site_version':site['Modified_Time'],
        'observed_at':at,'language':language,'language_source':'owner_selection','opt_out':False}
    context={**ids,'recipient_email':contact.get('Email'),'observed_at':at,'suppression_checked_at':at,
        **{flag:False for flag in domain.STOP_FLAGS}}
    if kind=='quote':
        identifier=s['estimate_fixture_id']+('-lostack' if probe else '')
        context.update(object_id=identifier,estimate_id=identifier,estimate_number='TEST-EST-18-'+language.upper()+('-LOSTACK' if probe else ''),
            finance_integrated=False,source_kind='TEST_STATUS_EQUIVALENT',status_equivalent_fixture=True,
            finance_account_id=account['id'],finance_deal_id=deal['id'],finance_site_id=site['id'],
            status='sent',sent_at=(real_now-timedelta(days=8)).isoformat(),expiry_date=(real_now+timedelta(days=60)).date().isoformat(),deal_active=True)
        function=domain.plan_quote_reminder
    else:
        selected=instance.state['operations']['phase18-schedule-'+language]
        latest=instance.state.get('reschedules',{}).get(language)
        context.update(object_id=visit['id'],installation_id=visit['id'],installation_status=visit['Installation_Status'],
            **{'installation_'+key:value for key,value in ids.items()},timezone='America/Toronto',
            scheduled_at=visit.get('Scheduled_Date'),technician_required=True,technician_id=visit.get('Assigned_To'),
            access_instructions=visit.get('Instructions_Notes'),site_display='123 TEST Avenue, Montréal',
            human_schedule_confirmed=True,human_schedule_evidence=(latest or selected)['action_id'],
            cancelled=visit['Installation_Status']=='Cancelled',return_visit_required=visit['Installation_Status']=='Revisit Required',
            human_completion_confirmed=visit['Installation_Status']=='Completed',human_completion_evidence='manual-root-TEST-transition',
            completed_at=instance.state.get('completed_at',{}).get(language))
        function={'confirmation':domain.plan_appointment_confirmation,'reminder':domain.plan_appointment_reminder,
            'completion':domain.plan_completion_message}[kind]
    history=delivery.history()
    plan=decorate(function(context,proof,history,now,communications_enabled=True))
    source={'proof':proof,'context':context,'history':history,'plan':plan,'native_observed_at':real_now.isoformat(),
        'test_clock':now.isoformat(),'source_kind':'CONTROLLED_NATIVE_TEST_WITH_EXPLICIT_CLOCK',
        'provider_financial_writes':0,'test_run':RUN}
    return plan,source

def main():
    if len(sys.argv)!=3 or sys.argv[1] not in {'quote1','quote2','confirmation','reschedule','reminder','completion','lostack','stops','replay','kill-test','reconcile'} or sys.argv[2] not in {'fr','en'}:
        raise ValueError('Explicit quote1/quote2/confirmation/reschedule/reminder/completion/lostack/stops LANGUAGE required')
    instance=lab();activate(instance)
    # Prior identity tests used a controlled plus alias. Bind these operational
    # sends to the one exact owner mailbox allowed by the communication guard.
    contact=instance.crm('Contacts',instance.state['parents']['contact_id'])
    if contact.get('Email')!='yboucher@opticable.ca':
        instance.update('phase18-controlled-recipient','Contacts',contact['id'],
            {'Email':'yboucher@opticable.ca'},scope='crm.test.transition')
    delivery=sender(instance)
    action,language=sys.argv[1:]
    if action=='reconcile':
        from test_lab import atomic
        results=[]
        for action_id,item in list(delivery.state['effects'].items()):
            if item['state']!='verified':results.append(delivery.reconcile(action_id))
        atomic(ROOT/'communication-reconciliation.json',{'results':results,'provider_send_calls':0})
        print(json.dumps({'action':action,'results':results,'provider_send_calls':0}));return
    if action in {'replay','kill-test'}:
        from workflow.automation import customer_send_control as control
        from test_lab import atomic
        before=len(delivery.state['effects']);results=[]
        if action=='kill-test':
            policy=json.loads(control.CONTROL.read_text());policy['test_enabled']=False;atomic(control.CONTROL,policy)
        for item in delivery.state['effects'].values():
            if item['state']!='verified':raise ValueError('Reconcile unverified effect before replay')
            source=json.loads((control.ROOT/'sources'/(item['source_key']+'.json')).read_text())
            result=delivery.send(source['plan'],source)
            expected='VERIFIED_REPLAY' if action=='replay' else 'SUPPRESSED'
            if result['state']!=expected or result.get('sent'):raise ValueError('Replay or kill failed')
            results.append(result['state'])
        if before!=len(delivery.state['effects']):raise ValueError('Replay created a new effect')
        atomic(ROOT/('communication-'+action+'.json'),{'checks':len(results),'states':results,'provider_send_calls':0})
        print(json.dumps({'action':action,'checks':len(results),'provider_send_calls':0}));return
    if action=='reschedule':
        visit=instance.crm('Installations',instance.state['scenarios'][language]['installation_id'])
        date=datetime.fromisoformat(instance.state['scenarios'][language]['scheduled_at'])+timedelta(days=1)
        key='phase18-reschedule-'+language
        instance.update(key,'Installations',visit['id'],{'Scheduled_Date':date.isoformat()},scope='crm.test.transition')
        instance.state.setdefault('reschedules',{})[language]=instance.state['operations'][key];instance.save()
    if action=='completion':
        visit=instance.crm('Installations',instance.state['scenarios'][language]['installation_id'])
        key='phase18-complete-'+language
        instance.update(key,'Installations',visit['id'],{'Installation_Status':'Completed',
            'Completion_Notes':MARKER+' — synthetic human completion, no actual work or billing.'},scope='crm.test.transition')
        instance.state.setdefault('completed_at',{}).setdefault(language,datetime.now(timezone.utc).isoformat());instance.save()
    kind='quote' if action.startswith('quote') or action in {'lostack','stops'} else 'confirmation' if action=='reschedule' else action
    clock=None
    if action=='quote2':
        from workflow.automation.customer_communications import business_days_after
        identifier=instance.state['scenarios'][language]['estimate_fixture_id']
        first=[r for r in delivery.history() if r['object_id']==identifier and r.get('sequence')==1 and r['status']=='verified']
        if len(first)!=1:raise ValueError('Second reminder needs one independently verified first effect')
        clock=business_days_after(first[0]['sent_at'],5)+timedelta(seconds=1)
    if action=='reminder':
        visit=instance.crm('Installations',instance.state['scenarios'][language]['installation_id'])
        clock=datetime.fromisoformat(visit['Scheduled_Date'])-timedelta(hours=23)
    plan,source=build(instance,delivery,kind,language,clock=clock,probe=action=='lostack')
    if action=='stops':
        from workflow.automation import customer_communications as domain
        from test_lab import atomic
        results=[]
        for patch in [{'status':'accepted'},{'status':'declined'},{'deal_active':False}]+[{flag:True} for flag in domain.STOP_FLAGS]:
            value=domain.plan_quote_reminder({**source['context'],**patch},source['proof'],[],datetime.fromisoformat(source['test_clock']),communications_enabled=True)
            if value['state']!='SUPPRESSED':raise ValueError('Stop condition failed')
            results.append({'condition':list(patch)[0],'state':value['state'],'provider_send_calls':0})
        atomic(ROOT/('communication-stops-'+language+'.json'),{'checks':results,'provider_send_calls':0})
        print(json.dumps({'suppression_checks':len(results),'provider_send_calls':0}));return
    if plan['state']!='READY':raise ValueError('TEST plan not ready: '+plan['reason'])
    delivery.refresh=lambda:build(instance,delivery,kind,language,clock=clock,probe=action=='lostack')[0]
    result=delivery.send(plan,source,lost_ack=action=='lostack')
    from test_lab import atomic
    atomic(ROOT/('communication-'+action+'-'+language+'.json'),{'action':action,'language':language,'result':result,
        'family':plan['family'],'key':plan['idempotency_key'],'financial_writes':0,'native_test_bindings':plan['expected_native_bindings']})
    print(json.dumps({'action':action,'language':language,'result':result,'financial_writes':0}))

if __name__=='__main__':main()
