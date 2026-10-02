#!/usr/bin/env python3
"""Reconcile one authenticated, already submitted TEST form; never resubmit it."""
from datetime import datetime, timezone
import json
import re
import sys
from test_lab import Lab, ROOT, RUN, MARKER, atomic, same_value


def route(lab, lang):
    from workflow.automation.phase9_form_receipts import parse_notification, FormReceiptLedger
    from workflow.automation.lifecycle import plan_intake
    from workflow.automation.lifecycle_control import digest, trusted_json, BASELINE
    bundle = json.loads((ROOT / ('form-' + lang + '-provider-mail.json')).read_text())
    data = {k: v['data']['data'] for k, v in bundle.items()}
    receipt = parse_notification(message_id=data['details']['messageId'], details=data['details'],
        content=data['content'], headers=data['header']['headerContent'], now=datetime.now(timezone.utc))
    if not receipt['test_only'] or receipt['submitted_email'] != 'logs@opticable.ca':
        raise ValueError('Form is outside the exact controlled test identity')
    if RUN + '-form-' + lang not in receipt['fields'].get('notes', ''):
        raise ValueError('Published form lacks this exact run/language lineage')
    ledger = FormReceiptLedger('/var/lib/opticable-workflow-api/output/automation/phase9-form-receipts.db')
    ledger.record(receipt)
    key = 'form-intake-' + lang
    if key in lab.state.get('forms', {}):
        lead = lab.crm('Leads', lab.state['forms'][key]['lead_id'])
        if lead.get('OptiBrain_Test') is not True:
            raise ValueError('Previously linked TEST form Lead drifted')
        print('Published', lang, 'form replay: existing receipt/Lead/Task, no provider write', flush=True)
        return
    fields = receipt['fields']
    labels = {'Câblage structuré': 'Structured Cabling', 'Cabling': 'Structured Cabling'}
    if fields.get('service') not in labels:
        raise ValueError('TEST service mapping is ambiguous')
    payload = {'name': fields['name'].replace(',', ' '), 'company': fields['company'],
        'email': fields['email'], 'phone': fields['phone'], 'service': labels[fields['service']],
        'message': fields['notes'], 'consent': True, 'source_record_id': receipt['event_id'],
        'attribution': {prefix + field: value for prefix in ('first_', 'last_') for field, value in
            {'source': 'zoho_form', 'site': 'https://opticable.ca',
             'touch_time': receipt['occurred_at']}.items()}}
    # Campaign/click IDs are absent from the actual provider notification.
    # Keep that limitation visible; never reconstruct them from browser memory.
    source = {'schema': 1, 'source': 'zoho_form', 'origin': 'https://opticable.ca',
        'inquiry_id': receipt['event_id'], 'submitted_email': receipt['submitted_email'],
        'occurred_at': receipt['occurred_at'], 'request': payload, 'payload_hash': digest(payload),
        'request_hash': receipt['raw_hash'], 'origin_site': 'https://opticable.ca',
        'origin_path': '/' + lang + '/contact/', 'origin_service': labels[fields['service']]}
    leads = lab.lists('Leads', 'id,Email,Phone,Created_Time,First_Source,First_Site,First_Touch_Time')
    candidates = [r for r in leads if str(r.get('Email') or '').casefold() == receipt['submitted_email']]
    if any(str(r['id']) not in lab.ownership['records'] for r in candidates):
        raise ValueError('Uncontrolled native Forms CRM write or unowned identity; stop')
    contacts = lab.lists('Contacts', 'id,Email,Account_Name')
    baseline = trusted_json(BASELINE)
    protected = {str(i) for m in baseline['modules'].values() for i in m['protected_versions']}
    plan = plan_intake(source, leads, contacts, protected_ids=protected)
    if plan['decision'] not in {'CREATE', 'UPDATE'}:
        raise ValueError('TEST form needs human identity review')
    patch = {**plan['patch'], 'OptiBrain_Test': True}
    previous = lab.state['operations'].get(key)
    if previous:
        if previous['state'] not in {'acknowledged','verified'}:
            raise ValueError('Previous form effect is reconciliation-only')
        rows=previous['result'].get('data',{}).get('data',[])
        if len(rows)!=1 or rows[0].get('code')!='SUCCESS':raise ValueError('Form create lacks provider acknowledgment')
        lead=lab.crm('Leads',str(rows[0]['details']['id']))
        with lab.journal.connect() as db:
            envelope=json.loads(db.execute('SELECT envelope FROM lifecycle_intents WHERE action_id=?',
                (previous['action_id'],)).fetchone()[0])
        if envelope['path']!='/crm/v8/Leads':raise ValueError('Previous form effect is not the original creation')
        if any(not same_value(lead.get(k),v) for k,v in envelope['body']['data'][0].items()):
            raise ValueError('Original form create differs from provider readback')
        lab.verified(key,str(lead['id']),{'id':str(lead['id']),'reconciled_by':'GET only; empty Zoho text is null'})
    else:
        lead = (lab.create(key, 'Leads', patch) if plan['decision'] == 'CREATE'
                else lab.update(key, 'Leads', plan['record_id'], patch))
    identity = str(lead['id'])
    task_id = lab.state.setdefault('lead_tasks', {}).get(identity)
    if not task_id:
        task = lab.create('form-intake-task-' + identity, 'Tasks', {
            'Subject': MARKER + ' — Review published form inquiry', 'What_Id': {'id': identity},
            '$se_module': 'Leads', 'Status': 'Not Started', 'OptiBrain_Test': True,
            'Due_Date': lead['Next_Followup_At'][:10], 'Description': MARKER + ' — Human qualification only.',
            'Send_Notification_Email': False})
        task_id = str(task['id']); lab.state['lead_tasks'][identity] = task_id
    ledger.link_test_lead(receipt['event_id'], lead, set(lab.ownership['records']))
    lab.state.setdefault('forms', {})[key] = {'lead_id': identity, 'task_id': task_id,
        'event_id': receipt['event_id'], 'native_crm_writer': False, 'test_only': True,
        'campaign': 'UNAVAILABLE IN NATIVE NOTIFICATION', 'source': source}
    lab.save()
    atomic(ROOT / ('form-' + lang + '-routing.json'), lab.state['forms'][key])
    print('Published', lang, 'form authenticated, central Lead', plan['decision'], identity,
          'one internal Task', task_id, 'TEST metrics excluded', flush=True)


if __name__ == '__main__':
    if sys.argv[1:] not in (['fr'], ['en']):
        raise SystemExit('Explicit published TEST form language required')
    route(Lab(), sys.argv[1])
