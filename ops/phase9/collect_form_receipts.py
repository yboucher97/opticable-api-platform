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


def main():
    settings = load_settings()
    client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
    ledger = FormReceiptLedger(Path(settings.automation.db_path).parent / "phase9-form-receipts.db")
    mail_result = collect_form_mail(client, ledger)
    crm_result = reconcile_form_crm(client, ledger)
    with httpx.Client(timeout=30, follow_redirects=False) as http:
        connector_result = collect_connector_receipts(
            http, ledger, base_url=settings.zoho_gateway.base_url,
            api_key=os.environ.get("OPTIBRAIN_RECEIPT_EXPORT_KEY"))
    print(json.dumps({"form_mail": mail_result, "form_crm": crm_result,
                      "connector": connector_result}, sort_keys=True))


if __name__ == "__main__":
    main()
