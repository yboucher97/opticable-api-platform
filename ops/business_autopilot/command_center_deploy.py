"""Offline plan sealing/identifier rendering only. No provider write transport."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

PLAN=Path(__file__).with_name('command_center_rollout.json')


def plan():return json.loads(PLAN.read_text())


def validate(value):
    # Exact reviewed plan, not a general-purpose provider configuration gateway.
    if value!=plan():raise ValueError('Exact reviewed rollout policy required')
    app=value['access_application'];policy=app['policies']
    assert app['domain']=='app.opticable.ca' and app['allowed_idps']==['9752fcb8-4a90-4605-bfb3-91dc144501e9']
    assert len(policy)==1 and policy[0]['decision']=='allow' and policy[0]['include']==[{'email':{'email':'info@opticable.ca'}}]
    assert value['maximum_incremental_cost']['amount']==0 and value['origin_template']['staging_public_key'] is None
    ingress=value['ingress_template']['ingress'];assert len(ingress)==2 and ingress[-1]=={'service':'http_status:404'}
    assert ingress[0]['originRequest']['access']['required'] is True and ingress[0]['originRequest']['noTLSVerify'] is False
    return sha256(PLAN.read_bytes()).hexdigest()


def render(value,*,access_aud,tunnel_uuid):
    validate(value)
    if not re.fullmatch('[a-f0-9]{64}',access_aud):raise ValueError('Exact returned Access audience required')
    if not re.fullmatch('[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',tunnel_uuid):raise ValueError('Exact returned tunnel UUID required')
    raw=json.dumps(deepcopy(value),ensure_ascii=False)
    raw=raw.replace('${CREATED_ACCESS_AUD}',access_aud).replace('${CREATED_TUNNEL_UUID}',tunnel_uuid)
    resolved=json.loads(raw)
    return {k:resolved[k] for k in ('access_application','ingress_template','dns_template','cache_bypass','https_redirect','origin_template')}


if __name__=='__main__':print(json.dumps({'policy_sha256':validate(plan()),'state':'PROPOSED_NOT_APPROVED','provider_mutations':0}))
