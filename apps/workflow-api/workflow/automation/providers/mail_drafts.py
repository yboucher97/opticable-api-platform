"""Shared Zoho Mail draft transport. This operation can never send."""
from __future__ import annotations

import re


def mail_data(response, expected=dict):
    outer=response.get('data') or {}
    value=outer.get('data')
    if response.get('ok') is not True or response.get('status')!=200 or (outer.get('status') or {}).get('code')!=200 or not isinstance(value,expected):
        raise ValueError('Native Mail readback unavailable')
    return value


def draft_folder(client,account_id):
    rows=mail_data(client.request('mail','GET',f'/api/accounts/{account_id}/folders'),list)
    found=[str(r.get('folderId','')) for r in rows if r.get('folderType')=='Drafts' and r.get('path')=='/Drafts']
    if len(found)!=1 or not re.fullmatch(r'[0-9]{1,30}',found[0]):raise ValueError('Exact native Drafts destination required')
    return found[0]


def verify_mail_draft(client,account_id,folder_id,message_id,payload):
    from ..customer_delivery import addresses,plain
    from ..event_schema import digest
    base=f'/api/accounts/{account_id}/folders/{folder_id}/messages/{message_id}'
    details=mail_data(client.request('mail','GET',base+'/details'))
    content=mail_data(client.request('mail','GET',base+'/content')).get('content')
    if isinstance(content,dict):content=content.get('content')
    if (str(details.get('messageId'))!=message_id or str(details.get('folderId'))!=folder_id
        or addresses(details.get('fromAddress'))!=[payload['fromAddress']]
        or addresses(details.get('toAddress'))!=[payload['toAddress']]
        or addresses(details.get('ccAddress')) or addresses(details.get('bccAddress'))
        or details.get('subject')!=payload['subject'] or not isinstance(content,str)
        or plain(content)!=plain(payload['content'])):
        raise ValueError('Native draft differs from exact proposed recipient, subject or content')
    return {'draft_id':message_id,'folder_id':folder_id,'content_hash':digest(payload),'native_state':'DRAFT_VERIFIED'}


def save_mail_draft(client, account_id, payload):
    allowed = {"mode", "fromAddress", "toAddress", "subject", "content", "mailFormat", "inReplyTo"}
    if (not re.fullmatch(r"[0-9]{1,30}", str(account_id))
            or payload.get("mode") != "draft" or set(payload) - allowed):
        raise ValueError("Invalid draft-only request")
    return client.request(
        "mail", "POST", f"/api/accounts/{account_id}/messages",
        body=payload, reason="Customer lifecycle: save reply as Zoho Mail draft", confirm=True,
    )
