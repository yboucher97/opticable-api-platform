"""Preserve every existing archive; capacity is bytes, never a generation cutoff."""

def preservation_plan(records, free_bytes):
    if not records or any(not r.get('sidecar_matches') or r.get('size',0)<=0 or r.get('uncompressed_bytes',0)<=0 for r in records):
        raise ValueError('Verified archive inventory required')
    # Two archives plus two independent restored workspaces and rollback workspace.
    required=max(4*1024**3,6*max(r['uncompressed_bytes'] for r in records)+2*max(r['size'] for r in records))
    if free_bytes<required:raise ValueError('Insufficient preservation/restore capacity')
    return {'mode':'preserve-all-existing','existing_generations':len(records),'required_free_bytes':required,
            'free_bytes':free_bytes,'deletions':[],'moves':[],'retention_override':False}
