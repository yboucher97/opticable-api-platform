"""Storage admission and lifecycle metadata in the existing artifact/action registry.

No provider operations, schema migration, new database or scheduler. Missing
metadata fails closed for removal. Existing immutable facts are never pruned.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from zoneinfo import ZoneInfo

GIB = 1024**3
SOURCE = 'platform:business_autopilot'
ROOT = Path('/var/lib/opticable-workflow-api/output/automation/business-autopilot')
POLICY_PATH = Path('/etc/optibrain/business-storage-policy.json')
APPROVAL_PATH = Path('/etc/optibrain/business-storage-approval.json')
POLICY = {
    'schema': 1, 'policy_id': 'optibrain-disposable-v1',
    'daily_marketing_items': 2, 'rolling_seven_day_marketing_items': 10,
    'active_pending_items': 30, 'disposable_bytes': 2 * GIB,
    'minimum_free_bytes': 25 * GIB, 'pause_free_bytes': 35 * GIB,
    'pause_disposable_bytes': 1800 * 1024**2, 'run_bytes': 8 * 1024**2,
    'draft_days': 30, 'temporary_days': 7, 'staging_days': 14,
    'quarantine_days': 7, 'max_cleanup_files_per_cycle': 100,
    'allowlisted_roots': [str(ROOT / 'artifacts'), str(ROOT / 'temporary'),
                          str(ROOT / 'disposable-previews')],
    'protected': ['approved', 'rejected', 'commented', 'legal', 'customer',
                  'financial', 'audit', 'github_source', 'recovery', 'backup',
                  'unresolved_incident', 'required_test_evidence'],
}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def timestamp(value):
    if not isinstance(value, str): raise ValueError('Lifecycle timestamp must be a string')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Aware lifecycle timestamp required')
    return dt


def load_policy(path=POLICY_PATH):
    """Limits may only be reduced; policy changes invalidate standing approval."""
    path = Path(path); s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
        raise PermissionError('Root-owned read-only storage policy required')
    value = json.loads(path.read_text())
    if set(value) != set(POLICY):
        raise ValueError('Exact policy fields required')
    for k, default in POLICY.items():
        v = value[k]
        if type(default) is int:
            if type(v) is not int or v <= 0:
                raise ValueError('Positive integer policy limit required')
            if k in ('minimum_free_bytes', 'pause_free_bytes', 'quarantine_days'):
                if v < default: raise ValueError('Protection cannot be lowered')
            elif v > default:
                raise ValueError('Storage ceiling cannot be raised')
        elif v != default:
            raise ValueError('Reviewed policy namespace required')
    if value['pause_free_bytes'] < value['minimum_free_bytes'] + value['run_bytes']:
        raise ValueError('Free-space pause margin required')
    if value['pause_disposable_bytes'] + value['run_bytes'] > value['disposable_bytes']:
        raise ValueError('Disposable storage pause margin required')
    return value


def append(db, aid, kind, value, now):
    from workflow.automation.action_evidence import ActionEvidence
    ActionEvidence.append(db, aid, kind, value, now)


def table(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def metadata(db):
    """No LIMIT that could silently forget an older decision or pending item."""
    assets = {}
    for at, raw in db.execute("SELECT retrieved_at,normalized_value FROM acquisition_facts WHERE source=? ORDER BY retrieved_at,id", (SOURCE,)):
        v = json.loads(raw)
        if v.get('path') and re.fullmatch('[a-f0-9]{64}', v.get('sha256', '')):
            key = (v['path'], v['sha256'])
            if key not in assets:
                assets[key] = {**v, 'registered_at': at}
    decisions = {}; states = {}; reservations = {}; holds = set()
    if table(db, 'action_evidence'):
        for aid, kind, raw in db.execute('SELECT action_id,kind,evidence_json FROM action_evidence ORDER BY event_id'):
            # Only our precise metadata kinds are exempt from reference holds.
            v = json.loads(raw)
            if kind == 'business_storage_lifecycle':
                states[aid] = v
            elif kind == 'business_storage_reservation':
                reservations[aid] = v
            elif kind == 'business_review_decision':
                decisions.setdefault(v.get('id'), []).append(v)
            elif kind not in ('business_storage_cycle',):
                # Any separate action/incident/test referencing a disposable file
                # wins over expiry, including unknown future evidence kinds.
                holds.update(re.findall(r'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])', raw))
                for key, a in assets.items():
                    if a['path'] in raw or a.get('logical_path', '\0') in raw:
                        holds.add(a['sha256'])
    return list(assets.values()), decisions, states, reservations, holds


def family(item):
    path = item.get('logical_path', '')
    if item.get('business_private') or path.startswith('business-work/'):
        return 'customer'
    if item.get('lifecycle_class') in ('temporary_test', 'private_staging'):
        return item['lifecycle_class']
    if path.startswith('campaigns/'):
        return 'marketing'
    if path.startswith('planning/'):
        return 'recommendation'
    if path.startswith('analytics/'):
        return 'analysis'
    return 'protected_unknown'


def semantic(item):
    """Dates/weekly campaign names are not a new business purpose."""
    path = item.get('logical_path', '')
    path = re.sub(r'\b\d{4}-W\d{2}\b|\b\d{4}-\d{2}-\d{2}\b', '@period', path)
    path = re.sub(r'\.r-[a-f0-9]+', '', path)
    # A numbered social slot cannot manufacture another pending item.
    path = re.sub(r'day-\d+', 'slot', path)
    return digest([family(item), path])


def operation_id(item):
    return 'business-storage:' + digest([item['path'], item['sha256']])


def awaiting_review(item, decisions):
    events = decisions.get(item['sha256'], [])
    return not events or events[-1].get('choice') not in ('APPROVE', 'REJECT')


def activity(item, decisions):
    dates = [timestamp(item['registered_at']), timestamp(item.get('last_interaction_at') or item['registered_at'])]
    dates += [timestamp(e['at']) for e in decisions.get(item['sha256'], []) if e.get('at')]
    return max(dates)


def protection(item, decisions, holds):
    if decisions.get(item['sha256']): return 'owner_interaction_immutable_hold'
    if item['sha256'] in holds: return 'referenced_action_incident_or_test_evidence'
    for k in POLICY['protected'] + ['published', 'business_private', 'hold', 'legal_hold', 'incident_hold', 'test_hold']:
        if item.get(k): return 'protected_' + k
    if item.get('status') not in ('DRAFT_ONLY', 'UNREVIEWED', 'TEMPORARY', 'PRIVATE_STAGING'):
        return 'unknown_or_protected_status'
    if family(item) in ('customer', 'protected_unknown', 'analysis'):
        return 'protected_' + family(item)
    if family(item) in ('temporary_test', 'private_staging'):
        if item.get('disposable') is not True or item.get('in_use') is not False or item.get('evidence_required') is not False:
            return 'missing_explicit_disposable_unused_evidence_release'
    return None


def footprint(root):
    """Logical and allocated bytes, no symlink traversal or double hardlink count."""
    total = allocated = count = 0; seen = set()
    for base in ('artifacts', 'website-preview', 'temporary', 'disposable-previews'):
        p = Path(root) / base
        if not p.exists(): continue
        if p.is_symlink(): raise ValueError('Symlink storage root')
        for directory, dirs, files in os.walk(p, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
            for name in files:
                st = (Path(directory) / name).lstat()
                if not stat.S_ISREG(st.st_mode): continue
                key = (st.st_dev, st.st_ino)
                if key in seen: continue
                seen.add(key); total += st.st_size; allocated += st.st_blocks * 512; count += 1
    return {'logical_bytes': total, 'allocated_bytes': allocated, 'files': count}


def admission(db, root, now, policy=POLICY, free_bytes=None):
    assets, decisions, states, reservations, holds = metadata(db)
    today = now.astimezone(ZoneInfo('America/Toronto')).date()
    marketing = [a for a in assets if family(a) == 'marketing']
    daily = sum(timestamp(a['registered_at']).astimezone(ZoneInfo('America/Toronto')).date() == today for a in marketing)
    weekly = sum(now - timedelta(days=7) < timestamp(a['registered_at']) <= now for a in marketing)
    active = [a for a in assets if awaiting_review(a, decisions)
              and states.get(operation_id(a), {}).get('state') not in ('QUARANTINED', 'DELETED')
              and now < activity(a, decisions) + timedelta(days=policy['draft_days'])]
    for v in reservations.values():
        if v['state'] != 'RESERVED': continue
        at = timestamp(v['at'])
        if at.astimezone(ZoneInfo('America/Toronto')).date() == today: daily += v['slots']
        if now - timedelta(days=7) < at <= now: weekly += v['slots']
        # Interrupted reservations never permit an overflow of pending work.
        active.extend([{}] * v['slots'])
    usage = footprint(root)
    # Quarantine lives under the root monitor's sealed custody, outside the
    # service-readable tree. Charge its immutable registry identities as well.
    quarantined = [v for v in states.values() if v['state'] in ('QUARANTINE_INTENT','QUARANTINED','DELETE_INTENT','RECONCILE_HOLD')]
    usage['quarantine_bytes'] = sum(v.get('quarantine_identity', v['candidate']['identity'])['bytes'] for v in quarantined)
    usage['logical_bytes'] += usage['quarantine_bytes']
    usage['allocated_bytes'] += sum(v.get('quarantine_identity', v['candidate']['identity'])['allocated_bytes'] for v in quarantined)
    usage['reserved_bytes'] = sum(v['maximum_bytes'] for v in reservations.values() if v['state'] == 'RESERVED')
    usage['logical_bytes'] += usage['reserved_bytes']
    if free_bytes is None:
        fs = os.statvfs(root); free_bytes = fs.f_bavail * fs.f_frsize
    reasons = []
    if free_bytes - policy['run_bytes'] < policy['pause_free_bytes']: reasons.append('free_disk_pause_margin')
    if usage['logical_bytes'] + policy['run_bytes'] > policy['pause_disposable_bytes']: reasons.append('disposable_pause_margin')
    slots = max(0, min(policy['daily_marketing_items'] - daily,
                       policy['rolling_seven_day_marketing_items'] - weekly,
                       policy['active_pending_items'] - len(active)))
    if daily >= policy['daily_marketing_items']: reasons.append('daily_marketing_cap')
    if weekly >= policy['rolling_seven_day_marketing_items']: reasons.append('rolling_seven_day_cap')
    if len(active) >= policy['active_pending_items']: reasons.append('pending_review_cap')
    # Even after expiry, an equivalent unresolved draft blocks repetition.
    pending = {semantic(a): a['sha256'] for a in assets if awaiting_review(a, decisions)
               and states.get(operation_id(a), {}).get('state') != 'DELETED'}
    return {'policy_sha256': digest(policy), 'daily_marketing_items': daily,
            'rolling_seven_day_marketing_items': weekly, 'active_pending_items': len(active),
            'marketing_slots': 0 if reasons else slots,
            'pending_slots': max(0, policy['active_pending_items'] - len(active)),
            'generation_bytes': policy['run_bytes'], 'usage': usage, 'free_bytes': free_bytes,
            'optional_paused': bool(reasons), 'pause_reasons': reasons,
            'disk_paused': any(r.endswith('pause_margin') for r in reasons),
            'pending_semantics': pending, 'protected_hashes': sorted(holds)}


def select(files, additions, ctx):
    """Invoked in the sandbox BEFORE any artifact is written."""
    budget = ctx.get('storage_budget')
    if budget is None: raise ValueError('Storage admission required before writing')
    by_path = {a['logical_path']: a for a in additions}
    prior = set(ctx.get('artifact_hashes', [])); pending = dict(budget['pending_semantics'])
    selected = {}; metadata_out = {}; used = 0
    slots = budget['marketing_slots']; pending_slots = budget['pending_slots']
    for path, raw in sorted(files.items()):
        if sha256(raw).hexdigest() in prior: continue
        item = {'logical_path': path, **by_path.get(path, {})}
        kind = family(item); key = semantic(item)
        # Full disk pauses all new file creation, while source analysis and
        # business planning still run and publish the bounded latest summary.
        if budget['disk_paused']: continue
        revision = item.get('revision_of')
        requested = revision and any(f.get('asset_sha256') == revision and f.get('choice') == 'REQUEST_REVISION' for f in ctx.get('feedback', []))
        if key in pending and not requested: continue
        if kind == 'marketing' and (slots <= 0 or budget['optional_paused']): continue
        if pending_slots <= 0: continue
        if used + len(raw) > budget['generation_bytes']: continue
        if kind == 'marketing': slots -= 1
        pending_slots -= 1
        selected[path] = raw; used += len(raw); pending[key] = sha256(raw).hexdigest()
        metadata_out[path] = {'storage_class': kind, 'semantic_key': key,
                              'disposable': kind in ('marketing', 'recommendation')}
    return selected, metadata_out


def reserve(db, key, budget, now):
    aid = 'business-storage-reservation:' + key
    value = {'state': 'RESERVED', 'at': now.isoformat(), 'slots': budget['marketing_slots'],
             'maximum_bytes': budget['generation_bytes'], 'policy_sha256': budget['policy_sha256']}
    append(db, aid, 'business_storage_reservation', value, now)
    return aid, value


def complete(db, reservation, value, manifest, now):
    append(db, reservation, 'business_storage_reservation', {**value, 'state': 'COMPLETED',
        'written_items': len(manifest), 'written_bytes': sum(x['bytes'] for x in manifest)}, now)


def replace_report(path, value):
    path = Path(path); tmp = path.with_name('.' + path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, sort_keys=True, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
