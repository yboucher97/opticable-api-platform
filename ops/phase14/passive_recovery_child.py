"""Restricted one-shot verification child; systemd starts it as nobody, never root."""
import sys,json,socket,resource,os
from pathlib import Path
from datetime import datetime,timezone
if os.geteuid()!=65534:raise PermissionError('Unprivileged verification context required')
resource.setrlimit(resource.RLIMIT_CPU,(5,5))
resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,256*1024**2))
resource.setrlimit(resource.RLIMIT_FSIZE,(8192,8192))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
root=Path('/usr/local/lib/optibrain-recovery')
sys.path[:0]=[str(root),str(root/'vendor')]
from workflow.automation.development_sandbox import restrict_child
restrict_child(root,Path('/tmp'))
from workflow.automation.release_recovery import RecoverySupervisor
refused=False
try:
    RecoverySupervisor(object(),{}, {},expected_digest='',git_file=None,probe=None,data_probe=None,now=datetime.now(timezone.utc))
except ValueError:refused=True
network=False
try:socket.socket()
except PermissionError:network=True
print(json.dumps({'runtime_imported':True,'api_imported':'workflow.api' in sys.modules,
    'uid':os.geteuid(),'production_scope_refused':refused,'network_denied':network,
    'observed_at':datetime.now(timezone.utc).isoformat()}))
