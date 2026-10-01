#!/usr/bin/env python3
"""Poll verified Zoho Forms notifications into immutable read-only receipts."""
from pathlib import Path
import json
import os
import sys
import httpx

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
sys.path.insert(0, str(APP))

from workflow.config import load_settings
from workflow.zoho_oauth import ZohoOAuthManager
from workflow.zoho_gateway import ZohoGatewayClient
from workflow.automation.phase9_form_receipts import (
    FormReceiptLedger, collect_form_mail, collect_connector_receipts,
    reconcile_form_crm,
)
from workflow.automation.provider_usage import ProviderUsage, record_call
from workflow.automation.job_runtime import job_lock
from workflow.automation.phase9_form_enrichment import POLICY as ENRICHMENT_POLICY, enrich_form_leads


def main():
    settings = load_settings()
    target=Path(settings.automation.db_path).parent
    with job_lock(target / "phase9-receipts.lock") as held:
        if not held:
            print(json.dumps({"status":"locked"}));return
        with ProviderUsage(target / "phase9-form-receipts.db","phase9-receipts",runs_per_day=288,soft_budget=12) as usage:
            result=collect(settings)
        result["provider_usage"]=usage.summary
        print(json.dumps(result,sort_keys=True))


def collect(settings):
    client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
    ledger = FormReceiptLedger(Path(settings.automation.db_path).parent / "phase9-form-receipts.db")
    mail_result = collect_form_mail(client, ledger)
    crm_result = reconcile_form_crm(client, ledger)
    enrichment = None
    if os.environ.get("OPTIBRAIN_PHASE9_FORM_ENRICHMENT") == ENRICHMENT_POLICY:
        go_live = os.environ.get("OPTIBRAIN_PHASE9_FORM_GO_LIVE")
        if not go_live:
            raise ValueError("Form enrichment go-live fence is missing")
        enrichment = enrich_form_leads(client, ledger, go_live=go_live)
    with httpx.Client(timeout=30, follow_redirects=False) as http:
        class ExportHttp:
            def get(self,*args,**kwargs):
                record_call("cloudflare","GET")
                return http.get(*args,**kwargs)
        connector_result = collect_connector_receipts(
            ExportHttp(), ledger, base_url=settings.zoho_gateway.base_url,
            api_key=os.environ.get("OPTIBRAIN_RECEIPT_EXPORT_KEY"))
    return {"form_mail": mail_result, "form_crm": crm_result, "enrichment": enrichment,
            "connector": connector_result}


if __name__ == "__main__":
    main()
