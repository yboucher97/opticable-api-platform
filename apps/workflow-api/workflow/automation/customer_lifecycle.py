"""Read-only customer lifecycle decisions from bounded CRM relationships.

Deals carry service facts; an Account is not called a customer merely because it
exists. Historical records with sparse facts remain unclassified suggestions.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
import json
from zoneinfo import ZoneInfo

from .providers.crm_leads import records
from .service_inventory import read_inventory

TORONTO = ZoneInfo("America/Toronto")
LAB_REGISTRY = Path("/etc/optibrain/phase8-test-lab-registry.json")
ACCOUNT_FIELDS = "id,Account_Name,Description,OptiBrain_Test,Created_Time,Modified_Time,Last_Activity_Time"
CONTACT_FIELDS = "id,Full_Name,Account_Name,OptiBrain_Test,Description"
DEAL_FIELDS = ("id,Deal_Name,Stage,Account_Name,Contact_Name,Service_Types,Description,"
               "Closing_Date,OptiBrain_Test,Created_Time,Modified_Time,Last_Activity_Time,"
               "First_Source,First_Campaign,Last_Source,Last_Campaign,"
               "OptiBrain_Installed_On,OptiBrain_Last_Service_On,OptiBrain_Maintenance_Due,"
               "OptiBrain_Renewal_On,OptiBrain_Recurrence")
OPEN_STAGES = {"Qualification", "Value Proposition", "Needs Analysis", "Id. Decision Makers",
               "Contracts In Progress", "Contracts Signed", "Scheduling", "Installation",
               "Proposal/Price Quote", "Negotiation/Review", "Installation Booked"}
ACTIVE_PROJECT_STAGES = {"Contracts Signed", "Scheduling", "Installation", "Installation Booked"}
COMPLETE_STAGES = {"Closed Won"}


def _instant(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError("CRM lifecycle instant requires timezone")
    return dt.astimezone(timezone.utc)


def _day(value):
    return date.fromisoformat(str(value)) if value else None


def _local(value):
    return _instant(value).astimezone(TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z") if value else None


def _local_day(value):
    return _day(value).strftime("%b %-d, %Y") if value else None


def _list(client, module, fields):
    result = client.request("zohoapis", "GET", f"/crm/v8/{module}",
                            query={"fields": fields, "per_page": 200, "page": 1})
    rows = records(result, empty=True)
    if (result.get("data") or {}).get("info", {}).get("more_records"):
        raise ValueError(f"{module} inventory exceeded bounded lifecycle view")
    if len({str(x.get("id")) for x in rows}) != len(rows):
        raise ValueError(f"{module} identity collision")
    return rows


def _linked_id(row, field):
    value = row.get(field)
    return str(value.get("id") or "") if isinstance(value, dict) else ""


def _service_name(deal):
    return str(deal.get("Service_Types") or "").strip()


def _service_kind(name):
    s = name.casefold()
    if "cabl" in s: return "cabling"
    if "camera" in s or "cctv" in s: return "cameras"
    if "wi-fi" in s or "wifi" in s: return "wifi"
    if "access control" in s: return "access_control"
    if "ptp" in s or "point-to-point" in s: return "ptp"
    if "telephone" in s or "telephony" in s: return "telephony"
    if "ai loss" in s: return "ai"
    return "other"


def analyze_customer(account, contacts, deals, *, now, test_only, service_rows=None):
    if now.utcoffset() is None:
        raise ValueError("Lifecycle clock requires timezone")
    today = now.astimezone(TORONTO).date()
    service_rows = service_rows or []
    linked_deals = {s["deal_id"] for s in service_rows if s.get("deal_id")}
    # A CRM Service supersedes its source Deal for inventory; never count both.
    inventory_deals = [d for d in deals if str(d["id"]) not in linked_deals]
    completed = [d for d in inventory_deals if d.get("Stage") in COMPLETE_STAGES]
    active = [d for d in deals if d.get("Stage") in ACTIVE_PROJECT_STAGES]
    recurring = [d for d in completed if str(d.get("OptiBrain_Recurrence") or "").strip()]
    installed = [d for d in completed if d.get("OptiBrain_Installed_On")]
    for d in deals:
        for key in ("Created_Time", "Modified_Time", "Last_Activity_Time"):
            if d.get(key): _instant(d[key])
        for key in ("OptiBrain_Installed_On", "OptiBrain_Last_Service_On",
                    "OptiBrain_Maintenance_Due", "OptiBrain_Renewal_On"):
            _day(d.get(key))
    service_days = [_day(d.get("OptiBrain_Last_Service_On") or d.get("OptiBrain_Installed_On"))
                    for d in installed]
    service_days.extend(_day(s.get("last_service_on") or s.get("installed_on"))
                        for s in service_rows if s.get("last_service_on") or s.get("installed_on"))
    last_service = max(service_days) if service_days else None
    maintenance = sorted((d for d in installed if d.get("OptiBrain_Maintenance_Due")
                          and _day(d["OptiBrain_Maintenance_Due"]) <= today),
                         key=lambda d: d["OptiBrain_Maintenance_Due"])
    renewal = sorted((d for d in recurring if d.get("OptiBrain_Renewal_On")
                      and _day(d["OptiBrain_Renewal_On"]) <= today + timedelta(days=45)),
                     key=lambda d: d["OptiBrain_Renewal_On"])
    service_maintenance = sorted((s for s in service_rows if s["maintenance_status"] == "DUE"),
                                 key=lambda s: s["maintenance_due_on"])
    service_renewal = sorted((s for s in service_rows if s["renewal_status"] in {"DUE", "OVERDUE"}),
                             key=lambda s: s["renewal_on"])
    active_recurring = [s for s in service_rows if s["active_recurring"]]
    known_installed = bool(installed or any(s["installed_on"] for s in service_rows))
    dormant = bool(known_installed and last_service and last_service < today - timedelta(days=540)
                   and not active and not recurring and not active_recurring)
    kinds = {_service_kind(_service_name(d)) for d in completed}
    kinds.update({"cabling" if s["category"] == "Structured cabling" else
                  "cameras" if s["category"] == "Cameras/CCTV" else
                  "wifi" if s["category"] == "Commercial Wi-Fi" else "other"
                  for s in service_rows if s["installed_on"]})
    # Keep project context when its Deal is superseded by a linked Service.
    descriptions = " ".join(str(d.get("Description") or "") for d in deals).casefold()
    cross_sell = bool("cabling" in kinds and "wifi" not in kinds
                      and ("wireless" in descriptions or "wi-fi" in descriptions or "wifi" in descriptions))
    upsell = bool("cameras" in kinds and ("expansion" in descriptions or "coverage gap" in descriptions)
                  and not any("expansion" in str(d.get("Deal_Name") or "").casefold()
                              and d.get("Stage") in OPEN_STAGES for d in deals))
    stage = ("ACTIVE PROJECT" if active else "RENEWAL DUE" if renewal or service_renewal else
             "MAINTENANCE / SUPPORT" if maintenance or service_maintenance else
             "RECURRING SERVICE" if recurring or active_recurring else
             "DORMANT CUSTOMER" if dormant else "PROJECT COMPLETE" if completed else
             "PROJECT COMPLETE" if known_installed else
             "ACTIVE OPPORTUNITY" if any(d.get("Stage") in OPEN_STAGES for d in deals) else "UNKNOWN")
    if service_renewal:
        chosen = service_renewal[0]
        action, why, review = ("Review recurring-service renewal",
                               f"{chosen['category']} renewal is {chosen['renewal_status'].lower()} for {_local_day(chosen['renewal_on'])}.",
                               chosen["renewal_on"])
    elif renewal:
        chosen = renewal[0]
        action, why, review = ("Review recurring-service renewal",
                               f"{_service_name(chosen)} renews on {_local_day(chosen['OptiBrain_Renewal_On'])}.",
                               chosen["OptiBrain_Renewal_On"])
    elif service_maintenance:
        chosen = service_maintenance[0]
        action, why, review = ("Offer a maintenance health-check review",
                               f"Installed {chosen['category']} at {chosen['site']} needs maintenance since {_local_day(chosen['maintenance_due_on'])}.",
                               chosen["maintenance_due_on"])
    elif maintenance:
        chosen = maintenance[0]
        action, why, review = ("Offer a maintenance health-check review",
                               f"Recorded {_service_name(chosen)} maintenance was due {_local_day(chosen['OptiBrain_Maintenance_Due'])}.",
                               chosen["OptiBrain_Maintenance_Due"])
    elif active:
        action, why, review = ("Track active project delivery", "An accepted project is in an active delivery stage.", None)
    elif dormant:
        action, why, review = ("Review dormant customer relationship",
                               f"Completed work is recorded; last verified service was {_local_day(last_service.isoformat())}.",
                               today.isoformat())
    elif upsell:
        action, why, review = ("Review camera-system expansion",
                               "Installed cameras and a documented expansion or coverage gap support a targeted review.",
                               today.isoformat())
    elif cross_sell:
        action, why, review = ("Review managed Wi-Fi need",
                               "Completed cabling work explicitly mentions wireless needs; no Wi-Fi service is recorded.",
                               today.isoformat())
    else:
        action, why, review = ("No action — monitor", "No verified lifecycle trigger supports outreach now.", None)
    if not test_only and action != "No action — monitor":
        why += " Read-only suggestion; confirm service facts before any customer action."
    confidence = ("VERIFIED" if test_only and (active or completed or known_installed) else
                  "POSSIBLE" if not test_only and (completed or known_installed) else "INSUFFICIENT DATA")
    if not test_only and not known_installed:
        # A historical Deal stage alone does not prove an installation or service interval.
        if stage not in {"ACTIVE PROJECT", "ACTIVE OPPORTUNITY"}:
            stage, action, why, review, confidence = ("UNKNOWN", "No action — monitor",
                "Installation and service history are not verified in CRM.", None, "INSUFFICIENT DATA")
    source_deal = next((d for d in deals if d.get("First_Source")), None)
    return {
        "account_id": str(account["id"]), "account": str(account.get("Account_Name") or ""),
        "contact": str(contacts[0].get("Full_Name") or "") if len(contacts) == 1 else None,
        "contact_state": "VERIFIED" if len(contacts) == 1 else "AMBIGUOUS" if contacts else "UNKNOWN",
        "stage": stage, "confidence": confidence, "test_only": test_only,
        "services": sorted({_service_name(d) for d in completed if _service_name(d)} |
                           {s["category"] for s in service_rows if s["installed_on"]}),
        "active_opportunities": [str(d.get("Deal_Name") or "") for d in deals if d.get("Stage") in OPEN_STAGES],
        "recurring": [{"deal_id": str(d["id"]), "service": _service_name(d),
                       "cadence": str(d.get("OptiBrain_Recurrence") or ""),
                       "start": _local_day(d.get("OptiBrain_Installed_On")),
                       "next_review": _local_day(d.get("OptiBrain_Renewal_On")),
                       "renewal": _local_day(d.get("OptiBrain_Renewal_On")),
                       "status": "TEST ONLY" if test_only else "REVIEW"}
                      for d in recurring] +
                     [{"deal_id": s["deal_id"], "service": s["category"],
                       "cadence": s["cadence"], "start": _local_day(s["installed_on"]),
                       "next_review": _local_day(s["renewal_on"]),
                       "renewal": _local_day(s["renewal_on"]), "status": s["stage"],
                       "mrr_cad": s["mrr_cad"]} for s in active_recurring],
        "last_service": _local_day(last_service.isoformat()) if last_service else None,
        "last_crm_activity": _local(max((d["Last_Activity_Time"] for d in deals
                                         if d.get("Last_Activity_Time")),
                                        key=_instant, default=None)),
        "maintenance_due": bool(maintenance or service_maintenance),
        "renewal_due": bool(renewal or service_renewal), "dormant": dormant,
        "cross_sell": cross_sell, "upsell": upsell, "action": action, "reason": why,
        "next_review": _local_day(review),
        "source": {"first": source_deal.get("First_Source") if source_deal else None,
                   "campaign": source_deal.get("First_Campaign") if source_deal else None},
        "deal_ids": [str(d["id"]) for d in deals], "service_rows": service_rows,
    }


def build_customer_lifecycle(client, *, scope="live", now=None, registry_path=LAB_REGISTRY):
    if scope not in {"live", "lab"}:
        raise ValueError("Lifecycle scope must be live or lab")
    clock = now or datetime.now(timezone.utc)
    if clock.utcoffset() is None:
        raise ValueError("Lifecycle clock requires timezone")
    accounts = _list(client, "Accounts", ACCOUNT_FIELDS)
    contacts = _list(client, "Contacts", CONTACT_FIELDS)
    deals = _list(client, "Deals", DEAL_FIELDS)
    owned = {"Accounts": set(), "Contacts": set(), "Deals": set()}
    registry = {}
    if scope == "lab":
        registry = json.loads(Path(registry_path).read_text())
        owned = {module: set(registry.get("records", {}).get(module) or [])
                 for module in owned}
    selected = ([a for a in accounts if a.get("OptiBrain_Test") is True
                 and str(a["id"]) in owned["Accounts"]] if scope == "lab" else
                [a for a in accounts if a.get("OptiBrain_Test") is not True])
    service_rows = read_inventory(client, selected, deals, scope=scope,
                                  registry=registry, now=clock)
    rows = []
    for account in selected:
        identity = str(account["id"])
        related_contacts = [x for x in contacts if _linked_id(x, "Account_Name") == identity
                            and (x.get("OptiBrain_Test") is True) == (scope == "lab")
                            and (scope != "lab" or str(x["id"]) in owned["Contacts"])]
        related_deals = [x for x in deals if _linked_id(x, "Account_Name") == identity
                         and (x.get("OptiBrain_Test") is True) == (scope == "lab")
                         and (scope != "lab" or str(x["id"]) in owned["Deals"])]
        if scope == "lab" and not str(account.get("Description") or "").startswith("OPTIBRAIN TEST — PHASE "):
            raise ValueError("Lab Account marker changed")
        rows.append(analyze_customer(account, related_contacts, related_deals,
                                     now=clock, test_only=scope == "lab",
                                     service_rows=[s for s in service_rows if s["account_id"] == identity]))
    order = {"Review recurring-service renewal": 0, "Offer a maintenance health-check review": 1,
             "Review dormant customer relationship": 2, "Review camera-system expansion": 3,
             "Review managed Wi-Fi need": 4, "Track active project delivery": 5,
             "No action — monitor": 6}
    rows.sort(key=lambda x: (order.get(x["action"], 7), x["account"].casefold()))
    return {"scope": scope, "read_at": _local(clock.isoformat()), "sample_count": len(rows),
            "summary": {"needs_attention": sum(x["action"] not in {"No action — monitor", "Track active project delivery"} for x in rows),
                        "renewal_due": sum(x["renewal_due"] for x in rows),
                        "maintenance_due": sum(x["maintenance_due"] for x in rows),
                        "dormant": sum(x["dormant"] for x in rows),
                        "cross_sell": sum(x["cross_sell"] for x in rows),
                        "upsell": sum(x["upsell"] for x in rows),
                        "active_recurring": sum(bool(x["recurring"]) for x in rows),
                        "no_action": sum(x["action"] == "No action — monitor" for x in rows)},
            "rows": rows, "service_rows": service_rows,
            "writes_enabled": False, "revenue_totals": None}


def render_customer_lifecycle(view):
    h = lambda value: escape(str(value if value is not None else "—"), quote=True)
    s = view["summary"]
    cards = []
    for row in view["rows"]:
        services = ", ".join(row["services"]) or "Unknown"
        installed_sites = "; ".join(f"{s['category']} at {s['site']}"
                                    for s in row["service_rows"] if s["installed_on"]) or "None verified"
        recurring = "; ".join(f"{x['service']} · {x['cadence']} · started {x['start'] or 'unknown'}"
                              f" · renewal {x['renewal'] or 'unknown'}"
                              f" · MRR CAD {x.get('mrr_cad') or 'unknown'}"
                              for x in row["recurring"]) or "None verified"
        cards.append(f"<article><h2>{h(row['account'])}</h2><p>{h(row['stage'])} · {h(row['confidence'])}"
                     f"{' · TEST ONLY' if row['test_only'] else ' · READ-ONLY'}<br>Contact: {h(row['contact'])}"
                     f" · Services: {h(services)}<br>Installed at: {h(installed_sites)}"
                     f" · Last verified service: {h(row['last_service'])}"
                     f" · Last CRM activity: {h(row['last_crm_activity'])}"
                     f" · Recurring: {h(recurring)}<br>First source: {h(row['source']['first'])}"
                     f" · Campaign: {h(row['source']['campaign'])}</p>"
                     f"<p><b>Next:</b> {h(row['action'])} · Review {h(row['next_review'])}<br>"
                     f"<small>{h(row['reason'])} Deal evidence: {h(', '.join(row['deal_ids']))}</small></p></article>")
    html = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>OptiBrain customer lifecycle</title>"
            "<style>body{font:16px/1.45 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#182536}"
            "article{border:1px solid #ccd;border-radius:.5rem;padding:.8rem 1rem;margin:1rem 0}small{color:#526174}"
            "summary{font-weight:700}</style>"
            f"<h1>Customer lifecycle · {h(view['scope'].upper())}</h1><p>CRM projection observed {h(view['read_at'])}. "
            "Calendar dates use Montreal business time. "
            "Recommendations are read-only; no outreach or finance action is enabled.</p>"
            f"<p><b>{s['needs_attention']}</b> need review · {s['renewal_due']} renewals · "
            f"{s['maintenance_due']} maintenance · {s['dormant']} dormant · {s['cross_sell']} cross-sell · "
            f"{s['upsell']} upsell · {s['active_recurring']} recurring · {s['no_action']} no action</p>"
            + "".join(cards) + ("<p>TEST ONLY CRM values are synthetic and excluded from real revenue.</p>"
                                  if view["scope"] == "lab" else
                                  "<p>Test Lab records are excluded. Unknown contract values are never estimated.</p>")
            + "</html>")
    return html
