'use strict';
// Session metadata and CSRF remain in memory. No token or private-data storage.
(function(root){
 function createSessionClient({fetch:transport,now=()=>Date.now(),setTimer=setTimeout,clearTimer=clearTimeout,
   visible=()=>true,exclusive=null,onSession=()=>{},onExpired=()=>{}}){
  let value=null,tail=Promise.resolve(),timer=null,starting=null,renewing=null,stopped=false,expired=false;
  let blockedIdentityExpiry=null;
  const seconds=()=>now()/1000;
  class SignInRequired extends Error {}

  // Reads, rotations and mutations share one queue. Web Locks extends the same
  // boundary across tabs without sharing credentials through browser storage.
  function serial(operation){
   const run=()=>exclusive?exclusive(operation):operation();
   const result=tail.then(run);tail=result.catch(()=>{});return result;
  }
  function cancelTimer(){if(timer!==null)clearTimer(timer);timer=null;}
  function adopt(next){
   if(!next||![next.expires_at,next.identity_expires_at,next.absolute_expires_at].every(Number.isFinite)||
      next.expires_at<=seconds()||next.expires_at>Math.min(next.identity_expires_at,next.absolute_expires_at))
    throw new SignInRequired('A verified session is required.');
   value=next;expired=false;onSession(next);arm();return next;
  }
  function expire(automatic){
   cancelTimer();if(stopped||expired)return;
   expired=true;value=null;onSession(null);onExpired({automatic});
  }
  function canExtend(){
   return exclusive&&value&&value.identity_expires_at!==blockedIdentityExpiry&&
    Math.min(value.identity_expires_at,value.absolute_expires_at)>value.expires_at+5;
  }
  function arm(){
   cancelTimer();if(!value||stopped||!visible())return;
   const extend=canExtend();
   const due=value.expires_at+(extend?-120:1);
   timer=setTimer(()=>{
    timer=null;if(!visible())return;
    if(extend)renew(false).catch(()=>{});
    else serial(()=>expire(true)).catch(()=>{});
   },Math.max(250,(due-seconds())*1000));
  }
  async function raw(path,{method='GET',body,csrf=false,auth=false,binary=false}={}){
   const headers={'X-Requested-With':'XMLHttpRequest'};
   if(method==='POST')headers['Content-Type']='application/json';
   if(csrf){if(!value)throw new SignInRequired('Sign in before submitting this action.');headers['X-Optibrain-CSRF']=value.csrf;}
   const controller=new AbortController(),timeout=setTimer(()=>controller.abort(),30000);
   try{
    const response=await transport(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),
     credentials:'same-origin',cache:'no-store',redirect:'manual',signal:controller.signal});
    if(response.type==='opaqueredirect'||response.status===401||(response.status>=300&&response.status<400))
     throw new SignInRequired('Continue through Access to renew your sign-in.');
    if(binary&&response.ok)return await response.blob();
    let data;try{data=await response.json();}catch(e){throw new Error('Private response unavailable. No action was retried.');}
    if(!response.ok){
     const message=data.error||'Private request unavailable.';
     if(auth&&response.status===403)throw new SignInRequired(message);
     const error=new Error(message);error.status=response.status;throw error;
    }
    return data;
   }finally{clearTimer(timeout);}
  }
  async function sync(){return adopt(await raw('/auth/session',{auth:true}));}
  function handle(error,automatic){if(error instanceof SignInRequired)expire(automatic);throw error;}

  function start(){
   if(stopped)return Promise.reject(new Error('Signed out.'));
   if(starting)return starting;
   starting=serial(async()=>adopt(await raw('/auth/login',{method:'POST',body:{},auth:true})))
    .catch(e=>handle(e,true)).finally(()=>{starting=null;});
   return starting;
  }
  function request(path,options={}){
   if(!/^\/api\//.test(path)||!['GET','POST'].includes(options.method||'GET'))
    return Promise.reject(new Error('Unknown private request.'));
   const mutation=options.method==='POST';
   return serial(async()=>{
    if(stopped||expired)throw new SignInRequired('Sign in and review the exact action again.');
    // Refresh shared-cookie CSRF metadata while holding the cross-tab lock.
    await sync();return raw(path,options);
   }).catch(e=>{
    if(mutation&&!(e instanceof SignInRequired))e.message+=' This action was not retried. Check its recorded status before submitting again.';
    return handle(e,!mutation);
   }); // Never replay a failed mutation.
  }
  function renew(manual=true){
   if(renewing)return renewing;
   renewing=serial(async()=>{
    if(stopped||expired)throw new SignInRequired('Your sign-in needs renewal.');
    await sync();
    cancelTimer();
    // A token ceiling is not an invitation to rotate the same cookie again.
    if(!canExtend()||value.expires_at-seconds()>120){arm();return value;}
    const before=value.expires_at;
    const next=await raw('/auth/renew',{method:'POST',body:{},csrf:true,auth:true});
    if(next.expires_at<=before+5)blockedIdentityExpiry=next.identity_expires_at;
    return adopt(next);
   }).catch(e=>{cancelTimer();if(!(e instanceof SignInRequired))expire(false);return handle(e,!manual);}).finally(()=>{renewing=null;});
   return renewing;
  }
  function resume(){
   if(stopped||expired||!visible())return Promise.resolve(null);
   if(starting)return starting;
   if(!value||value.expires_at<=seconds())return start();
   return serial(sync).catch(e=>handle(e,true));
  }
  function stop(){stopped=true;cancelTimer();value=null;onSession(null);}
  function logout(){
   return serial(async()=>{
    if(stopped)throw new Error('Already signed out.');
    await sync();const out=await raw('/auth/logout',{method:'POST',body:{},csrf:true,auth:true});
    stop();return out;
   }).catch(e=>handle(e,false));
  }
  return {start,request,renew,resume,logout,stop,pause:cancelTimer};
 }

 // The URL marker stores only an attempt time. It is neither a credential nor
 // authorization. Keep it through an unsuccessful return to bound redirects.
 function reauthenticationTarget(href,now=Date.now(),force=false){
  const url=new URL(href),previous=Number(url.searchParams.get('_ob_reauth'));
  if(!force&&previous>0&&now-previous<120000)return null;
  const hash=/^#(?:overview|sales|marketing|content|review|files|system|settings)(?:\?[^\r\n]*)?$/.test(url.hash)?url.hash:'#overview';
  return url.origin+'/?_ob_reauth='+Math.trunc(now)+'&_ob_section='+hash.slice(1).split('?')[0]+hash;
 }
 const api={createSessionClient,reauthenticationTarget};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 else root.OptiBrainSession=Object.freeze(api);
})(typeof window==='undefined'?globalThis:window);
