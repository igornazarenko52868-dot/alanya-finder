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
PAL = ["#0e5c7a,#14a3a0", "#1c6e5c,#7bc47f", "#254a73,#4b8fc4", "#5b3f8c,#b37fd1", "#7a4a1e,#e0a458", "#8a2f4a,#e2778f"]
IMG = (".jpg", ".jpeg", ".png", ".webp")
PRICE = re.compile(r"(\d{1,3}(?:[ .,]\d{3})+|\d{4,7})\s*(?:€|euro|eur)", re.I)
PRICE2 = re.compile(r"(?:€|euro|eur)\s*(\d{1,3}(?:[ .,]\d{3})+|\d{4,7})", re.I)


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


def parse_line(l, room):
    m = PRICE.search(l) or PRICE2.search(l)
    if not m:
        return None
    p = int(re.sub(r"\D", "", m.group(1)))
    if p < 5000 or p > 5_000_000:
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
            "o": "o" if re.search(r"sahibinden|owner|владел|хозяин", l, re.I) else "a"}


def mk(src, agency, tel, x, ref, url="", ph=None):
    return {"d": x["d"], "r": x["r"], "m": x["m"], "sea": 0, "fl": x["fl"], "age": 0, "aid": 0,
            "dd": x["dd"], "o": x["o"], "nw": 0, "old": 0, "ag": [[agency, x["p"]]], "tel": tel,
            "url": url, "ph": ph or [], "src": src, "ref": ref}


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


def collect_drive(s):
    out, seen = [], set()
    fid = re.search(r"/folders/([\w-]+)", s["url"]).group(1)

    def walk(f, depth):
        items = drive_list(f)
        time.sleep(0.4)
        print("  folder", f, "->", len(items), "entries")
        for eid, name, isf in items:
            if not isf or eid in seen or len(seen) > 300:
                continue
            seen.add(eid)
            x = parse_line(name, "")
            if x:
                photos = []
                for pid, pname, pf in drive_list(eid):
                    if not pf and pname.lower().endswith(IMG) and len(photos) < 3:
                        photos.append("https://drive.google.com/thumbnail?id=" + pid + "&sz=w800")
                time.sleep(0.4)
                out.append(mk(s["name"], s["name"], s.get("tel", ""), x, "drive:" + eid,
                              "https://drive.google.com/drive/folders/" + eid, photos))
            elif depth < 2:
                walk(eid, depth + 1)

    walk(fid, 0)
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
    res = finalize(merge(cur), prev)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    stamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    json.dump({"updated": stamp, "listings": res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("DONE", len(res), "listings")


if __name__ == "__main__":
    main()
