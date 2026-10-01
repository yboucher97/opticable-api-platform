function torontoParts(epochMs) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Toronto",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  });
  const parts = Object.fromEntries(formatter.formatToParts(new Date(epochMs)).map((p) => [p.type, p.value]));
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    weekday: parts.weekday,
    hour: Number(parts.hour),
    minute: Number(parts.minute)
  };
}


function intent(event_type, bucket, payload) { return {event_type, bucket, payload}; }

export function lifecycleSchedules(epochMs) {
  const local = torontoParts(epochMs);
  const slot = `${local.date}T${String(local.hour).padStart(2, "0")}:${String(local.minute).padStart(2, "0")}`;
  const events = [];

  // Mailbox: hourly. One search call per hour; downstream event idempotency prevents duplicate processing.
  if (local.minute === 0) {
    events.push(intent("customer.lifecycle.mailbox.poll.requested", `mail-${slot}`, {
      account_id: "1083319000000008002",
      mailbox_address: "yboucher@opticable.ca",
      window_days: 1,
      limit: 100
    }));
  }

  // Zoho Sign observation: every two hours during the normal operating day, read-only.
  if (local.minute === 15 && local.hour >= 7 && local.hour <= 21 && local.hour % 2 === 1) {
    events.push(intent("customer.lifecycle.sign.poll.requested", `sign-${slot}`, {
      page: 1,
      per_page: 100
    }));
  }

  // Finance observation: once daily. Zoho Books is strictly GET/read-only by policy and gateway enforcement.
  if (local.hour === 7 && local.minute === 15) {
    events.push(intent("customer.lifecycle.finance.poll.requested", `finance-${local.date}`, {
      organization_id: "802337532",
      per_page: 100
    }));
  }

  // Phase13 P1: retired digest/draft workflows have no scheduling authority.
  // Do not enqueue disabled daily/weekly producers or add customer Mail writes.

  return events;
}

export async function deliverEvent(env, event, PermanentError) {
  const base = env.CORE_API_URL.replace(/\/$/, "");
  const response = await fetch(`${base}/v1/automation/events`, {
    method: "POST",
    headers: {"content-type": "application/json", "x-api-key": env.CORE_API_KEY,
      "x-opticable-correlation-id": event.correlation_id, "x-opticable-idempotency-key": event.idempotency_key},
    body: JSON.stringify(event)
  });
  if (!response.ok) {
    const permanent = response.status >= 400 && response.status < 500 && ![408, 429].includes(response.status);
    // Never put a provider response or credentials in Workflow error logs.
    throw new (permanent ? PermanentError : Error)(`Automation kernel HTTP ${response.status}`);
  }
  const text = await response.text();
  let body = text;
  try { body = JSON.parse(text); } catch {}
  return {status: response.status, body};
}

export async function workflowInstanceId(eventId) {
  // Preserve historical valid instance IDs and the original business event ID.
  // Provider IDs disallow ':' in the scheduler's Toronto slots. Hash invalid
  // IDs instead of sanitizing them, which would collapse distinct identities.
  if (/^[a-zA-Z0-9_][a-zA-Z0-9_-]{0,99}$/.test(eventId) && !/^cf_[0-9a-f]{64}$/.test(eventId))
    return eventId;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(eventId));
  return 'ob-' + Array.from(new Uint8Array(digest), b=>b.toString(16).padStart(2,'0')).join('');
}
