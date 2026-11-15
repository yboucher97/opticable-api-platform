// Existing Playwright/axe installation; synthetic staging JWT only, no real approval.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.BUSINESS_PLAYWRIGHT);
const AxeBuilder=require(process.env.BUSINESS_AXE).default;
(async()=>{
 const auth=JSON.parse(fs.readFileSync(process.env.COMMAND_PREVIEW_AUTH,'utf8'));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({ignoreHTTPSErrors:true,extraHTTPHeaders:{'Cf-Access-Jwt-Assertion':auth.jwt},viewport:{width:1440,height:1100}});
 const page=await context.newPage(),errors=[],checks=[];let outside=0;
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',r=>{if(new URL(r.request().url()).origin!==auth.url){outside++;return r.abort();}return r.continue();});
 await page.goto(auth.url,{waitUntil:'networkidle'});await page.getByRole('heading',{name:'Today at Opticable'}).waitFor();
 for(const [width,height,label] of [[1440,1100,'desktop'],[834,1112,'tablet'],[390,1200,'mobile']]){
  await page.setViewportSize({width,height});await page.goto(auth.url+'/#overview',{waitUntil:'networkidle'});await page.getByRole('heading',{name:'Today at Opticable'}).waitFor();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();assert.equal(axe.violations.length,0,JSON.stringify(axe.violations));
  if(label!=='tablet')await page.screenshot({path:process.env.COMMAND_SCREENSHOTS+'/'+label+'.png',fullPage:true});
  checks.push({label,width,axe_violations:0,overflow:false});
 }
 await page.setViewportSize({width:1440,height:1100});
 const routes={sales:'Move the right conversations forward',marketing:'Measure business performance',content:'Content & campaigns',review:'Review existing work',files:'Business files & reports',system:'System, integrations & storage',settings:'Owner settings'};
 for(const [route,title] of Object.entries(routes)){
  await page.goto(auth.url+'/#'+route,{waitUntil:'networkidle'});await page.getByRole('heading',{name:title,exact:true}).waitFor();
  assert.equal(await page.locator('.error-page').count(),0);checks.push({route,navigation:'PASS'});
 }
 await page.goto(auth.url+'/#review',{waitUntil:'networkidle'});await page.getByRole('heading',{name:'Review existing work',exact:true}).waitFor();assert.equal(await page.locator('.work-card').count(),10);
 await page.getByRole('button',{name:'Next',exact:true}).click();await page.waitForFunction(()=>location.hash.includes('page=2'));await page.waitForFunction(()=>document.querySelectorAll('.work-card').length===6);
 await page.goto(auth.url+'/#files',{waitUntil:'networkidle'});await page.getByRole('heading',{name:'Business files & reports',exact:true}).waitFor();await page.getByRole('searchbox').fill('EST-1145');await page.getByRole('button',{name:'Search',exact:true}).click();
 await page.waitForFunction(()=>location.hash.includes('EST-1145'));await page.locator('.work-card').first().waitFor();assert(await page.locator('.work-card').count()>0);
 await page.getByRole('link',{name:'View exact draft →'}).first().click();await page.getByRole('button',{name:'Accept draft',exact:true}).waitFor();
 await page.getByRole('button',{name:'Accept draft',exact:true}).click();await page.getByRole('dialog').waitFor();assert(await page.getByRole('dialog').textContent().then(t=>t.includes('grants no permission')));
 await page.getByRole('button',{name:'Validate preview decision',exact:true}).click();await page.getByRole('status').filter({hasText:'Preview validated'}).waitFor();
 await page.getByRole('button',{name:'Request revision',exact:true}).click();assert(await page.locator('#revision-reason').getAttribute('required')!==null);await page.getByLabel('Feedback').fill('Synthetic staging validation only; do not record a production revision.');await page.getByRole('button',{name:'Validate preview decision',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('dialog').open);
 const noStorage=await page.evaluate(async()=>({local:Object.keys(localStorage),session:Object.keys(sessionStorage),caches:await caches.keys(),workers:(await navigator.serviceWorker.getRegistrations()).length}));assert.deepEqual(noStorage,{local:[],session:[],caches:[],workers:0});
 const cookie=(await context.cookies()).find(c=>c.name==='__Host-optibrain');assert(cookie&&cookie.secure&&cookie.httpOnly&&cookie.sameSite==='Strict');
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Open navigation',exact:true}).click();assert.equal(await page.locator('#open-nav').getAttribute('aria-expanded'),'true');await page.keyboard.press('Escape');assert.equal(await page.locator('#open-nav').getAttribute('aria-expanded'),'false');
 await page.getByRole('button',{name:'Sign out',exact:true}).click();await page.getByRole('heading',{name:'You are signed out'}).waitFor();assert.equal((await context.cookies()).filter(c=>c.name==='__Host-optibrain').length,0);
 assert.deepEqual(errors,[]);assert.equal(outside,0);await browser.close();
 console.log(JSON.stringify({passed:true,checks,packages:16,registered_items:91,default_packages:10,editorial_preview_only:true,storage:noStorage,logout:'PASS',mobile_menu_keyboard:'PASS',outside_requests:0,production_decisions:0,screenshots:['desktop.png','mobile.png']}));
})().catch(e=>{console.error(e);process.exit(1)});
