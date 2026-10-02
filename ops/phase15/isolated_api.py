#!/usr/bin/env python3
"""Offline drill server entry point; layered network denial, no provider credentials."""
import ipaddress
import os
from pathlib import Path
import socket
import sys

sys.dont_write_bytecode=True
AUDIT=Path('/run/optibrain-isolated/network-attempts')
if not Path('/etc/optibrain-rebuild-target').is_file() or os.geteuid()==0:
    raise SystemExit('Unprivileged marked isolated target required')


def denied():
    with AUDIT.open('a') as stream:stream.write('blocked\n')
    raise OSError('External network prohibited in isolated recovery boot')


original_connect=socket.socket.connect
original_connect_ex=socket.socket.connect_ex
original_dns=socket.getaddrinfo
original_sendto=socket.socket.sendto


def local(address):
    if isinstance(address,(str,bytes)):return True  # AF_UNIX
    try:return ipaddress.ip_address(address[0]).is_loopback
    except ValueError:return False


def connect(self,address):
    if not local(address):denied()
    return original_connect(self,address)


def connect_ex(self,address):
    if not local(address):denied()
    return original_connect_ex(self,address)


def dns(host,*args,**kwargs):
    if host not in ('localhost',None) and not local((host,0)):denied()
    return original_dns(host,*args,**kwargs)


def sendto(self,data,*args):
    if args and not local(args[-1]):denied()
    return original_sendto(self,data,*args)


socket.socket.connect=connect;socket.socket.connect_ex=connect_ex
socket.getaddrinfo=dns;socket.socket.sendto=sendto
sys.path.insert(0,'/opt/opticable-api-platform/apps/workflow-api')
import uvicorn
uvicorn.run('workflow.api:app',host='127.0.0.1',port=8100,access_log=False)
