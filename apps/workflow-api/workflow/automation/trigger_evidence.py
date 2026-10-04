"""Rebuildable trigger proof. Research evidence never grants contact authority."""
from datetime import datetime, timezone
import re
from .evidence_quality import geography_evidence


def timestamp(value):
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d if d.tzinfo else None
    except (TypeError,ValueError):return None


def latest_releases(releases):
    """SEAO release IDs encode amendment time; creation date can stay older."""
    def version(r):
        native=str(r.get('id',''));d=timestamp(r.get('date'))
        if re.fullmatch(r'\d{14}',native):
            try:return (datetime.strptime(native,'%Y%m%d%H%M%S').isoformat(),native)
            except ValueError:pass
        return (d.astimezone(timezone.utc).replace(tzinfo=None).isoformat() if d else '',native.zfill(20) if native.isdigit() else native)
    result={}
    for r in releases:
        ocid=r.get('ocid')
        if ocid and (ocid not in result or version(r)>version(result[ocid])):result[ocid]=r
    return result


def tender_status(tender,now):
    status=str(tender.get('status','')).casefold()
    if status in {'cancelled','canceled','withdrawn'}:return 'CANCELLED'
    if status in {'complete','awarded'}:return 'AWARDED'
    if status in {'closed','unsuccessful'}:return 'CLOSED'
    end=timestamp(tender.get('tenderPeriod',{}).get('endDate'))
    if end and end<=now:return 'CLOSED'
    return 'OPEN' if status=='active' and end else 'UNKNOWN'


def actors_from_release(row):
    buyer=row.get('buyer',{});native=buyer.get('id')
    # Procurement buyer is a proven actor, not automatically the best cold contact.
    return [{'role':'BUYER','name':buyer.get('name'),'source_actor_id':native,
             'confidence':'EXACT' if native else 'UNRESOLVED','source_record_id':row.get('ocid'),
             'source_version':row.get('id'),'contact_role_relevance':'PROCUREMENT — OWNER REVIEWS REQUIREMENTS'}] if buyer.get('name') else []


def assess_trigger(row,*,now):
    result=dict(row)
    checked=timestamp(row.get('last_checked') or row.get('retrieved_at'))
    effective=timestamp(row.get('source_published_at')) or checked
    fresh=bool(checked and effective and 0<=(now-checked).total_seconds()<=72*3600 and 0<=(now-effective).total_seconds()<=72*3600)
    status=row.get('current_status','UNKNOWN')
    ends=timestamp(row.get('deadline'))
    if ends and ends<=now:status='CLOSED'
    actors=row.get('actors',[])
    # Never upgrade a likely actor, an applicant, or a name-only match.
    roles={'BUYER','PROPERTY OWNER','DEVELOPER','TENANT','GENERAL CONTRACTOR','PROPERTY MANAGER'}
    proven=[a for a in actors if a.get('role') in roles and a.get('confidence') in {'EXACT','SUPPORTED'} and a.get('source_actor_id') and a.get('source_record_id')]
    company_proof=row.get('company_identity',{})
    resolved=bool(not row.get('identity_unresolved',True) and row.get('domain') and
                  company_proof.get('confidence') in {'EXACT','SUPPORTED'} and company_proof.get('source_url') and proven)
    geo=geography_evidence(row)
    actionable=bool(status in {'OPEN','ISSUED'} and row.get('native_version') and fresh and resolved and geo['quebec_recommendation_allowed'] and not row.get('test_only'))
    missing=[]
    if not fresh:missing.append('Current source/version verification')
    if status not in {'OPEN','ISSUED'}:missing.append('Open/current trigger status')
    if not row.get('native_version'):missing.append('Native version')
    if not resolved:missing.append('Proven target company/actor identity')
    if not geo['quebec_recommendation_allowed']:missing.append('Québec market relevance')
    result.update(current_status=status,source_freshness='FRESH' if fresh else 'STALE / UNVERIFIED',
        identity_unresolved=not resolved,actor_confidence='SUPPORTED' if proven else 'UNRESOLVED',
        geography_evidence=geo,sales_review_eligible=actionable,
        recommendation_state='OWNER REVIEW — NO CONTACT AUTHORITY' if actionable else 'RESEARCH NEEDED' if status in {'OPEN','ISSUED','UNKNOWN'} else 'HISTORICAL — NOT ACTIVE',
        missing_evidence=missing,contact_allowed=False,cold_send_allowed=False)
    return result
