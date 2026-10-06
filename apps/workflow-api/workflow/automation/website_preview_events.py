"""Signed, bounded event intake. Events are hints for reconciliation, never commands."""
from typing import Protocol
import hashlib
import hmac
import json
import re
from .website_preview_model import repository_name


class SignatureVerifier(Protocol):
    def verify(self,body:bytes,signature:str)->bool: ...


class HMACVerifier:
    def __init__(self,key):
        if not isinstance(key,bytes) or len(key)<16:raise ValueError('Webhook verifier configuration required')
        self._key=key
    def verify(self,body,signature):
        if not isinstance(signature,str) or not re.fullmatch('sha256=[a-f0-9]{64}',signature):return False
        expected='sha256='+hmac.new(self._key,body,hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected,signature)


def handle_webhook(store,verifier,body,*,signature,event_id,kind,allowed_repositories,now):
    if not isinstance(body,bytes) or not 1<=len(body)<=65536:raise ValueError('Webhook payload bound exceeded')
    if not re.fullmatch('[A-Za-z0-9-]{8,100}',event_id) or kind not in {'push','pull_request','workflow_run'}:raise ValueError('Known event and delivery ID required')
    if not verifier.verify(body,signature):raise ValueError('Webhook invalid signature')
    try:payload=json.loads(body)
    except (ValueError,UnicodeDecodeError):raise ValueError('Invalid webhook JSON') from None
    if not isinstance(payload,dict) or not isinstance(payload.get('repository'),dict):raise ValueError('Webhook repository required')
    repo=repository_name(payload['repository'].get('full_name'))
    if repo not in allowed_repositories:raise ValueError('Unallowed webhook repository')
    # Raw payload, user text and any command keys are never stored or executed.
    event={'event_id':event_id,'repository':repo,'kind':kind,'payload_hash':hashlib.sha256(body).hexdigest(),
           'reconcile_required':True,'execution_authorized':False}
    return store.accept_webhook(event,now)
