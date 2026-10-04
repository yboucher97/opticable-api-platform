#!/usr/bin/env python3
"""Bounded own-site crawl: robots, sitemaps, pages; no publication or crawler writes."""
import asyncio,json,sys,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET
import httpx
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO/'apps/workflow-api'))
from workflow.automation.seo_intelligence import own_url,page_inventory
ROOT=Path('/home/optibrain/phase28-29-evidence')

async def main():
    discovery=json.loads((ROOT/'site-discovery.json').read_text());robots={};targets={}
    for host in ('opticable.ca','ai.opticable.ca'):
        base='https://'+host;rp=RobotFileParser();rp.parse(discovery[base+'/robots.txt'].get('text','').splitlines());robots[host]=rp
        xml=ET.fromstring(discovery[base+'/sitemap.xml']['text'])
        for node in xml.findall('{*}url'):
            url=node.findtext('{*}loc')
            if own_url(url):targets[url]={'in_sitemap':True,'lastmod':node.findtext('{*}lastmod')}
        targets[base+'/']={'in_sitemap':False}
    if len(targets)>160:raise ValueError('Own-site crawl exceeds 160-page budget')
    now=datetime.now(timezone.utc).isoformat();rows=[];gate=asyncio.Semaphore(4);clock=asyncio.Lock();last=[0.0]
    async with httpx.AsyncClient(timeout=httpx.Timeout(8,connect=3),follow_redirects=False,headers={'User-Agent':'OptiBrain owned-site SEO audit/1.0'}) as client:
        async def fetch(url,meta):
            allowed=robots[urlsplit(url).hostname].can_fetch('*',url)
            row={'url':url,**meta,'retrieved_at':now,'robots_allowed':allowed,'redirect_chain':[]}
            if not allowed:row['status']='ROBOTS BLOCKED';return row
            async with gate:
                async with clock:
                    delay=max(.25,robots[urlsplit(url).hostname].crawl_delay('*') or 0)
                    await asyncio.sleep(max(0,delay-(time.monotonic()-last[0])));last[0]=time.monotonic()
                target=url
                try:
                    for _ in range(4):
                        async with client.stream('GET',target) as response:
                            body=b''
                            async for chunk in response.aiter_bytes():
                                body+=chunk
                                if len(body)>1048576:raise ValueError('HTML exceeds page byte bound')
                            row['status']=response.status_code;row['x_robots_tag']=response.headers.get('x-robots-tag','')
                            if response.status_code in (301,302,307,308):
                                next_url=urljoin(target,response.headers.get('location',''))
                                row['redirect_chain'].append({'url':target,'status':response.status_code,'to':next_url})
                                destination=robots.get(urlsplit(next_url).hostname)
                                if not own_url(next_url) or not destination or not destination.can_fetch('*',next_url):break
                                target=next_url;continue
                            if response.status_code==200 and 'text/html' in response.headers.get('content-type',''):row['html']=body.decode('utf-8','replace')
                            row['final_url']=target;break
                except (httpx.HTTPError,ValueError) as exc:row['error_class']=type(exc).__name__
                return row
        rows=await asyncio.gather(*(fetch(url,meta) for url,meta in targets.items()))
    raw={'schema':1,'at':now,'robots_sitemaps':discovery,'pages':rows,'provider_writes':0};inventory=[page_inventory(r) for r in rows]
    (ROOT/'website-raw.json').write_text(json.dumps(raw,ensure_ascii=False));(ROOT/'website-inventory.json').write_text(json.dumps({'schema':1,'at':now,'pages':inventory},ensure_ascii=False))
    print(json.dumps({'pages':len(rows),'readable':sum('html' in r for r in rows),'indexable_candidates':sum(p['indexable_candidate'] for p in inventory),'provider_writes':0}))

if __name__=='__main__':asyncio.run(main())
