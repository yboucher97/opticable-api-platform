import {
  WorkflowEntrypoint,
  type WorkflowEvent,
  type WorkflowStep,
} from "cloudflare:workers";

interface AutomationEvent {
  event_id: string;
  event_type: string;
  source: string;
  occurred_at: string;
  received_at: string;
  correlation_id?: string | null;
  idempotency_key?: string | null;
  payload: Record<string, unknown>;
}

interface Env {
  DB: D1Database;
  EVENTS: Queue<AutomationEvent>;
  AUTOMATION_WORKFLOW: Workflow;
  CORE_API_KEY: string;
  ENVIRONMENT?: string;
}

function json(data: unknown, status = 200): Response {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function nowIso(): string {
  return new Date().toISOString();
}

function uuid(): string {
  return crypto.randomUUID();
}

function bearer(request: Request): string | null {
  const value = request.headers.get("authorization") || "";
  if (!value.toLowerCase().startsWith("bearer ")) return null;
  return value.slice(7).trim();
}

function authorized(request: Request, env: Env): boolean {
  const token = bearer(request);
  return Boolean(token && env.CORE_API_KEY && token === env.CORE_API_KEY);
}

function cleanString(value: unknown, max = 200): string {
  return String(value ?? "").trim().slice(0, max);
}

async function audit(
  env: Env,
  action: string,
  success: boolean,
  metadata: Record<string, unknown> = {},
  options: { category?: string; actor?: string; target?: string | null; correlation_id?: string | null } = {},
): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO audit_log
      (audit_id, created_at, category, action, actor, target, success, correlation_id, metadata_json)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      uuid(),
      nowIso(),
      options.category || "automation",
      action,
      options.actor || "autonomous-core",
      options.target || null,
      success ? 1 : 0,
      options.correlation_id || null,
      JSON.stringify(metadata),
    )
    .run();
}

async function acceptEvent(request: Request, env: Env): Promise<Response> {
  if (!authorized(request, env)) return json({ error: "Unauthorized" }, 401);

  const contentType = request.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return json({ error: "Content-Type must be application/json." }, 415);
  }

  const length = Number(request.headers.get("content-length") || "0");
  if (length > 256_000) return json({ error: "Event payload too large." }, 413);

  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return json({ error: "Invalid JSON." }, 400);
  }

  const eventType = cleanString(body.event_type, 160);
  const source = cleanString(body.source, 120);
  if (!eventType || !source) {
    return json({ error: "event_type and source are required." }, 422);
  }

  const eventId = cleanString(body.event_id, 100) || uuid();
  const idempotencyKey = cleanString(
    body.idempotency_key ?? request.headers.get("idempotency-key"),
    240,
  ) || null;
  const correlationId = cleanString(body.correlation_id, 120) || eventId;
  const occurredAt = cleanString(body.occurred_at, 64) || nowIso();
  const receivedAt = nowIso();
  const payload =
    body.payload && typeof body.payload === "object" && !Array.isArray(body.payload)
      ? (body.payload as Record<string, unknown>)
      : {};

  if (idempotencyKey) {
    const existing = await env.DB.prepare(
      "SELECT event_id, status, workflow_instance_id FROM events WHERE idempotency_key = ? LIMIT 1",
    )
      .bind(idempotencyKey)
      .first<{ event_id: string; status: string; workflow_instance_id: string | null }>();
    if (existing) {
      return json({
        accepted: true,
        duplicate: true,
        event_id: existing.event_id,
        status: existing.status,
        workflow_instance_id: existing.workflow_instance_id,
      });
    }
  }

  try {
    await env.DB.prepare(
      `INSERT INTO events
        (event_id, event_type, source, occurred_at, received_at, correlation_id, idempotency_key, payload_json, status)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'accepted')`,
    )
      .bind(
        eventId,
        eventType,
        source,
        occurredAt,
        receivedAt,
        correlationId,
        idempotencyKey,
        JSON.stringify(payload),
      )
      .run();
  } catch (error) {
    if (idempotencyKey) {
      const existing = await env.DB.prepare(
        "SELECT event_id, status, workflow_instance_id FROM events WHERE idempotency_key = ? LIMIT 1",
      )
        .bind(idempotencyKey)
        .first<{ event_id: string; status: string; workflow_instance_id: string | null }>();
      if (existing) {
        return json({ accepted: true, duplicate: true, ...existing });
      }
    }
    throw error;
  }

  const event: AutomationEvent = {
    event_id: eventId,
    event_type: eventType,
    source,
    occurred_at: occurredAt,
    received_at: receivedAt,
    correlation_id: correlationId,
    idempotency_key: idempotencyKey,
    payload,
  };

  await env.EVENTS.send(event);
  await audit(env, "event.accepted", true, { event_type: eventType, source }, {
    target: eventId,
    correlation_id: correlationId,
  });

  return json({ accepted: true, duplicate: false, event_id: eventId, status: "accepted" }, 202);
}

