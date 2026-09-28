-- Exact Phase 3 schema, exported from baseline 10e2d1feac9e724ee7d78ba3333a6242fde82898.
CREATE TABLE automation_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    correlation_id TEXT,
                    target TEXT,
                    success INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );
CREATE TABLE automation_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT,
                    idempotency_key TEXT UNIQUE,
                    depth INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
CREATE TABLE automation_run_claims (
                    run_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL UNIQUE,
                    claimed_at INTEGER NOT NULL,
                    lease_expires_at INTEGER NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id)
                );
CREATE TABLE automation_run_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_id TEXT,
                    attempt_id TEXT,
                    category TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    diagnostic_json TEXT NOT NULL DEFAULT '{}',
                    terminal_state TEXT,
                    redrive_permitted INTEGER NOT NULL DEFAULT 0,
                    human_required INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id)
                );
CREATE TABLE automation_run_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    error TEXT,
                    result_json TEXT, action_identity TEXT, provider_operation_id TEXT,
                    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id)
                );
CREATE TABLE automation_runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    context_json TEXT,
                    FOREIGN KEY(workflow_id) REFERENCES automation_workflows(workflow_id),
                    FOREIGN KEY(event_id) REFERENCES automation_events(event_id)
                );
CREATE TABLE automation_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    definition_json TEXT NOT NULL,
                    source_path TEXT,
                    updated_at TEXT NOT NULL
                );
CREATE INDEX idx_automation_audit_correlation ON automation_audit(correlation_id);
CREATE INDEX idx_automation_events_correlation ON automation_events(correlation_id);
CREATE INDEX idx_automation_events_type ON automation_events(event_type);
CREATE INDEX idx_automation_run_claims_expiry ON automation_run_claims(lease_expires_at);
CREATE INDEX idx_automation_run_failures_run ON automation_run_failures(run_id,id);
CREATE INDEX idx_automation_run_steps_run ON automation_run_steps(run_id);
CREATE INDEX idx_automation_runs_event ON automation_runs(event_id);
CREATE INDEX idx_automation_runs_workflow ON automation_runs(workflow_id);
PRAGMA user_version=1;
