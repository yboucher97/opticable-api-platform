// Real Chromium plus the actual production-mode application over loopback only.
// Access/SSO is simulated with conspicuously synthetic cookie names and values.
// No live hostname is contacted and no real owner credential is read or replayed.
const assert=require('node:assert/strict'),https=require('node:https');
const {chromium}=require(process.env.BUSINESS_PLAYWRIGHT);
const backend=new URL(process.env.COMMAND_FIXTURE_URL),control=process.env.COMMAND_FIXTURE_CONTROL;
assert.equal(backend.hostname,'localhost');backend.hostname='127.0.0.1';
const origin='https://app.opticable.ca',accessName='Fixture_Access_Authorization';
const rpc=async()=>{const r=await fetch(control+'/identity',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});assert(r.ok);return r.json();};
function local(path,method,headers,body){
 return new Promise((resolve,reject)=>{
  const request=https.request(new URL(path,backend),{method,rejectUnauthorized:false,
   headers:{...headers,host:'app.opticable.ca'}},response=>{
    const chunks=[];response.on('data',b=>chunks.push(b));response.on('end',()=>resolve({status:response.statusCode,
     headers:Object.fromEntries(Object.entries(response.headers).map(([k,v])=>[k,Array.isArray(v)?v.join('\n'):String(v)])),body:Buffer.concat(chunks)}));
   });request.on('error',reject);request.end(body);
 });
}
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({ignoreHTTPSErrors:true,serviceWorkers:'block'});
 let identity=await rpc(),accessActive=true,globalActive=true,globalRevoked=false,logoutRequests=0,originLogouts=0,unexpected=0;
 let originCookie,oldIdentity,rootNavigations=0;const errors=[],statuses=[];
 const marketing=()=>context.cookies().then(c=>c.filter(x=>x.name.startsWith('Fixture_Marketing_')).map(x=>({name:x.name,domain:x.domain,path:x.path,value:x.value})).sort((a,b)=>a.name.localeCompare(b.name)));
 await context.addCookies([
  {name:accessName,value:'synthetic-app-access',domain:'app.opticable.ca',path:'/',httpOnly:true,secure:true,sameSite:'Lax'},
  {name:'Fixture_Global_SSO',value:'synthetic-global-session',domain:'fixture-sso.example.test',path:'/',httpOnly:true,secure:true,sameSite:'Lax'},
  {name:'Fixture_Marketing_Analytics',value:'synthetic-analytics',domain:'.opticable.ca',path:'/',secure:true,sameSite:'Lax'},
  {name:'Fixture_Marketing_Advertising',value:'synthetic-advertising',domain:'www.opticable.ca',path:'/',secure:true,sameSite:'Lax'},
  {name:'Fixture_Marketing_Consent',value:'synthetic-consent',domain:'www.opticable.ca',path:'/',secure:true,sameSite:'Lax'}]);
 const marketingBefore=await marketing();
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());
  if(url.origin!==origin){unexpected++;return route.abort();}
  if(request.isNavigationRequest()&&url.pathname==='/')rootNavigations++;
  const names=(request.headers().cookie||'').split(';').map(x=>x.trim().split('=')[0]);
  if(url.pathname==='/cdn-cgi/access/logout'){
   logoutRequests++;assert(names.includes(accessName),'Access must receive its cookie before provider logout');
   assert(!names.includes('__Host-optibrain'),'Origin cookie must already have been expired');
   accessActive=false;globalActive=false;globalRevoked=true;
   return route.fulfill({status:200,contentType:'text/html',headers:{'Cache-Control':'no-store','Set-Cookie':accessName+'=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax'},
    body:'<!doctype html><h1>Fixture Access logout completed</h1><p>Application and global Access sessions revoked.</p>'});
  }
  if(!accessActive)return route.fulfill({status:401,contentType:'application/json',body:'{"error":"Synthetic Access session revoked"}'});
  const response=await local(url.pathname+url.search,request.method(),{...request.headers(),'cf-access-jwt-assertion':identity.jwt},request.postDataBuffer());
  statuses.push({path:url.pathname,status:response.status});
  if(url.pathname==='/auth/logout'){
   originLogouts++;assert.equal(response.status,200);
   assert.equal(response.headers['clear-site-data'],'"cache", "storage"');
   assert.equal(JSON.parse(response.body).logout_url,origin+'/cdn-cgi/access/logout');
  }
  await route.fulfill(response);
 });
 try{
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/#review');await page.getByRole('heading',{name:'Review existing work',exact:true}).waitFor();
  assert.equal(await page.locator('.work-card').count(),10);
  originCookie=(await context.cookies(origin)).find(c=>c.name==='__Host-optibrain').value;oldIdentity=identity.jwt;
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await page.getByRole('heading',{name:'Fixture Access logout completed',exact:true}).waitFor();
  assert.equal(originLogouts,1);assert.equal(logoutRequests,1);
  assert(!accessActive&&!globalActive&&globalRevoked,'Model documented cross-application/global revocation explicitly');
  assert(!(await context.cookies(origin)).some(c=>c.name==='__Host-optibrain'||c.name===accessName));
  assert.deepEqual(await marketing(),marketingBefore,'Logout must not clear unrelated marketing/consent cookies');
  const empty=await page.evaluate(async()=>({local:Object.keys(localStorage),session:Object.keys(sessionStorage),caches:await caches.keys()}));
  assert.deepEqual(empty,{local:[],session:[],caches:[]});
  assert.equal((await local('/api/overview','GET',{'cf-access-jwt-assertion':oldIdentity,cookie:'__Host-optibrain='+originCookie})).status,401);
  identity=await rpc();
  assert.equal((await local('/api/overview','GET',{'cf-access-jwt-assertion':identity.jwt,cookie:'__Host-optibrain='+originCookie})).status,403);
  // An explicit new synthetic identity models a new sign-in after global logout.
  accessActive=true;globalActive=true;
  await context.addCookies([{name:accessName,value:'synthetic-new-app-access',domain:'app.opticable.ca',path:'/',httpOnly:true,secure:true,sameSite:'Lax'}]);
  await page.goto(origin+'/#review');await page.getByRole('heading',{name:'Review existing work',exact:true}).waitFor();
  const fresh=(await context.cookies(origin)).find(c=>c.name==='__Host-optibrain');assert(fresh&&fresh.value!==originCookie);
  assert.equal(await page.locator('.error-page').count(),0);assert.deepEqual(await marketing(),marketingBefore);
  assert.equal(statuses.filter(x=>x.path==='/auth/renew').length,0);
  assert(statuses.every(x=>x.status===200));assert.equal(rootNavigations,2);assert.equal(unexpected,0);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,synthetic_only:true,production_mode_loopback_application:true,
   live_cloudflare_or_google_acceptance:false,actual_origin_logout:200,origin_session_and_old_token_rejected:true,
   access_cookie_received_before_edge_logout:true,documented_global_sso_effect_explicitly_simulated:true,
   fresh_second_login:true,marketing_cookie_names_preserved:marketingBefore.map(x=>x.name),marketing_cookie_values_unchanged:true,
   no_private_storage:true,renewal_storm:false,root_navigations:rootNavigations,real_external_requests:unexpected}));
 }finally{await context.close();await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
