// Real Chromium navigation/cookie/timer semantics against a loopback-only fixture.
// The simulated Access edge uses a distinct synthetic issuer/key and no Google
// credentials. A pass is not real-owner Cloudflare acceptance.
const assert=require('node:assert/strict');
const {chromium}=require(process.env.BUSINESS_PLAYWRIGHT);
const origin=process.env.COMMAND_FIXTURE_URL,control=process.env.COMMAND_FIXTURE_CONTROL;
const identityOrigin='https://127.0.0.1:'+new URL(origin).port;
async function rpc(path,body){const r=await fetch(control+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});assert(r.ok);return r.json();}
const metadata=async()=>(await(await fetch(control+'/events')).json()).events;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
// Playwright route interception does not re-run our synthetic identity handler
// on every HTTP redirect hop. Use separate document navigations for the mock
// SSO hand-off; Sec-Fetch-* remains browser-generated on the real origin GET.
const navigate=target=>({status:200,contentType:'text/html',headers:{'Cache-Control':'no-store'},body:'<!doctype html><script>location.replace('+JSON.stringify(target)+')</script>'});
async function until(predicate,label){for(let i=0;i<100;i++){if(await predicate())return;await wait(50);}throw new Error('Expected bounded browser transition did not complete: '+label);}
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']}),checks=[];
 let outside=0;
 async function fixture({ttl=3600,anonymous=false,mobile=false,dropFragment=false}={}){
  let identity=await rpc('/identity',{ttl}),now=identity.now,returns=0,hold=null;
  const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:mobile?{width:390,height:844}:{width:1440,height:1000},isMobile:mobile,hasTouch:mobile});
  const errors=[];context.on('page',page=>page.on('pageerror',e=>errors.push(e.message)));
  let returnTarget=origin+'/',page;
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin===identityOrigin){
    if(url.pathname==='/embed')return route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><iframe src="'+origin+'/"></iframe>'});
    if(url.pathname==='/callback'){
     identity=await rpc('/identity',{ttl});now=identity.now;returns++;
     return route.fulfill(navigate(returnTarget+(dropFragment?'#':'')));
    }
    return route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><a href="'+origin+'/">Return from identity provider</a>'});
   }
   if(url.origin!==origin){outside++;return route.abort();}
   if(anonymous)return route.continue();
   if(now>=identity.identity_expires_at){
    if(request.isNavigationRequest()&&request.frame()===page.mainFrame()){
     returnTarget=request.url();return route.fulfill(navigate(identityOrigin+'/callback'));
    }
    return route.fulfill({status:401,contentType:'application/json',body:'{"error":"Synthetic Access expired"}'});
   }
   if(hold&&url.pathname==='/api/sales')await hold;
   return route.continue({headers:{...request.headers(),'Cf-Access-Jwt-Assertion':identity.jwt}});
  });
  page=await context.newPage();await page.clock.install({time:new Date(now*1000)});
  return {context,page,errors,returns:()=>returns,
   advance:async(seconds,{timers=true}={})=>{const result=await rpc('/advance',{seconds});now=result.now;
    for(const p of context.pages())if(timers)await p.clock.fastForward(seconds*1000);else await p.clock.setFixedTime(new Date(now*1000));},
   hold:promise=>{hold=promise;},
   newPage:async()=>{const p=await context.newPage();await p.clock.install({time:new Date(now*1000)});return p;},
   fresh:async()=>{identity=await rpc('/identity',{ttl});now=identity.now;}};
 }
 try{
  // Browser-generated cross-site headers, not injected Sec-Fetch-* fixtures.
  const f=await fixture();await f.page.goto(identityOrigin+'/');
  const rootPromise=f.page.waitForResponse(response=>new URL(response.url()).origin===origin&&new URL(response.url()).pathname==='/'&&response.status()===200);
  await f.page.getByRole('link',{name:'Return from identity provider'}).click();const rootResponse=await rootPromise;
  await f.page.getByRole('heading',{name:'Today at Opticable',exact:true}).waitFor();
  let events=await metadata();assert(events.some(e=>e.path==='/'&&e.status===200&&e.site==='cross-site'&&e.mode==='navigate'&&e.destination==='document'));
  await f.page.goto(origin+'/#review');await f.page.getByRole('heading',{name:'Review existing work',exact:true}).waitFor();
  assert(rootResponse.headers()['content-security-policy'].includes("frame-ancestors 'none'"));assert.equal(rootResponse.headers()['x-frame-options'],'DENY');
  assert.equal(await f.page.locator('.work-card').count(),10);assert.equal(await f.page.locator('.error-page').count(),0);
  checks.push('actual cross-site document return and 16-package review UI');

  // A real in-flight fetch holds the cross-tab lock while renewal waits.
  const second=await f.newPage();await second.goto(origin+'/#overview');await second.getByRole('heading',{name:'Today at Opticable',exact:true}).waitFor();
  await f.advance(1081,{timers:false});
  let release;f.hold(new Promise(r=>{release=r;}));
  await f.page.evaluate(()=>{location.hash='#sales';});await wait(200);
  const before=(await metadata()).filter(e=>e.path==='/auth/renew').length;
  await second.getByRole('button',{name:'Renew session',exact:true}).click();await wait(200);
  assert.equal((await metadata()).filter(e=>e.path==='/auth/renew').length,before);
  release();f.hold(null);await f.page.getByRole('heading',{name:'Move the right conversations forward',exact:true}).waitFor();
  await second.getByRole('status').filter({hasText:'has been renewed'}).waitFor();
  assert.equal((await metadata()).filter(e=>e.path==='/auth/renew'&&e.status===200).length,before+1);
  await f.page.evaluate(()=>{location.hash='#marketing';});await f.page.getByRole('heading',{name:'Measure business performance',exact:true}).waitFor();
  checks.push('two real tabs, in-flight read/rotation coordination and fresh shared-cookie CSRF');
  await second.close();

  // Same-origin iframe is denied by the origin as well as its CSP.
  const embed=await f.newPage();await embed.goto(identityOrigin+'/embed');await wait(200);
  assert.equal(embed.frames().length,2);
  assert.equal(await embed.frames()[1].getByRole('heading',{name:'Today at Opticable',exact:true}).count(),0);
  await embed.close();checks.push('browser embedding blocked; CSP/frame headers enforced, origin iframe guard tested separately');
  // route.continue above uses a real loopback TLS response: Chromium processes
  // Clear-Site-Data here, unlike a wholly intercepted/fulfilled fake response.
  const fixtureAccess='Fixture_Access_Authorization';
  await f.context.addCookies([
   {name:fixtureAccess,value:'synthetic-access-cookie',domain:'localhost',path:'/',secure:true,httpOnly:true,sameSite:'Lax'},
   {name:'Fixture_Analytics',value:'synthetic-analytics-cookie',domain:'localhost',path:'/',secure:true,sameSite:'Lax'},
   {name:'Fixture_Advertising',value:'synthetic-advertising-cookie',domain:'localhost',path:'/public-site/',secure:true,sameSite:'Lax'},
   {name:'Fixture_Consent',value:'synthetic-consent-cookie',domain:'localhost',path:'/',secure:true,sameSite:'Lax'}]);
  const retained=async()=>(await f.context.cookies()).filter(c=>c.name.startsWith('Fixture_')).sort((a,b)=>a.name.localeCompare(b.name));
  const beforeLogout=await retained();
  await f.page.getByRole('button',{name:'Sign out',exact:true}).click();await f.page.getByRole('heading',{name:'You are signed out',exact:true}).waitFor();
  assert.equal((await f.context.cookies()).filter(c=>c.name==='__Host-optibrain').length,0);
  assert.deepEqual(await retained(),beforeLogout,'Real TLS logout must preserve synthetic Access, analytics, advertising and consent cookies');
  let edgeSawCookie=false;
  await f.page.route(origin+'/cdn-cgi/access/logout',async route=>{
   edgeSawCookie=(route.request().headers().cookie||'').split(';').some(c=>c.trim().startsWith(fixtureAccess+'='));
   return route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><h1>Synthetic Access logout handoff</h1>'});
  });
  await f.page.goto(origin+'/cdn-cgi/access/logout');assert(edgeSawCookie,'Access cookie must survive until the edge logout request');
  await f.page.unroute(origin+'/cdn-cgi/access/logout');
  checks.push('real TLS Clear-Site-Data preserves Access handoff and unrelated marketing/consent cookies');
  await f.fresh();await f.page.goto(identityOrigin+'/');await f.page.getByRole('link',{name:'Return from identity provider'}).click();
  await f.page.getByRole('heading',{name:'Today at Opticable',exact:true}).waitFor();assert.deepEqual(f.errors,[]);
  checks.push('logout and subsequent new synthetic Access login');await f.context.close();

  const a=await fixture({anonymous:true});const denied=await a.page.goto(origin+'/');assert.equal(denied.status(),401);
  assert.equal(await a.page.getByRole('heading',{name:'Today at Opticable'}).count(),0);await a.context.close();checks.push('anonymous origin rejection');

  // One full 15-minute Access rollover, with valid simulated global SSO.
  // Deliberately remove the fragment at callback: section-only query survives.
  const r=await fixture({ttl:900,dropFragment:true,mobile:true});
  await r.page.goto(origin+'/#review');await r.page.getByRole('heading',{name:'Review existing work',exact:true}).waitFor();
  const renewBefore=(await metadata()).filter(e=>e.path==='/auth/renew').length;
  await r.advance(902);await until(()=>r.returns()===1,'15-minute rollover');await r.page.getByRole('heading',{name:'Review existing work',exact:true}).waitFor();
  await r.page.waitForFunction(()=>location.hash==='#review'&&!location.search);
  assert.equal(r.returns(),1);assert.equal((await metadata()).filter(e=>e.path==='/auth/renew').length,renewBefore);
  await wait(500);assert.equal(r.returns(),1);assert.equal(await r.page.locator('.error-page').count(),0);
  assert(await r.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  checks.push('15-minute token rollover, bounded SSO return, selected section and mobile layout');

  // Background/mobile resume uses a fresh origin session or SSO once, never a
  // one-second rotation loop. Focus dispatch exercises the shipped handler.
  await r.advance(1000,{timers:false});await r.page.evaluate(()=>window.dispatchEvent(new Event('focus')));await until(()=>r.returns()===2,'mobile resume');
  await r.page.waitForFunction(()=>location.hash==='#review');await r.page.getByRole('heading',{name:'Review existing work',exact:true}).waitFor();
  assert.equal(r.returns(),2);assert.deepEqual(r.errors,[]);
  const empty=await r.page.evaluate(async()=>({local:Object.keys(localStorage),session:Object.keys(sessionStorage),cache:await caches.keys()}));
  assert.deepEqual(empty,{local:[],session:[],cache:[]});checks.push('idle/mobile resume without credential or private-data storage');await r.context.close();

  // An unusably short return never becomes an automatic navigation loop.
  const b=await fixture({ttl:2});await b.page.goto(origin+'/#sales');await b.page.getByRole('heading',{name:'Move the right conversations forward',exact:true}).waitFor();
  await b.advance(4);await until(()=>b.returns()===1,'short-token loop bound');await b.page.getByRole('heading',{name:'Move the right conversations forward',exact:true}).waitFor();
  await b.advance(4);await b.page.getByRole('button',{name:'Continue securely',exact:true}).waitFor();
  assert.equal(b.returns(),1);await wait(500);assert.equal(b.returns(),1);checks.push('failed SSO refresh stops after one automatic return');await b.context.close();
  assert.equal(outside,0);
  console.log(JSON.stringify({passed:true,checks,real_browser:'Chromium',production_owner_authentication:false,
   simulated_access_and_sso:true,synthetic_journal_only:true,outside_requests:outside,production_mutations:0}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
