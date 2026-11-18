// Deterministic browser-session logic. Synthetic metadata only, no live tokens.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {createSessionClient,reauthenticationTarget}=require('./command_center_assets/session.js');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function clock(){
 let current=2000000000000,id=0;const tasks=new Map();
 return {now:()=>current,set:(fn,ms)=>{tasks.set(++id,{fn,at:current+ms});return id;},clear:id=>tasks.delete(id),
  advance:async ms=>{current+=ms;for(const [id,task]of [...tasks])if(task.at<=current){tasks.delete(id);task.fn();}await flush();await flush();},
  pending:()=>[...tasks.values()].map(t=>t.at-current)};
}
function fixture({lock=true,identity=3600,origin=1200,noAdvance=false}={}){
 const time=clock(),base=time.now()/1000,calls=[],expired=[];
 let sharedTail=Promise.resolve(),version=1,active=true,slow=null,failMutation=false;
 const shared={expires_at:base+origin,identity_expires_at:base+identity,absolute_expires_at:base+28800,
  csrf:'synthetic-csrf-1',email:'owner@example.test',mode:'staging',editorial_writes:false};
 function exclusive(fn){const r=sharedTail.then(fn);sharedTail=r.catch(()=>{});return r;}
 const response=(status,body)=>({status,ok:status>=200&&status<300,json:async()=>({...body})});
 async function transport(path,options){
  calls.push({path,options,version});
  if(time.now()/1000>=shared.identity_expires_at)return response(401,{error:'Access expired'});
  if(path==='/auth/login'){
   if(time.now()/1000>=shared.expires_at)active=false;
   if(!active){active=true;shared.expires_at=Math.min(time.now()/1000+1200,shared.identity_expires_at);}
   return response(200,shared);
  }
  if(!active||time.now()/1000>=shared.expires_at){active=false;return response(403,{error:'Session required'});}
  if(path==='/auth/session')return response(200,shared);
  if(options.method==='POST'&&options.headers['X-Optibrain-CSRF']!==shared.csrf)return response(403,{error:'CSRF'});
  if(path==='/api/slow'&&slow)await slow;
  if(path==='/auth/renew'){
   version++;shared.csrf='synthetic-csrf-'+version;
   if(!noAdvance)shared.expires_at=Math.min(time.now()/1000+1200,shared.identity_expires_at,shared.absolute_expires_at);
   return response(200,shared);
  }
  if(path==='/auth/logout'){active=false;return response(200,{signed_out:true,logout_url:null});}
  return response(failMutation&&options.method==='POST'?503:200,{okay:true});
 }
 const make=(options={})=>createSessionClient({fetch:transport,now:time.now,setTimer:time.set,clearTimer:time.clear,
  exclusive:lock?exclusive:null,onExpired:e=>expired.push(e),...options});
 return {time,calls,expired,shared,make,slow:promise=>{slow=promise;},failMutation:()=>{failMutation=true;}};
}

