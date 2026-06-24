#!/usr/bin/env python3
"""Build the Blood Meridian Kindle dictionaries.

Produces two sideloadable Kindle dictionaries (.mobi):

  1. Webster_1913_Dictionary.mobi          - Webster's 1913 (public domain) standalone
  2. Blood_Meridian_Dictionary_Extended.mobi - Webster's 1913 with this book's ~1,300
     special terms folded in (the in-context gloss + book quote shown first, then the
     general Webster definition).

Inputs (resolved automatically, override with flags):
  - Webster source : webster_1913.json next to this script; if absent it is downloaded
                     from matthewreagan/WebstersEnglishDictionary (public domain).
  - Blood Meridian : Blood_Meridian_Vocabulary_Companion.epub next to this script;
                     entries are read straight out of the EPUB.
  - kindlegen      : the real .mobi builder. Found via --kindlegen, $KINDLEGEN, PATH,
                     or the copy bundled inside Kindle Previewer on macOS. If it can't
                     be found, the OPF source is written out and you can build manually.

Usage:
  python3 build_dicts.py
  python3 build_dicts.py --outdir dist --kindlegen /path/to/kindlegen

Notes:
  - kindlegen is run with -c1 (PalmDOC). -c2 (Huffdic) segfaults on this content.
  - Requires Python 3.8+ and a network connection on first run (to fetch the Webster
    source) unless webster_1913.json is already present.
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.request
import uuid
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WEBSTER_URL = ("https://raw.githubusercontent.com/matthewreagan/"
               "WebstersEnglishDictionary/master/dictionary.json")
KINDLEGEN_MAC = ("/Applications/Kindle Previewer 3.app/Contents/lib/fc/bin/kindlegen")
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

# ---------- parse Blood Meridian companion (read from the EPUB) ----------
ENTRY_RE = re.compile(r'<p class="entry">(.*?)</p>', re.S)
TERM_RE  = re.compile(r'<span class="term">(.*?)</span>', re.S)
POS_RE   = re.compile(r'<span class="pos">(.*?)</span>', re.S)
Q_RE     = re.compile(r'<span class="q"><em>(.*?)</em></span>', re.S)

def parse_bm(companion_epub):
    names = (["OEBPS/epigraphs.xhtml"]
             + [f"OEBPS/chapter-{i:02d}.xhtml" for i in range(1, 24)]
             + ["OEBPS/epilogue.xhtml"])
    groups, order = {}, []
    with zipfile.ZipFile(companion_epub) as z:
        present = set(z.namelist())
        for name in names:
            if name not in present:
                continue
            doc = z.read(name).decode("utf-8")
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
                sig = re.sub(r'\s+', ' ', strip_tags(def_raw).lower()).strip()[:90]
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
    with open(os.path.join(out_dir, "dict.css"), "w", encoding="utf-8") as fh:
        fh.write(CSS)
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
    with open(os.path.join(out_dir, "content.opf"), "w", encoding="utf-8") as fh:
        fh.write(opf)
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
    with open(os.path.join(out_dir, "toc.ncx"), "w", encoding="utf-8") as fh:
        fh.write(ncx)
    return len(rendered), len(files)

# ---------- inputs & kindlegen ----------
def ensure_webster(path):
    p = Path(path).resolve() if path else (SCRIPT_DIR / "webster_1913.json")
    if p.exists():
        return p
    print(f"Webster source not found at {p}\n  downloading public-domain Webster's 1913 from\n  {WEBSTER_URL}")
    p.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(WEBSTER_URL, p)
    print(f"  saved {p} ({p.stat().st_size // (1024*1024)} MB)")
    return p

def find_kindlegen(explicit):
    for cand in (explicit, os.environ.get("KINDLEGEN"),
                 shutil.which("kindlegen"), KINDLEGEN_MAC):
        if cand and Path(cand).exists():
            return cand
    return None

def produce(mobi_name, title, entries, outdir, kindlegen):
    """Emit OPF source and (if kindlegen is available) build the .mobi into outdir."""
    if kindlegen:
        tmp = Path(tempfile.mkdtemp(prefix="dictbuild_"))
        try:
            n, _ = emit_dict(str(tmp), title, entries)
            # kindlegen writes the .mobi next to content.opf; -c1 (PalmDOC), -c2 segfaults.
            proc = subprocess.run([kindlegen, "content.opf", "-c1", "-o", mobi_name],
                                  cwd=str(tmp), capture_output=True, text=True)
            built = tmp / mobi_name
            if not built.exists():
                sys.stderr.write(proc.stdout[-1500:] + "\n" + proc.stderr[-800:] + "\n")
                raise SystemExit(f"kindlegen failed to produce {mobi_name} (exit {proc.returncode})")
            dest = outdir / mobi_name
            shutil.move(str(built), str(dest))
            print(f"  built {dest.name}  ({n:,} entries)  ->  {dest}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        src = outdir / "_build" / (mobi_name[:-5] + "_src")
        n, f = emit_dict(str(src), title, entries)
        print(f"  wrote source for {mobi_name} to {src}  ({n:,} entries, {f} files)")
        print(f"    kindlegen not found; build manually:  kindlegen \"{src}/content.opf\" -c1 -o {mobi_name}")
    return mobi_name

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Build the Blood Meridian Kindle dictionaries.")
    ap.add_argument("--webster", help="Webster's 1913 JSON (default: webster_1913.json beside this script, downloaded if missing)")
    ap.add_argument("--companion", help="Blood Meridian companion .epub (default: beside this script)")
    ap.add_argument("--kindlegen", help="path to kindlegen (default: $KINDLEGEN, PATH, or Kindle Previewer on macOS)")
    ap.add_argument("--outdir", default=str(SCRIPT_DIR / "dictionaries"), help="where to write the .mobi files (default: ./dictionaries)")
    args = ap.parse_args()

    outdir = Path(args.outdir).resolve(); outdir.mkdir(parents=True, exist_ok=True)
    companion = Path(args.companion).resolve() if args.companion else (SCRIPT_DIR / "Blood_Meridian_Vocabulary_Companion.epub")
    if not companion.exists():
        raise SystemExit(f"companion EPUB not found: {companion}")
    web_path = ensure_webster(args.webster)
    kindlegen = find_kindlegen(args.kindlegen)
    print(f"Webster source : {web_path}")
    print(f"Companion EPUB : {companion}")
    print(f"kindlegen      : {kindlegen or '(not found - will emit source only)'}")
    print(f"Output dir     : {outdir}\n")

    # ----- build Webster entries (shared by both dictionaries) -----
    with open(web_path, encoding="utf-8") as fh:
        web = json.load(fh)
    web_entries = {}
    for key in sorted(web.keys()):
        deftext = web[key]
        if not deftext or not deftext.strip(): continue
        prim, forms = lookup_keys(key)
        if not prim: continue
        disp = key[:1].upper() + key[1:]
        web_entries[key] = {"display": xml_escape(disp), "primary": prim,
                            "iforms": forms, "body": web_body(deftext)}
    print(f"Webster entries parsed: {len(web_entries):,}")

    # ----- DICT 1: Webster standalone -----
    produce("Webster_1913_Dictionary.mobi", "Webster's 1913 Dictionary",
            list(web_entries.values()), outdir, kindlegen)

    # ----- DICT 2: Extended (Blood Meridian senses first, then Webster) -----
    BM_HDR  = '<p class="bmh"><b>&#9656; Blood Meridian</b></p>'   # noqa: F841 (kept for reference)
    WEB_HDR = '<p class="bmh"><b>&#9656; Webster 1913</b></p>'
    bm_groups, bm_order = parse_bm(companion)
    web_keys = set(web_entries.keys())

    bm_for_web = {}   # web_key -> list of (group, bm_forms)  (handles multi-hit)
    extra = []        # Blood-Meridian-only standalone entries
    for k in bm_order:
        g = bm_groups[k]
        pl = g["plain"].lower()
        cands = [pl, ascii_fold(pl)]
        if pl.endswith('s'):  cands.append(pl[:-1])
        if pl.endswith('es'): cands.append(pl[:-2])
        hit = next((c for c in cands if c in web_keys), None)
        bm_prim, bm_forms = lookup_keys(g["plain"])
        if hit:
            bm_for_web.setdefault(hit, []).append((g, bm_forms))
        elif bm_prim:
            extra.append({"display": g["display"], "primary": bm_prim,
                          "iforms": bm_forms, "body": bm_body(g["senses"], header=False)})

    d = {k: dict(v, iforms=set(v["iforms"])) for k, v in web_entries.items()}
    for wk, lst in bm_for_web.items():
        e = d[wk]
        bm_html = "".join(bm_body(g["senses"], header=False) for g, _ in lst)
        for _, frm in lst: e["iforms"] |= frm
        e["body"] = bm_html + WEB_HDR + web_entries[wk]["body"]   # Blood Meridian first
    ext_entries = sorted(list(d.values()) + extra,
                         key=lambda e: strip_tags(e["display"]).lower())
    print(f"Blood Meridian terms: {len(bm_for_web):,} folded into Webster headwords, "
          f"{len(extra):,} added standalone")

    produce("Blood_Meridian_Dictionary_Extended.mobi", "Blood Meridian Extended Dictionary",
            ext_entries, outdir, kindlegen)
    print("\nDone.")

if __name__ == "__main__":
    main()
