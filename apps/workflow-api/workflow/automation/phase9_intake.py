"""Immutable, provider-reconciled intake receipts and source-to-outcome trace.

The ledger is written only after a CRM readback. It never grants provider writes.
An inquiry ID identifies a replay; a returning person uses a new inquiry ID.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
SOURCES = {"ai_website": ("website", "AI website"),
           "opticable_website": ("website", "Main-origin connector"),
           "zoho_form": ("form", "Zoho Form"),
           "manual_crm": ("manual", "Manual CRM"),
           "email_manual": ("manual", "Email/manual")}
FEEDBACK = {"LEAD_CREATED", "QUALIFIED_LEAD", "QUOTE_READY", "OPPORTUNITY_CREATED", "WON", "LOST"}
ID = re.compile(r"[0-9]{1,30}\Z")


def instant(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError("Intake timestamp needs an explicit offset")
    return dt.astimezone(timezone.utc).isoformat()


def source_info(source):
    key = str(source or "").strip().lower()
    if not key:
        return ("unknown", "Unknown")
    return SOURCES.get(key, ("other", key))


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def event_id(source, inquiry_id):
    if not inquiry_id or len(str(inquiry_id)) > 255:
        raise ValueError("Stable inquiry ID required")
    return "OB-I-" + hashlib.sha256((source + "\0" + inquiry_id).encode()).hexdigest()[:24].upper()


class IntakeLedger:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self, *, read_only=False):
        if read_only:
            db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS intake_events (
                    event_id TEXT PRIMARY KEY, inquiry_id TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL, source TEXT NOT NULL, source_type TEXT NOT NULL,
                    source_detail TEXT, medium TEXT, campaign TEXT, content TEXT, term TEXT,
                    form_id TEXT, landing_page TEXT, referrer TEXT,
                    submitted_email TEXT NOT NULL, canonical_module TEXT NOT NULL,
                    canonical_id TEXT NOT NULL, crm_action TEXT NOT NULL,
                    request_hash TEXT NOT NULL, crm_version TEXT NOT NULL,
                    test_only INTEGER NOT NULL CHECK(test_only=1),
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intake_canonical ON intake_events(canonical_id,occurred_at,event_id);
                CREATE TRIGGER IF NOT EXISTS intake_immutable_update BEFORE UPDATE ON intake_events
                    BEGIN SELECT RAISE(ABORT,'intake evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS intake_immutable_delete BEFORE DELETE ON intake_events
                    BEGIN SELECT RAISE(ABORT,'intake evidence is immutable'); END;
                CREATE TABLE IF NOT EXISTS feedback_events (
                    feedback_id TEXT PRIMARY KEY, kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    canonical_id TEXT NOT NULL, related_module TEXT NOT NULL, related_id TEXT NOT NULL,
                    first_intake_event_id TEXT NOT NULL REFERENCES intake_events(event_id),
                    test_only INTEGER NOT NULL CHECK(test_only=1), evidence_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS feedback_immutable_update BEFORE UPDATE ON feedback_events
                    BEGIN SELECT RAISE(ABORT,'feedback evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS feedback_immutable_delete BEFORE DELETE ON feedback_events
                    BEGIN SELECT RAISE(ABORT,'feedback evidence is immutable'); END;
            """)

    def record(self, receipt, crm):
        """Append one TEST_ONLY receipt only after exact provider readback."""
        self.initialize()
        source = str(receipt["source"]).strip().lower()
        source_type, _ = source_info(source)
        inquiry = str(receipt["inquiry_id"])
        identity = event_id(source, inquiry)
        crm_id = str(crm.get("id") or "")
        email = str(receipt["email"]).strip().casefold()
        if (not ID.fullmatch(crm_id) or crm.get("OptiBrain_Test") is not True
                or not str(crm.get("Description") or "").startswith("OPTIBRAIN TEST — PHASE ")
                or str(crm.get("Inquiry_ID") or "") != inquiry
                or str(crm.get("Ingestion_Source") or "") != source
                or str(crm.get("Email") or "").strip().casefold() != email):
            raise ValueError("Provider readback does not prove exact TEST_ONLY intake")
        at = instant(receipt["occurred_at"])
        version = instant(crm["Modified_Time"])
        request_hash = canonical_hash(receipt["request"])
        attr = receipt.get("attribution") or {}
        if not isinstance(attr, dict) or len(email) > 254 or "@" not in email:
            raise ValueError("Invalid intake identity or attribution")
        row = (identity, inquiry, at, source, source_type,
               receipt.get("source_detail"), attr.get("last_medium"), attr.get("last_campaign"),
               attr.get("last_content"), attr.get("last_term"), receipt.get("form_id"),
               attr.get("last_landing_url"), attr.get("last_referrer"), email, "Leads", crm_id,
               receipt["crm_action"], request_hash, version, 1,
               datetime.now(timezone.utc).isoformat())
        with self._connect() as db:
            existing = db.execute("SELECT * FROM intake_events WHERE inquiry_id=?", (inquiry,)).fetchone()
            if existing:
                if (existing["event_id"], existing["request_hash"], existing["canonical_id"]) != (identity, request_hash, crm_id):
                    raise ValueError("Inquiry ID replay conflicts with immutable evidence")
                return {"event_id": identity, "decision": "REPLAY", "canonical_id": crm_id}
            prior = db.execute("SELECT event_id,submitted_email FROM intake_events WHERE canonical_id=? ORDER BY occurred_at,event_id LIMIT 1", (crm_id,)).fetchone()
            collision = db.execute("SELECT canonical_id FROM intake_events WHERE submitted_email=? AND canonical_id<>? LIMIT 1", (email, crm_id)).fetchone()
            if collision:
                raise ValueError("Exact email maps to multiple canonical IDs; human review required")
            if prior and prior["submitted_email"] != email:
                raise ValueError("Canonical identity email changed; human review required")
            db.execute("INSERT INTO intake_events VALUES (" + ",".join("?" * len(row)) + ")", row)
            return {"event_id": identity, "decision": "EXACT EXISTING IDENTITY" if prior else "NEW IDENTITY",
                    "canonical_id": crm_id}

    def feedback(self, *, kind, canonical_id, related_module, related_id, occurred_at, evidence):
        if kind not in FEEDBACK or related_module not in {"Leads", "Contacts", "Accounts", "Deals"}:
            raise ValueError("Unsupported feedback kind or module")
        if not ID.fullmatch(str(canonical_id)) or not ID.fullmatch(str(related_id)):
            raise ValueError("Invalid feedback record ID")
        at = instant(occurred_at)
        digest = canonical_hash(evidence)
        identity = "OB-F-" + hashlib.sha256((kind+"\0"+str(canonical_id)+"\0"+str(related_id)).encode()).hexdigest()[:24].upper()
        with self._connect() as db:
            first = db.execute("SELECT event_id FROM intake_events WHERE canonical_id=? ORDER BY occurred_at,event_id LIMIT 1", (canonical_id,)).fetchone()
            if not first:
                raise ValueError("Feedback has no traced intake")
            prior = db.execute("SELECT evidence_hash FROM feedback_events WHERE feedback_id=?", (identity,)).fetchone()
            if prior:
                if prior["evidence_hash"] != digest:
                    raise ValueError("Feedback replay conflicts with immutable evidence")
                return identity
            db.execute("INSERT INTO feedback_events VALUES(?,?,?,?,?,?,?,?,?)", (identity,kind,at,str(canonical_id),related_module,str(related_id),first["event_id"],1,digest))
        return identity

    def trace(self, canonical_id):
        if not ID.fullmatch(str(canonical_id)):
            raise ValueError("Invalid canonical ID")
        with self._connect(read_only=True) as db:
            events = [dict(r) for r in db.execute("SELECT * FROM intake_events WHERE canonical_id=? ORDER BY occurred_at,event_id", (canonical_id,))]
            feedback = [dict(r) for r in db.execute("SELECT * FROM feedback_events WHERE canonical_id=? ORDER BY occurred_at,feedback_id", (canonical_id,))]
        if not events:
            return None
        for event in events:
            event["occurred_at_montreal"] = datetime.fromisoformat(event["occurred_at"]).astimezone(TORONTO).isoformat()
        return {"canonical_id": str(canonical_id), "first_touch": events[0]["source"],
                "latest_touch": events[-1]["source"], "events": events,
                "feedback": feedback, "test_only": True, "external_exports_enabled": False}
