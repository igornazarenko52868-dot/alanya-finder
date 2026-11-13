#!/usr/bin/env python3
"""Alanya Finder collector.
Reads sources.json (Google Drive folders, Google Docs, websites),
extracts apartments for sale and writes data/listings.json.
Uses only the Python standard library."""
import datetime, hashlib, html, json, os, re, time
import urllib.parse, urllib.request, urllib.robotparser

UA = "Mozilla/5.0 (compatible; AlanyaFinderBot/1.0; personal use)"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "listings.json")
KD = ["Mahmutlar", "Kestel", "Oba", "Tosmur", "Cikcilli", "Çıkcılı", "Kargicak", "Kargıcak",
      "Demirtaş", "Avsallar", "Konaklı", "Payallar", "Türkler", "Okurcalar", "Merkez", "Center", "Alanya"]
# Only listings that mention one of these places are kept (set "alanya_only": false on a source to switch this off).
ALANYA = ["Alanya", "Mahmutlar", "Kestel", "Oba", "Tosmur", "Cikcilli", "Çıkcılı", "Kargicak", "Kargıcak", "Demirtaş",
          "Avsallar", "Konaklı", "Payallar", "Türkler", "Okurcalar", "İncekum", "Incekum", "Kızlarpınarı", "Obagöl",
          "Sugözü", "Şekerhane", "Hacet", "Gazipaşa"]
AL_RX = re.compile(r"(?<![^\W\d_])(?:" + "|".join(re.escape(k) for k in ALANYA) + r")(?![^\W\d_])", re.I)


def is_alanya(trail, det):
    return bool(det and det.get("al")) or bool(AL_RX.search(" ".join(trail)))


PAL = ["#0e5c7a,#14a3a0", "#1c6e5c,#7bc47f", "#254a73,#4b8fc4", "#5b3f8c,#b37fd1", "#7a4a1e,#e0a458", "#8a2f4a,#e2778f"]
IMG = (".jpg", ".jpeg", ".png", ".webp")
DOCS = (".pdf", ".docx", ".txt")
# How many photos to keep per property. More photos = more storage in the repository (about 0.1 MB each).
MAX_PHOTOS = 10
PRICE = re.compile(r"(?<![\d+])(\d{1,3}(?:[ .,]\d{3})+|\d{4,7})\s*(?:€|euro|eur)", re.I)
# Rate used to convert prices written in Turkish lira (TL). Change it when the rate moves.
TRY_PER_EUR = 56
PRICE_TL = re.compile(r"(?<![\d+])(\d{1,3}(?:[ .,]\d{3})+|\d{4,9})\s*(?:₺|tl\b|try\b|lira)", re.I)
RENT = re.compile(r"kiral[ıi]k|\brent|аренд|/\s*ay\b|ayl[ıi]k|per month|monthly|в месяц", re.I)
PRICE2 = re.compile(r"(?:€|euro|eur)\s*(?<![\d+])(\d{1,3}(?:[ .,]\d{3})+|\d{4,7})", re.I)


def get(url, tries=2):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "tr,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(2)
    print("  FAIL", url, last)
    return ""


_rp = {}


def allowed(url):
    p = urllib.parse.urlparse(url)
    base = p.scheme + "://" + p.netloc
    if base not in _rp:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None
        _rp[base] = rp
    rp = _rp[base]
    return True if rp is None else rp.can_fetch(UA, url)


def norm_tel(p):
    p = re.sub(r"[^\d+]", "", p or "")
    if not p:
        return ""
    if p[0] == "0":
        return "+9" + p
    return p if p[0] == "+" else "+" + p


