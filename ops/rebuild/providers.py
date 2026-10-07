"""Bounded identity/read probes using existing clients. Never return provider bodies."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from common import REPO, RebuildError, env_file, require


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def bounded_get(url, headers=None):
    require(url.startswith(('https://api.github.com/', 'https://api.cloudflare.com/',
                            'https://www.googleapis.com/', 'https://analyticsadmin.googleapis.com/')),
            'provider_origin_not_allowed')
    with build_opener(NoRedirect()).open(Request(url, headers=headers or {}, method='GET'), timeout=20) as response:
        raw = response.read(1024*1024+1)
        require(len(raw) <= 1024*1024, 'provider_response_too_large')
        return json.loads(raw)


def probe_all(*, manifest, app_repo=Path('/opt/opticable-api-platform'), environment=None):
    """Use private disposable OAuth copies; leave restored/source credentials intact."""
    import dataclasses
    import shutil
    import tempfile
    if environment is not None: os.environ.update(environment)
    else: os.environ.update(env_file('/etc/opticable-workflow-api.env'))
    sys.path.insert(0,str(app_repo/'apps/workflow-api'))
    from workflow.config import load_settings
    from workflow.zoho_oauth import ZohoOAuthManager
    settings=load_settings()
    with tempfile.TemporaryDirectory(prefix='rebuild-provider-binding-') as temporary:
        directory=Path(temporary)
        zoho_path=directory/'zoho.json';google_path=directory/'google.json'
        for source,dest in ((settings.zoho_oauth.credentials_path,zoho_path),(settings.google_oauth.credentials_path,google_path)):
            if source.is_file():shutil.copyfile(source,dest);dest.chmod(0o600)
        cache=directory/'zoho-cache.json'
        current=ZohoOAuthManager(settings.zoho_oauth).cache_path
        if current.is_file():shutil.copyfile(current,cache);cache.chmod(0o600)
        zoho=dataclasses.replace(settings.zoho_oauth,credentials_path=zoho_path,access_cache_path=cache)
        google=dataclasses.replace(settings.google_oauth,credentials_path=google_path)
        return _probe_all(manifest=manifest,app_repo=app_repo,settings=dataclasses.replace(settings,zoho_oauth=zoho,google_oauth=google))


def _probe_all(*, manifest, app_repo, settings):
    # No owner JWT, mail body fetch, form submission, enrichment, or mutation probe.
    results = {}

    def test(name, function):
        started = time.monotonic()
        try:
            facts = function()
            results[name] = {'status':'PASS','read_only':True,'duration_ms':round((time.monotonic()-started)*1000),
                             'evidence':facts or {'authenticated_read':True}}
        except Exception as exc:
            response = getattr(exc,'response',None)
            code = getattr(response,'status_code',None) or getattr(exc,'code',None)
            results[name] = {'status':'BLOCKED','read_only':True,'duration_ms':round((time.monotonic()-started)*1000),
                             'error_type':type(exc).__name__,'http_status':code,'owner_action_required':code in (401,403)}

    def github():
        from workflow.github_api import GithubApiClient
        require(str(settings.github.app_id)=='5077440' and str(settings.github.installation_id)=='164914980', 'github_identity_mismatch')
        client=GithubApiClient(settings.github)
        # JWT-authenticated metadata GETs; installation token exchange is auth only.
        headers=client._headers(client._app_jwt())
        app=bounded_get('https://api.github.com/app',headers)
        installation=bounded_get('https://api.github.com/app/installations/164914980',headers)
        require(app.get('id')==5077440 and app.get('name')=='OptiBrain Production'
                and installation.get('id')==164914980 and installation.get('app_id')==5077440
                and installation.get('account',{}).get('login')=='yboucher97','github_identity_readback_failed')
        data=client.request('/repos/yboucher97/opticable-api-platform')['data']
        require(data.get('full_name')=='yboucher97/opticable-api-platform','github_repository_access_failed')
        return {'app_id':app['id'],'installation_id':installation['id'],'repository':data['full_name'],'auth_exchanges_only':True}
    test('GITHUB',github)

    def cloudflare():
        from workflow.cloudflare_api import CloudflareApiClient
        client=CloudflareApiClient(settings.cloudflare)
        account=settings.cloudflare.account_id
        require(account==manifest['provider_identities']['CLOUDFLARE_ACCOUNT_ID'],'cloudflare_account_mismatch')
        data=client.request('/accounts/'+account)['data']
        require(data.get('success') is True and data.get('result',{}).get('id')==account,'cloudflare_account_readback_failed')
        scripts=client.request('/accounts/'+account+'/workers/scripts')['data']
        require(scripts.get('success') is True,'cloudflare_worker_read_failed')
        return {'account_id':account,'workers_read':True}
    test('CLOUDFLARE',cloudflare)

    def builds():
        from workflow.automation.website_preview_cloudflare_safety import CloudflareBuildsReadHTTP, ACCOUNT
        transport=CloudflareBuildsReadHTTP(maximum=6)
        verified,_=transport.read('/user/tokens/verify')
        require(verified.get('status')=='active','cloudflare_builds_binding_inactive')
        account,_=transport.read('/accounts/'+ACCOUNT)
        require(account.get('id')==ACCOUNT,'cloudflare_builds_account_mismatch')
        workers,_=transport.read('/accounts/'+ACCOUNT+'/workers/scripts')
        required=manifest['bootstrap'].get('builds_worker_ids',[])
        require(bool(required),'builds_worker_identity_missing')
        for worker_id in required: transport.read('/accounts/'+ACCOUNT+'/builds/workers/'+worker_id+'/triggers')
        return {'account_id':ACCOUNT,'worker_reads':len(workers),'builds_read':True}
    test('CLOUDFLARE_BUILDS',builds)

    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.zoho_oauth import ZohoOAuthManager
    zoho=ZohoGatewayClient(settings.zoho_gateway,ZohoOAuthManager(settings.zoho_oauth))
    def zoho_read(service,path,query=None,headers=None):
        data=zoho.request(service,'GET',path,query=query or {},headers=headers or {})
        require(data.get('ok') is True,'zoho_read_failed')
        return {'service':service,'http_status':data['status'],'authenticated_read':True}
    test('ZOHO_CRM',lambda:zoho_read('zohoapis','/crm/v8/org'))
    test('ZOHO_BOOKS',lambda:zoho_read('zohoapis','/books/v3/organizations'))
    test('ZOHO_MAIL',lambda:zoho_read('mail','/api/accounts'))
    # Forms' production integration observes signed connector receipts and Mail
    # acknowledgements. Its native public form API is not a portable OAuth port.
    def forms():
        from workflow.automation.phase9_form_receipts import ACCOUNT_ID
        result=zoho_read('mail','/api/accounts/'+ACCOUNT_ID+'/folders')
        values=env_file('/etc/optibrain/phase9-receipt-export.env')
        import httpx
        key=values.get('OPTIBRAIN_RECEIPT_EXPORT_KEY')
        require(bool(key),'forms_export_binding_missing')
        response=httpx.get(settings.zoho_gateway.base_url.rstrip('/')+'/api/intake-receipts',
            params={'limit':1},headers={'Authorization':'Bearer '+key},timeout=20,follow_redirects=False)
        require(response.status_code==200,'forms_authenticated_export_failed')
        data=response.json()
        require(data.get('ok') is True and isinstance(data.get('receipts'),list),'forms_export_readback_failed')
        return {**result,'authenticated_connector_export':True,'native_form_mutations':0,'native_integration_setting':'OWNER-UI evidence required at cutover'}
    test('ZOHO_FORMS',forms)
    test('ZOHO_WORKDRIVE',lambda:zoho_read('zohoapis','/workdrive/api/v1/users/me',headers={'Accept':'application/vnd.api+json'}))

    def google():
        from workflow.google_oauth import GoogleOAuthManager
        oauth=GoogleOAuthManager(settings.google_oauth)
        return oauth.access_token()
    def ga4():
        data=bounded_get('https://analyticsadmin.googleapis.com/v1beta/accountSummaries',{'Authorization':'Bearer '+google()})
        require(any(p.get('property')=='properties/530093120' for a in data.get('accountSummaries',[])
                    for p in a.get('propertySummaries',[])), 'ga4_property_access_failed')
        return {'property_id':'530093120','read_only':True}
    test('GA4',ga4)
    def gsc():
        data=bounded_get('https://www.googleapis.com/webmasters/v3/sites',{'Authorization':'Bearer '+google()})
        require(any(p.get('siteUrl')=='sc-domain:opticable.ca' for p in data.get('siteEntry',[])), 'gsc_site_access_failed')
        return {'site':'sc-domain:opticable.ca','read_only':True}
    test('GSC',gsc)
    # Ads uses existing constrained POST search read and owner-deferred Basic
    # access; never replace it with a campaign creation or new billing probe.
    results['GOOGLE_ADS']={'status':'DEFERRED','read_only':True,'reason':'Existing Google Basic access deferred by owner; preserved cache and source health are validated locally'}
    def apollo():
        from workflow.apollo_api import ApolloApiClient
        data=ApolloApiClient(settings.apollo).request('/auth/health')
        require(data.get('ok') is True,'apollo_read_failed')
        return {'zero_credit_read':True}
    test('APOLLO',apollo)
    results['OTHER_SOURCES']={'status':'DEFERRED','read_only':True,'reason':'Optional research sources and edge KV survive host move; no paid/model-generation health calls'}
    return results
