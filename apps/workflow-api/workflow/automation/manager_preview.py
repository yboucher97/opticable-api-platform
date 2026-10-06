"""Actual escaped local artifact in the existing shared proposal detail surface."""
from html import escape


def render_preview(item):
    r=item['record'];d=item['detail'];h=lambda v:escape(str(v),quote=True)
    if r['proposal_type']=='FORM_REVISION_DRAFT':
        return "<!doctype html><html><meta charset='utf-8'><title>Form draft</title><a href='/v1/operator/manager'>Business Manager</a><h1>"+h(r['recommended_change'])+'</h1><pre>'+h(d['draft'])+'</pre><p>'+h(r['owner_action_required'])+'</p></html>'
    out="<!doctype html><html lang='en'><meta charset='utf-8'><title>Website preview</title><style>body{font:16px system-ui;max-width:900px;margin:30px auto;padding:20px}section{padding:20px;background:#f5f7f8;margin:20px 0}pre{white-space:pre-wrap}</style><a href='/v1/operator/manager'>Business Manager</a><h1>"+h(r['recommended_change'])+'</h1><p>Local editorial draft · '+h(r['confidence'])+'</p><section><h2>'+h(d['draft']['heading'])+'</h2><p>'+h(d['draft']['copy'])+'</p><strong>'+h(d['draft']['cta'])+'</strong>'
    for faq in d['draft']['faq']:out+='<h3>'+h(faq['question'])+'</h3><p>'+h(faq['answer'])+'</p>'
    out+='</section><h2>Proposed links</h2><ul>'+''.join('<li>'+h(l['label'])+': '+h(l['target'])+'</li>' for l in d['draft']['links'])+'</ul>'
    for name in ('creative_brief','repurposing','checks','migration_plan','source_sample'):
        out+='<details><summary>'+h(name.replace('_',' ').title())+'</summary><pre>'+h(d.get(name))+'</pre></details>'
    out+='<p>Branch: '+h(d.get('repository_branch') or 'Pending exact repository mapping')+' · '+h(d['build_status'])+'</p>'
    out+='<p>'+h(r['risk'])+'</p><p>'+h(r['owner_action_required'])+'</p><p>Publication requires exact source/preview/build review and separate authority.</p></html>'
    return out