def parse_line(l, room, need_price=True):
    m = PRICE.search(l) or PRICE2.search(l)
    p = int(re.sub(r"\D", "", m.group(1))) if m else 0
    tl = 0
    if not m:
        mt = PRICE_TL.search(l)
        if mt:
            tl = int(re.sub(r"\D", "", mt.group(1)))
            p = round(tl / TRY_PER_EUR / 100) * 100
    # small amounts or rent words = monthly rent, not a sale price
    small = (not m) and bool(re.search(r"(?<![\d+.,])\d{2,4}\s*(?:€|euro|eur)\b", l, re.I))
    rent = bool(RENT.search(l)) or small or (m is not None and 0 < p < 5000) or (0 < tl < 200000)
    if rent or (p and (p < 5000 or p > 5_000_000)):
        p = 0
    if need_price and not p:
        return None
    rm = re.search(r"(\d\+\d)", l)
    ar = re.search(r"(\d{2,3})\s*(?:m2|m²|metre)", l, re.I)
    fl = re.search(r"(\d{1,2})\s*\.?\s*kat", l, re.I)
    lw, d = l.lower(), ""
    for k in KD:
        if re.search(r"(^|[^a-zçğıöşü])" + re.escape(k.lower()) + r"($|[^a-zçğıöşü])", lw):
            d = k
            break
    if d in ("Merkez", "Center"):
        d = "cen"
    return {"p": p, "d": d or "Alanya", "r": rm.group(1) if rm else room,
            "m": int(ar.group(1)) if ar else 0, "fl": int(fl.group(1)) if fl else 0,
            "dd": "p" if re.search(r"proje|off.?plan|inşaat", l, re.I) else "t",
            "o": "o" if re.search(r"sahibinden|owner|владел|хозяин", l, re.I) else "a",
            "tp": "v" if re.search(r"villa|vila\b|müstakil|mustakil|вилла", l, re.I) else "a",
            "rent": rent, "tl": tl if p else 0}


def mk(src, agency, tel, x, ref, url="", ph=None, title=""):
    return {"d": x["d"], "r": x["r"], "m": x["m"], "sea": 0, "fl": x["fl"], "age": 0, "aid": 0,
            "dd": x["dd"], "o": x["o"], "nw": 0, "old": 0, "ag": [[agency, x["p"]]], "tel": tel,
            "url": url, "ph": ph or [], "src": src, "ref": ref,
            "tp": x.get("tp", "a"), "t": title, "tl": x.get("tl", 0)}


def parse_text(text, src, agency, tel, url=""):
    out, room = [], ""
    if not tel:
        m = re.search(r"\+90[\d\s]{10,13}", text)
        tel = norm_tel(m.group(0)) if m else ""
    for line in re.split(r"\n+", text):
        l = line.strip()
        if not l:
            continue
        h = re.match(r"^\W*(\d\+\d)\W*daire", l, re.I)
        if h:
            room = h.group(1)
            continue
        x = parse_line(l, room)
        if x:
            ref = "txt:" + hashlib.md5((src + l).encode()).hexdigest()[:10]
            out.append(mk(src, agency, tel, x, ref, url))
    return out


def drive_list(fid):
    """Returns [(id, title, is_folder)] for a public Google Drive folder."""
    h = get("https://drive.google.com/embeddedfolderview?id=" + fid)
    out = []
    pat = r'<a href="https://drive\.google\.com/(drive/folders|file/d)/([\w-]+)[^"]*"[^>]*>.*?<div class="flip-entry-title">(.*?)</div>'
    for m in re.finditer(pat, h, re.S):
        out.append((m.group(2), html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip(), m.group(1) == "drive/folders"))
    return out


FEAT = [
    (r"a[cç][iıİI]k\s+havuz|open\s+pool|открыт\w*\s+бассейн", "pool"),
    (r"kapal[iıİI]\s+havuz|indoor\s+pool|закрыт\w*\s+бассейн", "pool_in"),
    (r"havuz|бассейн|\bpool\b", "pool_any"),
    (r"f[iıİI]tn[eE]ss?|spor\s+salonu|\bgym\b|фитнес|тренажерн", "gym"),
    (r"sauna|сауна", "sauna"),
    (r"hamam|хамам", "hamam"),
    (r"masaj|massage|массаж", "massage"),
    (r"barbek[uü]|\bbbq\b|барбекю|мангал", "bbq"),
    (r"kamelya|gazebo|беседк", "gazebo"),
    (r"e[sş]yal[iıİI]|furnished|с\s+мебелью|меблирован", "furn"),
    (r"asans[oö]r|elevator|лифт", "elev"),
    (r"otopark|parking|парковк", "park"),
    (r"g[uü]venl[iıİI]k|security|охран", "sec"),
    (r"[cç]ocuk\s+(?:oyun\s+)?(?:park|alan)|playground|детск\w+\s+площадк", "play"),
    (r"[cç]am\s+balkon|glass\s+balcon|стеклянн\w+\s+балкон", "gbal"),
    (r"jenerat[oö]r|generator|генератор", "gen"),
    (r"ten[iıİI]s|tennis|теннис", "tennis"),
    (r"merkez[iıİI]\s+uydu|central\s+satellite", "sat"),
    (r"ye[sş][iıİI]l\s+alan|green\s+area|зелен\w+\s+зона", "green"),
    (r"kapora\s+al[iıİI]nd[iıİI]|reserved|задаток", "dep"),
    (r"vatanda[sş]l[iıİI][gğ]a\s+uygun|citizenship", "cit"),
    (r"kredi(?:ye)?\s+(?:ve\s+vatanda\w*\s+)?uygun|mortgage", "cred"),
]


