# app.py
from flask import Flask, jsonify, make_response
import requests, time, re
from bs4 import BeautifulSoup

app = Flask(__name__)

AIRPORT_PANEL_URL = "https://vitoria-airport.com.br/painel-de-voos"
CACHE_TTL = 60  # segundos
_cache = {"ts": 0, "rows": []}

HDR = {
    "User-Agent": "Mozilla/5.0 (compatible; VIXPanel/1.0; +https://example.local)"
}

def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())

def time_like(s):
    return bool(re.match(r"^\d{2}:\d{2}$", s or ""))

def parse_html(html):
    soup = BeautifulSoup(html, "lxml")
    rows = []

    # 1) tentar <table> com cabeçalhos típicos
    for table in soup.find_all("table"):
        heads = [norm(th.get_text()) for th in table.find_all("th")]
        h = " ".join(heads).lower()
        if ("hora" in h or "horário" in h) and ("dest" in h or "destino" in h):
            for tr in table.find_all("tr"):
                tds = [norm(td.get_text()) for td in tr.find_all("td")]
                if len(tds) < 3:
                    continue
                time_str = tds[0] if time_like(tds[0]) else ""
                if not time_str:
                    continue
                airline    = tds[1] if len(tds) > 1 else ""
                flight     = tds[2] if len(tds) > 2 else ""
                destination= tds[3] if len(tds) > 3 else ""
                gate       = tds[4] if len(tds) > 4 else ""
                estimate   = tds[5] if len(tds) > 5 else ""
                status     = tds[6] if len(tds) > 6 else estimate
                rows.append({
                    "time": time_str or "—",
                    "airline": airline or "—",
                    "flight": flight or "—",
                    "destination": destination or "—",
                    "gate": gate or "—",
                    "estimate": estimate or "—",
                    "status": (status or "scheduled").lower()
                })

    # 2) fallback: blocos com HH:MM no começo
    if not rows:
        for el in soup.select("div, li, article, section"):
            txt = norm(el.get_text())
            if time_like(txt[:5]):
                parts = txt.split(" ")
                time_str = parts[0]
                rows.append({
                    "time": time_str,
                    "airline": "—",
                    "flight": "—",
                    "destination": "—",
                    "gate": "—",
                    "estimate": "—",
                    "status": "scheduled"
                })
                if len(rows) > 40:
                    break

    # dedup + sort
    unique, seen = [], set()
    for r in rows:
        k = (r["time"], r["flight"], r["destination"])
        if k in seen: 
            continue
        seen.add(k)
        unique.append(r)

    def to_min(hhmm):
        try:
            h, m = hhmm.split(":")
            return int(h)*60 + int(m)
        except:
            return 9999
    unique.sort(key=lambda r: to_min(r["time"]))
    return unique

def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=30"
    return resp

@app.get("/api/v1/vix/departures")
def departures():
    now = time.time()
    if _cache["rows"] and now - _cache["ts"] < CACHE_TTL:
        return cors(make_response(jsonify(_cache["rows"]), 200))

    r = requests.get(AIRPORT_PANEL_URL, headers=HDR, timeout=15)
    if r.status_code != 200:
        return cors(make_response(jsonify({"error": f"source status {r.status_code}"}), 502))

    rows = parse_html(r.text)
    _cache["ts"] = now
    _cache["rows"] = rows
    return cors(make_response(jsonify(rows), 200))

@app.get("/")
def health():
    return cors(make_response(jsonify({"ok": True}), 200))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
