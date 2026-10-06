"""Structured forms and local migration previews; production forms are immutable."""
from .phase9_form_receipts import MAIN_FORM,ENGLISH_FORM,LABELS,DESTINATION
from .acquisition_store import digest


def models():
    return [{'form_id':fid,'provider':'ZOHO_FORMS','language':lang,'website_embed':'Native published '+lang+' quote form',
        'fields':sorted(set(LABELS.values())-{'acquisition_context'}),'field_basis':'Observed notification labels, not full provider design inventory',
        'required_fields':None,'hidden_fields':['ob_attribution'],'attribution_fields':['ob_attribution'],
        'callbacks':{'form_submit':True,'form_view':'Ignored by success listener','alias':alias,'basis':'USER_CONFIRMED Phase32'},
        'notification_recipient':DESTINATION,'crm_writer_status':'OFF','conversion_telemetry':'Acknowledged native FR/EN diagnostic success proven; business outcomes separate',
        'submission_volume':None,'abandonment':None,'field_usefulness':'UNKNOWN','proposal_history':[],
        'truth_class':'USER_CONFIRMED','performance_status':'WAITING NATURAL DATA'}
        for fid,lang,alias in [(MAIN_FORM,'FR','opticablefrquote'),(ENGLISH_FORM,'EN','opticableenquote')]]


def preview(form):
    """Detect only observable design gaps; unresolved attributes are research gaps."""
    issues=[]
    fields=form.get('fields');required=form.get('required_fields')
    if isinstance(required,list) and len(required)>8:issues.append('Review required-field friction; length alone is not measured abandonment')
    if isinstance(fields,list) and form.get('design_verified') is True and 'service' not in fields:issues.append('Missing service selection')
    if form.get('attribution_fields')==[] and form.get('design_verified') is True:issues.append('Missing attribution field')
    if form.get('mapping_health')=='BROKEN':issues.append('Verified mapping failure')
    if not issues:return None
    return {'draft_id':digest([form['form_id'],issues]),'original_form_id':form['form_id'],'status':'LOCAL_DRAFT',
        'issues':issues,'mapping':{'service':'Existing canonical service parser','ob_attribution':'Strict existing acquisition-context parser'},
        'callbacks':form.get('callbacks'),'embed':'Keep original production embed; review new draft embed only after exact provider ID exists',
        'tests':['Required/optional field behavior','FR/EN acknowledgement','Attribution validation','CRM writer remains OFF','No TEST business claim'],
        'migration_plan':'Prepare local form specification; exact provider draft requires separate supported write authority; owner approves replacement and rollback',
        'rollback':'Retain original native form ID/embed/callbacks','provider_writes':0,'replace_production':False}
