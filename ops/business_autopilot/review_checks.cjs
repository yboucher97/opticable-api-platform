const {chromium}=require(process.env.BUSINESS_PLAYWRIGHT),AxeBuilder=require(process.env.BUSINESS_AXE).default;
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const credentials=JSON.parse(fs.readFileSync(process.env.BUSINESS_PREVIEW_CREDENTIALS,'utf8'));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({httpCredentials:credentials});let outside=0;const errors=[];
 await context.route('**/*',route=>{if(new URL(route.request().url()).origin!=='http://127.0.0.1:8876'){outside++;return route.abort();}return route.continue();});
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));const checks=[];
 for(const width of [375,1280]){
  await page.setViewportSize({width,height:900});await page.goto('http://127.0.0.1:8876/review/',{waitUntil:'networkidle'});
  const count=await page.locator('article').count();assert(count>=43);assert.equal(await page.locator('nav a').count(),7);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();assert.equal(axe.violations.length,0,JSON.stringify(axe.violations));
  await page.screenshot({path:process.env.BUSINESS_QA_DIR+`/review-${width}.png`,fullPage:false});checks.push({width,registered_items:count,axe_violations:0,overflow:false});
 }
 const href=await page.locator('article h2 a').first().getAttribute('href');await page.goto('http://127.0.0.1:8876'+href,{waitUntil:'networkidle'});
 assert.equal(await page.locator('[data-decision]').count(),3);assert(await page.locator('details').count());
 // Do not submit owner decisions for real production artifacts during testing.
 await page.goto('http://127.0.0.1:8876/experiments/inquiry-attribution/',{waitUntil:'networkidle'});
 await page.locator('#simulate').click();let denied=JSON.parse(await page.locator('#result').textContent());assert.equal(denied.logical_inquiries,0);
 await page.locator('#consent').check();await page.locator('#simulate').click();let first=JSON.parse(await page.locator('#result').textContent());
 assert.equal(first.logical_inquiries,1);const id=first.captured.attribution.inquiry_id;assert(/^obq_[a-f0-9]{32}$/.test(id));
 await page.locator('#simulate').click();assert.equal(JSON.parse(await page.locator('#result').textContent()).logical_inquiries,1);
 await page.locator('#new').click();await page.locator('#simulate').click();let next=JSON.parse(await page.locator('#result').textContent());assert.equal(next.logical_inquiries,2);assert.notEqual(next.captured.attribution.inquiry_id,id);
 await page.screenshot({path:process.env.BUSINESS_QA_DIR+'/tracking-fixture.png',fullPage:true});
 assert.deepEqual(errors,[]);assert.equal(outside,0);
 const result={passed:true,checks,protected_tracking:{denied_inquiries:0,first:1,duplicate:1,new_attempt:2,network_sends:0},outside_requests:outside,errors,real_owner_decisions_submitted:0};
 fs.writeFileSync(process.env.BUSINESS_QA_DIR+'/review-browser-results.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
