from workflow.universal_inbox_dry_run import classify_message


def test_partner_job_is_read_only():
    d = classify_message({"fromAddress":"support@fieldnation.com","toAddress":"admin@opticable.ca","subject":"Routed WO","summary":"STORE HARD DOWN Work Order ID 20033349"})
    assert d.category == "partner_job"
    assert d.priority == "urgent"
    assert d.mutate_mail is False
    assert d.mutate_crm is False
    assert d.books_write is False


def test_legacy_supplier_invoice_targets_factures():
    d = classify_message({"fromAddress":"invoices@infinitecables.com","toAddress":"yboucher@opti-plex.ca","subject":"Invoice","summary":"invoice attached"})
    assert d.category == "supplier_invoice_or_receipt"
    assert d.migration_candidate is True
    assert d.migration_target == "factures@opticable.ca"
    assert d.books_write is False


def test_soumissions_po_becomes_project_handoff():
    d = classify_message({"fromAddress":"client@example.com","toAddress":"soumissions@opticable.ca","subject":"Intercom","summary":"bon de commande"})
    assert d.category == "won_work_or_project_handoff"
    assert d.proposed_folder == "/Opticable/Clients and Projects"


def test_quotes_stays_sales_pipeline():
    d = classify_message({"fromAddress":"prospect@example.com","toAddress":"quotes@opticable.ca","subject":"Quote request","summary":"quote 4 doors"})
    assert d.category == "direct_quote_or_lead"
    assert d.proposed_folder == "/Opticable/Leads and Quotes"


def test_unknown_is_not_mutated():
    d = classify_message({"fromAddress":"person@example.net","toAddress":"yboucher@opticable.ca","subject":"Hello","summary":"Nice meeting you"})
    assert d.category == "unclassified"
    assert d.confidence < 0.5
    assert d.mutate_mail is False
    assert d.mutate_crm is False
