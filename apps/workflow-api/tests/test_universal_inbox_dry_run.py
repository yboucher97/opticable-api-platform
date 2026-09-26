from workflow.universal_inbox_dry_run import classify_batch, classify_message


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


def test_outbound_opticable_mail_is_ignored():
    d = classify_message({"fromAddress":"yboucher@opticable.ca","toAddress":"customer@example.com","subject":"Re: quote","summary":"thank you"})
    assert d.category == "outbound_opticable_message"
    assert d.proposed_folder is None


def test_hopla_is_isolated_from_opticable():
    d = classify_message({"fromAddress":"customer@example.com","toAddress":"info@hoplajeux.ca","subject":"Reservation","summary":"October rental"})
    assert d.category == "other_business_hopla_jeux"
    assert d.mutate_crm is False


def test_vendor_sent_to_quotes_does_not_create_lead():
    d = classify_message({"fromAddress":"sales@vendor.example","toAddress":"quotes@opticable.ca","subject":"Software demo","summary":"demo of our software platform"})
    assert d.category == "vendor_or_partner_inquiry"
    assert d.business_object == "provider_or_partner_inquiry"


def test_github_workflow_failure_becomes_system_incident():
    d = classify_message({"fromAddress":"notifications@github.com","toAddress":"yboucher@opticable.ca","subject":"Run failed: Customer Lifecycle Mailbox Poll","summary":"All jobs have failed workflow run"})
    assert d.category == "automation_failure"
    assert d.priority == "high"


def test_batch_deduplicates_same_thread_copy():
    messages = [
        {"messageId":"1","threadId":"t1","fromAddress":"aaron@birdseye.ca","toAddress":"quotes@opticable.ca","subject":"Subcontracting & Partnership Opportunity","summary":"service coordinator looking for subcontractor"},
        {"messageId":"2","threadId":"t1","fromAddress":"aaron@birdseye.ca","toAddress":"support@opticable.ca","subject":"Subcontracting & Partnership Opportunity","summary":"service coordinator looking for subcontractor"},
    ]
    results = classify_batch(messages)
    assert len(results) == 1
    assert results[0]["category"] == "partner_opportunity"


def test_unknown_is_not_mutated():
    d = classify_message({"fromAddress":"person@example.net","toAddress":"yboucher@opticable.ca","subject":"Hello","summary":"Nice meeting you"})
    assert d.category == "unclassified"
    assert d.confidence < 0.5
    assert d.mutate_mail is False
    assert d.mutate_crm is False
