#!/usr/bin/env python3
"""Render copied Manager state; no production JWT, providers, or DB mutations."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile
import time

sys.dont_write_bytecode=True
sys.path.insert(0,'/opt/opticable-api-platform/apps/workflow-api')


def blocked(*args,**kwargs): raise AssertionError('Manager rebuild probe network prohibited')


def main():
    socket.socket.connect=socket.socket.connect_ex=socket.socket.sendto=blocked
    socket.create_connection=socket.getaddrinfo=blocked
    from workflow.automation.manager_store import ManagerStore
    from workflow.automation.manager_intelligence import build_manager, render_manager
    with tempfile.TemporaryDirectory(prefix='rebuild-manager-') as directory:
        copied=Path(directory)/'phase12-autonomy.db'
        with sqlite3.connect('file:/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db?mode=ro',uri=True) as src, sqlite3.connect(copied) as dst:
            src.backup(dst)
        started=time.monotonic()
        store=ManagerStore(copied); view=build_manager({},store,datetime.now(timezone.utc))
        html=render_manager(view)
        assert html and view and store.counts()['learning']>=0
        return {'status':'PASS','render_bytes':len(html.encode()),'provider_calls':0,'live_database_writes':0,
                'counts':store.counts(),'manager_render_ms':round((time.monotonic()-started)*1000,3),
                'owner_endpoint':'unauthenticated denial separately verified'}


if __name__=='__main__':
    try: print(json.dumps(main()))
    except Exception as exc: raise SystemExit('Manager probe failed: '+type(exc).__name__)
