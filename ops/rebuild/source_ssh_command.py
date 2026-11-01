#!/usr/bin/env python3
"""Forced SSH entry: exactly one signed-protocol verb, never an internal CLI."""
import os,sys

def dispatch(argv):
 if argv!=['execute']:raise SystemExit(126)
 python='/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python'
 os.execve(python,[python,'-B','/usr/local/lib/optibrain-migration/source_executor.py','execute'],{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
if __name__=='__main__':dispatch(sys.argv[1:])
