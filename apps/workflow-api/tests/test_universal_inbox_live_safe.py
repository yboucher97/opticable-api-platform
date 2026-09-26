from pathlib import Path

from workflow.automation.store import AutomationStore
from workflow.universal_inbox_live_safe import observe_message


def _store(tmp_path: Path) -> AutomationStore:
    return AutomationStore(tmp_path / "automation.db")


def test_observer_persists_read_only_decision(tmp_path):
    store = _store(tmp_path)
    result = observe_message(store, {
        "messageId": "m1",
        "fromAddress": "support@fieldnation.com",
        "toAddress": "admin@opticable.ca",
        "subject": "New Work: Mirabel",
        "summary": "STORE HARD DOWN Work Order ID 20033349",
    })
    assert result["accepted"] is True
    assert result["duplicate"] is False
    assert result["mode"] == "observe_only"
    assert result["decision"]["category"] == "partner_job"
    assert result["decision"]["mutate_mail"] is False
    assert result["decision"]["mutate_crm"] is False
    assert result["decision"]["books_write"] is False


def test_thread_deduplication_blocks_duplicate_copies(tmp_path):
    store = _store(tmp_path)
    first = observe_message(store, {
        "messageId": "copy-a",
        "threadId": "thread-123",
        "fromAddress": "client@example.com",
        "toAddress": "quotes@opticable.ca",
        "subject": "Quote request",
        "summary": "Need four network drops",
    })
    second = observe_message(store, {
        "messageId": "copy-b",
        "threadId": "thread-123",
        "fromAddress": "client@example.com",
        "toAddress": "quotes@opticable.ca",
        "subject": "Quote request",
        "summary": "Need four network drops",
    })
    assert first["accepted"] is True
    assert second["accepted"] is False
    assert second["duplicate"] is True
    assert first["event_id"] == second["event_id"]


def test_hopla_is_observed_without_opticable_action(tmp_path):
    store = _store(tmp_path)
    result = observe_message(store, {
        "messageId": "hopla-1",
        "fromAddress": "customer@example.com",
        "toAddress": "info@hoplajeux.ca",
        "subject": "Reservation",
        "summary": "Inflatable game reservation",
    })
    assert result["accepted"] is True
    assert result["decision"]["category"] == "other_business"
    assert result["decision"]["next_action"] is None


def test_requires_stable_identity(tmp_path):
    store = _store(tmp_path)
    try:
        observe_message(store, {
            "fromAddress": "person@example.com",
            "toAddress": "yboucher@opticable.ca",
            "subject": "Hello",
        })
    except ValueError as exc:
        assert "messageId or threadId" in str(exc)
    else:
        raise AssertionError("Expected missing message identity to be rejected")
