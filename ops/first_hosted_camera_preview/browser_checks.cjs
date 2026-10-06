// Fixed policy: all browser traffic is served from tested local files or blocked.
const {chromium}=require('/opt/optibrain-preview-tools/node_modules/playwright');
const AxeBuilder=require('/opt/optibrain-preview-tools/node_modules/@axe-core/playwright').default;
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=process.env.OPTIBRAIN_PREVIEW_DIR;
 assert(root && path.isAbsolute(root));
 const hosted=process.env.OPTIBRAIN_PREVIEW_URL;
 if(hosted)assert(/^https:\/\/[a-f0-9]{8}-opticable-optimization-preview\.yboucher\.workers\.dev\/fr\/services\/systemes-cameras-securite\/$/.test(hosted));
 const origin=hosted?new URL(hosted).origin:'https://preview.test',hostname=new URL(origin).hostname;
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext(); let providerRequests=0,submitted=0;
 await context.route('**/*',async route=>{
  const request=route.request(),u=new URL(request.url());
  if(request.method()!=='GET'){submitted++;return route.abort();}
  if(u.hostname!==hostname)return route.abort();
  if(hosted)return route.continue();
  let filename=path.join(root,decodeURIComponent(u.pathname));
  if(u.pathname.endsWith('/'))filename=path.join(filename,'index.html');
  if(!filename.startsWith(root+'/')||!fs.existsSync(filename)||!fs.statSync(filename).isFile())return route.fulfill({status:404,body:'missing'});
  const ext=path.extname(filename);
  await route.fulfill({body:fs.readFileSync(filename),contentType:ext==='.html'?'text/html':ext==='.js'?'text/javascript':ext==='.css'?'text/css':ext==='.json'?'application/json':'application/octet-stream'});
 });
 const page=await context.newPage(),checks=[],violations=[];
 for(const [language,route] of [['fr','/fr/services/systemes-cameras-securite/'],['en','/en/services/security-camera-systems/']]){
  for(const width of [375,768,1440]){
   await page.setViewportSize({width,height:900});
   const response=await page.goto(origin+route,{waitUntil:'networkidle'});
   assert.equal(response.status(),200);assert.equal(page.url(),origin+route);
   assert.equal(await page.locator('h1').count(),1);
   assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'),'https://opticable.ca'+route);
   assert((await page.locator('meta[name=robots]').getAttribute('content')).includes('noindex'));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   assert.equal(await page.locator('script[src*="googletagmanager.com"]').count(),0);
   if(language==='fr'){
    assert(await page.getByRole('heading',{name:'Caméras IP pour commerces et entrepôts',exact:true}).count());
    assert(await page.getByText('Combien de caméras faut-il?',{exact:true}).count());
    assert(await page.locator('[data-preview-cta=quote]').count());
   }
   const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
   violations.push(...result.violations.map(v=>({id:v.id,impact:v.impact,language,width,nodes:v.nodes.map(n=>n.target)})));
   checks.push({language,width,overflow:false,axe_violations:result.violations.length});
  }
 }
 await page.goto(origin+'/fr/contact/?utm_source=preview&utm_campaign=camera&gclid=TEST_ONLY_PREVIEW',{waitUntil:'networkidle'});
 assert(await page.locator('.zoho-form-embed,[data-preview-form=present]').count());
 await page.locator('[data-cookie-accept]').click();
 const attribution=await page.evaluate(()=>window.OpticableAttribution.get());
 // Native production-mode checks prove campaign preservation. Preview mode
 // deliberately disables optional attribution storage alongside analytics.
 assert.deepEqual(attribution,{});
 const prefill=await page.evaluate(()=>window.OpticableAttribution.appendLeadToUrl('https://forms.zohopublic.com/example',{origin_site:location.hostname,origin_path:location.pathname}));
 const lead=JSON.parse(new URL(prefill).searchParams.get('ob_attribution'));
 assert.equal(lead.language,'fr');assert.deepEqual(lead.attribution,{origin_site:hostname,origin_path:'/fr/contact/'});
 assert.equal(await page.locator('script[src*="gtag/js"]').count(),0);
 await browser.close();
 console.log(JSON.stringify({passed:violations.length===0,checks,violations,provider_requests:providerRequests,form_submissions:submitted,tracking_enabled:false,attribution_checked:true,forms_shell_checked:true,hosted:!!hosted}));
 if(violations.length || submitted)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