def pdf_text(b):
    try:
        import pypdf
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pypdf"], check=False)
        try:
            import pypdf
        except ImportError:
            print("  pypdf is not available, PDFs are skipped")
            return ""
    import io
    r = pypdf.PdfReader(io.BytesIO(b))
    return "\n".join((p.extract_text() or "") for p in r.pages[:3])


def read_doc(fid, name):
    """Download a PDF / DOCX / TXT from a public Drive folder and return its text."""
    b = get_bytes("https://drive.google.com/uc?export=download&id=" + fid)
    n = name.lower()
    try:
        if n.endswith(".pdf") and b[:4] == b"%PDF":
            return pdf_text(b)
        if n.endswith(".docx") and b[:2] == b"PK":
            import io, zipfile
            x = zipfile.ZipFile(io.BytesIO(b)).read("word/document.xml").decode("utf-8", "replace")
            return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", x)))
        if n.endswith(".txt") and b:
            return b.decode("utf-8", "replace")
    except Exception as e:  # noqa
        print("  cannot read", name, e)
    return ""


def parse_details(text):
    """Pull area, floor, sea distance, building age, features, price... out of a description text."""
    if not text:
        return {}
    flat = re.sub(r"\s+", " ", text)
    d = {}
    if AL_RX.search(flat):
        d["al"] = True
    m = re.search(r"📍\s*([^\W\d_]+)", flat)
    if m:
        d["d"] = m.group(1)
        title = re.sub(r"\s+", " ", re.sub(r"[^\w\s\-+.,/&()'’]", "", flat.split("📍")[0])).strip(" -")
        if 3 <= len(title) <= 80:
            d["title"] = title
    if "d" not in d:  # no pin: look for a known district name
        for k in KD:
            if k != "Alanya" and re.search(r"(?<![^\W\d_])" + k + r"(?![^\W\d_])", flat, re.I):
                d["d"] = k
                break
    if d.get("d"):
        for k in KD:
            if k.lower() == d["d"].lower():
                d["d"] = k
        if d["d"] in ("Merkez", "Center"):
            d["d"] = "cen"
    if "title" not in d:  # e.g. *SONAS BUKET RESIDENCE*
        m = re.search(r"([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9 ]{2,40}(?:RESIDENCE|REZIDANS|REZİDANS|SİTESİ|SITESI))", flat)
        if m:
            d["title"] = m.group(1).strip().title()
    m = re.search(r"\bkod\s*:?\s*(\d{3,6})", flat, re.I)
    if m:
        d["cd"] = m.group(1)
    m = re.search(r"(\d\+\d)", flat)
    if m:
        d["r"] = m.group(1)
    m = re.search(r"(\d{2,3})\s*(?:m²|m2|м²|м2)", flat, re.I)
    if m:
        d["m"] = int(m.group(1))
    m = (re.search(r"bulundu[gğ]u\s+kat\D{0,3}(\d{1,2})", flat, re.I)
         or re.search(r"(?<![^\W\d_])(\d{1,2})\s*\.?\s*kat\b", flat, re.I)
         or re.search(r"этаж\s*:?\s*(\d{1,2})", flat, re.I))
    if m:
        d["fl"] = int(m.group(1))
    m = (re.search(r"🏖\D{0,6}?(\d{2,4})\s*m\b", flat) or re.search(r"denize\D{0,14}?(\d{2,4})\s*m(?:etre)?\b", flat, re.I)
         or re.search(r"до моря\D{0,14}?(\d{2,4})", flat, re.I))
    if m:
        d["sea"] = int(m.group(1))
    m = re.search(r"✈\D{0,6}?(\d{1,3})\s*km", flat) or re.search(r"(?:airport|havaalan\w*|аэропорт)\D{0,14}?(\d{1,3})\s*km", flat, re.I)
    if m:
        d["ap"] = int(m.group(1))
    m = re.search(r"🛒\D{0,6}?(\d{2,4})\s*m\b", flat)
    if m:
        d["mkt"] = int(m.group(1))
    if "sea" not in d:  # emojis lost: header looks like "300 m 35 km 100 m"
        m = re.search(r"\b(\d{2,4})\s*m\s+(\d{1,3})\s*km\s+(\d{2,4})\s*m\b", flat)
        if m:
            d["sea"], d["ap"], d["mkt"] = int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"(\d)\s*(?:wc\s*)?banyo|(\d)\s*bath|(\d)\s*ванн", flat, re.I)
    if m:
        d["ba"] = int(next(g for g in m.groups() if g))
    year = datetime.datetime.now().year
    m = re.search(r"yap[iıİ]m\s+y[iıİ]l[iıİ]\D{0,4}(\d{4})|year\s+built\D{0,4}(\d{4})|год\s+постройки\D{0,4}(\d{4})", flat, re.I)
    if m:
        built = int(next(g for g in m.groups() if g))
        if 1950 < built <= year + 3:
            d["age"] = max(0, year - built)
    m = re.search(r"bina\s+ya[sş][iıİ]\D{0,4}(\d{1,2})\b", flat, re.I)
    if m and "age" not in d:
        d["age"] = int(m.group(1))
    m = re.search(r"aidat\D{0,12}?(\d{1,3}(?:[.,]\d{3})+|\d{1,5})\s*(€|euro|eur|tl\b|₺)?", flat, re.I)
    if m:
        v, cur = int(re.sub(r"\D", "", m.group(1))), (m.group(2) or "").lower()
        d["aid"] = round(v / TRY_PER_EUR) if (cur in ("tl", "₺") or (not cur and v >= 300)) else v
    m = re.search(r"(?:pas\s+f[iİıI]yat[iı]|f[iİıI]yat[iı]?|price|цена)\D{0,8}?(?<![\d+])(\d{1,3}(?:[ .,]\d{3})+|\d{4,9})\s*(€|euro|eur|₺|tl\b|try\b)", flat, re.I)
    if m:
        v, cur = int(re.sub(r"\D", "", m.group(1))), m.group(2).lower()
        if cur in ("€", "euro", "eur"):
            d["p"] = v if v >= 5000 else 0
        elif v >= 200000:
            d["tl"], d["p"] = v, round(v / TRY_PER_EUR / 100) * 100
    if re.search(r"\bvilla\b|\bvila\b|müstakil|вилла", flat, re.I):
        d["tp"] = "v"
    if re.search(r"kiral[iıİI]k", flat, re.I) and not re.search(r"sat[iıİI]l[iıİI]k", flat, re.I):
        d["rent"] = True
    if re.search(r"sat[iıİI]ld[iıİI]\b|\bsold\b|продан", flat, re.I):
        d["sold"] = True
    ft = []
    for rx, code in FEAT:
        if re.search(rx, flat, re.I):
            if code == "pool_any":
                if "pool" in ft or "pool_in" in ft:
                    continue
                code = "pool"
            ft.append(code)
    if ft:
        d["ft"] = ft
    return d


