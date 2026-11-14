// Same local-only browser validation model as first_hosted_camera_preview.
const {chromium}=require(process.env.BUSINESS_PLAYWRIGHT);
const AxeBuilder=require(process.env.BUSINESS_AXE).default;
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const credentials=JSON.parse(fs.readFileSync(process.env.BUSINESS_PREVIEW_CREDENTIALS,'utf8'));
 const origin='http://127.0.0.1:8876';
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const anonymous=await browser.newContext();
 assert.equal((await anonymous.request.get(origin+'/fr/services/systemes-cameras-securite/')).status(),401);
 assert.equal((await anonymous.request.get(origin+'/robots.txt')).status(),401);
 await anonymous.close();
 const context=await browser.newContext({httpCredentials:credentials});
 let external=0,mutations=0;const errors=[],checks=[];
 await context.route('**/*',route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.origin!==origin){external++;return route.abort();}
   if(req.method()!=='GET'){mutations++;return route.abort();}
   return route.continue();
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 for(const [lang,path] of [['fr','/fr/services/systemes-cameras-securite/'],['en','/en/services/security-camera-systems/']]){
   for(const width of [375,768,1440]){
     await page.setViewportSize({width,height:1000});
     const response=await page.goto(origin+path,{waitUntil:'networkidle'});
     assert.equal(response.status(),200);assert(response.headers()['x-robots-tag'].includes('noindex'));
     assert.equal(await page.locator('h1').count(),1);
     assert.equal(await page.locator('html').getAttribute('lang'),lang==='fr'?'fr-CA':'en-CA');
     assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'),'https://opticable.ca'+path);
     assert((await page.locator('meta[name=robots]').getAttribute('content')).includes('noindex'));
     assert.equal(await page.locator('form,iframe,script[src]').count(),0);
     assert.equal(await page.locator('a[href^="https:"],a[href^="mailto:"],a[href^="tel:"]').count(),0);
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
     await page.locator('#brief-building').selectOption({index:2});
     await page.locator('#brief-priority').selectOption({index:1});
     await page.locator('#brief-ai').selectOption({index:1});
     const button=page.locator('[data-build-brief]');await button.focus();await page.keyboard.press('Enter');
     const text=await page.locator('[data-brief-output]').inputValue();
     assert(text.includes(lang==='fr'?'Entrepôt':'Warehouse'));assert(text.includes(lang==='fr'?'Livraisons':'Deliveries'));
     assert(text.includes(lang==='fr'?'vérification humaine':'human review'));
     assert(await page.locator('[data-brief-output]').evaluate(n=>document.activeElement===n));
     const before=text;await button.click();assert.equal(await page.locator('[data-brief-output]').inputValue(),before);
     const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
     checks.push({lang,width,brief_created:true,keyboard:true,overflow:false,axe_violations:result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))});
     if(width===375||width===1440)await page.screenshot({path:process.env.BUSINESS_QA_DIR+`/camera-${lang}-${width}.png`,fullPage:true});
     await page.reload({waitUntil:'networkidle'});assert.equal(await page.locator('[data-brief-output]').inputValue(),'');
   }
 }
 assert([403,405].includes((await context.request.post(origin+'/',{data:'blocked'})).status()));
 assert.equal((await context.request.get(origin+'/sitemap.xml')).status(),410);
 const robots=await context.request.get(origin+'/robots.txt');assert((await robots.text()).includes('Disallow: /'));
 const result={passed:checks.every(x=>x.axe_violations.length===0)&&errors.length===0&&external===0&&mutations===0,
   checks,errors,external_requests:external,browser_mutations:mutations,auth_required:true,post_rejected:true,sitemap_excluded:true,analytics_disabled:true};
 fs.writeFileSync(process.env.BUSINESS_QA_DIR+'/browser-results.json',JSON.stringify(result,null,2)+'\n');
 await browser.close();console.log(JSON.stringify(result));if(!result.passed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
