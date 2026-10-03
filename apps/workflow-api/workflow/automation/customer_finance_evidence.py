"""Read-only interpretation of Books' native Estimate send history.

Estimate detail does not expose a send timestamp in this organization's API.
The documented comments/history endpoint records system email events with a
local date and minute-precision time. Only recognized sent descriptors count;
creation, modified, viewed, manual comments and status-only changes do not.
"""
from datetime import datetime, timedelta, timezone
import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Some supported tzdata installations omit IANA's backward-link names. Books
# uses this official legacy alias for the observed organization configuration.
TIMEZONE_ALIASES = {'US/Eastern': 'America/New_York'}


def _human(reason):
    return {'decision': 'HUMAN', 'reason': reason, 'external_send': False,
            'financial_writes': False}


def _sent_description(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    value = ' '.join(value.split())
    # Exact native operational prefixes; trailing text can contain a recipient
    # and remains root-only. A free-form comment saying "sent" is insufficient.
    return bool(re.match(
        r'^(?:estimate (?:(?:has been|was) )?(?:sent|emailed)\b'
        r'|estimate (?:email|e-mail) (?:has been )?sent\b'
        r'|devis (?:a ete )?envoye (?:par e-mail|par email|par courriel|a|au)\b'
        r'|soumission (?:a ete )?envoyee (?:par e-mail|par email|par courriel|a|au)\b)', value))


def estimate_sent_at(history, organization_timezone, *, estimate_id=None, now=None):
    """Return a conservative reminder anchor from native Books system events.

    Callers must supply an independently read complete history and Books org
    timezone. Ambiguous DST minutes cannot establish a safe cadence. The first
    following minute is used as the cadence anchor because the provider does
    not expose the actual second of the send.
    """
    if not isinstance(history, list) or len(history) > 200:
        return _human('Complete bounded native Estimate history required')
    if estimate_id is not None and not re.fullmatch(r'[0-9]{1,30}', str(estimate_id)):
        return _human('Exact native Estimate identity required')
    try:
        zone = ZoneInfo(TIMEZONE_ALIASES.get(str(organization_timezone), str(organization_timezone)))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return _human('Independently read Books organization timezone required')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return _human('Observation time requires an offset')
    sent = []
    seen = {}
    for row in history:
        if not isinstance(row, dict):
            return _human('Native Estimate history has malformed entries')
        if (row.get('comment_type') != 'system' or row.get('transaction_type') != 'email'
                or row.get('operation_type') != 'Updated' or not _sent_description(row.get('description'))):
            continue
        identifier = str(row.get('comment_id') or '')
        native_estimate = str(row.get('estimate_id') or '')
        if (not re.fullmatch(r'[0-9]{1,30}', identifier)
                or not re.fullmatch(r'[0-9]{1,30}', native_estimate)
                or estimate_id is not None and native_estimate != str(estimate_id)):
            return _human('Send history is associated with another or missing Estimate identity')
        try:
            date = str(row['date'])
            time = str(row['time']).upper()
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) or not re.fullmatch(r'\d{1,2}:\d{2} [AP]M', time):
                raise ValueError('Native date/time format changed')
            local = datetime.strptime(date + ' ' + time, '%Y-%m-%d %I:%M %p')
            first, second = local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1)
            if first.utcoffset() != second.utcoffset():
                return _human('Native send minute is ambiguous/nonexistent at a DST transition')
            if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
                return _human('Native send minute does not exist in organization timezone')
            if first > current + timedelta(minutes=2):
                return _human('Native send history is in the future')
        except (KeyError, TypeError, ValueError):
            return _human('Native system send date/time is missing or invalid')
        binding = (native_estimate, first.isoformat())
        if identifier in seen and seen[identifier] != binding:
            return _human('One native history identity has conflicting send timestamps')
        seen[identifier] = binding
        sent.append((first, identifier, native_estimate))
    if not sent:
        return _human('No recognized native system email-send event; owner follow-up required')
    latest, comment_id, native_estimate = max(sent, key=lambda value: value[0])
    return {'decision': 'OBSERVE', 'estimate_id': native_estimate, 'comment_id': comment_id,
            'sent_at': latest.isoformat(), 'cadence_anchor_at': (latest + timedelta(minutes=1)).isoformat(),
            'source': 'BOOKS_SYSTEM_EMAIL_HISTORY', 'precision': 'MINUTE',
            'timezone': str(organization_timezone), 'external_send': False, 'financial_writes': False}
