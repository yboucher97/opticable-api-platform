"""Zoho Forms notification intake with immutable provider evidence.

Mail is an acknowledgement of the active embedded form, not proof of a CRM
write. Unlinked receipts remain visible for operator review. A separate
guarded reconciler may enrich a uniquely proven, newly created Lead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from .phase9_intake import event_id, instant

ACCOUNT_ID = "1083319000000008002"
SENDER = "notifications@zohoforms.com"
DESTINATION = "soumissions@opticable.ca"
MAIN_FORM = "i6pIlfoGOFER0OCZ4oUH_KMxVWRZKC9Of8vbyNAjR0g"
ENGLISH_FORM = "5kpuPyq6HG3cmmNAHG_2cFprnp16uoMzojC7Fxq42xo"
TORONTO = ZoneInfo("America/Toronto")
LABELS = {
    "Nom du contact": "name", "Entreprise": "company", "Courriel": "email",
    "Type de propriété": "property", "Téléphone": "phone", "Échéancier": "timeline",
    "Services requis": "service", "Code Promo": "promo", "Code de référence / partenaire": "reference",
    "Notes sur le projet": "notes",
    "Name of the contact": "name", "Company": "company", "Email": "email",
    "Type of property": "property", "Phone": "phone", "Preferred Timeline": "timeline",
    "Services": "service", "Description of your needs": "notes",
}


class UnsupportedFormNotification(ValueError):
    """Authenticated Zoho Forms mail that is not one of the two main-site forms."""


class _FormTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None and self.row is not None:
            self.row.append(unescape("".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def _body(response, kind):
    if response.get("ok") is not True:
        raise ValueError(f"Zoho Mail {kind} unavailable")
    data = (response.get("data") or {}).get("data")
    if not isinstance(data, dict):
        raise ValueError(f"Zoho Mail {kind} malformed")
    return data


def _one_header(headers, key):
    values = headers.get(key)
    return str(values[0]).strip() if isinstance(values, list) and len(values) == 1 else ""


def parse_notification(*, message_id, details, content, headers, now):
    """Require provider identity and authenticated Zoho Forms origin."""
    if not re.fullmatch(r"[0-9]{1,30}", str(message_id)):
        raise ValueError("Invalid provider message ID")
    if (str(details.get("messageId")) != str(message_id)
            or str(details.get("fromAddress") or "").casefold() != SENDER
            or DESTINATION not in unescape(str(details.get("toAddress") or "")).casefold()):
        raise ValueError("Mail identity does not match Zoho Forms notification")
    authentication = " ".join(headers.get("Authentication-Results") or [])
    if not re.search(r"dkim=pass\b", authentication, re.I) or not re.search(r"dmarc=pass\b", authentication, re.I):
        raise ValueError("Zoho Forms notification authentication is unproven")
    internet_id = _one_header(headers, "Message-ID")
    if not re.fullmatch(r"<[^\s<>]{1,300}@public\.zohoforms\.com>", internet_id, re.I):
        raise ValueError("Zoho Forms internet message identity unavailable")
    milliseconds = int(details["receivedTime"])
    occurred = datetime.fromtimestamp(milliseconds / 1000, timezone.utc)
    if occurred > now + timedelta(minutes=2):
        raise ValueError("Provider receive time is in the future")
    parser = _FormTable()
    parser.feed(str(content.get("content") or ""))
    fields = {}
    names = set()
    for row in parser.rows:
        if len(row) >= 3:
            label = " ".join(row[0].split())
            names.add(label)
            if label in LABELS:
                fields[LABELS[label]] = row[2][:2000]
    french = "Courriel" in names and "Nom du contact" in names
    english = "Email" in names and "Name of the contact" in names
    if not (french or english) or not all(fields.get(key) for key in ("name", "company", "email", "phone")):
        raise UnsupportedFormNotification("Notification is not a recognized main-site quote form")
    email = str(fields.get("email") or "").strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Form notification has no valid submitted email")
    reference = str(fields.get("reference") or "")
    test_only = (bool(re.fullmatch(r"hckyan97\+obp9[a-z0-9]+@gmail\.com", email))
                 and "OPTIBRAIN TEST" in str(fields.get("company") or "")
                 and "TEST ONLY" in str(fields.get("notes") or ""))
    raw_hash = hashlib.sha256(str(content["content"]).encode()).hexdigest()
    return {
        "event_id": event_id("zoho_form", internet_id), "provider_message_id": str(message_id),
        "internet_message_id": internet_id, "occurred_at": occurred.isoformat(),
        "source": "zoho_form", "source_detail": "Main website French quote form" if french else "Main website English quote form",
        "form_id": MAIN_FORM if french else ENGLISH_FORM, "submitted_email": email, "fields": fields,
        "reference": reference, "raw_hash": raw_hash, "test_only": test_only,
        "campaign": None, "attribution_confidence": "FORM_NOTIFICATION_ONLY",
    }


class FormReceiptLedger:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS form_receipts (
                    event_id TEXT PRIMARY KEY, provider_message_id TEXT NOT NULL UNIQUE,
                    internet_message_id TEXT NOT NULL UNIQUE, occurred_at TEXT NOT NULL,
                    source TEXT NOT NULL, form_id TEXT NOT NULL, submitted_email TEXT NOT NULL,
                    reference TEXT, raw_hash TEXT NOT NULL, test_only INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL, recorded_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS form_receipts_no_update BEFORE UPDATE ON form_receipts
                    BEGIN SELECT RAISE(ABORT,'form receipt is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS form_receipts_no_delete BEFORE DELETE ON form_receipts
                    BEGIN SELECT RAISE(ABORT,'form receipt is immutable'); END;
                CREATE TABLE IF NOT EXISTS form_receipt_links (
                    event_id TEXT PRIMARY KEY REFERENCES form_receipts(event_id),
                    canonical_module TEXT NOT NULL, canonical_id TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL, recorded_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS form_receipt_links_no_update BEFORE UPDATE ON form_receipt_links
                    BEGIN SELECT RAISE(ABORT,'form link is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS form_receipt_links_no_delete BEFORE DELETE ON form_receipt_links
                    BEGIN SELECT RAISE(ABORT,'form link is immutable'); END;
                CREATE TABLE IF NOT EXISTS form_provider_matches (
                    event_id TEXT PRIMARY KEY REFERENCES form_receipts(event_id),
                    crm_id TEXT NOT NULL, status TEXT NOT NULL, evidence_hash TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS form_provider_matches_no_update BEFORE UPDATE ON form_provider_matches
                    BEGIN SELECT RAISE(ABORT,'form provider match is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS form_provider_matches_no_delete BEFORE DELETE ON form_provider_matches
                    BEGIN SELECT RAISE(ABORT,'form provider match is immutable'); END;
                CREATE TABLE IF NOT EXISTS form_enrichment_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL,
                    crm_id TEXT NOT NULL, state TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_form_enrichment_event ON form_enrichment_journal(event_id,id);
                CREATE TRIGGER IF NOT EXISTS form_enrichment_no_update BEFORE UPDATE ON form_enrichment_journal
                    BEGIN SELECT RAISE(ABORT,'form enrichment journal is append only'); END;
                CREATE TRIGGER IF NOT EXISTS form_enrichment_no_delete BEFORE DELETE ON form_enrichment_journal
                    BEGIN SELECT RAISE(ABORT,'form enrichment journal is append only'); END;
                CREATE TABLE IF NOT EXISTS connector_receipts (
                    event_id TEXT PRIMARY KEY, source TEXT NOT NULL, inquiry_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL, submitted_email TEXT, request_hash TEXT NOT NULL,
                    action TEXT NOT NULL, module TEXT NOT NULL, canonical_id TEXT,
                    possible_duplicate_id TEXT, evidence_json TEXT NOT NULL, recorded_at TEXT NOT NULL,
                    UNIQUE(source, inquiry_id)
                );
                CREATE TRIGGER IF NOT EXISTS connector_receipts_no_update BEFORE UPDATE ON connector_receipts
                    BEGIN SELECT RAISE(ABORT,'connector receipt is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS connector_receipts_no_delete BEFORE DELETE ON connector_receipts
                    BEGIN SELECT RAISE(ABORT,'connector receipt is immutable'); END;
                CREATE INDEX IF NOT EXISTS idx_form_receipts_occurred ON form_receipts(occurred_at);
                CREATE INDEX IF NOT EXISTS idx_connector_receipts_canonical ON connector_receipts(canonical_id);
                CREATE TABLE IF NOT EXISTS mail_poll_state (
                    account_id TEXT PRIMARY KEY, successful_at TEXT NOT NULL,
                    full_scan_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mail_message_cache (
                    account_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    metadata_hash TEXT NOT NULL, classification TEXT NOT NULL,
                    seen_at TEXT NOT NULL, PRIMARY KEY(account_id,message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_mail_cache_seen ON mail_message_cache(seen_at);
            """)

    def poll_state(self, account_id):
        self.initialize()
        with self._connect() as db:
            row = db.execute("SELECT * FROM mail_poll_state WHERE account_id=?", (account_id,)).fetchone()
        return dict(row) if row else None

    def cached_message(self, account_id, message_id, metadata_hash):
        with self._connect() as db:
            row = db.execute("SELECT classification FROM mail_message_cache WHERE "
                "account_id=? AND message_id=? AND metadata_hash=?", (account_id,message_id,metadata_hash)).fetchone()
            if row and row[0] == "receipt" and not db.execute(
                    "SELECT 1 FROM form_receipts WHERE provider_message_id=?", (message_id,)).fetchone():
                return None
        return row[0] if row else None

    def cache_message(self, account_id, message_id, metadata_hash, classification, clock):
        # Discovery optimization only; never ownership, approval or write evidence.
        if classification not in {"receipt", "unsupported"}:
            raise ValueError("Unknown Mail cache classification")
        with self._connect() as db:
            db.execute("INSERT INTO mail_message_cache VALUES(?,?,?,?,?) ON CONFLICT(account_id,message_id) "
                "DO UPDATE SET metadata_hash=excluded.metadata_hash,classification=excluded.classification,"
                "seen_at=excluded.seen_at", (account_id,message_id,metadata_hash,classification,clock.isoformat()))

    def complete_poll(self, account_id, clock, *, full_scan):
        with self._connect() as db:
            prior = db.execute("SELECT full_scan_at FROM mail_poll_state WHERE account_id=?", (account_id,)).fetchone()
            full_at = clock.isoformat() if full_scan or not prior else prior[0]
            db.execute("INSERT INTO mail_poll_state VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
                "successful_at=excluded.successful_at,full_scan_at=excluded.full_scan_at", (account_id,clock.isoformat(),full_at))
            # Only expendable lookup metadata. Immutable receipts/links/history remain untouched.
            db.execute("DELETE FROM mail_message_cache WHERE seen_at<?", ((clock-timedelta(days=30)).isoformat(),))

    def record(self, receipt):
        self.initialize()
        payload = json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as db:
            prior = db.execute("SELECT evidence_json FROM form_receipts WHERE event_id=?", (receipt["event_id"],)).fetchone()
            if prior:
                if prior["evidence_json"] != payload:
                    raise ValueError("Provider replay conflicts with immutable form receipt")
                return "REPLAY"
            db.execute("INSERT INTO form_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                receipt["event_id"], receipt["provider_message_id"], receipt["internet_message_id"],
                receipt["occurred_at"], receipt["source"], receipt["form_id"],
                receipt["submitted_email"], receipt["reference"], receipt["raw_hash"],
                int(receipt["test_only"]), payload, datetime.now(timezone.utc).isoformat()))
        return "CREATED"

    def link_test_lead(self, event_id_value, crm, registered_ids):
        """Append a reviewed TEST_ONLY link after exact provider readback."""
        self.initialize()
        with self._connect() as db:
            row = db.execute("SELECT * FROM form_receipts WHERE event_id=?", (event_id_value,)).fetchone()
            if not row or row["test_only"] != 1:
                raise ValueError("Only controlled Test Lab form receipts may be linked")
            record_id = str(crm.get("id") or "")
            if (record_id not in registered_ids or crm.get("OptiBrain_Test") is not True
                    or not str(crm.get("Description") or "").startswith("OPTIBRAIN TEST — PHASE ")
                    or str(crm.get("Email") or "").strip().casefold() != row["submitted_email"]):
                raise ValueError("CRM readback is not registered Test Lab identity")
            digest = hashlib.sha256(json.dumps({"event_id": event_id_value, "crm_id": record_id,
                "crm_version": crm.get("Modified_Time")}, sort_keys=True).encode()).hexdigest()
            prior = db.execute("SELECT canonical_id FROM form_receipt_links WHERE event_id=?", (event_id_value,)).fetchone()
            if prior:
                if prior["canonical_id"] != record_id:
                    raise ValueError("Form receipt already linked to another identity")
                return "REPLAY"
            db.execute("INSERT INTO form_receipt_links VALUES(?,?,?,?,?)", (event_id_value,
                "Leads", record_id, digest, datetime.now(timezone.utc).isoformat()))
        return "LINKED"

    def list(self, limit=100):
        self.initialize()
        with self._connect() as db:
            rows = db.execute("SELECT r.*,COALESCE(l.canonical_id,m.crm_id) AS canonical_id,"
                "m.status AS provider_match_status,l.canonical_id AS reviewed_test_link "
                "FROM form_receipts r LEFT JOIN form_receipt_links l ON l.event_id=r.event_id "
                "LEFT JOIN form_provider_matches m ON m.event_id=r.event_id "
                "ORDER BY r.occurred_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def enrichment_state(self, event_id_value):
        self.initialize()
        with self._connect() as db:
            row = db.execute("SELECT * FROM form_enrichment_journal WHERE event_id=? "
                "ORDER BY id DESC LIMIT 1", (event_id_value,)).fetchone()
        return dict(row) if row else None

    def journal_enrichment(self, event_id_value, crm_id, state, payload_hash, evidence):
        if state not in {"ATTEMPTED", "VERIFIED", "REVIEW"} or not re.fullmatch(r"[0-9]{1,30}", str(crm_id)):
            raise ValueError("Invalid form enrichment journal identity")
        if not re.fullmatch(r"[a-f0-9]{64}", str(payload_hash)):
            raise ValueError("Invalid form enrichment payload hash")
        self.initialize()
        with self._connect() as db:
            match = db.execute("SELECT crm_id FROM form_provider_matches WHERE event_id=?", (event_id_value,)).fetchone()
            if not match or match["crm_id"] != str(crm_id):
                raise ValueError("Enrichment has no immutable exact provider match")
            previous = db.execute("SELECT state,payload_hash FROM form_enrichment_journal WHERE event_id=? "
                "ORDER BY id DESC LIMIT 1", (event_id_value,)).fetchone()
            if previous and previous["state"] in {"VERIFIED", "REVIEW"}:
                raise ValueError("Enrichment is terminal")
            if previous and (previous["state"] != "ATTEMPTED" or state == "ATTEMPTED"
                             or previous["payload_hash"] != payload_hash):
                raise ValueError("Ambiguous form enrichment replay")
            db.execute("INSERT INTO form_enrichment_journal(event_id,crm_id,state,payload_hash,evidence_json,recorded_at) "
                "VALUES(?,?,?,?,?,?)", (event_id_value, str(crm_id), state, payload_hash,
                json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                datetime.now(timezone.utc).isoformat()))

    def verified_test_ids(self):
        """Service-owned TEST_ONLY form Leads verified after guarded enrichment."""
        self.initialize()
        with self._connect() as db:
            rows = db.execute("SELECT j.crm_id FROM form_enrichment_journal j "
                "JOIN form_receipts r ON r.event_id=j.event_id "
                "WHERE j.state='VERIFIED' AND r.test_only=1 AND NOT EXISTS ("
                "SELECT 1 FROM form_enrichment_journal n WHERE n.event_id=j.event_id AND n.id>j.id)").fetchall()
        return {str(row["crm_id"]) for row in rows}

    def match_provider(self, event_id_value, crm):
        """Record a read-only, unique provider match; no CRM update is implied."""
        self.initialize()
        with self._connect() as db:
            receipt = db.execute("SELECT * FROM form_receipts WHERE event_id=?", (event_id_value,)).fetchone()
            if not receipt:
                raise ValueError("Form receipt unavailable")
            crm_id = str(crm.get("id") or "")
            if not re.fullmatch(r"[0-9]{1,30}", crm_id):
                raise ValueError("Invalid CRM identity")
            provider_email = str(crm.get("Email") or "").strip().casefold()
            if provider_email and provider_email != receipt["submitted_email"]:
                raise ValueError("Form and CRM email disagree")
            status = "MATCHED" if provider_email else "MATCHED_MISSING_EMAIL"
            digest = hashlib.sha256(json.dumps({"id": crm_id, "Created_Time": crm.get("Created_Time"),
                "Email": crm.get("Email"), "Phone": crm.get("Phone"), "Company": crm.get("Company")},
                sort_keys=True).encode()).hexdigest()
            prior = db.execute("SELECT crm_id FROM form_provider_matches WHERE event_id=?", (event_id_value,)).fetchone()
            if prior:
                if prior["crm_id"] != crm_id:
                    raise ValueError("Form provider match conflicts with immutable evidence")
                return "REPLAY"
            db.execute("INSERT INTO form_provider_matches VALUES(?,?,?,?,?)", (
                event_id_value, crm_id, status, digest, datetime.now(timezone.utc).isoformat()))
        return "MATCHED"

    def record_connector(self, receipt):
        """Append a connector-authorized CRM acknowledgement or review decision."""
        self.initialize()
        if receipt.get("schema") != 1 or receipt.get("source") not in {"ai_website", "opticable_website"}:
            raise ValueError("Unsupported connector receipt")
        source = receipt["source"]
        if receipt.get("origin") != ("https://ai.opticable.ca" if source == "ai_website" else "https://opticable.ca"):
            raise ValueError("Connector source and origin disagree")
        inquiry = str(receipt.get("inquiry_id") or "")
        if not inquiry or len(inquiry) > 255 or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("request_hash") or "")):
            raise ValueError("Connector inquiry or request hash invalid")
        action = receipt.get("action")
        if action not in {"created_lead", "updated_lead", "duplicate_lead", "created_deal_for_contact",
                          "duplicate_deal", "possible_duplicate", "would_create_lead",
                          "would_update_lead", "would_create_deal_for_contact"}:
            raise ValueError("Unexpected connector action")
        canonical = str(receipt.get("record_id") or "")
        possible = str(receipt.get("possible_duplicate_record_id") or "")
        if action == "possible_duplicate":
            if canonical or not re.fullmatch(r"[0-9]{1,30}", possible):
                raise ValueError("Ambiguous identity must carry only review candidate")
        elif not action.startswith("would_") and not re.fullmatch(r"[0-9]{1,30}", canonical):
            raise ValueError("Connector CRM acknowledgement missing record ID")
        at = instant(receipt["occurred_at"])
        email = str(receipt.get("submitted_email") or "").strip().casefold()
        evidence = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        identity = event_id(source, inquiry)
        with self._connect() as db:
            prior = db.execute("SELECT evidence_json FROM connector_receipts WHERE source=? AND inquiry_id=?",
                               (source, inquiry)).fetchone()
            if prior:
                if prior["evidence_json"] != evidence:
                    raise ValueError("Connector inquiry ID was reused with conflicting evidence")
                return "REPLAY"
            db.execute("INSERT INTO connector_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                identity, source, inquiry, at, email, receipt["request_hash"], action,
                str(receipt.get("module") or ""), canonical or None, possible or None,
                evidence, datetime.now(timezone.utc).isoformat()))
        return "CREATED"

    def list_connector(self, limit=100):
        self.initialize()
        with self._connect() as db:
            rows = db.execute("SELECT * FROM connector_receipts ORDER BY occurred_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def timeline(self, canonical_id):
        """Source chronology for one provider identity, without CRM mutation."""
        if not re.fullmatch(r"[0-9]{1,30}", str(canonical_id)):
            raise ValueError("Invalid CRM identity")
        self.initialize()
        with self._connect() as db:
            forms = db.execute("SELECT r.* FROM form_receipts r "
                "LEFT JOIN form_receipt_links l ON l.event_id=r.event_id "
                "LEFT JOIN form_provider_matches m ON m.event_id=r.event_id "
                "WHERE COALESCE(l.canonical_id,m.crm_id)=?", (str(canonical_id),)).fetchall()
            connector = db.execute("SELECT * FROM connector_receipts WHERE canonical_id=?",
                                   (str(canonical_id),)).fetchall()
        events = [{"event_id": r["event_id"], "source": "zoho_form",
                   "occurred_at": r["occurred_at"], "campaign": None,
                   "action": "form_provider_matched"} for r in forms]
        for row in connector:
            evidence = json.loads(row["evidence_json"])
            events.append({"event_id": row["event_id"], "source": row["source"],
                           "occurred_at": row["occurred_at"],
                           "campaign": (evidence.get("attribution") or {}).get("last_campaign"),
                           "action": row["action"]})
        return sorted(events, key=lambda row: (instant(row["occurred_at"]), row["event_id"]))


def collect_form_mail(client, ledger, *, account_id=ACCOUNT_ID, now=None, days=7):
    """Bounded polling; no automatic CRM writes. A complete search is required."""
    clock = now or datetime.now(timezone.utc)
    if clock.utcoffset() is None or not 1 <= days <= 30:
        raise ValueError("Bounded aware collection time required")
    clock = clock.astimezone(timezone.utc)
    local = clock.astimezone(TORONTO)
    account_id = str(account_id)
    state = ledger.poll_state(account_id)
    full_scan = (not state or clock < datetime.fromisoformat(state["successful_at"])
                 or clock-datetime.fromisoformat(state["full_scan_at"]) >= timedelta(days=1))
    # Two-day overlap protects delayed indexing; daily full sweep preserves the
    # original seven-day coverage. Downtime starts from the durable checkpoint.
    begin = local - timedelta(days=days) if full_scan else (
        datetime.fromisoformat(state["successful_at"]).astimezone(TORONTO)-timedelta(days=2))
    if state and clock-datetime.fromisoformat(state["successful_at"]) > timedelta(days=days):
        begin = datetime.fromisoformat(state["successful_at"]).astimezone(TORONTO)-timedelta(days=2)
    if local-begin > timedelta(days=30):
        raise ValueError("Mail checkpoint requires an explicit bounded backfill; preserved without advancing")
    search = f"sender:{SENDER}::fromDate:{begin:%d-%b-%Y}::toDate:{(local + timedelta(days=1)):%d-%b-%Y}"
    found = []
    for page in range(5):
        response = client.request("mail", "GET", f"/api/accounts/{account_id}/messages/search",
                                  query={"searchKey": search, "start": page * 200, "limit": 200})
        if response.get("ok") is not True or not isinstance((response.get("data") or {}).get("data"), list):
            raise ValueError("Form Mail search unavailable")
        batch = response["data"]["data"]
        found.extend(batch)
        if len(batch) < 200:
            break
    else:
        raise ValueError("Form Mail search exceeded bound")
    outcome = {"scanned": len(found), "created": 0, "replayed": 0, "skipped_other": 0,
               "cache_hits": 0, "full_scan": full_scan}
    for item in found:
        if str(item.get("fromAddress") or "").casefold() != SENDER:
            outcome["skipped_other"] += 1
            continue
        message_id = str(item.get("messageId") or "")
        folder = str(item.get("folderId") or "")
        if not re.fullmatch(r"[0-9]{1,30}", message_id) or not re.fullmatch(r"[0-9]{1,30}", folder):
            raise ValueError("Form Mail result lacks stable provider identity")
        # Folder/read flags change without changing a received message. Bind the
        # account and stable provider metadata, never arbitrary subject/body text.
        metadata_hash = hashlib.sha256(json.dumps({k:item.get(k) for k in (
            "messageId", "fromAddress", "toAddress", "receivedTime")},sort_keys=True).encode()).hexdigest()
        cached = ledger.cached_message(account_id,message_id,metadata_hash)
        if cached and not full_scan:
            outcome["cache_hits"] += 1
            outcome["replayed" if cached == "receipt" else "skipped_other"] += 1
            continue
        base = f"/api/accounts/{account_id}/folders/{folder}/messages/{message_id}"
        details = _body(client.request("mail", "GET", base + "/details"), "details")
        content = _body(client.request("mail", "GET", base + "/content"), "content")
        headers = _body(client.request("mail", "GET", base + "/header", query={"raw": "false"}), "header").get("headerContent")
        if not isinstance(headers, dict):
            raise ValueError("Form Mail headers unavailable")
        try:
            receipt = parse_notification(message_id=message_id, details=details, content=content,
                                          headers=headers, now=clock)
        except UnsupportedFormNotification:
            outcome["skipped_other"] += 1
            ledger.cache_message(account_id,message_id,metadata_hash,"unsupported",clock)
            continue
        result = ledger.record(receipt)
        ledger.cache_message(account_id,message_id,metadata_hash,"receipt",clock)
        outcome["created" if result == "CREATED" else "replayed"] += 1
    ledger.complete_poll(account_id,clock,full_scan=full_scan)
    return outcome


def reconcile_form_crm(client, ledger):
    """Read-only exact form-to-CRM matching over a bounded complete Lead inventory."""
    pending = [row for row in ledger.list(100) if not row["canonical_id"]]
    if not pending:
        return {"pending": 0, "matched": 0, "ambiguous": 0}
    leads = []
    for page in range(1, 6):
        response = client.request("zohoapis", "GET", "/crm/v8/Leads",
            query={"fields": "id,Email,Phone,Company,First_Name,Last_Name,Created_Time",
                   "per_page": 200, "page": page})
        data = response.get("data") or {}
        if response.get("ok") is not True or not isinstance(data.get("data"), list):
            raise ValueError("Bounded CRM Lead inventory unavailable")
        leads.extend(data["data"])
        if not (data.get("info") or {}).get("more_records"):
            break
    else:
        raise ValueError("CRM Lead inventory exceeded bound")
    result = {"pending": len(pending), "matched": 0, "ambiguous": 0}
    for receipt in pending:
        fields = json.loads(receipt["evidence_json"])["fields"]
        name = str(fields.get("name") or "")
        if ", " not in name or not fields.get("phone") or not fields.get("company"):
            result["ambiguous"] += 1
            continue
        first, last = name.split(", ", 1)
        occurred = datetime.fromisoformat(receipt["occurred_at"])
        matches = []
        for lead in leads:
            try:
                created = datetime.fromisoformat(str(lead.get("Created_Time") or ""))
            except ValueError:
                continue
            if (created.utcoffset() is None or abs((created - occurred).total_seconds()) > 300
                    or str(lead.get("First_Name") or "").strip() != first
                    or str(lead.get("Last_Name") or "").strip() != last
                    or str(lead.get("Company") or "").strip() != fields["company"]
                    or re.sub(r"\D", "", str(lead.get("Phone") or "")) != re.sub(r"\D", "", fields["phone"])):
                continue
            matches.append(lead)
        if len(matches) != 1:
            result["ambiguous"] += 1
            continue
        ledger.match_provider(receipt["event_id"], matches[0])
        result["matched"] += 1
    return result


def collect_connector_receipts(http, ledger, *, base_url, api_key):
    """Poll connector KV through its authenticated read-only export."""
    if not base_url.startswith("https://") or not api_key:
        raise ValueError("Authenticated HTTPS connector required")
    cursor = None
    totals = {"created": 0, "replayed": 0}
    for _ in range(20):
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = http.get(base_url.rstrip("/") + "/api/intake-receipts", params=params,
                            headers={"Authorization": "Bearer " + api_key})
        if response.status_code != 200:
            raise ValueError("Connector receipt export unavailable")
        page = response.json()
        if page.get("ok") is not True or not isinstance(page.get("receipts"), list):
            raise ValueError("Connector receipt export malformed")
        for receipt in page["receipts"]:
            result = ledger.record_connector(receipt)
            totals["created" if result == "CREATED" else "replayed"] += 1
        cursor = page.get("cursor")
        if not cursor:
            return totals
    raise ValueError("Connector receipt export exceeded bounded pages")
