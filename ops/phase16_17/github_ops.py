#!/usr/bin/env python3
"""Manual authenticated Git transport; credentials remain in child memory only."""
import base64
import os
import pwd
import subprocess
import sys
from inventory import clients

def main():
    if len(sys.argv)<4 or sys.argv[2] not in {'fetch','push'}:raise ValueError('Use REPO fetch/push arguments')
    settings,_,_=clients()
    from workflow.github_api import GithubApiClient
    client=GithubApiClient(settings.github)
    value=base64.b64encode(('x-access-token:'+client._auth_token()).encode()).decode()
    environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/home/optibrain','GIT_TERMINAL_PROMPT':'0',
        'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'http.https://github.com/.extraheader','GIT_CONFIG_VALUE_0':'AUTHORIZATION: basic '+value}
    user=pwd.getpwnam('optibrain')
    def unprivileged():os.setgroups([user.pw_gid]);os.setgid(user.pw_gid);os.setuid(user.pw_uid)
    result=subprocess.run(['/usr/bin/git','-C',sys.argv[1],*sys.argv[2:]],env=environment,preexec_fn=unprivileged)
    raise SystemExit(result.returncode)

if __name__=='__main__':main()
