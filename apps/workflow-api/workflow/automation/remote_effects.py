"""Atomic off-host claims survive rollback, stale backup and local journal loss.

An existing or uncertain claim NEVER permits another provider write. Conditional
R2 creation is the only way to acquire authority. Objects have no automatic TTL.
"""
import configparser
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re

from .business_autonomy import digest, utc_now

BUCKET = 'optibrain-recovery-prod'
PREFIX = 'business-effects/v1/'


@dataclass(frozen=True)
class FreshClaim:
    action_id: str
    payload_hash: str
    key: str
    fresh: bool


class RemoteEffects:
    def __init__(self, client):
        self.client = client

    @classmethod
    def root_store(cls):
        if os.geteuid() != 0: raise PermissionError('Off-host effect authority is root-only')
        import boto3
        from botocore.config import Config
        credentials = configparser.ConfigParser()
        credentials.read('/etc/optibrain/r2-uploader.env')
        config = dict(line.split('=',1) for line in Path('/etc/optibrain/phase2a.conf').read_text().splitlines()
                      if '=' in line and not line.startswith('#'))
        account = config['OPTIBRAIN_PHASE2A_ACCOUNT_ID'].strip().strip('"\'')
        if not re.fullmatch('[0-9a-f]{32}',account): raise ValueError('Invalid off-host account')
        return cls(boto3.client('s3',endpoint_url=f'https://{account}.r2.cloudflarestorage.com',
            aws_access_key_id=credentials['default']['aws_access_key_id'],
            aws_secret_access_key=credentials['default']['aws_secret_access_key'],region_name='auto',
            config=Config(connect_timeout=10,read_timeout=20,retries={'max_attempts':0})))

    @staticmethod
    def key(action, kind):
        if not re.fullmatch('[0-9a-f]{32}',action.action_id): raise ValueError('Invalid action ID')
        return PREFIX + action.action_id + '/' + kind + '.json'

    def get(self, action, kind):
        try:
            result=self.client.get_object(Bucket=BUCKET,Key=self.key(action,kind))
        except Exception as exc:
            code=str(getattr(exc,'response',{}).get('Error',{}).get('Code',''))
            if code in {'NoSuchKey','404'}: return None
            raise ValueError('Off-host execution evidence is unavailable') from exc
        raw=result['Body'].read(65537)
        if len(raw)>65536: raise ValueError('Off-host execution evidence is unbounded')
        value=json.loads(raw)
        if (value.get('schema')!=1 or value.get('action_id')!=action.action_id
                or value.get('payload_hash')!=action.payload_hash or value.get('target_id')!=action.target_id):
            raise ValueError('Off-host execution binding changed')
        return value

    def claim(self, action):
        if action.action_type!='crm.task.create' or action.target_module!='Leads':
            raise ValueError('Unsupported off-host execution claim')
        value={'schema':1,'action_id':action.action_id,'payload_hash':action.payload_hash,
               'target_id':action.target_id,'created_at':utc_now(),'envelope':action.__dict__}
        # Secret rejection is also enforced by the central journal; only synthetic
        # Task proposals reach this store, after fresh ownership verification.
        key=self.key(action,'claim')
        try:
            self.client.put_object(Bucket=BUCKET,Key=key,Body=json.dumps(value,sort_keys=True).encode(),
                                   ContentType='application/json',IfNoneMatch='*')
        except Exception as exc:
            code=str(getattr(exc,'response',{}).get('Error',{}).get('Code',''))
            if code in {'PreconditionFailed','412','ConditionalRequestConflict','409','ObjectLockedByBucketPolicy'}:
                if not self.get(action,'claim'): raise ValueError('Existing claim is not readable')
                return FreshClaim(action.action_id,action.payload_hash,key,False)
            # Even an upload timeout may have committed. Do not retry or grant.
            raise ValueError('Off-host claim outcome is uncertain; reconciliation only') from exc
        if not self.get(action,'claim'): raise ValueError('Fresh off-host claim readback unavailable')
        return FreshClaim(action.action_id,action.payload_hash,key,True)

    def complete(self, action, provider_id):
        if not str(provider_id).isdigit(): raise ValueError('Exact provider ID required')
        value={'schema':1,'action_id':action.action_id,'payload_hash':action.payload_hash,
               'target_id':action.target_id,'provider_id':str(provider_id),'verified_at':utc_now()}
        try:
            self.client.put_object(Bucket=BUCKET,Key=self.key(action,'result'),
                Body=json.dumps(value,sort_keys=True).encode(),ContentType='application/json',IfNoneMatch='*')
        except Exception as exc:
            old=self.get(action,'result')
            if not old or old.get('provider_id')!=str(provider_id):
                raise ValueError('Off-host result is uncertain or changed') from exc
        return value
