#!/usr/bin/env python3
"""
Fetches Attio + Fireflies data and bakes it directly into index.html.
Run from event-dashboards/: python3 scripts/bake.py
Then: git add index.html && git commit -m "Update baked data" && git push
"""

import json, re, sys, requests
from datetime import datetime, timezone

ATTIO_KEY     = 'da486bd28d0a1a9abb18e6b899b5f1396d3755a53bbe4160be4a6f5e21e9fab3'
ATTIO_BASE    = 'https://api.attio.com/v2'
FIREFLIES_KEY = '35381824-8184-4800-ab0b-606086b44cb5'
FIREFLIES_GQL = 'https://api.fireflies.ai/graphql'

COMPANIES = {
    'dLocal':       'dlocal',
    'Wellhub':      'wellhub',
    'Clara':        'claracc',
    'Grão Direto':  'graodireto',
    'Intelipost':   'intelipost',
    'Swap':         'swapfinancial',
    '180 Seguros':  '180-seguros',
    'Netlex':       'netlex-io',
    'Ascenty':      'ascenty',
    'Medway':       'medway-educacao-medica',
    'Meli':         'mercadolibre',
    'Rivio':        'riviotech',
}

# ── Attio helpers ────────────────────────────────────────────

def attio_post(path, body):
    r = requests.post(f'{ATTIO_BASE}{path}',
                      headers={'Authorization': f'Bearer {ATTIO_KEY}', 'Content-Type': 'application/json'},
                      json=body, timeout=30)
    r.raise_for_status()
    return r.json()

def norm_li(url):
    if not url: return None
    m = re.search(r'linkedin\.com/company/([^/?#]+)', str(url), re.I)
    return m.group(1).lower() if m else str(url).lower().strip()

def a_val(arr, kind='value'):
    if not arr: return None
    a = next((v for v in arr if v.get('active_until') is None), None)
    if not a: return None
    v = a.get(kind)
    if isinstance(v, dict): return v.get('title') or v.get('name') or str(v)
    return v

def a_val_select(arr):
    if not arr: return None
    a = next((v for v in arr if v.get('active_until') is None), None)
    return (a.get('option') or {}).get('title') if a else None

def a_interaction(arr):
    if not arr: return None
    a = next((v for v in arr if v.get('active_until') is None), None)
    if not a: return None
    return {'date': (a.get('interacted_at') or '')[:10] or None}

def p_name(vals):
    fn = a_val(vals.get('first_name', [])) or ''
    ln = a_val(vals.get('last_name', [])) or ''
    name = f'{fn} {ln}'.strip()
    return name or a_val(vals.get('name', [])) or None

def p_co_id(vals):
    for key in ('company', 'companies'):
        lst = vals.get(key) or []
        a = next((v for v in lst if v.get('active_until') is None), None)
        if a: return a.get('target_record_id')
    return None

def seniority_n(title):
    if not title: return 4
    t = title.lower()
    cxo = ['ceo','cto','cfo','coo','chro']
    if any(re.search(r'(?<![a-z])'+kw+r'(?![a-z])', t) for kw in cxo): return 0
    if any(kw in t for kw in ['chief','president','founder','co-founder','owner']): return 0
    if re.search(r'\bvp\b', t) or any(kw in t for kw in ['vice president','svp']): return 1
    if any(kw in t for kw in ['director','diretor','head of']) or re.search(r'\bhead\b', t): return 2
    if any(kw in t for kw in ['manager','gerente',' lead','senior']): return 3
    return 4

def infer_role(title):
    s = seniority_n(title)
    return 'Decisor' if s == 0 else 'Influenciador' if s in (1, 2) else 'Usuário'

# ── Fetch Attio companies ─────────────────────────────────────

print('Fetching companies…', flush=True)
co_by_li, co_by_name, co_by_id = {}, {}, {}
off = 0
while True:
    d = attio_post('/objects/companies/records/query', {'limit': 500, 'offset': off})
    for rec in d.get('data', []):
        rid = rec['id']['record_id']
        li  = a_val(rec['values'].get('linkedin', []))
        nm  = a_val(rec['values'].get('name', []))
        ls  = a_val(rec['values'].get('lifecycle_status', []), 'status')
        co_by_id[rid] = {'name': nm, 'linkedin': li, 'lifecycleStatus': ls}
        if li: co_by_li[norm_li(li)] = rid
        if nm: co_by_name[nm.lower()] = rid
    if d.get('next_cursor'): off = d['next_cursor']; continue
    if len(d.get('data', [])) < 500: break
    off += 500
print(f'  {len(co_by_id)} companies', flush=True)

# ── Fetch Attio people ────────────────────────────────────────

print('Fetching people…', flush=True)
p_by_co_id = {}
off = 0
while True:
    d = attio_post('/objects/people/records/query', {'limit': 500, 'offset': off})
    for p in d.get('data', []):
        vals  = p['values']
        co_id = p_co_id(vals)
        if not co_id: continue
        title  = a_val(vals.get('job_title', [])) or ''
        li_url = a_val(vals.get('linkedin', [])) or a_val(vals.get('linkedin_profile_url', [])) or ''
        fi     = a_interaction(vals.get('first_interaction', []))
        lmeet  = a_interaction(vals.get('last_calendar_interaction', []))
        lemail = a_interaction(vals.get('last_email_interaction', []))
        person = {
            'id':                   p['id']['record_id'],
            'name':                 p_name(vals),
            'job_title':            title,
            'linkedin':             li_url,
            'role':                 infer_role(title),
            'seniority':            seniority_n(title),
            'touchpoint_count':     a_val(vals.get('touchpoint_count', [])),
            'last_touchpoint_date': a_val(vals.get('last_touchpoint_date', [])),
            'first_interaction_date': fi['date'] if fi else None,
            'last_meeting_date':    lmeet['date'] if lmeet else None,
            'last_email_date':      lemail['date'] if lemail else None,
        }
        p_by_co_id.setdefault(co_id, []).append(person)
    if d.get('next_cursor'): off = d['next_cursor']; continue
    if len(d.get('data', [])) < 500: break
    off += 500