def apply_details(x, det):
    for k in ("m", "fl"):
        if det.get(k):
            x[k] = det[k]
    if not x["r"] and det.get("r"):
        x["r"] = det["r"]
    if x["d"] == "Alanya" and det.get("d"):
        x["d"] = det["d"]
    if not x["p"] and det.get("p"):
        x["p"], x["tl"] = det["p"], det.get("tl", 0)
    if det.get("tp") == "v":
        x["tp"] = "v"


def collect_drive(s):
    out, seen = [], set()
    fid = re.search(r"/folders/([\w-]+)", s["url"]).group(1)

    def walk(f, depth, trail):
        items = drive_list(f)
        time.sleep(0.4)
        print("  folder", f, "->", len(items), "entries |", " / ".join(trail)[:70])
        imgs = ["https://drive.google.com/thumbnail?id=" + i + "&sz=w800"
                for i, n, fo in items if not fo and n.lower().endswith(IMG)][:MAX_PHOTOS]
        docs = [(i, n) for i, n, fo in items if not fo and n.lower().endswith(DOCS)][:3]
        if trail and (imgs or docs):  # a folder with photos or a description = one property
            x = parse_line(" / ".join(reversed(trail)), "", False)
            if x["rent"]:
                print("    skipped (rent):", " / ".join(trail[-2:])[:60])
            else:
                det = {}
                for did, dname in docs:
                    for k, v in parse_details(read_doc(did, dname)).items():
                        if k == "ft":
                            det["ft"] = sorted(set(det.get("ft", [])) | set(v))
                        elif k not in det:
                            det[k] = v
                    time.sleep(0.4)
                if det.get("rent") or det.get("sold"):
                    print("    skipped (rent/sold):", " / ".join(trail[-2:])[:60])
                    det = None
                elif s.get("alanya_only", True) and not is_alanya(trail, det):
                    print("    skipped (not Alanya):", " / ".join(trail[-2:])[:60])
                    det = None
                else:
                    apply_details(x, det)
                    item = mk(s["name"], s["name"], s.get("tel", ""), x, "drive:" + f,
                              "https://drive.google.com/drive/folders/" + f, imgs,
                              det.get("title") or " / ".join(trail[-2:]))
                    item.update({k: det[k] for k in ("sea", "age", "aid", "ft", "ap", "mkt", "ba", "cd") if det.get(k)})
                    out.append(item)
                if docs and det:
                    print("    details:", {k: v for k, v in det.items() if k != "ft"}, det.get("ft", []))
        for eid, name, isf in items:
            if isf and eid not in seen and len(seen) < 400 and depth < 4:
                seen.add(eid)
                walk(eid, depth + 1, trail + [name])

    walk(fid, 0, [])
    return out


