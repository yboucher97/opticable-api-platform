#!/usr/bin/env python3
"""Bounded pages of competitors discovered in recorded live service searches.

Search-result visibility is not a neutral Google ranking or market share.
No copied content is published; pages are private source evidence.
"""
import json
from datetime import datetime,timezone
from pathlib import Path
import httpx

DISCOVERED=[
 ('https://softflow.ca/fr/cablage-montreal/','câblage structuré commercial Montréal Laval'),
 ('https://solutionsdctech.com/','câblage structuré commercial Montréal Laval'),
 ('https://www.sicard-reseautique.com/','câblage structuré commercial Montréal Laval'),
 ('https://www.flexcom.ca/cablage-structure.php','câblage structuré commercial Montréal Laval'),
 ('https://www.reseautageplus.ca/services','commercial wifi installation warehouse Montreal'),
 ('https://fortexasecurity.com/','installation caméra surveillance entreprise Laval Montréal'),
 ('https://fortega.ca/locations/montreal','commercial security cameras Montreal access control'),
 ('https://securlink.ca/','commercial security cameras Montreal access control'),
 ('https://areasecurite.ca/accueil/solutions/surveillance-video/','caméra surveillance commercial Laval'),
 ('https://protechmax.com/','caméra surveillance commercial Laval'),
]

def main():
    rows=[];now=datetime.now(timezone.utc).isoformat()
    with httpx.Client(timeout=8,follow_redirects=False,headers={'User-Agent':'OptiBrain market research/1.0'}) as client:
        for url,query in DISCOVERED:
            row={'url':url,'discovery_query':query,'retrieved_at':now,'discovery_evidence':'public-discovery.json / recorded live service searches','ranking':None,'authority':None}
            try:
                with client.stream('GET',url) as response:
                    b=b''
                    for chunk in response.iter_bytes():
                        b+=chunk
                        if len(b)>524288:raise ValueError('Competitor page exceeds bounded sample')
                    row.update(http_status=response.status_code,content_type=response.headers.get('content-type'),location=response.headers.get('location'))
                    if response.status_code==200 and 'text/html' in row['content_type']:row['html']=b.decode('utf-8','replace')
            except (httpx.HTTPError,ValueError) as exc:row['error_class']=type(exc).__name__
            rows.append(row)
    p=Path('/home/optibrain/phase28-29-evidence/competitor-pages.json');p.write_text(json.dumps({'schema':1,'at':now,'pages':rows},ensure_ascii=False));p.chmod(0o600)
    print(json.dumps({'pages':len(rows),'readable':sum('html' in r for r in rows),'redirects':sum(r.get('http_status',0) in (301,302,307,308) for r in rows),'provider_writes':0}))

if __name__=='__main__':main()
