import { WorkflowEntrypoint, WorkflowEvent, WorkflowStep } from "cloudflare:workers";

type BusinessEvent = {
  event_id: string;
  event_type: string;
  source: string;
  occurred_at: string;
  correlation_id: string;
  causation_id?: string | null;
  idempotency_key: string;
  depth: number;
  payload: Record<string, unknown>;
};

interface Env {
  EVENTS: Queue<BusinessEvent>;
  BUSINESS_WORKFLOW: Workflow;
  CONTROL_PLANE_API_KEY: string;
  CORE_API_KEY: string;
  CORE_API_URL: string;
}

const json = (value: unknown, status = 200) =>
  Response.json(value, { status, headers: { "cache-control": "no-store" } });

function authorized(request: Request, env: Env): boolean {
  const auth = request.headers.get("authorization") || "";
  return Boolean(env.CONTROL_PLANE_API_KEY) && auth === `Bearer ${env.CONTROL_PLANE_API_KEY}`;
}

function normalizeEvent(input: unknown): BusinessEvent {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Event body must be an object.");
  const raw = input as Record<string, unknown>;
  const eventType = String(raw.event_type || "").trim();
  const source = String(raw.source || "").trim();
  if (!eventType || !/^[a-z0-9_.:-]{3,120}$/i.test(eventType)) throw new Error("Invalid event_type.");
  if (!source || source.length > 120) throw new Error("Invalid source.");

  const eventId = String(raw.event_id || crypto.randomUUID()).trim();
  const correlationId = String(raw.correlation_id || eventId).trim();
  const idempotencyKey = String(raw.idempotency_key || eventId).trim();
  const depth = Math.max(0, Number(raw.depth || 0));
  if (!eventId || eventId.length > 100) throw new Error("event_id must be 1-100 characters.");
  if (!Number.isInteger(depth) || depth > 16) throw new Error("depth must be an integer between 0 and 16.");

  return {
    event_id: eventId,
    event_type: eventType,
    source,
    occurred_at: String(raw.occurred_at || new Date().toISOString()),
    correlation_id: correlationId,
    causation_id: raw.causation_id == null ? null : String(raw.causation_id),
    idempotency_key: idempotencyKey,
    depth,
    payload: raw.payload && typeof raw.payload === "object" && !Array.isArray(raw.payload)
      ? raw.payload as Record<string, unknown>
      : {}
  };
}

export class BusinessWorkflow extends WorkflowEntrypoint<Env, BusinessEvent> {
  async run(event: WorkflowEvent<BusinessEvent>, step: WorkflowStep) {
    const businessEvent = await step.do("validate-event", async () => normalizeEvent(event.payload));

    const delivered = await step.do(
      "deliver-to-automation-kernel",
      { retries: { limit: 8, delay: "5 seconds", backoff: "exponential" }, timeout: "30 seconds" },
      async () => {
        const base = this.env.CORE_API_URL.replace(/\/$/, "");
        const response = await fetch(`${base}/v1/automation/events`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-api-key": this.env.CORE_API_KEY,
            "x-opticable-correlation-id": businessEvent.correlation_id,
            "x-opticable-idempotency-key": businessEvent.idempotency_key
          },
          body: JSON.stringify(businessEvent)
        });
        const text = await response.text();
        if (!response.ok) throw new Error(`Automation kernel HTTP ${response.status}: ${text.slice(0, 1000)}`);
        let body: unknown = text;
        try { body = JSON.parse(text); } catch {}
        return { status: response.status, body };
      }
    );

    return {
      ok: true,
      event_id: businessEvent.event_id,
      correlation_id: businessEvent.correlation_id,
      delivered
    };
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ service: "Opticable Control Plane", ok: true, durable_workflows: true, event_queue: true });
    }
    if (request.method === "POST" && url.pathname === "/v1/events") {
      if (!authorized(request, env)) return json({ error: "Unauthorized" }, 401);
      let event: BusinessEvent;
      try { event = normalizeEvent(await request.json()); }
      catch (error) { return json({ error: error instanceof Error ? error.message : "Invalid event" }, 400); }

      await env.EVENTS.send(event, { contentType: "json" });
      return json({
        accepted: true,
        event_id: event.event_id,
        correlation_id: event.correlation_id,
        queued: true
      }, 202);
    }
    return json({ error: "Not found" }, 404);
  },

  async queue(batch: MessageBatch<BusinessEvent>, env: Env): Promise<void> {
    for (const message of batch.messages) {
      const event = normalizeEvent(message.body);
      try {
        await env.BUSINESS_WORKFLOW.create({ id: event.event_id, params: event });
        message.ack();
      } catch (error) {
        const msg = error instanceof Error ? error.message.toLowerCase() : "";
        if (msg.includes("already") && msg.includes("exist")) {
          message.ack();
        } else {
          message.retry();
        }
      }
    }
  }
};
