import {test} from 'node:test';
import assert from 'node:assert/strict';
import {lifecycleSchedules, deliverEvent, workflowInstanceId, validateHeldIdentity, captureHeldQueueMessage} from '../src/runtime-policy.js';

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

test('provider instance identity preserves old IDs and safely maps every scheduled slot', async () => {
  assert.equal(await workflowInstanceId('mailbox-poll-123'),'mailbox-poll-123');
  const original='schedule-customer-lifecycle-mailbox-poll-requested-mail-2026-10-01T19:00';
  const mapped=await workflowInstanceId(original);
  assert.match(mapped,/^[a-zA-Z0-9_][a-zA-Z0-9_-]{0,99}$/);
  assert.equal(mapped,await workflowInstanceId(original));
  assert.notEqual(mapped,await workflowInstanceId(original.replace(':','-')));
  const ids=[];
  for (let i=0;i<96;i++) for (const intent of lifecycleSchedules(Date.parse('2026-10-01T04:00:00Z')+i*900000)) {
    const id=await workflowInstanceId(`schedule-${intent.event_type}-${intent.bucket}`);
    assert.match(id,/^[a-zA-Z0-9_][a-zA-Z0-9_-]{0,99}$/);ids.push(id);
  }
  assert.equal(new Set(ids).size,ids.length);
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

test('hold handoff requires a committed receipt for this original delivery', async () => {
  const previous=globalThis.fetch;
  const env={CORE_API_URL:'https://example.invalid',CORE_API_KEY:'fixture',CORE_INTAKE_HOLD_REQUIRED:'true'};
  const event={event_id:'original',correlation_id:'original',idempotency_key:'original'};
  const receipt={accepted:true,duplicate:false,event_id:'original',received_event_id:'original',
    durable:true,intake_only:true,held:true,run_ids:[]};
  try {
    for (const value of ['unconfirmed',{}, {...receipt,durable:false}, {...receipt,intake_only:false},
      {...receipt,received_event_id:'different'}, {...receipt,accepted:false},
      {...receipt,duplicate:true}, {...receipt,run_ids:['unexpected-run']}, {...receipt,held:false}]) {
      globalThis.fetch=async()=>new Response(JSON.stringify(value),{status:202});
      await assert.rejects(deliverEvent(env,event,Error),/Durable intake receipt not confirmed/);
    }
    for (const value of [receipt,{...receipt,accepted:false,duplicate:true,event_id:'earlier-canonical',held:false}]) {
      globalThis.fetch=async()=>new Response(JSON.stringify(value),{status:202});
      assert.deepEqual(await deliverEvent(env,event,Error),{status:202,body:value});
    }
    env.CORE_INTAKE_HOLD_REQUIRED='typo';
    await assert.rejects(deliverEvent(env,event,Error),/Invalid intake receipt policy/);
  } finally {globalThis.fetch=previous;}
});

test('hold queue ACK occurs only after a validated committed receipt; errors retry original', async () => {
  const previous=globalThis.fetch;
  const env={CORE_API_URL:'https://example.invalid',CORE_API_KEY:'fixture',CORE_INTAKE_HOLD_REQUIRED:'true'};
  const event={event_id:'original',correlation_id:'original',idempotency_key:'original'};
  try {
    for (const sample of [{status:503,body:{}},{status:202,body:{}},
        {status:202,body:{accepted:true,duplicate:false,event_id:'original',received_event_id:'original',durable:true,intake_only:true,held:true,run_ids:[]}},
        {status:202,body:{accepted:false,duplicate:true,event_id:'original',received_event_id:'original',durable:true,intake_only:true,held:true,run_ids:[]}}]) {
      const calls=[];
      globalThis.fetch=async(url,options)=>{
        assert.equal(JSON.parse(options.body).event_id,'original');
        calls.push('committed-response');return new Response(JSON.stringify(sample.body),{status:sample.status});
      };
      await captureHeldQueueMessage(env,{ack:()=>calls.push('ACK'),retry:()=>calls.push('RETRY')},event);
      assert.deepEqual(calls,['committed-response',sample.body.durable===true?'ACK':'RETRY']);
    }
    for (const input of [null,{}, {event_id:''},{event_id:123}])
      assert.throws(()=>validateHeldIdentity(env,input),/Original event_id/);
    assert.equal(validateHeldIdentity(env,event),event);
  } finally {globalThis.fetch=previous;}
});
