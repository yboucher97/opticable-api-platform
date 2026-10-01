import {test} from 'node:test';
import assert from 'node:assert/strict';
import {lifecycleSchedules, deliverEvent} from '../src/runtime-policy.js';

test('one scheduler owns observers; retired draft/digest producers never enqueue', () => {
  for (let ms=Date.parse('2026-10-01T04:00:00Z');ms<Date.parse('2026-10-02T04:00:00Z');ms+=900000) {
    for (const event of lifecycleSchedules(ms)) {
      assert.match(event.event_type, /^customer\.lifecycle\.(mailbox|sign|finance)\.poll\.requested$/);
      assert.equal(event.payload.create_mail_draft, undefined);
    }
  }
  const day=Array.from({length:96},(_,i)=>lifecycleSchedules(Date.parse('2026-10-01T04:00:00Z')+i*900000)).flat();
  assert.equal(day.filter(x=>x.event_type.includes('mailbox')).length,24);
  assert.equal(day.filter(x=>x.event_type.includes('sign')).length,8);
  assert.equal(day.filter(x=>x.event_type.includes('finance')).length,1);
  assert.deepEqual(lifecycleSchedules(Date.parse('2026-10-01T11:15:00Z')),
    lifecycleSchedules(Date.parse('2026-10-01T11:15:00Z')));
});

test('Toronto finance slot stays 07:15 across DST', () => {
  for (const time of ['2026-10-01T11:15:00Z','2026-12-01T12:15:00Z'])
    assert.ok(lifecycleSchedules(Date.parse(time)).some(x=>x.event_type.includes('finance')));
});

test('delivery preserves idempotency and avoids retrying permanent failures or leaking bodies', async () => {
  class PermanentError extends Error {}
  const previous=globalThis.fetch;
  const env={CORE_API_URL:'https://example.invalid/',CORE_API_KEY:'fixture'};
  const event={event_id:'test',correlation_id:'test',idempotency_key:'test'};
  try {
    for (const status of [400,401,403,404,422,408,429,500,503]) {
      globalThis.fetch=async (url,options)=>{
        assert.equal(url,'https://example.invalid/v1/automation/events');
        assert.equal(options.headers['x-opticable-idempotency-key'],'test');
        return new Response('SECRET-RESPONSE',{status});
      };
      await assert.rejects(deliverEvent(env,event,PermanentError), error=>{
        assert.equal(error instanceof PermanentError,[400,401,403,404,422].includes(status));
        assert.equal(error.message,`Automation kernel HTTP ${status}`);
        return true;
      });
    }
    globalThis.fetch=async()=>new Response('{"accepted":true}',{status:202});
    assert.deepEqual(await deliverEvent(env,event,PermanentError),{status:202,body:{accepted:true}});
  } finally {globalThis.fetch=previous;}
});
