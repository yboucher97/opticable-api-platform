"""Protected local demonstration using reviewed candidate capture functions.

No real form fields,provider iframe,analytics tag or customer endpoint is present.
"""
from hashlib import sha256
from html import escape
from pathlib import Path
import json
import re


def build(source):
    source=Path(source);text=source.read_text()
    functions=[]
    for name in ('inquiryAttemptId','appendLeadAttributionToUrl','safeAnalyticsValue','pushSiteEvent'):
        match=re.search(r'^function '+name+r'\(.*?^}',text,re.M|re.S)
        if not match:raise ValueError('Reviewed native function missing: '+name)
        functions.append(match.group())
    script="""const inquiryAttemptMemory={};const siteAnalyticsId='LOCAL_TEST_SINK';window.dataLayer=[];
function hasSiteMeasurementConsent(){return document.querySelector('#consent').checked;}
function appendAttributionToUrl(raw){return raw;}
function getSiteAttribution(){return {first_source:'STAGING_ONLY',first_campaign:'camera-scope',first_campaign_id:'fixture-campaign'};}
function loadSiteMeasurement(){} function loadSiteAnalytics(){} function analyticsPageLocation(){return location.origin+location.pathname;}
window.gtag=(...args)=>dataLayer.push(args);
"""+'\n'.join(functions)+"""
let seen=new Set();
document.querySelector('#simulate').addEventListener('click',()=>{
 const url=appendLeadAttributionToUrl('https://example.invalid/NO_SUBMISSION',{origin_service:'security-camera-systems'});
 const captured=JSON.parse(new URL(url).searchParams.get('ob_attribution')||'{}');
 const id=captured.attribution?.inquiry_id;
 if(id&&!seen.has(id)){seen.add(id);pushSiteEvent('site_native_form_success',{form_name:'LOCAL_FIXTURE_ONLY',inquiry_id:id});}
 document.querySelector('#result').textContent=JSON.stringify({environment:'ISOLATED_STAGING',captured,logical_inquiries:seen.size,local_events:dataLayer,network_sends:0},null,2);
});
document.querySelector('#new').addEventListener('click',()=>{sessionStorage.removeItem('opticable_inquiry_attempt_v1_en');delete inquiryAttemptMemory.en;});
"""
    manifest={'source':'sitegen_data.py','source_sha256':sha256(source.read_bytes()).hexdigest(),
              'functions':[{'name':n,'sha256':sha256(f.encode()).hexdigest()} for n,f in zip(('inquiryAttemptId','appendLeadAttributionToUrl','safeAnalyticsValue','pushSiteEvent'),functions)],
              'state':'PROTECTED_LOCAL_ONLY','provider_calls':0,'customer_fields':False,'deployment_authorized':False}
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Opticable tracking correction — isolated review</title><style>body{font:18px/1.5 system-ui;max-width:1000px;margin:30px auto;padding:20px;background:#10251b;color:#f4faf6}button,input{min-height:44px;font:inherit;margin:12px;padding:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#8df1b2}</style></head><body><h1>Inquiry correlation — isolated tracking review</h1><p>This simulation uses candidate capture code. There are no customer fields,submissions,advertising tags or external analytics connections.</p><label><input id="consent" type="checkbox"> Simulate existing analytics consent</label><p><button id="simulate">Simulate local acknowledgement</button><button id="new">Start another synthetic inquiry</button></p><pre id="result" role="status">No simulation yet.</pre><a href="manifest.json">Exact source/function hashes</a><script>'''+script+'</script></body></html>'
    return html,manifest
