// Reuses installed Playwright/axe/browser dependencies. No screenshots or content files.
const {chromium}=require(process.env.BUSINESS_PLAYWRIGHT);
const AxeBuilder=require(process.env.BUSINESS_AXE).default;
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const c=JSON.parse(fs.readFileSync(process.env.BUSINESS_PREVIEW_CREDENTIALS,'utf8'));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({httpCredentials:{username:c.username,password:c.password}});
 let outside=0;const errors=[],checks=[];
 await context.route('**/*',route=>{if(new URL(route.request().url()).origin!=='http://127.0.0.1:8876'){outside++;return route.abort();}return route.continue();});
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 for(const width of [375,1280]){
  await page.setViewportSize({width,height:900});await page.goto('http://127.0.0.1:8876/review/',{waitUntil:'networkidle'});
  assert.equal(await page.locator('[data-package]').count(),10);
  assert.equal(await page.locator('#decisions + ol > li').count(),5);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();assert.equal(axe.violations.length,0,JSON.stringify(axe.violations));
  checks.push({width,default_packages:10,top_decisions:5,axe_violations:0,overflow:false});
 }
 const q=await(await context.request.get('http://127.0.0.1:8876/review/queue.json')).json();
 assert.equal(q.registered_items,91);assert.equal(q.packages.length,16);
 const ids=q.packages.flatMap(p=>p.items.map(i=>i.id));assert.equal(ids.length,91);assert.equal(new Set(ids).size,91);
 assert(q.packages.every(p=>p.execution_enabled===false));
 await page.goto('http://127.0.0.1:8876/review/?view=items',{waitUntil:'networkidle'});assert.equal(await page.locator('[data-artifact]').count(),91);
 await page.goto('http://127.0.0.1:8876/review/?q=EST-1145',{waitUntil:'networkidle'});assert((await page.locator('[data-artifact]').count())>=1);
 await page.goto('http://127.0.0.1:8876/review/?package='+q.packages[0].id,{waitUntil:'networkidle'});assert.equal(await page.locator('[data-package]').count(),1);
 const href=await page.locator('[data-package] li a').first().getAttribute('href');await page.goto('http://127.0.0.1:8876'+href,{waitUntil:'networkidle'});assert.equal(await page.locator('[data-decision]').count(),3);
 assert.deepEqual(errors,[]);assert.equal(outside,0);await browser.close();
 console.log(JSON.stringify({passed:true,checks,registered_items:91,packages:16,coverage_ids:91,search:'PASS',exact_item_controls:'PASS',outside_requests:outside,real_decisions_submitted:0,screenshots_created:0,files_generated:0}));
})().catch(e=>{console.error(e);process.exit(1)});
