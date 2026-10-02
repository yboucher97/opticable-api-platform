"""Read-only Account → Service Location → Service projection.

Zoho Services is the existing business-level inventory. A completed Deal alone
does not prove a contract or an installed system. Monetary values are explicit
CRM service facts, normalized with Decimal, and never read from Books.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from zoneinfo import ZoneInfo

from .providers.crm_leads import records

TORONTO = ZoneInfo("America/Toronto")
LOCATION_FIELDS = "id,Name,Linked_Account,Primary_Contact,OptiBrain_Test,Created_Time"
SERVICE_FIELDS = ("id,Name,Linked_Service_Location,Linked_Deal,Service_Type,Service_Stage,Contract_Type,"
                  "Service_Contract_Signed_Date,Created_Time,Modified_Time,Last_Activity_Time,OptiBrain_Test,"
                  "OptiBrain_Installed_On,OptiBrain_Last_Service_On,OptiBrain_Maintenance_Due,"
                  "OptiBrain_Renewal_On,OptiBrain_Recurrence,OptiBrain_Recurring_Amount_CAD")
CADENCES = {"Monthly": Decimal("1"), "Quarterly": Decimal("3"), "Annual": Decimal("12")}


def _list(client, module, fields):
    result = client.request("zohoapis", "GET", f"/crm/v8/{module}",
                            query={"fields": fields, "per_page": 200, "page": 1})
    rows = records(result, empty=True)
    if (result.get("data") or {}).get("info", {}).get("more_records"):
        raise ValueError(f"{module} inventory exceeds bounded view")
    if len({str(r.get("id")) for r in rows}) != len(rows):
        raise ValueError(f"{module} duplicate provider identity")
    return rows


def _linked(row, key):
    value = row.get(key)
    return str(value.get("id") or "") if isinstance(value, dict) else ""


def _day(value):
    return date.fromisoformat(str(value)) if value else None


def _local_day(value):
    day = _day(value)
    return day.strftime("%b %-d, %Y") if day else None


def service_category(row):
    value = (str(row.get("Service_Type") or "") + " " + str(row.get("Name") or "")).casefold()
    for token, category in (("ptp", "PTP link"), ("point-to-point", "PTP link"),
                            ("ai loss", "AI loss prevention"), ("jobsite", "Temporary jobsite service"),
                            ("voip", "IP telephony"), ("telephony", "IP telephony"),
                            ("camera", "Cameras/CCTV"), ("cabl", "Structured cabling"),
                            ("wifi", "Commercial Wi-Fi"), ("wi-fi", "Commercial Wi-Fi"),
                            ("access control", "Access control"), ("fiber", "Fiber")):
        if token in value:
            return category
    return "Other / needs classification"


def project_service(row, location, *, today, test_only):
    for field in ("OptiBrain_Installed_On", "OptiBrain_Last_Service_On",
                  "OptiBrain_Maintenance_Due", "OptiBrain_Renewal_On"):
        _day(row.get(field))
    for field in ("Created_Time", "Modified_Time", "Last_Activity_Time", "Service_Contract_Signed_Date"):
        if row.get(field):
            instant = datetime.fromisoformat(str(row[field]).replace("Z", "+00:00"))
            if instant.utcoffset() is None:
                raise ValueError(f"Naive CRM service instant: {field}")
    stage = str(row.get("Service_Stage") or "UNKNOWN")
    recurring = str(row.get("Contract_Type") or "") == "Recurring Service"
    active = recurring and stage == "Active"
    cadence = str(row.get("OptiBrain_Recurrence") or "")
    value = row.get("OptiBrain_Recurring_Amount_CAD")
    mrr = arr = None
    if value is not None:
        try:
            money = Decimal(str(value))
            if not money.is_finite() or money < 0 or money > 1000000 or money.as_tuple().exponent < -2:
                raise ValueError("CRM service value is out of bounds")
        except InvalidOperation as exc:
            raise ValueError("CRM service value is malformed") from exc
        if recurring and active and cadence in CADENCES:
            mrr = (money / CADENCES[cadence]).quantize(Decimal("0.01"))
            arr = (money * Decimal("12") / CADENCES[cadence]).quantize(Decimal("0.01"))
    due = _day(row.get("OptiBrain_Maintenance_Due"))
    last = _day(row.get("OptiBrain_Last_Service_On"))
    maintenance = ("NOT ACTIVE" if stage in {"Cancelled", "Suspended"} and due else
                   "DUE" if due and due <= today and (not last or last < due) else
                   "CURRENT" if due else "UNKNOWN")
    renewal = _day(row.get("OptiBrain_Renewal_On"))
    renewal_state = ("OVERDUE" if renewal < today else "DUE" if renewal <= today + timedelta(days=45)
                     else "MONITOR") if active and renewal else "UNKNOWN"
    installed = _day(row.get("OptiBrain_Installed_On"))
    return {
        "id": str(row["id"]), "name": str(row.get("Name") or ""),
        "category": service_category(row), "service_type": row.get("Service_Type"),
        "site": str(location.get("Name") or ""), "site_id": str(location["id"]),
        "account_id": _linked(location, "Linked_Account"),
        "deal_id": _linked(row, "Linked_Deal") or None,
        "stage": stage, "contract_type": row.get("Contract_Type"),
        "contract_signed_at": row.get("Service_Contract_Signed_Date"),
        "installed_on": installed.isoformat() if installed else None,
        "last_service_on": last.isoformat() if last else None,
        "maintenance_due_on": due.isoformat() if due else None,
        "maintenance_status": maintenance,
        "renewal_on": renewal.isoformat() if renewal else None,
        "renewal_status": renewal_state,
        "recurring": recurring, "active_recurring": active,
        "cadence": cadence or None,
        "contract_value_cad": str(value) if value is not None else None,
        "mrr_cad": str(mrr) if mrr is not None else None,
        "arr_cad": str(arr) if arr is not None else None,
        "test_only": test_only,
        "evidence": "Verified CRM Service and Service Location" if installed or recurring else
                    "CRM Service exists; installation and contract facts incomplete",
    }


def read_inventory(client, accounts, deals, *, scope, registry, now):
    if now.utcoffset() is None or scope not in {"lab", "live"}:
        raise ValueError("Service inventory requires aware time and explicit scope")
    today = now.astimezone(TORONTO).date()
    account_by_id = {str(x["id"]): x for x in accounts}
    deal_by_id = {str(x["id"]): x for x in deals}
    owned = (registry.get("records") or {}) if scope == "lab" else {}
    locations = _list(client, "Service_Locations", LOCATION_FIELDS)
    services = _list(client, "Services", SERVICE_FIELDS)
    usable_locations = {}
    for location in locations:
        lid = str(location["id"])
        if (location.get("OptiBrain_Test") is True) != (scope == "lab"):
            continue
        if scope == "lab" and lid not in set(owned.get("Service_Locations") or []):
            continue
        aid = _linked(location, "Linked_Account")
        if aid not in account_by_id:
            continue
        if scope == "lab" and not str(location.get("Name") or "").startswith("OPTIBRAIN TEST — PHASE "):
            raise ValueError("Test Lab Service Location marker changed")
        usable_locations[lid] = location
    result = []
    for row in services:
        sid = str(row["id"])
        if (row.get("OptiBrain_Test") is True) != (scope == "lab"):
            continue
        if scope == "lab" and sid not in set(owned.get("Services") or []):
            continue
        location = usable_locations.get(_linked(row, "Linked_Service_Location"))
        if location is None:
            continue
        if scope == "lab" and not str(row.get("Name") or "").startswith("OPTIBRAIN TEST — PHASE "):
            raise ValueError("Test Lab Service marker changed")
        deal_id = _linked(row, "Linked_Deal")
        if deal_id and (deal_id not in deal_by_id or
                        _linked(deal_by_id[deal_id], "Account_Name") != _linked(location, "Linked_Account") or
                        (deal_by_id[deal_id].get("OptiBrain_Test") is True) != (scope == "lab") or
                        scope == "lab" and deal_id not in set(owned.get("Deals") or [])):
            raise ValueError("Service-to-Deal customer relationship changed")
        projected = project_service(row, location, today=today, test_only=scope == "lab")
        projected["account"] = str(account_by_id[projected["account_id"]].get("Account_Name") or "")
        source = deal_by_id.get(deal_id) if deal_id else None
        projected["source"] = (source or {}).get("First_Source")
        projected["campaign"] = (source or {}).get("First_Campaign")
        result.append(projected)
    return result


def build_recurring_view(lifecycle):
    rows = [s for s in lifecycle["service_rows"] if s["recurring"]]
    lab = lifecycle["scope"] == "lab"
    known = [s for s in rows if s["active_recurring"] and s["mrr_cad"] is not None]
    complete = len(known) == sum(s["active_recurring"] for s in rows)
    mrr = sum((Decimal(s["mrr_cad"]) for s in known), Decimal("0"))
    arr = sum((Decimal(s["arr_cad"]) for s in known), Decimal("0"))
    published_totals = complete and (lab or bool(known))
    return {"scope": lifecycle["scope"], "read_at": lifecycle["read_at"], "rows": rows,
            "active_count": sum(s["active_recurring"] for s in rows),
            "mrr_cad": str(mrr) if published_totals else None,
            "arr_cad": str(arr) if published_totals else None,
            "totals_complete": complete, "synthetic": lab, "writes_enabled": False}


def render_recurring_view(view):
    h = lambda v: escape(str(v if v is not None else "—"), quote=True)
    lines = []
    for s in view["rows"]:
        lines.append(f"<article><h2>{h(s['account'])}</h2><p>{h(s['name'])} · Site: {h(s['site'])} · {h(s['category'])}"
                     f" · {h(s['stage'])} · {h(s['cadence'])}</p>"
                     f"<p>MRR CAD {h(s['mrr_cad'])} · ARR CAD {h(s['arr_cad'])}"
                     f" · Renewal {h(_local_day(s['renewal_on']))} ({h(s['renewal_status'])})"
                     f" · Maintenance {h(_local_day(s['maintenance_due_on']))} ({h(s['maintenance_status'])})</p>"
                     f"<small>Source {h(s['source'])} · Service {h(s['id'])} · Deal {h(s['deal_id'])}</small></article>")
    note = "Synthetic TEST ONLY; excluded from real revenue and Books." if view["synthetic"] else \
           "Read-only verified CRM values only; unknown contracts are not estimated."
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>OptiBrain recurring services</title>"
            "<style>body{font:16px/1.45 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#182536}"
            "article{border:1px solid #ccd;border-radius:.5rem;padding:.8rem 1rem;margin:1rem 0}</style>"
            f"<h1>Recurring services · {h(view['scope'].upper())}</h1>"
            f"<p>CRM projection observed {h(view['read_at'])}. Montreal business dates. {h(note)}</p>"
            f"<p>{view['active_count']} active · MRR CAD {h(view['mrr_cad'])} · ARR CAD {h(view['arr_cad'])}</p>"
            + "".join(lines) + "</html>")
