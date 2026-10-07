// All provider requests are intercepted, including Forms and consented analytics.
const {chromium}=require('/opt/optibrain-preview-tools/node_modules/playwright');
const AxeBuilder=require('/opt/optibrain-preview-tools/node_modules/@axe-core/playwright').default;
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=process.env.OPTIBRAIN_PREVIEW_DIR,hosted=process.env.OPTIBRAIN_PREVIEW_URL;
 assert(root&&path.isAbsolute(root));
 if(hosted)assert(/^https:\/\/[a-f0-9]{8}-opticable-ai-optimization-preview\.yboucher\.workers\.dev\/fr\/$/.test(hosted));
 const origin=hosted?new URL(hosted).origin:'https://ai-preview.test';
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext();let providerRequests=0,submitted=0,unexpected=0;const violations=[],checks=[];
 await context.route('**/*',async route=>{
  const request=route.request(),u=new URL(request.url());
  if(u.hostname!==new URL(origin).hostname){providerRequests++;return route.abort();}
  if(request.method()!=='GET'){submitted++;return route.abort();}
  if(hosted)return route.continue();
  let f=path.join(root,decodeURIComponent(u.pathname));if(u.pathname.endsWith('/'))f=path.join(f,'index.html');
  if(!f.startsWith(root+'/')||!fs.existsSync(f)||!fs.statSync(f).isFile()){unexpected++;return route.fulfill({status:404,body:'missing'});}
  const ext=path.extname(f);return route.fulfill({body:fs.readFileSync(f),contentType:ext==='.html'?'text/html':ext==='.js'?'text/javascript':ext==='.css'?'text/css':ext==='.json'?'application/json':'application/octet-stream'});
 });
 const page=await context.newPage();
 for(const language of ['fr','en'])for(const width of [375,768,1440]){
  await page.setViewportSize({width,height:900});
  const route='/'+language+'/';const response=await page.goto(origin+route,{waitUntil:'networkidle'});
  assert.equal(response.status(),200);assert.equal(await page.locator('h1').count(),1);
  assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'),'https://ai.opticable.ca'+route);
  assert((await page.locator('meta[name=robots]').getAttribute('content')).includes('noindex'));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert(await page.getByText('OPTIBRAIN PREVIEW',{exact:false}).count());
  assert.equal(await page.locator('script[src*="gtag/js"]').count(),0);
  const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  violations.push(...axe.violations.map(v=>({id:v.id,impact:v.impact,language,width,nodes:v.nodes.map(n=>n.target)})));
  checks.push({language,width,overflow:false,axe_violations:axe.violations.length});
 }
 await page.goto(origin+'/en/evaluation/',{waitUntil:'networkidle'});
 assert.equal(await page.locator('form').count(),1);
 await page.locator('.cookie-banner button').first().click();
 assert.equal(await page.locator('script[src*="gtag/js"]').count(),0);
 for(const [name,value] of Object.entries({name:'TEST ONLY',company:'TEST ONLY',email:'preview@example.invalid',city:'Montréal'}))await page.locator(`[name="${name}"]`).fill(value);
 await page.locator('#industry').selectOption('pharmacy');await page.locator('#cameras').selectOption('yes');await page.locator('#lead-consent').check();
 await page.locator('form button[type=submit]').click();await page.waitForTimeout(200);
 assert.equal(submitted,0);assert.equal(providerRequests,0);
 await browser.close();
 console.log(JSON.stringify({passed:violations.length===0&&unexpected===0,checks,violations,provider_requests:providerRequests,form_submissions:submitted,unexpected_asset_requests:unexpected,hosted:!!hosted}));
 if(violations.length||unexpected)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
