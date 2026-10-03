from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json, time, unittest, tempfile
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_marketing_attribution import fixture
from workflow.automation.business_intelligence import build_business, project_source, period_bounds, export_csv, render_business
from workflow.operator_phase7_api import install_phase7_canary_routes

NOW=datetime(2026,10,3,12,tzinfo=timezone.utc)


def data():
    s=fixture();s['leads'][0]['Created_Time']='2026-10-02T12:00:00-04:00'
    s['deals'][0].update(Created_Time='2026-09-01T12:00:00-04:00',Stage='Quote Sent',Amount='500',Currency='CAD',Deal_Name='Example')
    s['books_invoices'][0].update(date='2026-10-01',due_date='2026-10-02')
    s['books_estimate_index']['8'].update(date='2026-10-01',currency_code='CAD')
    s['base_currency']='CAD';s['optional_reads']={'payments':'PROVEN','expenses':'PROVEN'}
    s['payments']=[{'payment_id':'20','customer_id':'9','date':'2026-10-02','payment_status':'paid','bcy_amount':'100','bcy_refunded_amount':'10'}]
    s['expenses']=[{'expense_id':'21','total':'50'}]
    return s


class BusinessTests(unittest.TestCase):
    def view(self,s=None,**kwargs):return build_business(s or data(),now=NOW,**kwargs)
    def test_invoice_and_actual_payments_are_distinct(self):
        v=self.view();self.assertEqual(v['financial']['invoiced_gross'],{'CAD':'200'})
        self.assertEqual(v['financial']['recorded_payments_gross'],{'CAD':'100'})
        self.assertEqual(v['financial']['payment_refunds'],{'CAD':'10'})
    def test_partial_balance_and_credits_not_called_cash(self):
        s=data();s['payments']=[];s['books_invoices'][0].update(balance='100',status='partially_paid')
        v=self.view(s);self.assertEqual(v['financial']['paid_invoice_value'],{});self.assertEqual(v['financial']['recorded_payments_gross'],{})
    def test_future_recorded_payment_not_in_to_date_period(self):
        s=data();s['payments'][0]['date']='2026-10-28'
        self.assertEqual(self.view(s)['financial']['recorded_payments_gross'],{})
    def test_overdue_is_asof_stock_even_outside_invoice_period(self):
        s=data();s['books_invoices'][0].update(date='2026-09-01',balance='100',status='overdue')
        v=self.view(s);self.assertEqual(v['financial']['invoiced_gross'],{});self.assertEqual(v['financial']['overdue'],{'CAD':'100'})
    def test_draft_void_excluded_from_all_financials(self):
        for status in ('draft','void'):
            with self.subTest(status=status):
                s=data();s['books_invoices'][0]['status']=status
                v=self.view(s);self.assertEqual(v['financial']['invoiced_gross'],{});self.assertEqual(v['customer_value'],[])
    def test_conflicting_account_withheld(self):
        s=data();s['customers'][0]['zcrm_account_id']='99'
        v=self.view(s);self.assertEqual(v['financial']['invoiced_gross'],{});self.assertIn('Conflicting financial relationship withheld',v['issues'])
    def test_currency_not_combined(self):
        s=data();s['books_invoices'].append({**s['books_invoices'][0],'invoice_id':'22','currency_code':'USD'})
        self.assertEqual(self.view(s)['financial']['invoiced_gross'],{'CAD':'200','USD':'200'})
    def test_test_lineage_removes_payments_metrics_and_customers(self):
        s=data();s['accounts'][0]['OptiBrain_Test']=True
        v=self.view(s);self.assertEqual(v['financial']['invoiced_gross'],{});self.assertEqual(v['financial']['recorded_payments_gross'],{});self.assertEqual(v['customer_value'],[])
    def test_missing_cost_never_manufactures_margin(self):
        v=self.view();self.assertEqual(v['profitability']['state'],'NOT CURRENTLY MEASURABLE');self.assertIsNone(v['profitability']['gross_margin'])
    def test_missing_spend_no_roas(self):self.assertIsNone(self.view()['roas'])
    def test_pipeline_has_age_value_missing_next_action(self):
        s=data();s['deals'][0]['Amount']=None;v=self.view(s)
        self.assertEqual(v['sales']['pipeline'][0]['missing_value'],1);self.assertEqual(v['sales']['deals'][0]['age_days'],32)
        self.assertEqual(v['sales']['deals'][0]['next_action'],'Review in CRM');self.assertIsNone(v['sales']['win_rate'])
    def test_annual_active_profile_normalizes_net_before_tax(self):
        s=data();s['profiles']=[{'recurring_invoice_id':'12','customer_id':'9','status':'active','repeat_every':1,'recurrence_frequency':'years','sub_total':'1200','total':'1380','currency_code':'CAD'}]
        v=self.view(s);self.assertEqual(v['recurring']['normalized_monthly_net'],{'CAD':'100'});self.assertEqual(v['recurring']['annualized_net'],{'CAD':'1200'})
        self.assertEqual(v['recurring']['active_recurring_services'],0);self.assertEqual(v['recurring']['confidence'],'PARTIAL')
    def test_unknown_frequency_excludes_instead_of_estimates(self):
        s=data();s['profiles']=[{'recurring_invoice_id':'12','customer_id':'9','status':'active','repeat_every':1,'recurrence_frequency':'fortnights','sub_total':'1200','currency_code':'CAD'}]
        self.assertEqual(self.view(s)['recurring']['normalized_monthly_net'],{})
    def test_monthly_recurring_revenue_not_new_lead(self):
        s=data();s['profiles']=[{'recurring_invoice_id':'12','customer_id':'9','status':'active','repeat_every':1,'recurrence_frequency':'months','sub_total':'100','currency_code':'CAD'}]
        s['books_invoices'][0]['recurring_invoice_id']='12';s['generated']={'12':deepcopy(s['books_invoices'])}
        v=self.view(s);self.assertEqual(v['sales']['new_leads'],1);self.assertEqual(v['marketing'][0]['invoice_value'],{'CAD':'200'})
    def test_periods_and_toronto_midnight(self):
        n=datetime(2026,10,1,2,tzinfo=timezone.utc)
        self.assertEqual(str(period_bounds('month',n)[0]),'2026-09-01')
        for p,expected in [('today','2026-10-03'),('week','2026-09-28'),('month','2026-10-01'),('last_month','2026-09-01'),('quarter','2026-10-01'),('year','2026-01-01')]:
            with self.subTest(period=p):self.assertEqual(str(period_bounds(p,NOW)[0]),expected)
    def test_dst_and_offset_events_use_business_date(self):
        s=data();s['leads'][0]['Created_Time']='2026-10-01T02:00:00Z'
        self.assertEqual(self.view(s)['sales']['new_leads'],0)
    def test_invalid_range_denied(self):
        for start,end in [('2026-10-03','2026-10-01'),('invalid','2026-10-01'),('2000-01-01','2026-10-01')]:
            with self.subTest(start=start),self.assertRaises(ValueError):self.view(period='custom',start=start,end=end)
    def test_period_population_not_snapshot_conversion_percentage(self):
        v=self.view(period='last_month');self.assertEqual(v['sales']['new_leads'],0);self.assertIsNone(v['sales']['win_rate'])
    def test_private_projection_no_emails_clicks_or_urls(self):
        s=data();s['leads'][0].update(Email='PRIVATE',Google_GCLID='PRIVATE',First_Landing_URL='PRIVATE')
        self.assertNotIn('PRIVATE',json.dumps(project_source(s)))
    def test_read_only_projection_preserves_totals_and_source_time(self):
        s=data();before=deepcopy(s);v=self.view(s);p=self.view(project_source(s));self.assertEqual(v['financial'],p['financial']);self.assertEqual(v['observed_at'],p['observed_at']);self.assertEqual(s,before)
    def test_csv_injection_and_html_escape(self):
        s=data();s['deals'][0]['First_Source']='=FORMULA';s['deals'][0]['Deal_Name']='<script>bad</script>'
        v=self.view(s);self.assertNotIn('<script>',render_business(v))
        self.assertIn('COST DATA INCOMPLETE',export_csv(v));self.assertNotIn('\n=FORMULA',export_csv(v))
    def test_performance_uses_no_provider_reads(self):
        s=data();s['books_invoices']=[{**s['books_invoices'][0],'invoice_id':str(100+i)} for i in range(200)]
        begin=time.monotonic();v=self.view(s);render_business(v)
        self.assertLess(time.monotonic()-begin,1.0);self.assertEqual(v['invoice_count'],200)


