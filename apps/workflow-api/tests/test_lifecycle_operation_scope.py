import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from workflow.automation import lifecycle_control as lc
from workflow.automation import real_internal as ri
from workflow.automation.lifecycle import OWNER

NOW=datetime.now(timezone.utc).replace(microsecond=0)
ACT=(NOW-timedelta(hours=1)).isoformat()
RUN='narrow-operations-fixture'


class LifecycleOperationScopeTests(unittest.TestCase):
    def setUp(self):
        self.registry={'records':{
            '500':{'module':'Services','ownership':'REAL_NEW','run':RUN,'created_at':NOW.isoformat(),'source':'ai_website'},
            '600':{'module':'Installations','ownership':'REAL_NEW','run':RUN,'created_at':NOW.isoformat(),'source':'ai_website'},
            '201':{'module':'Deals','ownership':'REAL_NEW','run':RUN,'created_at':NOW.isoformat(),'source':'ai_website'},
            '400':{'module':'Service_Locations','ownership':'REAL_NEW','run':RUN,'created_at':NOW.isoformat(),'source':'ai_website'},
            '200':{'module':'Accounts','ownership':'REAL_NEW','run':RUN,'created_at':NOW.isoformat(),'source':'ai_website'},
            '300':{'module':'Contacts','ownership':'REAL_NEW','run':RUN,'created_at':NOW.isoformat(),'source':'ai_website'},
        }}
        self.policy={'test_run':RUN,'activated_at':ACT,'approved_sources':['ai_website'],
            'real_scopes':sorted(lc.REAL_SCOPES),'test_scopes':[]}
        self.baseline={'modules':{'Services':{'protected_versions':{'999':'version1'}}}}
        self.source=None;self.auth=None
        self.patches=[patch.object(lc.os,'geteuid',return_value=0),
            patch.object(lc,'read_policy',return_value=self.policy),patch.object(lc,'trusted_json',side_effect=self.read)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
    def read(self,path,*args):
        if path==lc.REAL_REGISTRY:return self.registry
        if path==lc.BASELINE:return self.baseline
        if path.parent==lc.REAL_ROOT/'authorizations':return self.auth
        if path.parent==lc.REAL_ROOT/'sources':return self.source
        raise AssertionError('Unexpected authority read')
    def request(self,module,row,scope,*,target=None):
        path='/crm/v8/'+module+('/'+target if target else '')
        headers={'If-Unmodified-Since':NOW.isoformat()} if target else {}
        if target:row={'id':target,**row}
        lc.validate_request('zohoapis','PUT' if target else 'POST',path,
            {'data':[row],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]},headers,
            'application/json',{},scope=scope,mode='REAL_NEW',run=RUN)
    def service(self):
        return {'Name':'Structured Cabling — New accepted work','Linked_Service_Location':{'id':'400'},
            'Linked_Deal':{'id':'201'},'Service_Type':'Cabling Installation','Service_Stage':'Ready for Scheduling'}
    def completion_source(self):
        return {'eligible':True,'kind':'installation_completed','source':'ai_website','occurred_at':NOW.isoformat(),
            'record':{'id':'600','Installation_Status':'Completed','Completion_Notes':'Verified physical work'},
            'timeline':[{'id':'owner-event','record':{'id':'600','module':{'api_name':'Installations'}},
                'audited_time':NOW.isoformat(),'source':'crm_ui','done_by':{'id':OWNER},
                'field_history':[{'api_name':'Installation_Status','_value':{'old':'In Progress','new':'Completed'}}]}]}
    def effect(self):
        return lc.LifecycleEffect(RUN+':complete-service-500',{'service':'zohoapis','method':'PUT',
            'path':'/crm/v8/Services/500','body':{'data':[{'id':'500','Service_Stage':'Active'}],'trigger':[]},
            'headers':{'If-Unmodified-Since':NOW.isoformat()},'content_type':'application/json','query':{}})
    def authorize(self,effect,source,scope='crm.service.activate'):
        self.source=source
        self.auth={'family':'REAL_LEAD_INTERNAL_AUTOMATION_V1','eligible':True,'run':RUN,
            'scope':scope,'action_id':effect.action_id,'payload_hash':effect.payload_hash,
            'policy_hash':lc.digest(self.policy),'source_key':lc.digest(source),'source_hash':lc.digest(source),
            'expires_at':(NOW+timedelta(minutes=5)).isoformat()}

    def test_original_service_scope_only_creates_prepared_not_active_or_dated(self):
        self.request('Services',self.service(),'crm.service.create')
        for change in ({'Service_Stage':'Active'},{'OptiBrain_Installed_On':'2026-10-03'},
                       {'OptiBrain_Last_Service_On':'2026-10-03'},{'Service_Stage':'Suspended'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.request('Services',{**self.service(),**change},'crm.service.create')
        for change in ({'Service_Stage':'Ready for Scheduling'},{'Service_Stage':'Active'},
                       {'OptiBrain_Last_Service_On':'2026-10-03'}):
            with self.subTest(update=change),self.assertRaises(ValueError):
                self.request('Services',change,'crm.service.create',target='500')

    def test_activation_scope_is_conditional_update_only_and_cannot_reparent_or_price(self):
        self.request('Services',{'Service_Stage':'Active','OptiBrain_Last_Service_On':'2026-10-03'},
            'crm.service.activate',target='500')
        for change in ({'Name':'Other service'},{'Linked_Deal':{'id':'201'}},{'Service_Type':'Other'},
                       {'Amount':100},{'OptiBrain_Test':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.request('Services',{'Service_Stage':'Active',**change},'crm.service.activate',target='500')
        with self.assertRaises(ValueError):self.request('Services',{'Service_Stage':'Active'},'crm.service.activate')

    def test_activation_scope_cannot_be_used_for_any_other_module(self):
        for module,row,target in [('Installations',{'Installation_Status':'Completed'},'600'),
                ('Deals',{'Stage':'Contracts In Progress'},'201'),('Tasks',{'Subject':'Attention'},None),
                ('Cases',{'Subject':'Issue','Status':'New','Case_Origin':'Web'},None)]:
            with self.subTest(module=module),self.assertRaises(ValueError):
                self.request(module,row,'crm.service.activate',target=target)

    def test_original_installation_scope_creates_unscheduled_requested_visits_only(self):
        row={'Name':'Installation','Linked_Service':{'id':'500'},'Installation_Status':'Requested'}
        self.request('Installations',row,'crm.installation.prepare')
        for change in ({'Installation_Status':'Completed'},{'Installation_Status':'Scheduled'},
                       {'Scheduled_Date':NOW.isoformat()},{'Assigned_To':'technician'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.request('Installations',{**row,**change},'crm.installation.prepare')
        for status in ('Requested','Completed','Scheduled','Revisit Required'):
            with self.subTest(status=status),self.assertRaises(ValueError):
                self.request('Installations',{'Installation_Status':status},'crm.installation.prepare',target='600')

    def test_protected_and_reference_service_targets_cannot_activate(self):
        self.registry['records']['999']={**self.registry['records']['500']}
        with self.assertRaisesRegex(ValueError,'Protected'):
            self.request('Services',{'Service_Stage':'Active'},'crm.service.activate',target='999')
        self.registry['records']['500']['ownership']='REAL_REFERENCE'
        with self.assertRaises(ValueError):
            self.request('Services',{'Service_Stage':'Active'},'crm.service.activate',target='500')

    def test_activation_requires_latest_matching_native_owner_completion_source(self):
        effect=self.effect();self.authorize(effect,self.completion_source())
        lc.check_real_effect(effect,'crm.service.activate',RUN)
        for change in ('other module','other record','API','other actor','older cutoff','latest API'):
            with self.subTest(change=change):
                source=self.completion_source();event=source['timeline'][0]
                if change=='other module':event['record']['module']['api_name']='Leads'
                elif change=='other record':event['record']['id']='601'
                elif change=='API':event['source']='crm_api'
                elif change=='other actor':event['done_by']['id']='another-owner'
                elif change=='older cutoff':event['audited_time']=(NOW-timedelta(hours=2)).isoformat()
                else:
                    later=copy.deepcopy(event);later['source']='crm_api';later['audited_time']=(NOW+timedelta(seconds=1)).isoformat()
                    source['timeline'].append(later)
                self.authorize(effect,source)
                with self.assertRaises(ValueError):lc.check_real_effect(effect,'crm.service.activate',RUN)

    def test_stale_or_changed_root_activation_authorization_does_not_grant_effect(self):
        effect=self.effect();self.authorize(effect,self.completion_source())
        self.auth['expires_at']=(NOW-timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):lc.check_real_effect(effect,'crm.service.activate',RUN)
        self.authorize(effect,self.completion_source());self.source['record']['Completion_Notes']='Changed after intent'
        with self.assertRaises(ValueError):lc.check_real_effect(effect,'crm.service.activate',RUN)

    def test_return_visit_effect_independently_requires_latest_matching_native_owner_transition(self):
        source=self.completion_source();source['kind']='installation_return_visit'
        source['record']['Installation_Status']='Revisit Required'
        source['record']['Instructions_Notes']='Site not ready; return required'
        source['timeline'][0]['field_history'][0]['_value']['new']='Revisit Required'
        effect=lc.LifecycleEffect(RUN+':return-visit',{'service':'zohoapis','method':'POST',
            'path':'/crm/v8/Installations','body':{'data':[{'Name':'Return visit','Installation_Status':'Requested',
            'Linked_Service':{'id':'500'}}],'trigger':[]},'headers':{},'content_type':'application/json','query':{}})
        self.authorize(effect,source,'crm.installation.prepare')
        lc.check_real_effect(effect,'crm.installation.prepare',RUN)
        for change in ('API','other module','other record','other actor','unapproved source','wrong desired','latest API'):
            with self.subTest(change=change):
                value=copy.deepcopy(source);event=value['timeline'][0]
                if change=='API':event['source']='crm_api'
                elif change=='other module':event['record']['module']['api_name']='Services'
                elif change=='other record':event['record']['id']='601'
                elif change=='other actor':event['done_by']['id']='another-owner'
                elif change=='unapproved source':value['source']='unapproved_intake'
                elif change=='wrong desired':event['field_history'][0]['_value']['new']='Completed'
                else:
                    later=copy.deepcopy(event);later['source']='crm_api';later['audited_time']=(NOW+timedelta(seconds=1)).isoformat()
                    value['timeline'].append(later)
                self.authorize(effect,value,'crm.installation.prepare')
                with self.assertRaises(ValueError):lc.check_real_effect(effect,'crm.installation.prepare',RUN)

    def test_existing_scopes_keep_human_qualification_pricing_and_parent_creation_denied(self):
        for module,row,scope in [('Leads',{'Last_Name':'Person','Lead_Status':'Pre-Qualified'},'crm.lead.intake'),
                ('Deals',{'Deal_Name':'Work','Amount':100},'crm.deal.prepare'),
                ('Accounts',{'Account_Name':'Company'},'crm.account.create'),
                ('Contacts',{'Last_Name':'Person'},'crm.contact.create')]:
            with self.subTest(module=module),self.assertRaises(ValueError):self.request(module,row,scope)

    def test_site_preparation_cannot_link_original_account_after_owner_changes_deal_parent(self):
        for changed in ('Account_Name','Contact_Name'):
            with self.subTest(changed=changed):
                engine=object.__new__(ri.Engine);engine.dry_run=False
                engine.state={'deals':{'201':{'account_id':'200','contact_id':'300','source':'ai_website',
                    'site_address':{'street':'123 Main Street','unit':'','city':'Montréal','province':'QC','postal_code':'H1A1A1','country':'Canada'}}},'attention':{}}
                deal={'id':'201','Deal_Name':'Accepted work','Created_Time':NOW.isoformat(),
                      'Account_Name':{'id':'200'},'Contact_Name':{'id':'300'}}
                deal[changed]={'id':'999'}
                engine.list=Mock(return_value=[]);engine.record=Mock(return_value=deal)
                engine.create=Mock(return_value={'id':'400'});engine.update=Mock();engine.trigger=Mock();engine.save=Mock()
                engine.sites()
                self.assertIn('site:201',engine.state['attention'])
                engine.create.assert_not_called();engine.update.assert_not_called();engine.trigger.assert_not_called()