total_p = sum(len(v) for v in p_by_co_id.values())
print(f'  {total_p} people', flush=True)

# ── Fetch Attio deals ─────────────────────────────────────────

print('Fetching deals…', flush=True)
d_by_co_id = {}
d = attio_post('/objects/deals/records/query', {'limit': 500})
for deal in d.get('data', []):
    vals    = deal['values']
    co_list = (vals.get('associated_company') or vals.get('associated_company_5') or
               vals.get('associated_company_2') or vals.get('company') or vals.get('client') or [])
    co_a    = next((v for v in co_list if v.get('active_until') is None), None)
    co_id   = co_a.get('target_record_id') if co_a else None
    if not co_id: continue
    val_list = vals.get('value') or vals.get('deal_value') or []
    val_a    = next((v for v in val_list if v.get('active_until') is None), None)
    bdr_list = vals.get('bdr_associated') or vals.get('owner') or []
    bdr_a    = next((v for v in bdr_list if v.get('active_until') is None), None)
    bdr      = None
    if bdr_a:
        bdr = ((bdr_a.get('option') or {}).get('title') or bdr_a.get('name') or
               bdr_a.get('full_name') or bdr_a.get('referenced_actor_name'))
    obj = {
        'id':             deal['id']['record_id'],
        'name':           a_val(vals.get('name', [])),
        'stage':          a_val(vals.get('stage', [])),
        'value_amount':   (val_a.get('amount') or val_a.get('value')) if val_a else None,
        'value_currency': val_a.get('currency_code') if val_a else None,
        'bdr':            bdr,
        'deal_source':    a_val_select(vals.get('deal_source', [])),
        'date_mql':       (a_val(vals.get('date_mql', [])) or '')[:10] or None,
        'date_sal':       (a_val(vals.get('date_sal', [])) or '')[:10] or None,
        'date_won':       (a_val(vals.get('date_won', [])) or '')[:10] or None,
        'date_lost':      (a_val(vals.get('date_lost', [])) or '')[:10] or None,
        'lost_reason':    a_val(vals.get('lost_reason', [])),
    }
    d_by_co_id.setdefault(co_id, []).append(obj)
print(f'  {sum(len(v) for v in d_by_co_id.values())} deals', flush=True)

# ── Filter to our 12 companies only ──────────────────────────

company_ids = set()
for name, slug in COMPANIES.items():
    rid = co_by_li.get(slug) or co_by_name.get(name.lower())
    if rid: company_ids.add(rid)

p_by_co_id = {k: v for k, v in p_by_co_id.items() if k in company_ids}
d_by_co_id = {k: v for k, v in d_by_co_id.items() if k in company_ids}
print(f'  Filtered: {len(p_by_co_id)} companies with people', flush=True)

# ── Fetch Fireflies ───────────────────────────────────────────

print('Fetching Fireflies…', flush=True)
ff_data = {}
for name in COMPANIES:
    try:
        r = requests.post(FIREFLIES_GQL,
            headers={'Authorization': f'Bearer {FIREFLIES_KEY}', 'Content-Type': 'application/json'},
            json={
                'query': 'query SearchTranscripts($title:String){transcripts(title:$title){id title date duration host_email meeting_attendees{displayName email}}}',
                'variables': {'title': name}
            }, timeout=20)
        raw = (r.json().get('data') or {}).get('transcripts') or []
        meetings = []
        for t in raw:
            date = t.get('date')
            if isinstance(date, (int, float)):
                date = datetime.fromtimestamp(date / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
            meetings.append({
                'id':           t.get('id'),
                'title':        t.get('title'),
                'date':         date,
                'duration_min': round(t['duration'] / 60) if t.get('duration') else None,
                'host_email':   t.get('host_email'),
                'attendees':    [{'name': a.get('displayName'), 'email': a.get('email')}
                                 for a in (t.get('meeting_attendees') or [])],
            })
        meetings.sort(key=lambda x: x.get('date') or '', reverse=True)
        ff_data[name] = meetings
        print(f'  {name}: {len(meetings)} meetings', flush=True)
    except Exception as e:
        print(f'  {name}: ERROR — {e}', flush=True)
        ff_data[name] = []

# ── Build SD blob ─────────────────────────────────────────────

sd = {
    'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'attio': {
        'coByLi':   co_by_li,
        'coByName': co_by_name,
        'coById':   co_by_id,
        'pByCoId':  p_by_co_id,
        'dByCoId':  d_by_co_id,
    },
    'ff': ff_data,
}

sd_json = json.dumps(sd, ensure_ascii=False, separators=(',', ':'))

# ── Inject into index.html ────────────────────────────────────

html_path = 'index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

html, n = re.subn(
    r'const SD = .*?; // __BAKED_DATA__',
    f'const SD = {sd_json}; // __BAKED_DATA__',
    html
)
if n == 0:
    print('ERROR: __BAKED_DATA__ placeholder not found in index.html', file=sys.stderr)
    sys.exit(1)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

size_kb = len(sd_json.encode()) / 1024
print(f'\nDone! {size_kb:.0f} KB baked into {html_path}')
print(f'Generated at: {sd["generated_at"]}')
print(f'\nTo publish:')
print(f'  git add index.html && git commit -m "Update baked data {sd["generated_at"][:10]}" && git push')
