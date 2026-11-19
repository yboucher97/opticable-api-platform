"""Offline preparation model. No credentials, network client or provider writes.

Only the existing application and its non-reusable owner policy are in scope.
"""
from copy import deepcopy
from hashlib import sha256
import json

APP='709f26d3-0a65-493c-b27b-162ebbceb701'
POLICY='d280ded5-ad48-451b-8427-d32e0fdc8891'
IDP='9752fcb8-4a90-4605-bfb3-91dc144501e9'
APP_FIELDS=('type','name','domain','self_hosted_domains','destinations','app_launcher_visible','allowed_idps','tags','auto_redirect_to_identity','session_duration','enable_binding_cookie','http_only_cookie_attribute','same_site_cookie_attribute','options_preflight_bypass','eager_redirect_cookie_setting')
POLICY_FIELDS=('name','decision','include','exclude','require','precedence','session_duration')
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def checksum(v):return sha256(canonical(v)).hexdigest()
def semantic(v):
    if isinstance(v,dict):return {k:semantic(x) for k,x in v.items() if k not in ('created_at','updated_at')}
    if isinstance(v,list):return [semantic(x) for x in v]
    return v
def validate_baseline(app,policy):
    if app['id']!=APP or app['domain']!='app.opticable.ca' or app['destinations']!=[{'type':'public','uri':'app.opticable.ca'}]:raise ValueError('Exact existing app/hostname required')
    if app['allowed_idps']!=[IDP] or app['enable_binding_cookie'] is not True or app['session_duration']!='1h':raise ValueError('Baseline drift')
    if policy['id']!=POLICY or policy.get('reusable') is not False or policy['session_duration']!='1h':raise ValueError('Exact app-specific owner policy required')
    if policy['decision']!='allow' or policy['include']!=[{'email':{'email':'info@opticable.ca'}}] or policy['exclude']!=[] or policy['require']!=[{'login_method':{'id':IDP}}]:raise ValueError('Exact Google owner-only policy required')
    if len(app['policies'])!=1 or app['policies'][0]['id']!=POLICY:raise ValueError('No additional/replaced policy')
def bodies(app,policy):
    validate_baseline(app,policy)
    app_before={k:deepcopy(app[k]) for k in APP_FIELDS if k in app}
    # The documented update API can reference an existing policy by ID. Do not
    # inline/recreate it or send read-only metadata back as configuration.
    app_before['policies']=[{'id':POLICY,'precedence':policy['precedence']}]
    app_test={**app_before,'enable_binding_cookie':False,'session_duration':'15m'}
    policy_before={k:deepcopy(policy[k]) for k in POLICY_FIELDS if k in policy}
    policy_short={**policy_before,'session_duration':'15m'}
    return {'app_restore':app_before,'app_test':app_test,'policy_restore':policy_before,'policy_short':policy_short}
def expected(app,policy,binding=True,app_duration='1h',policy_duration='1h'):
    a=deepcopy(app);p=deepcopy(policy);a['enable_binding_cookie']=binding;a['session_duration']=app_duration;p['session_duration']=policy_duration;a['policies']=[deepcopy(p)]
    return semantic(a),semantic(p)
def assert_state(actual_app,actual_policy,target):
    if (semantic(actual_app),semantic(actual_policy))!=target:raise ValueError('Unexpected semantic configuration drift; stop and execute only scoped recovery')
def permit_open(app,policy,revoke_acknowledged,cooldown_seconds,ready):
    if not ready or not revoke_acknowledged or cooldown_seconds<60:raise PermissionError('Approval/READY, app-only revocation and full cooldown required')
    if app['enable_binding_cookie'] is not True or policy['session_duration']!='15m':raise PermissionError('Short policy must be verified while binding remains on')
def approve(package_sha,receipt):
    if receipt.get('state')!='APPROVED' or receipt.get('package_sha256')!=package_sha or receipt.get('owner')!='info@opticable.ca' or receipt.get('ready') is not True or receipt.get('maximum_incremental_cost_cad')!=0:raise PermissionError('New exact test approval and READY required')
class Simulation:
    """Fault-injection fixture, deliberately no HTTP or production execution."""
    def __init__(self,app,policy):self.original=(deepcopy(app),deepcopy(policy));self.app=deepcopy(app);self.policy=deepcopy(policy);self.events=[];self.revokes=0
    def test(self,fail_at=None,owner_completed=False):
        validate_baseline(*self.original)
        try:
            self.policy['session_duration']='15m';self.app['policies']=[deepcopy(self.policy)];self.events.append('short-policy-verified')
            if fail_at=='shorten':raise RuntimeError('Injected failure')
            self.revokes+=1;self.events.append('old-app-tokens-revoked');permit_open(self.app,self.policy,True,60,True)
            if fail_at=='revoke':raise RuntimeError('Injected failure')
            self.app['session_duration']='15m';self.app['enable_binding_cookie']=False;self.events.append('binding-off-verified')
            if fail_at in ('disable','monitor'):raise RuntimeError('Injected failure')
            self.events.append('owner-completed' if owner_completed else 'five-minute-deadline')
        finally:
            # Re-enable binding FIRST. The still-short policy prevents any newly
            # issued one-hour unbound token during the rollback sequence.
            self.app=deepcopy(self.original[0]);self.app['policies']=[deepcopy(self.policy)];self.events.append('binding-restored-first')
            self.policy=deepcopy(self.original[1]);self.app['policies']=[deepcopy(self.policy)];self.events.append('original-policy-restored')
            self.revokes+=1;self.events.append('test-app-tokens-revoked');assert_state(self.app,self.policy,expected(*self.original))