test('fixed Access ceiling never rotates repeatedly, and expires once',async()=>{
 const f=fixture({identity:90,origin:90}),c=f.make();await c.start();
 await c.renew();await c.renew();assert.equal(f.calls.filter(x=>x.path==='/auth/renew').length,0);
 assert.deepEqual(f.time.pending(),[91000]);await f.time.advance(92000);assert.equal(f.expired.length,1);
 await f.time.advance(600000);await c.resume();assert.equal(f.expired.length,1);assert.deepEqual(f.time.pending(),[]);
});
test('server response with unchanged expiry suppresses another rotation',async()=>{
 const f=fixture({noAdvance:true,origin:60}),c=f.make();await c.start();await c.renew();await c.renew();
 assert.equal(f.calls.filter(x=>x.path==='/auth/renew').length,1);
 assert.deepEqual(f.time.pending(),[61000]);
});
test('renewal is single flight and waits for in-flight reads',async()=>{
 const f=fixture({origin:60}),c=f.make();await c.start();let release;f.slow(new Promise(r=>{release=r;}));
 const read=c.request('/api/slow');await flush();const a=c.renew(),b=c.renew();assert.equal(a,b);
 const next=c.request('/api/overview');await flush();assert.equal(f.calls.filter(x=>x.path==='/auth/renew').length,0);
 release();await Promise.all([read,a,next]);
 const order=f.calls.map(x=>x.path);assert(order.indexOf('/api/slow')<order.indexOf('/auth/renew'));
 assert(order.indexOf('/auth/renew')<order.indexOf('/api/overview'));assert.equal(order.filter(x=>x==='/auth/renew').length,1);
});
test('two tabs share the lock and refresh CSRF after another tab rotates',async()=>{
 const f=fixture({origin:60}),a=f.make(),b=f.make();await a.start();await b.start();
 let release;f.slow(new Promise(r=>{release=r;}));const reading=a.request('/api/slow');await flush();
 const rotation=b.renew(),mutation=a.request('/api/review/decisions',{method:'POST',body:{choice:'APPROVE'},csrf:true});
 await flush();assert.equal(f.calls.filter(x=>x.path==='/auth/renew').length,0);
 release();await Promise.all([reading,rotation,mutation]);
 const sent=f.calls.find(x=>x.path==='/api/review/decisions');assert.equal(sent.options.headers['X-Optibrain-CSRF'],'synthetic-csrf-2');
 assert.equal(f.calls.filter(x=>x.path==='/api/review/decisions').length,1);
});
test('an unsuccessful consequential mutation is never retried',async()=>{
 const f=fixture(),c=f.make();await c.start();f.failMutation();
 await assert.rejects(c.request('/api/review/decisions',{method:'POST',body:{},csrf:true}));
 assert.equal(f.calls.filter(x=>x.path==='/api/review/decisions').length,1);assert.equal(f.expired.length,0);
});
test('edge redirect is not followed by fetch and sign-in is requested once',async()=>{
 const f=fixture(),c=f.make({fetch:async()=>({type:'opaqueredirect',status:0})});
 await assert.rejects(c.start());await c.resume();assert.deepEqual(f.expired,[{automatic:true}]);
 const g=fixture(),d=g.make();await d.start();
 assert(g.calls.every(x=>x.options.redirect==='manual'&&x.options.cache==='no-store'&&x.options.credentials==='same-origin'));
 assert(g.calls.every(x=>x.options.headers['X-Requested-With']==='XMLHttpRequest'));
});
test('idle and mobile resume renew an expired origin session under a valid identity',async()=>{
 let visible=false;const f=fixture({origin:60}),c=f.make({visible:()=>visible});await c.start();assert.deepEqual(f.time.pending(),[]);
 await f.time.advance(90000);visible=true;f.shared.expires_at=f.time.now()/1000-1;
 // The first expired origin session is found on resume; start is idempotent.
 // The gateway stub marks it expired before issuing a new bounded session.
 const originalCalls=f.calls.length;
 // Model cookie expiration (the real browser removes Max-Age at this point).
 const expiredSession=await c.resume();
 assert(expiredSession.expires_at>f.time.now()/1000);assert(f.calls.length>originalCalls);assert.equal(f.expired.length,0);
 assert(f.shared.expires_at<=f.shared.identity_expires_at);
});
test('expired Access on resume requires SSO rather than repeated origin logins',async()=>{
 const f=fixture({identity:60,origin:60}),c=f.make();await c.start();c.pause();await f.time.advance(90000);
 await assert.rejects(c.resume());await c.resume();assert.equal(f.expired.length,1);
 assert.equal(f.calls.filter(x=>x.path==='/auth/login').length,2);
});
test('without Web Locks origin rotation is disabled, not raced across tabs',async()=>{
 const f=fixture({lock:false}),c=f.make();await c.start();await c.renew();
 assert.equal(f.calls.filter(x=>x.path==='/auth/renew').length,0);assert.deepEqual(f.time.pending(),[1201000]);
});
test('logout stops timers, requests and automatic resume',async()=>{
 const f=fixture(),c=f.make();await c.start();await c.logout();await c.resume();
 await assert.rejects(c.request('/api/overview'));assert.deepEqual(f.time.pending(),[]);assert.equal(f.expired.length,0);
 assert.equal(f.calls.filter(x=>x.path==='/auth/logout').length,1);
});
test('same-origin SSO return preserves section and bounds automatic navigation',()=>{
 const now=2000000000000,url='https://app.opticable.ca/#review?package=synthetic';
 const target=reauthenticationTarget(url,now);const parsed=new URL(target);
 assert.equal(parsed.origin,'https://app.opticable.ca');assert.equal(parsed.pathname,'/');
 assert.equal(parsed.hash,'#review?package=synthetic');assert.equal(parsed.searchParams.get('_ob_section'),'review');
 assert.equal(reauthenticationTarget(target,now+1000),null);assert(reauthenticationTarget(target,now+1000,true));
 assert.equal(new URL(reauthenticationTarget('https://app.opticable.ca/evil#https://evil.test',now)).hash,'#overview');
});
test('rotation transport failure stops timers instead of a retry loop',async()=>{
 const f=fixture({origin:60});let attempts=0;
 const c=f.make({fetch:async(path,options)=>{
  if(path==='/auth/renew'){attempts++;throw new Error('Synthetic transport failure');}
  if(path==='/auth/login'||path==='/auth/session')return {status:200,ok:true,json:async()=>f.shared};
 }});
 await c.start();await assert.rejects(c.renew(false));await f.time.advance(600000);
 assert.equal(attempts,1);assert.deepEqual(f.time.pending(),[]);assert.deepEqual(f.expired,[{automatic:false}]);
});
test('32 short-token cycles model a workday without an origin renewal storm',async()=>{
 const f=fixture({identity:900,origin:900}),globalEnd=f.time.now()/1000+28800;
 for(let cycle=0;cycle<32;cycle++){
  const c=f.make();await c.start();
  await f.time.advance((f.shared.expires_at-f.time.now()/1000+1)*1000);
  assert.equal(f.expired.length,cycle+1);
  if(cycle<31){f.shared.identity_expires_at=Math.min(globalEnd,f.time.now()/1000+900);f.shared.expires_at=f.shared.identity_expires_at;}
 }
 assert.equal(f.calls.filter(x=>x.path==='/auth/renew').length,0);
 assert.equal(f.calls.filter(x=>x.path==='/auth/login').length,32);
 await assert.rejects(f.make().start()); // The simulated global identity is over.
});
test('expired or malformed session metadata cannot cause a new timer loop',async()=>{
 const f=fixture(),c=f.make({fetch:async()=>({status:200,ok:true,json:async()=>({...f.shared,expires_at:f.time.now()/1000-1})})});
 await assert.rejects(c.start());assert.deepEqual(f.time.pending(),[]);assert.equal(f.expired.length,1);
});
