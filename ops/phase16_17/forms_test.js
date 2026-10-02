/* Manual, exact published TEST form submission. Never repeats an attempted click. */
const {chromium}=require('/home/optibrain/phase9-browser/node_modules/playwright');
const fs=require('fs');const crypto=require('crypto');
const root='/home/optibrain/phase16-17-evidence/form-browser';const lang=process.argv[2];
if(!['fr','en'].includes(lang)||process.getuid()===0)throw Error('Explicit unprivileged TEST browser language required');
const owner=JSON.parse(fs.readFileSync(root+'/forms-owner-confirmation.json'));
if(owner.confirmed!==true||owner.autoreplies!==false||!['yboucher@opticable.ca','soumissions@opticable.ca'].includes(owner.recipient)
 ||(owner.subject_prefix!=='[OPTIBRAIN TEST]'&&owner.native_subject_exception!==true))throw Error('Owner-held notification configuration not confirmed');
const run='phase16-20261002-lifecycle-v1';const marker='OPTIBRAIN TEST — PHASE 16';
const perma=lang==='fr'?'i6pIlfoGOFER0OCZ4oUH_KMxVWRZKC9Of8vbyNAjR0g':'5kpuPyq6HG3cmmNAHG_2cFprnp16uoMzojC7Fxq42xo';
const key=run+'-form-'+lang;const attempt=root+'/form-'+lang+'-attempt.json';const result=root+'/form-'+lang+'-result.json';
const payload={name:marker+' — Person A',company:marker+' — Lifecycle Company A',email:'logs@opticable.ca',phone:'5145550116',reference:key,
notes:'[OPTIBRAIN TEST] TEST ONLY. '+key+'. Synthetic structured cabling inquiry; no actual customer work, quote, invoice or commitment.'};
const pageUrl='https://opticable.ca/'+lang+'/contact/?utm_source=phase16_test&utm_medium=cpc&utm_campaign=phase16_'+lang+'&utm_id=phase16_forms_'+lang;
function exclusive(path,value){fs.writeFileSync(path,JSON.stringify(value,null,2)+'\n',{flag:'wx',mode:0o600});}
(async()=>{if(fs.existsSync(attempt))throw Error('Existing form attempt is reconciliation-only; no repeat');
exclusive(attempt,{state:'prepared',run,key,lang,payload,pageUrl,payload_hash:crypto.createHash('sha256').update(JSON.stringify(payload)).digest('hex'),at:new Date().toISOString()});
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});const page=await browser.newPage();const posts=[];
page.on('response',r=>{if(r.request().method()==='POST'&&new URL(r.url()).hostname.endsWith('.zohopublic.com')){
 const receipt={path:new URL(r.url()).pathname,status:r.status(),at:new Date().toISOString()};posts.push(receipt);
 fs.appendFileSync(root+'/form-'+lang+'-responses.jsonl',JSON.stringify(receipt)+'\n',{mode:0o600});}});
try{await page.goto(pageUrl,{waitUntil:'domcontentloaded',timeout:30000});await page.waitForTimeout(2500);
const f=page.frames().find(f=>f.url().includes('forms.zohopublic.com')&&f.url().includes(perma));if(!f)throw Error('Exact published form unavailable');
await f.locator('input[name=Name]').nth(0).fill(marker+' — Person');await f.locator('input[name=Name]').nth(1).fill('A');
await f.locator('input[name=SingleLine]').fill(payload.company);await f.locator('input[name=Email]').fill(payload.email);await f.locator('input[name=PhoneNumber]').fill(payload.phone);
await f.locator('select[name=Dropdown]').selectOption(lang==='fr'?'Site industriel ou entrepôt':'industrial or warehouse');
await f.locator('select[name=Dropdown1]').selectOption(lang==='fr'?'Dans les 30 jours':'30 days');
const service=lang==='fr'?'Câblage structuré':'Cabling';await f.locator('input[name=Checkbox]').evaluateAll((nodes,value)=>{const n=nodes.find(n=>n.value===value);if(!n)throw Error('Service unavailable');n.click();},service);
if(lang==='fr')await f.locator('input[name=SingleLine2]').fill(key);
await f.locator('textarea[name=MultiLine]').fill(payload.notes);
const current=JSON.parse(fs.readFileSync(attempt));current.state='attempted';current.attempted_at=new Date().toISOString();fs.writeFileSync(attempt,JSON.stringify(current,null,2)+'\n',{mode:0o600});
await f.locator('button.zfbtnSubmit').click();await page.waitForTimeout(9000);
// A successful native submission may replace/detach the iframe. Inspect the
// remaining frames rather than treating that normal navigation as a failed send.
const texts=[];for(const currentFrame of page.frames()){
 try{texts.push((await currentFrame.locator('body').innerText({timeout:1500})).slice(0,1500));}catch(_){}}
const observed={run,key,lang,at:new Date().toISOString(),posts,form_url:page.frames().map(x=>x.url().split('?')[0]),visible_text:texts.join('\n').slice(0,2500)};
exclusive(result,observed);console.log(JSON.stringify({lang,posts,thank_you:/merci|thank/i.test(observed.visible_text),result}));
}finally{await browser.close();}})().catch(e=>{console.error(e.message);process.exit(1)});