class BusinessAuthTests(unittest.TestCase):
    def test_owner_auth_private_html_csv_and_invalid_range(self):
        class Verifier:
            def verify(self,token):
                if token!='owner':raise ValueError('denied')
                return SimpleNamespace(subject='owner',actor='owner')
        with tempfile.TemporaryDirectory() as tmp, patch('workflow.automation.today.read_internal_attention',return_value={'snapshot':project_source(data())}) as read:
            app=FastAPI();install_phase7_canary_routes(app,verifier=Verifier(),client=object(),store=SimpleNamespace(db_path=Path(tmp)/'state.db'),account_id='1',from_address='fixture@example.test',allowed_origin='https://example.test',clock=lambda:NOW)
            http=TestClient(app);headers={'Cf-Access-Jwt-Assertion':'owner'}
            self.assertEqual(http.get('/v1/operator/business').status_code,401);read.assert_not_called()
            for query in ('','?format=csv'):
                r=http.get('/v1/operator/business'+query,headers=headers);self.assertEqual(r.status_code,200);self.assertIn('no-store',r.headers['cache-control']);self.assertEqual(r.headers['x-frame-options'],'DENY')
            self.assertEqual(http.get('/v1/operator/business?period=custom&start=bad&end=bad',headers=headers).status_code,422)
            self.assertEqual(http.get('/v1/operator/business?format=json',headers=headers).status_code,422)
            read.return_value=None
            self.assertEqual(http.get('/v1/operator/business',headers=headers).status_code,503)