def collect_doc(s):
    did = re.search(r"/d/([\w-]+)", s["url"]).group(1)
    text = get("https://docs.google.com/document/d/" + did + "/export?format=txt")
    return parse_text(text, s["name"], s["name"], norm_tel(s.get("tel", "")), s["url"])


def html_to_text(h):
    h = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", h)
    h = re.sub(r"(?i)</?(p|div|li|tr|br|h\d|section|article|ul|ol|table)[^>]*>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    return html.unescape(re.sub(r"[ \t\xa0]+", " ", h))


def collect_site(s):
    if not allowed(s["url"]):
        print("  skipped: robots.txt disallows", s["url"])
        return []
    time.sleep(1)
    return parse_text(html_to_text(get(s["url"])), s["name"], s["name"], norm_tel(s.get("tel", "")), s["url"])


PHOTO_DIR = os.path.join(HERE, "data", "photos")
# Listings first seen more than this many days ago are removed from the app together with their photos.
# (The files on Google Drive are never touched.) 120 days is about 4 months.
MAX_AGE_DAYS = 120
RETIRED = os.path.join(HERE, "data", "retired.json")


def get_bytes(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read()
    except Exception as e:  # noqa
        print("  photo FAIL", url[:70], e)
        return b""


def is_img(b):
    return len(b) > 2000 and (b[:2] == b"\xff\xd8" or b[:4] == b"\x89PNG" or (b[:4] == b"RIFF" and b[8:12] == b"WEBP"))


def localize(listings):
    """Copy photos from Google Drive into data/photos so the site can attach them when sharing."""
    os.makedirs(PHOTO_DIR, exist_ok=True)
    used = set()
    for x in listings:
        out = []
        for u in x.get("ph", []):
            m = re.search(r"id=([\w-]+)", u)
            if not m:
                out.append(u)
                if u.startswith("data/photos/"):
                    used.add(os.path.basename(u))
                continue
            name = m.group(1) + ".jpg"
            path = os.path.join(PHOTO_DIR, name)
            if not os.path.exists(path):
                for src in ("https://lh3.googleusercontent.com/d/" + m.group(1) + "=w800",
                            "https://drive.google.com/thumbnail?id=" + m.group(1) + "&sz=w800"):
                    b = get_bytes(src)
                    time.sleep(0.3)
                    if is_img(b):
                        open(path, "wb").write(b)
                        break
            if os.path.exists(path):
                out.append("data/photos/" + name)
                used.add(name)
            else:
                out.append(u)
        x["ph"] = out
    for f in os.listdir(PHOTO_DIR):
        if f not in used:
            os.remove(os.path.join(PHOTO_DIR, f))


def key(x):
    if x["m"]:
        return "|".join(str(x[k]) for k in ("d", "r", "m", "fl"))
    return "ref|" + x["ref"]


def merge(items):
    d = {}
    for x in items:
        k = key(x)
        if k not in d:
            d[k] = x
            continue
        e = d[k]
        for a in x["ag"]:
            f = [z for z in e["ag"] if z[0] == a[0]]
            if f:
                f[0][1] = a[1]
            else:
                e["ag"].append(a)
        e["tel"] = e["tel"] or x["tel"]
        e["ph"] = e["ph"] or x["ph"]
    return list(d.values())


def finalize(cur, prev):
    now = datetime.datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    pm = {p.get("key"): p for p in prev}
    first_run = not prev
    for x in cur:
        k = key(x)
        x["key"] = k
        x["id"] = int(hashlib.md5(k.encode()).hexdigest()[:8], 16)
        x["p"] = min(a[1] for a in x["ag"])
        o = pm.get(k)
        x["first"] = o["first"] if o else today
        hist = list((o or {}).get("hist", []))
        if not hist or hist[-1][1] != x["p"]:
            hist.append([today, x["p"]])
        x["hist"] = hist[-20:]
        x["old"] = 0
        if len(hist) > 1 and hist[-1][1] < hist[-2][1]:
            if (now - datetime.datetime.strptime(hist[-1][0], "%Y-%m-%d")).days <= 14:
                x["old"] = hist[-2][1]
        age = (now - datetime.datetime.strptime(x["first"], "%Y-%m-%d")).days
        x["nw"] = 1 if (not first_run and age <= 3) else 0
        x["c"] = PAL[x["id"] % len(PAL)]
    return cur


def main():
    cfg = json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))
    prev = []
    try:
        prev = json.load(open(OUT, encoding="utf-8")).get("listings", [])
    except Exception:
        pass
    cur, counts = [], {}
    for s in cfg["sources"]:
        if s.get("enabled", True) is False:
            continue
        print("SOURCE", s["name"], s["type"])
        try:
            got = {"drive": collect_drive, "doc": collect_doc}.get(s["type"], collect_site)(s)
        except Exception as e:  # noqa
            print("  ERROR", e)
            got = []
        print("  ->", len(got), "listings")
        counts[s["name"]] = len(got)
        cur += got
    # if a source returned nothing this time, keep what it had before (it may just be down)
    for p in prev:
        if counts.get(p.get("src"), 1) == 0:
            cur.append(p)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    merged = merge(cur)
    try:
        retired = json.load(open(RETIRED, encoding="utf-8"))
    except Exception:
        retired = {}
    present = {key(x) for x in merged}
    res = finalize([x for x in merged if key(x) not in retired], prev)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    keep = []
    for x in res:
        if (now - datetime.datetime.strptime(x["first"], "%Y-%m-%d")).days > MAX_AGE_DAYS:
            retired[x["key"]] = now.strftime("%Y-%m-%d")
            print("  retired (older than %d days):" % MAX_AGE_DAYS, x.get("t") or x["d"])
        else:
            keep.append(x)
    res = keep
    # forget retired entries that are no longer in the sources at all
    retired = {k: v for k, v in retired.items() if k in present}
    json.dump(retired, open(RETIRED, "w", encoding="utf-8"))
    localize(res)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    stamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    json.dump({"updated": stamp, "listings": res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("DONE", len(res), "listings")


if __name__ == "__main__":
    main()
