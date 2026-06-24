#!/usr/bin/env python3
"""Build two Kindle dictionaries:
   1. Webster's 1913 (public domain) standalone  -> web_src/
   2. Webster's 1913 + Blood Meridian entries folded in -> ext_src/
"""
import os, re, html, json, uuid, unicodedata

BASE = "/private/tmp/claude-501/-Users-benjaminfeder-Programming-blood-meridian-guide/0d3b33f1-bcae-4e34-9cb7-4534d8bada54/scratchpad"
WEB_JSON = f"{BASE}/webster/reagan.json"
BM_DIR   = f"{BASE}/build/OEBPS"
IDX_NS = "https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf"
CHUNK = 500

STOP = set("""the a an of and or to in on at by for from with as his her its their our your my
he she it they we you this that these those who whom whose which what when where how not but""".split())

# ---------- helpers ----------
def strip_tags(s): return re.sub(r'<[^>]+>', '', s)
def attr_escape(s):
    return (s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;'))
def xml_escape(s):
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
def ascii_fold(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def add_clean(forms, t):
    t = re.sub(r"[^a-zÀ-ɏ'\-]", "", t.strip().lower())
    if len(t) >= 2: forms.add(t)
    af = re.sub(r"[^a-z'\-]", "", ascii_fold(t))
    if len(af) >= 2: forms.add(af)

def add_s(base, out):
    if re.search(r'(s|x|z|ch|sh)$', base): out.add(base+'es')
    elif re.search(r'[^aeiou]y$', base):   out.add(base[:-1]+'ies')
    else:                                  out.add(base+'s')

def gen_infl(w):
    """Generic (POS-free) inflections for a single English word."""
    forms = set(); add_clean(forms, w)
    tmp = set()
    if not w.endswith('s'): add_s(w, tmp)
    elif len(w) > 3: tmp.add(w[:-1])
    if w.endswith('e'): tmp.update([w+'d', w[:-1]+'ing', w+'s'])
    else:               tmp.update([w+'ed', w+'ing', w+'s'])
    for x in tmp: add_clean(forms, x)
    return forms

def lookup_keys(plain):
    """Return (primary clean token, set of iform keys) for a headword string."""
    toks = re.findall(r"[^\W\d_]+", plain, re.UNICODE)
    if not toks: return None, set()
    forms = set()
    if len(toks) == 1:
        w = toks[0].lower()
        forms |= gen_infl(w)
        base = re.sub(r"[^a-z'\-]", "", ascii_fold(w))
        primary = base if len(base) >= 2 else None
    else:
        for t in toks:
            tl = t.lower()
            if len(tl) >= 4 and tl not in STOP: add_clean(forms, tl)
        add_clean(forms, "".join(toks).lower())   # de-hyphenated / de-spaced whole
        if not forms: add_clean(forms, max(toks, key=len).lower())
        primary = None
    if primary is None:
        cand = sorted((f for f in forms if len(f) >= 2), key=lambda x: (len(x), x))
        primary = cand[-1] if cand else None
    if primary: forms.add(primary)
    forms = {f for f in forms if f and len(f) >= 2}
    return primary, forms

# ---------- parse Blood Meridian companion ----------
ENTRY_RE = re.compile(r'<p class="entry">(.*?)</p>', re.S)
TERM_RE  = re.compile(r'<span class="term">(.*?)</span>', re.S)
POS_RE   = re.compile(r'<span class="pos">(.*?)</span>', re.S)
Q_RE     = re.compile(r'<span class="q"><em>(.*?)</em></span>', re.S)

def parse_bm():
    files = ([f"{BM_DIR}/epigraphs.xhtml"]
             + [f"{BM_DIR}/chapter-{i:02d}.xhtml" for i in range(1,24)]
             + [f"{BM_DIR}/epilogue.xhtml"])
    groups, order = {}, []
    for path in files:
        doc = open(path, encoding="utf-8").read()
        for block in ENTRY_RE.findall(doc):
            mt = TERM_RE.search(block)
            if not mt: continue
            term_raw = mt.group(1).strip()
            term_plain = html.unescape(strip_tags(term_raw)).strip()
            if not term_plain: continue
            mp = POS_RE.search(block); mq = Q_RE.search(block)
            pos_raw = mp.group(1).strip() if mp else ''
            quote_raw = mq.group(1).strip() if mq else ''
            after = block[mp.end():] if mp else block[mt.end():]
            after = re.sub(r'^\s*&#8212;\s*', '', after, count=1)
            def_raw = re.split(r'<span class="q">', after, maxsplit=1)[0].strip()
            key = term_plain.lower()
            if key not in groups:
                groups[key] = {"display": term_raw, "plain": term_plain, "senses": []}
                order.append(key)
            g = groups[key]
            sig = re.sub(r'\s+',' ', strip_tags(def_raw).lower()).strip()[:90]
            if any(s["sig"] == sig for s in g["senses"]): continue
            g["senses"].append({"pos": pos_raw, "def": def_raw, "quote": quote_raw, "sig": sig})
    return groups, order

def bm_body(senses, header):
    out = []
    if header: out.append('<p class="bmh"><b>&#9656; Blood Meridian</b></p>')
    multi = len(senses) > 1
    for i, s in enumerate(senses, 1):
        pos = f'<i>{s["pos"]}</i> ' if s["pos"] else ''
        num = f'<b>{i}.</b> ' if multi else ''
        out.append(f'<p class="bm">{pos}{num}{s["def"]}</p>')
        if s["quote"]: out.append(f'<p class="q">{s["quote"]}</p>')
    return "".join(out)

# ---------- render Webster body (styled & spaced) ----------
LBL_RE   = re.compile(r'^\([A-Z][^)]{0,22}\)')                   # leading domain label, e.g. (Astron.)
TAG_RE2  = re.compile(r'\[[^\]]{1,18}\]')                        # status tag, e.g. [Obs.]
QUOTE_RE = re.compile(r'(["“][^"”]{1,250}?["”])') # "quotation" / smart quotes

def _style_text(raw):
    """Escape one chunk of definition text and add inline styling (quotes, tags, label)."""
    s = xml_escape(raw.strip())
    # dim quotations & tags FIRST, while the only quotes/brackets present are real text
    s = QUOTE_RE.sub(lambda mo: f'<span class="qt">{mo.group(1)}</span>', s)
    s = TAG_RE2.sub(lambda mo: f'<span class="tag">{mo.group(0)}</span>', s)
    m = LBL_RE.match(s)            # leading domain label -> italic (added last to avoid quote clash)
    if m:
        s = f'<i class="lbl">{m.group(0)}</i>' + s[m.end():]
    return s

def _split_senses(block):
    """Split a POS block into numbered senses by walking the expected 1,2,3... markers."""
    bounds, n, pos = [], 1, 0
    while True:
        m = re.compile(r'(?:^|\s)%d\.\s' % n).search(block, pos)
        if not m: break
        bounds.append(m); pos = m.end(); n += 1
    if not bounds:
        return block.strip(), []
    senses = []
    for i, m in enumerate(bounds):
        end = bounds[i+1].start() if i+1 < len(bounds) else len(block)
        senses.append(block[m.end():end].strip())
    return block[:bounds[0].start()].strip(), senses

def _peel_runins(seg):
    """Pull trailing ' -- ' run-in sub-entries (and Syn. lists) out of a sense."""
    parts = re.split(r'\s+--\s+', seg)
    if len(parts) == 1:
        return seg.rstrip(), [], []
    main = parts[0].rstrip()
    phrases, syns = [], []
    syn_first = bool(re.search(r'\bSyn\.\s*$', main))
    if syn_first: main = re.sub(r'\bSyn\.\s*$', '', main).rstrip()
    for i, p in enumerate(parts[1:]):
        p = p.strip()
        if not p: continue
        if syn_first and i == 0:
            syns.append(p)
        elif re.match(r'[A-Z]', p) or p.startswith(('To ', 'See ')):
            phrases.append(p)                          # looks like a sub-entry lemma
        else:
            main = main.rstrip() + ' — ' + p      # lowercase tail -> keep inline
    return main.rstrip(), phrases, syns

def _render_phrase(p):
    mm = re.match(r'^(.{1,42}?)\s*[,;.]\s+(.*)$', p, re.S)
    if mm:
        return f'<b>{xml_escape(mm.group(1).strip())}</b> &#8212; {_style_text(mm.group(2))}'
    return _style_text(p)

def web_body(deftext):
    try:
        return _format_webster(deftext)
    except Exception:                                  # never let one odd entry break the build
        paras = re.split(r'\n\s*\n', deftext)
        out = [f"<p>{xml_escape(' '.join(p.split()))}</p>" for p in paras if p.strip()]
        return "".join(out) if out else "<p>&#160;</p>"

def _format_webster(deftext):
    items, phrases, syns = [], [], []
    for bi, block in enumerate(re.split(r'\n\s*\n', deftext)):
        block = block.strip()
        if not block: continue
        lead, senses = _split_senses(block)
        first = True
        if not senses:
            seg, ph, sy = _peel_runins(block)
            items.append({"t": seg, "num": False, "gap": bi > 0})
            phrases += ph; syns += sy
            continue
        if lead:
            items.append({"t": lead, "num": False, "gap": bi > 0}); first = False
        for stext in senses:
            seg, ph, sy = _peel_runins(stext)
            if seg:
                items.append({"t": seg, "num": True, "gap": bi > 0 and first}); first = False
            phrases += ph; syns += sy
    multi = sum(1 for it in items if it["num"]) > 1
    out, k = [], 0
    for it in items:
        cls = "s gap" if it["gap"] else "s"
        styled = _style_text(it["t"])
        if it["num"] and multi:
            k += 1
            out.append(f'<p class="{cls}"><b class="n">{k}.</b> {styled}</p>')
        else:
            out.append(f'<p class="{cls}">{styled}</p>')
    if syns:
        out.append('<p class="phh">Synonyms</p>')
        out += [f'<p class="ph">{_style_text(s)}</p>' for s in syns]
    if phrases:
        out.append('<p class="phh">Phrases</p>')
        out += [f'<p class="ph">{_render_phrase(p)}</p>' for p in phrases]
    return "".join(out) if out else "<p>&#160;</p>"

# ---------- generic dictionary emitter ----------
def render_entry(e):
    if not e["primary"]: return None
    iforms = "".join(f'<idx:iform value="{attr_escape(f)}"/>'
                     for f in sorted(e["iforms"]) if f != e["primary"])
    infl = f"<idx:infl>{iforms}</idx:infl>" if iforms else ""
    return (f'<idx:entry name="headword" scriptable="yes" spell="yes">'
            f'<idx:orth value="{attr_escape(e["primary"])}"><b>{e["display"]}</b>'
            f'{infl}</idx:orth>{e["body"]}</idx:entry>')

HEAD = ('<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:idx="{IDX_NS}" xmlns:mbp="{IDX_NS}"><head><meta charset="utf-8"/>'
        '<link rel="stylesheet" type="text/css" href="dict.css"/></head><body>\n<mbp:frameset>\n')
TAIL = '\n</mbp:frameset></body></html>\n'
CSS = ("body{font-family:Georgia,serif}b{font-weight:bold}"
       "p{margin:0.22em 0}"
       ".s{margin:0.18em 0}.s.gap{margin-top:0.55em}.n{font-weight:bold}"
       ".lbl{font-style:italic}.tag{color:#777;font-size:0.85em}"
       ".qt{color:#888;font-style:italic}"
       ".phh{font-weight:bold;margin:0.5em 0 0.1em 0}"
       ".ph{margin:0.12em 0 0.12em 0.9em;text-indent:-0.9em}"
       ".q{font-style:italic;color:#555;margin:0 0 0.4em 0}"
       ".bmh{margin:0.5em 0 0.1em 0}.bm{margin:0.15em 0}")

def emit_dict(out_dir, title, entries):
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir): os.remove(os.path.join(out_dir, f))
    rendered = [r for r in (render_entry(e) for e in entries) if r]
    files = []
    for ci in range(0, len(rendered), CHUNK):
        fn = f"content-{ci//CHUNK:04d}.xhtml"; files.append(fn)
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as fh:
            fh.write(HEAD); fh.write("\n".join(rendered[ci:ci+CHUNK])); fh.write(TAIL)
    open(os.path.join(out_dir,"dict.css"),"w",encoding="utf-8").write(CSS)
    uid = "urn:uuid:" + str(uuid.uuid4())
    man = ['    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
           '    <item id="css" href="dict.css" media-type="text/css"/>']
    spine, nav = [], []
    for i, f in enumerate(files):
        man.append(f'    <item id="c{i}" href="{f}" media-type="application/xhtml+xml"/>')
        spine.append(f'    <itemref idref="c{i}"/>')
        nav.append(f'    <navPoint id="n{i}" playOrder="{i+1}"><navLabel><text>{i+1}</text>'
                   f'</navLabel><content src="{f}"/></navPoint>')
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{title}</dc:title>
    <dc:creator opf:role="aut">Benjamin Feder</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="BookId">{uid}</dc:identifier>
    <x-metadata>
      <DictionaryInLanguage>en</DictionaryInLanguage>
      <DictionaryOutLanguage>en</DictionaryOutLanguage>
      <DefaultLookupIndex>headword</DefaultLookupIndex>
    </x-metadata>
  </metadata>
  <manifest>
{os.linesep.join(man)}
  </manifest>
  <spine toc="ncx">
{os.linesep.join(spine)}
  </spine>
</package>
'''
    open(os.path.join(out_dir,"content.opf"),"w",encoding="utf-8").write(opf)
    ncx = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="{uid}"/></head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>
{os.linesep.join(nav)}
  </navMap>
</ncx>
'''
    open(os.path.join(out_dir,"toc.ncx"),"w",encoding="utf-8").write(ncx)
    return len(rendered), len(files)

# ---------- build Webster entries ----------
web = json.load(open(WEB_JSON, encoding="utf-8"))
web_entries = {}   # key -> entry dict (kept for augmentation)
for key in sorted(web.keys()):
    deftext = web[key]
    if not deftext or not deftext.strip(): continue
    prim, forms = lookup_keys(key)
    if not prim: continue
    disp = key[:1].upper() + key[1:]
    web_entries[key] = {"display": xml_escape(disp), "primary": prim,
                        "iforms": forms, "body": web_body(deftext)}

# ---------- DICT 1: Webster only ----------
n1, f1 = emit_dict(f"{BASE}/webster/web_src",
                   "Webster's 1913 Dictionary", list(web_entries.values()))
print(f"Webster dict: {n1} entries, {f1} files")

# ---------- DICT 2: two Extended variants (fold BM into Webster) ----------
BM_HDR  = '<p class="bmh"><b>&#9656; Blood Meridian</b></p>'
WEB_HDR = '<p class="bmh"><b>&#9656; Webster 1913</b></p>'
bm_groups, bm_order = parse_bm()
web_keys = set(web_entries.keys())

bm_for_web = {}   # web_key -> list of (group, bm_forms)  (handles multi-hit)
extra = []        # BM-only standalone entries, identical in both variants
for k in bm_order:
    g = bm_groups[k]
    plain = g["plain"]; pl = plain.lower()
    cands = [pl, ascii_fold(pl)]
    if pl.endswith('s'):  cands.append(pl[:-1])
    if pl.endswith('es'): cands.append(pl[:-2])
    hit = next((c for c in cands if c in web_keys), None)
    bm_prim, bm_forms = lookup_keys(plain)
    if hit:
        bm_for_web.setdefault(hit, []).append((g, bm_forms))
    elif bm_prim:
        extra.append({"display": g["display"], "primary": bm_prim,
                      "iforms": bm_forms, "body": bm_body(g["senses"], header=False)})

def build_ext(lead):
    """lead='web' -> Webster def first then BM block; lead='bm' -> BM block first then Webster."""
    d = {k: dict(v, iforms=set(v["iforms"])) for k, v in web_entries.items()}
    for wk, lst in bm_for_web.items():
        e = d[wk]
        bm_html = "".join(bm_body(g["senses"], header=False) for g, _ in lst)
        for _, frm in lst: e["iforms"] |= frm
        wbody = web_entries[wk]["body"]
        e["body"] = (wbody + BM_HDR + bm_html) if lead == "web" else (bm_html + WEB_HDR + wbody)
    return sorted(list(d.values()) + extra, key=lambda e: strip_tags(e["display"]).lower())

nb, fb = emit_dict(f"{BASE}/webster/ext_bf",
                   "Blood Meridian Extended Dictionary (Blood Meridian first)", build_ext("bm"))
print(f"Extended (BM-first): {nb} entries, {fb} files")
print(f"  BM folded into existing Webster entries: {len(bm_for_web)} headwords")
print(f"  BM added as new standalone entries:      {len(extra)}")