async function eventStatus(request: Request, env: Env, eventId: string): Promise<Response> {
  if (!authorized(request, env)) return json({ error: "Unauthorized" }, 401);
  const row = await env.DB.prepare(
    `SELECT event_id, event_type, source, occurred_at, received_at, correlation_id,
            status, workflow_instance_id, last_error
       FROM events WHERE event_id = ?`,
  ).bind(eventId).first();
  if (!row) return json({ error: "Not found" }, 404);
  return json(row);
}

export class AutomationWorkflow extends WorkflowEntrypoint<Env, AutomationEvent> {
  async run(event: WorkflowEvent<AutomationEvent>, step: WorkflowStep) {
    const input = event.payload;
    const runId = uuid();

    await step.do("mark workflow started", async () => {
      await this.env.DB.batch([
        this.env.DB.prepare(
          "UPDATE events SET status = 'running', workflow_instance_id = ? WHERE event_id = ?",
        ).bind(event.instanceId, input.event_id),
        this.env.DB.prepare(
          `INSERT INTO workflow_runs
            (run_id, event_id, workflow_instance_id, workflow_name, status, started_at, attempt)
           VALUES (?, ?, ?, 'automation-core', 'running', ?, 1)`,
        ).bind(runId, input.event_id, event.instanceId, nowIso()),
      ]);
    });

    const dispatch = await step.do(
      "dispatch event",
      {
        retries: { limit: 5, delay: "10 seconds", backoff: "exponential" },
        timeout: "5 minutes",
      },
      async () => {
        // This durable runtime intentionally starts provider-neutral.
        // Provider adapters are added as explicit, versioned handlers rather than
        // embedding vendor-specific behavior in the event ingestion path.
        return {
          event_type: input.event_type,
          source: input.source,
          accepted_payload_keys: Object.keys(input.payload || {}).sort(),
        };
      },
    );

    await step.do("mark workflow completed", async () => {
      await this.env.DB.batch([
        this.env.DB.prepare(
          "UPDATE events SET status = 'completed', last_error = NULL WHERE event_id = ?",
        ).bind(input.event_id),
        this.env.DB.prepare(
          "UPDATE workflow_runs SET status = 'completed', completed_at = ? WHERE run_id = ?",
        ).bind(nowIso(), runId),
        this.env.DB.prepare(
          `INSERT INTO audit_log
            (audit_id, created_at, category, action, actor, target, success, correlation_id, metadata_json)
           VALUES (?, ?, 'workflow', 'workflow.completed', 'autonomous-core', ?, 1, ?, ?)`,
        ).bind(
          uuid(),
          nowIso(),
          input.event_id,
          input.correlation_id || input.event_id,
          JSON.stringify(dispatch),
        ),
      ]);
    });

    return { event_id: input.event_id, run_id: runId, dispatch };
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health") {
      const db = await env.DB.prepare("SELECT 1 AS ok").first<{ ok: number }>();
      return json({
        service: "Opticable Autonomous Core",
        ok: db?.ok === 1,
        environment: env.ENVIRONMENT || "production",
        durable_runtime: "cloudflare-workflows",
        state: "cloudflare-d1",
        queue: "cloudflare-queues",
      });
    }

    if (request.method === "POST" && url.pathname === "/v1/events") {
      return acceptEvent(request, env);
    }

    const eventMatch = url.pathname.match(/^\/v1\/events\/([A-Za-z0-9._:-]+)$/);
    if (request.method === "GET" && eventMatch) {
      return eventStatus(request, env, eventMatch[1]);
    }

    return json({ error: "Not found" }, 404);
  },

  async queue(batch: MessageBatch<unknown>, env: Env): Promise<void> {
    for (const message of batch.messages) {
      const body = message.body as Partial<AutomationEvent> | null;
      const eventId = typeof body?.event_id === "string" ? body.event_id : null;
      if (!eventId) {
        message.ack();
        await audit(env, "queue.invalid_message", false, { reason: "missing event_id" }, {
          category: "queue",
          target: null,
        });
        continue;
      }

      try {
        const automationEvent = body as AutomationEvent;
        const instance = await env.AUTOMATION_WORKFLOW.create({
          id: `event-${eventId}`,
          params: automationEvent,
        });
        await env.DB.prepare(
          "UPDATE events SET status = 'queued', workflow_instance_id = ? WHERE event_id = ?",
        ).bind(instance.id, eventId).run();
        message.ack();
      } catch (error) {
        await env.DB.prepare(
          "UPDATE events SET status = 'queue_error', last_error = ? WHERE event_id = ?",
        ).bind(String(error).slice(0, 2000), eventId).run();
        message.retry();
      }
    }
  },
} satisfies ExportedHandler<Env>;
