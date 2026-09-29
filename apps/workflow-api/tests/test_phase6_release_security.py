import copy,importlib.util,json,os,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[3]
def module(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'ops/phase6'/f'{name}.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
trust=module('release_trust');backup=module('backup_policy')
class ReleaseSecurityTests(unittest.TestCase):
 def fixture(self):
  now=datetime.now(timezone.utc);target='a'*40
  auth={'candidate':target,'validated_sha':target,'baseline':trust.BASELINE,'branch':trust.BRANCH,'approved_by':'human:fixture','approved_at':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat(),'ci_run_id':123,'full_tests':580,'subtests':540,'focused_tests':156,'failures':0,'errors':0,'skipped':0}
  guard={'candidate':target,'baseline':trust.BASELINE,'status':'promoted','completed_gates':sorted(trust.REQUIRED),'workflow_hashes_verified':True,'external_actions_enabled':False,'recovery_strategy':'forward-only-preserve-v2','candidate_backup':{'generation':'20260929T000000Z','sha256':'b'*64},'pre_reference_sha':trust.BASELINE,'recovery_reference_verified':True}
  receipt={'generation':'20260929T000000Z','source_sha256':'b'*64,'verification_status':'download_hash_verified'}
  return target,guard,auth,receipt
 def test_exact_release_and_verified_recovery_accept(self):trust.validate_release(*self.fixture())
 def test_command_ref_url_repository_and_shell_injections_refuse(self):
  target,guard,auth,receipt=self.fixture()
  for value in ('main','refs/heads/main','https://evil.test/repo','a'*40+';id','a'*40+' --exec=x','$(id)','../candidate','A'*40,'b'*40):
   with self.subTest(value=value),self.assertRaises(Exception):trust.validate_release(value,guard,auth,receipt)
 def test_missing_gates_receipts_policy_or_authority_refuse(self):
  for location,key,value in ((1,'completed_gates',[]),(1,'workflow_hashes_verified',False),(1,'external_actions_enabled',True),(1,'recovery_strategy','baseline-reset'),(1,'status','staged'),(1,'recovery_reference_verified',False),(2,'branch','main'),(2,'approved_by','ai:fixture'),(2,'validated_sha','c'*40),(2,'full_tests',579),(3,'source_sha256','c'*64),(3,'generation','20260101T000000Z'),(3,'verification_status','uploaded')):
   values=list(self.fixture());values[location][key]=value
   with self.subTest(key=key),self.assertRaises(Exception):trust.validate_release(*values)
 def test_every_recovery_gate_is_required(self):
  for gate in trust.REQUIRED:
   values=list(self.fixture());values[1]['completed_gates'].remove(gate)
   with self.subTest(gate=gate),self.assertRaises(RuntimeError):trust.validate_release(*values)
 def test_expired_and_naive_authority_refuse(self):
  for key,value in (('expires_at',(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()),('approved_at',datetime.now().isoformat()),('expires_at',(datetime.now(timezone.utc)+timedelta(hours=3)).isoformat())):
   values=list(self.fixture());values[2][key]=value
   with self.subTest(key=key),self.assertRaises(Exception):trust.validate_release(*values)
 def test_static_wrapper_embeds_exact_reviewed_verifier_and_never_materializes_code(self):
  shell=(ROOT/'deploy/production-root-command.sh').read_text();self.assertEqual(shell.split("<<'PY'\n",1)[1].rsplit('PY\n',1)[0],(ROOT/'ops/phase6/release_trust.py').read_text())
  for text in ('deploy/update-production.sh','git show','reset --hard','systemctl restart','systemctl stop'):
   self.assertNotIn(text,shell)
  self.assertIn(REMOTE:=trust.REMOTE,shell);self.assertIn("'merge-base','--is-ancestor'",shell)
 def test_unprivileged_or_extra_wrapper_arguments_refuse_before_verification(self):
  import subprocess
  for arguments in ([],['a'*40,'extra'],['a'*40+';id'],['refs/heads/main']):
   with self.subTest(arguments=arguments):
    p=subprocess.run(['bash',str(ROOT/'deploy/production-root-command.sh'),*arguments],capture_output=True);self.assertEqual(p.returncode,64)
 def test_symlink_leaf_and_parent_never_loaded(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);target=root/'target';target.write_text('{}');link=root/'link';link.symlink_to(target)
   with self.assertRaises(Exception):trust.protected(link)
   parent=root/'parent';parent.symlink_to(root,target_is_directory=True)
   with self.assertRaises(Exception):trust.protected(parent/'target')
 def test_no_caller_repository_or_executable_overrides(self):
  import inspect
  source=inspect.getsource(trust.reconcile)
  self.assertNotIn('os.environ',source);self.assertIn("'/usr/bin/git'",source);self.assertIn("'/usr/sbin/runuser'",source)
  self.assertNotIn('git(PROD',source)
 def test_wrong_repository_metadata_stops_before_git_or_source(self):
  target,guard,auth,receipt=self.fixture();guard['authorization_sha256']='hash'
  with patch.object(trust.os,'geteuid',return_value=0),patch.object(trust,'protected',side_effect=[guard,auth,receipt]),patch.object(trust,'sha',return_value='hash'),patch.object(trust,'run',return_value=json.dumps({'repository':{'full_name':'evil/repo'}})) as execute:
   with self.assertRaisesRegex(RuntimeError,'ci_repository_or_sha'):trust.reconcile(target)
  self.assertEqual(execute.call_count,1);self.assertEqual(execute.call_args.args[0][0],'/usr/bin/curl')
 def test_seven_or_more_verified_generations_are_preserved_by_capacity(self):
  records=[{'size':1000,'uncompressed_bytes':2000,'sidecar_matches':True} for _ in range(9)]
  result=backup.preservation_plan(records,10*1024**3);self.assertEqual(result['existing_generations'],9);self.assertEqual(result['deletions'],[]);self.assertEqual(result['moves'],[])
 def test_unverified_or_low_capacity_fails_without_cleanup(self):
  for records,free in (([],10**12),([{'size':1,'uncompressed_bytes':2,'sidecar_matches':False}],10**12),([{'size':1,'uncompressed_bytes':2,'sidecar_matches':True}],1)):
   with self.subTest(records=records),self.assertRaises(ValueError):backup.preservation_plan(records,free)
 def test_wrong_remote_sha_and_nonancestor_never_reach_production(self):
  import stat,subprocess,types
  for failure in ('remote_sha','ancestry'):
   target,guard,auth,receipt=self.fixture();guard['authorization_sha256']='hash'
   commands=[]
   def command(args):
    commands.append(args)
    if args[0]=='/usr/bin/curl':return json.dumps({'head_sha':target,'head_branch':trust.BRANCH,'name':'Validate API Platform','conclusion':'success','repository':{'full_name':'yboucher97/opticable-api-platform'}})
    if 'rev-parse' in args:return 'b'*40 if failure=='remote_sha' else target
    if 'merge-base' in args:raise subprocess.CalledProcessError(1,args)
    return ''
   archive=types.SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_nlink=1)
   def digest(path):return 'hash' if path==trust.AUTH else 'b'*64
   with self.subTest(failure=failure),patch.object(trust.os,'geteuid',return_value=0),patch.object(trust,'protected',side_effect=[guard,auth,receipt]),patch.object(trust,'sha',side_effect=digest),patch.object(trust,'run',side_effect=command),patch.object(Path,'lstat',return_value=archive),patch.object(trust.tempfile,'TemporaryDirectory') as tmp,patch.object(trust.os,'chmod'):
    tmp.return_value.__enter__.return_value='/var/tmp/private-fixture'
    with self.assertRaises(Exception):trust.reconcile(target)
   self.assertFalse(any(args[0]=='/usr/sbin/runuser' for args in commands))
   self.assertFalse(any('show' in args or 'checkout' in args or 'bash' in args for args in commands))
   fetch=next(args for args in commands if 'fetch' in args)
   self.assertIn(trust.REMOTE,fetch)
   self.assertIn('--filter=blob:none',fetch)
 def test_changed_authorization_stops_before_any_metadata_download(self):
  target,guard,auth,receipt=self.fixture();guard['authorization_sha256']='wrong'
  with patch.object(trust.os,'geteuid',return_value=0),patch.object(trust,'protected',side_effect=[guard,auth,receipt]),patch.object(trust,'sha',return_value='right'),patch.object(trust,'run') as execute:
   with self.assertRaisesRegex(RuntimeError,'authorization_changed'):trust.reconcile(target)
  execute.assert_not_called()
 def test_untrusted_candidate_cannot_execute_before_policy_validation(self):
  with patch.object(trust.os,'geteuid',return_value=0),patch.object(trust,'protected',side_effect=RuntimeError('unsafe policy')),patch.object(trust,'run') as execute:
   with self.assertRaisesRegex(RuntimeError,'unsafe policy'):trust.reconcile('a'*40)
  execute.assert_not_called()
 def test_forced_command_refuses_extra_space_newline_and_arguments(self):
  import subprocess
  source=(ROOT/'deploy/bootstrap-deploy-user.sh').read_text()
  script=source.split('cat >"${COMMAND_WRAPPER}" <<\'EOF\'\n',1)[1].split('\nEOF',1)[0]
  self.assertIn('exec /usr/bin/sudo -n /usr/local/sbin/opticable-api-deploy-root',script)
  with tempfile.TemporaryDirectory() as temp:
   wrapper=Path(temp)/'forced-command.sh';wrapper.write_text(script)
   for command in ('','bash','deploy main','deploy '+ 'a'*40+';id','deploy '+ 'a'*40+' extra','deploy  '+'a'*40,'deploy\n'+'a'*40,'deploy\t'+'a'*40):
    with self.subTest(command=command):
     result=subprocess.run(['/bin/bash',str(wrapper)],env={'PATH':'/usr/bin:/bin','SSH_ORIGINAL_COMMAND':command},capture_output=True)
     self.assertEqual(result.returncode,64)
 def test_loader_validates_archive_as_data_and_refuses_links_path_or_digest_substitution(self):
  import hashlib,io,tarfile
  spec=importlib.util.spec_from_file_location('static_loader',ROOT/'deploy/phase6-release-loader.py');loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
  content=b'# reviewed exact campaign\n';digest=hashlib.sha256(content).hexdigest()
  for malicious in (None,'link','../escape','/absolute','duplicate','.git/config','wrong_digest'):
   stream=io.BytesIO()
   with tarfile.open(fileobj=stream,mode='w') as archive:
    member=tarfile.TarInfo(loader.CAMPAIGN);member.size=len(content);archive.addfile(member,io.BytesIO(content))
    if malicious in ('link','../escape','/absolute','duplicate','.git/config'):
     path=loader.CAMPAIGN if malicious in ('link','duplicate') else malicious
     extra=tarfile.TarInfo(path)
     if malicious=='link':extra.type=tarfile.SYMTYPE;extra.linkname='/bin/sh'
     else:extra.size=1
     archive.addfile(extra,None if malicious=='link' else io.BytesIO(b'x'))
   with self.subTest(malicious=malicious):
    if malicious is None:self.assertTrue(loader.validate_archive(stream.getvalue(),digest))
    else:
     with self.assertRaises(Exception):loader.validate_archive(stream.getvalue(),'a'*64 if malicious=='wrong_digest' else digest)
 def test_loader_missing_policy_or_mismatched_authority_never_enters_candidate_code(self):
  spec=importlib.util.spec_from_file_location('static_loader_noexecute',ROOT/'deploy/phase6-release-loader.py');loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
  with patch.object(loader.os,'geteuid',return_value=0),patch.object(loader,'protected',return_value={}),patch.object(loader,'command') as command,patch.object(loader.subprocess,'run') as invoke:
   with self.assertRaises(Exception):loader.execute('a'*40)
  command.assert_not_called();invoke.assert_not_called()
 def test_loader_fixed_repository_and_binary_paths_cannot_be_overridden(self):
  source=(ROOT/'deploy/phase6-release-loader.py').read_text()
  self.assertNotIn('os.environ',source)
  self.assertIn("subprocess.run(['/usr/bin/python3','-I'",source)
  self.assertNotIn("subprocess.run(['/opt/",source)
  self.assertLess(source.index("validate_archive(material, auth['campaign_sha256'])"),source.index("subprocess.run(['/usr/bin/python3','-I'"))
  self.assertIn("'merge-base','--is-ancestor',BASELINE,candidate",source)
