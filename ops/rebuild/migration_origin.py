"""Existing cutover's missing origin prerequisite; no standalone live CLI.
Called only inside the exact DNS scope, after intake/private/Worker verification.
Never changes DNS, API code, business flags or database contents.
"""
import hashlib,http.client,json,os,pwd,socket,ssl,stat,uuid
from pathlib import Path
from common import atomic_json,file_hash,require
HOST='optibrain.opticable.ca'
NAMES={
 'acme/'+p+'/users/default/default.'+suffix
 for p in ('acme-staging-v02.api.letsencrypt.org-directory','acme-v02.api.letsencrypt.org-directory')
 for suffix in ('json','key')
}|{'certificates/acme-v02.api.letsencrypt.org-directory/'+HOST+'/'+HOST+'.'+s for s in ('crt','json','key')}
CERT='certificates/acme-v02.api.letsencrypt.org-directory/'+HOST+'/'+HOST+'.crt'

def regular(path):
 s=path.lstat();require(stat.S_ISREG(s.st_mode) and s.st_nlink==1,'origin_file_not_private_regular');return s

def material(scope,destination):
 """Read-only complete validation before the first install or proxy change."""
 source=Path(scope['tls_source']);manifest=Path(scope['tls_manifest']);config=Path(scope['production_config']);private=Path(scope['current_config'])
 for p in (manifest,config,private):regular(p)
 require(file_hash(manifest)==scope['tls_manifest_sha256'],'origin_TLS_manifest_changed')
 require(file_hash(config)==scope['production_config_sha256'] and config.read_text().startswith(HOST+' {'),'origin_production_config_changed')
 require(file_hash(private)==scope['before_config_sha256'],'origin_private_config_changed')
 rows=json.loads(manifest.read_text());require(set(rows)==NAMES,'origin_exact_seven_TLS_files_required')
 for name,row in rows.items():
  src=source/name;regular(src);require(src.resolve()==src and src.stat().st_size==row['bytes'] and file_hash(src)==row['sha256'],'origin_TLS_source_changed')
  dest=destination/name
  for parent in (dest,*dest.parents):
   require(not parent.is_symlink(),'origin_destination_symlink')
  if dest.exists():regular(dest);require(file_hash(dest)==row['sha256'],'origin_existing_TLS_state_conflict')
 return rows

def config_write(path,data):
 # Preserve ownership and publish a complete config even if SSH or the runner dies.
 previous=regular(path);temporary=path.with_name(path.name+'.migration-'+uuid.uuid4().hex)
 with temporary.open('xb') as output:
  output.write(data);output.flush();os.fsync(output.fileno())
 temporary.chmod(stat.S_IMODE(previous.st_mode));os.chown(temporary,previous.st_uid,previous.st_gid);os.replace(temporary,path)
 fd=os.open(path.parent,os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)

def probe(headers=None):
 """Real origin CA/SNI + hostname, HTTP and hold/auth readback; never bypass TLS."""
 context=ssl.create_default_context();result={}
 for name,h in [('unauthorized',{}),('hold',headers or {})]:
  with socket.create_connection(('127.0.0.1',443),timeout=15) as raw:
   with context.wrap_socket(raw,server_hostname=HOST) as tls:
    require(all('\r' not in k+v and '\n' not in k+v for k,v in h.items()),'origin_header_invalid')
    request='GET /v1/automation/event-health HTTP/1.1\r\nHost: '+HOST+'\r\nConnection: close\r\n'+''.join(k+': '+v+'\r\n' for k,v in h.items())+'\r\n'
    tls.sendall(request.encode());response=http.client.HTTPResponse(tls);response.begin();body=response.read(2*1024**2);result[name]={'http':response.status,'certificate_sha256':hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest(),'CA_hostname_verified':True}
    if name=='unauthorized':require(response.status in (401,403),'origin_auth_denial_failed')
    else:
     require(response.status==200,'origin_authenticated_hold_failed');hold=json.loads(body).get('intake_hold',{});require(hold.get('mode')=='hold-v1' and hold.get('capture_available') is True,'origin_hold_not_ready')
 return result

def enable(live):
 """One guarded local activation before any DNS transport. Failure contains NEW."""
 live.approval('dns_cutover');require(os.geteuid()==0 and os.uname().nodename=='vps-f8e9b20e','origin_NEW_root_only')
 require(live.source('status')['fenced'] and live.edge(__import__('migration_adapters').QUEUE)['settings'].get('delivery_paused') is True,'origin_source_or_queue_not_held')
 live.private_api();scope=live.p['scopes']['dns_cutover']['origin'];destination=Path('/var/lib/caddy/.local/share/caddy');rows=material(scope,destination)
 cert=Path(scope['tls_source'])/CERT
 live.run_origin(['openssl','verify','-verify_hostname',HOST,'-untrusted',str(cert),str(cert)])
 live.run_origin(['openssl','x509','-in',str(cert),'-noout','-checkend','86400'])
 private=Path(scope['current_config']);saved=private.read_bytes();receipt=live.root/'origin-activation.json';require(not receipt.exists(),'origin_attempt_exists_reconcile_only')
 atomic_json(receipt,{'state':'ATTEMPTED','before_config_sha256':file_hash(private),'production_config_sha256':scope['production_config_sha256'],'tls_manifest_sha256':scope['tls_manifest_sha256'],'before_config':saved.decode(),'DNS_transport_started':False})
 owner=pwd.getpwnam('caddy')
 try:
  for parent in reversed([destination,*destination.parents]):
   if not parent.exists():parent.mkdir(mode=0o700);os.chown(parent,owner.pw_uid,owner.pw_gid)
  for name,row in rows.items():
   dest=destination/name
   for parent in reversed(dest.parents):
    if parent==destination or destination in parent.parents:
     if not parent.exists():parent.mkdir(mode=0o700);os.chown(parent,owner.pw_uid,owner.pw_gid)
   if not dest.exists():
    with dest.open('xb') as output:
     output.write((Path(scope['tls_source'])/name).read_bytes());output.flush();os.fsync(output.fileno())
    dest.chmod(0o600);os.chown(dest,owner.pw_uid,owner.pw_gid)
   require(file_hash(dest)==row['sha256'],'origin_installed_TLS_readback_failed')
  live.run_origin(['caddy','validate','--config',scope['production_config']])
  config_write(private,Path(scope['production_config']).read_bytes())
  live.run_origin(['systemctl','reload','caddy.service'])
  result=probe(live.origin_headers());live.private_api()
  atomic_json(live.root/'origin-verified.json',{'status':'PASS','config_sha256':file_hash(private),'TLS_manifest_sha256':scope['tls_manifest_sha256'],'readback':result,'DNS_transport_started':False})
  return result
 except Exception as e:
  # This function never sends a DNS change. Restore only the local proxy configuration.
  config_write(private,saved)
  restored=False
  try:live.run_origin(['systemctl','reload','caddy.service']);restored=file_hash(private)==scope['before_config_sha256']
  except Exception:pass
  atomic_json(live.root/'origin-failure.json',{'error_class':type(e).__name__,'private_proxy_restored':restored,'DNS_transport_started':False,'OLD_fence_and_NEW_data_preserved':True})
  raise
