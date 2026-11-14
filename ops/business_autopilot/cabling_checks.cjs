// Actual authenticated native candidate: local requests only, no submissions.
const {chromium}=require(process.env.BUSINESS_PLAYWRIGHT);
const AxeBuilder=require(process.env.BUSINESS_AXE).default;
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const credentials=JSON.parse(fs.readFileSync(process.env.BUSINESS_PREVIEW_CREDENTIALS,'utf8'));
 const origin='http://127.0.0.1:8876',prefix='/experiments/cabling-handover/';
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const anon=await browser.newContext();assert.equal((await anon.request.get(origin+prefix)).status(),401);await anon.close();
 const ctx=await browser.newContext({httpCredentials:credentials});let outside=0,mutations=0;const errors=[],checks=[];
 await ctx.route('**/*',route=>{const r=route.request();if(new URL(r.url()).origin!==origin){outside++;return route.abort();}if(r.method()!=='GET'){mutations++;return route.abort();}return route.continue();});
 const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
 for(const [lang,slugs] of [['fr',['cablage-structure','installation-fibre-optique']],['en',['structured-cabling','fiber-optic-installation']]]){
  for(const slug of slugs)for(const width of [375,768,1440]){
   await page.setViewportSize({width,height:1000});const path=`${lang}/services/${slug}/`;
   const response=await page.goto(origin+prefix+path,{waitUntil:'networkidle'});
   assert.equal(response.status(),200);assert(response.headers()['x-robots-tag'].includes('noindex'));
   assert((await page.locator('meta[name=robots]').getAttribute('content')).includes('noindex'));
   assert.equal(await page.locator('h1').count(),1);assert.equal(await page.locator('form,iframe,script[src]').count(),0);
   assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'),'https://opticable.ca/'+path);
   assert.equal(await page.locator('a[href^="https:"],a[href^="mailto:"],a[href^="tel:"]').count(),0);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.locator('[data-build-handover]').click();assert.equal(await page.locator('[data-handover-output]').inputValue(),'');
   assert((await page.locator('[data-handover-status]').textContent()).length>0);
   await page.locator('#handover-labels').check();await page.locator('#handover-map').check();
   await page.locator('[data-build-handover]').focus();await page.keyboard.press('Enter');
   const text=await page.locator('[data-handover-output]').inputValue();assert(text.includes(lang==='fr'?'Repérage':'Matching labels'));
   assert(text.includes('\n'));assert(await page.locator('[data-handover-output]').evaluate(n=>document.activeElement===n));
   await page.locator('[data-build-handover]').click();assert.equal(await page.locator('[data-handover-output]').inputValue(),text);
   const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
   checks.push({lang,slug,width,keyboard:true,idempotent:true,overflow:false,axe_violations:axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))});
   if(width!==768)await page.screenshot({path:process.env.BUSINESS_QA_DIR+`/handover-${lang}-${slug}-${width}.png`,fullPage:true});
   await page.locator('[data-reset-handover]').click();assert.equal(await page.locator('[data-handover-option]:checked').count(),0);assert.equal(await page.locator('[data-handover-output]').inputValue(),'');
   await page.reload({waitUntil:'networkidle'});assert.equal(await page.locator('[data-handover-option]:checked').count(),0);
  }
 }
 const result={passed:checks.every(c=>!c.axe_violations.length)&&!errors.length&&!outside&&!mutations,checks,errors,outside_requests:outside,mutations,authenticated:true,noindex:true};
 fs.writeFileSync(process.env.BUSINESS_QA_DIR+'/cabling-browser-results.json',JSON.stringify(result,null,2)+'\n');
 await browser.close();console.log(JSON.stringify(result));if(!result.passed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
