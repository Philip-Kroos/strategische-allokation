"""Download all raw data into data/raw.

Run from the repository root:  PYTHONPATH=src python -m saa.fetch

Every source is fetched independently. If one fails, the previous file stays
in place and the build continues with it; the log says which source failed.
The script exits with an error only if nothing at all could be refreshed.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# The other columns of fred_bundle.csv are historical (DM/USD before 1999,
# discontinued national CPI) and need no refresh.
FRED_LIVE = ["IR3TIB01DEM156N", "CP0000DEM086NEST"]
ECB = {
    "ecb_yc_aaa.csv": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y+SR_2Y+SR_5Y+SR_10Y",
    "ecb_euribor3m.csv": "FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA",
    "ecb_hicp.csv": "ICP/M.DE+U2.N.000000.4.INX",
    "ecb_eurusd.csv": "EXR/M.USD.EUR.SP00.E",
    "ecb_estr.csv": "EST/B.EU000A2X2A25.WT",
}
FRENCH = ["F-F_Research_Data_Factors_CSV.zip", "Europe_3_Factors_CSV.zip",
          "Emerging_5_Factors_CSV.zip", "Developed_ex_US_3_Factors_CSV.zip"]
YAHOO = ["IEAC.L", "EUNH.DE", "EXSA.DE", "SXR8.DE", "EEM", "IEMM.AS", "GC=F",
         "^GSPC", "^STOXX", "IWDA.AS", "IBCI.AS"]
SIBLIS = {"cape": "https://siblisresearch.com/data/cape-ratios-by-country/",
          "dy": "https://siblisresearch.com/data/global-dividend-yields/"}
ISHARES_GEO = {"eq_em": "https://www.ishares.com/us/products/239637/ishares-msci-emerging-markets-etf",
               "eq_eu": "https://www.ishares.com/us/products/264617/ishares-core-msci-europe-etf"}
MSCI = {"eq_us": "https://www.msci.com/documents/10199/255599/msci-usa-index-net.pdf",
        "eq_eu": "https://www.msci.com/documents/10199/255599/msci-europe-index-net.pdf",
        "eq_em": "https://www.msci.com/documents/10199/255599/msci-emerging-markets-index-gross.pdf"}
MONTHS_EN = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
ISHARES_IEAC = "https://www.ishares.com/uk/individual/en/products/251726/ishares-euro-corporate-bond-ucits-etf"


def get(url: str, attempts: int = 3, read_timeout: int = 90, **kw) -> requests.Response:
    for attempt in range(attempts):
        try:
            r = requests.get(url, headers=UA, timeout=(10, read_timeout), **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def save(name: str, content: bytes, must_contain: bytes | None = None, min_bytes: int = 200) -> None:
    if len(content) < min_bytes or (must_contain and must_contain not in content):
        raise ValueError(f"{name}: response does not look like data ({len(content)} bytes)")
    (RAW / name).write_bytes(content)


def fred() -> None:
    """Series that still update: German three-month rate and HICP Germany.
    FRED answers slowly from some cloud networks, so each series gets two
    short attempts; columns that fail keep their previous values. Missing
    months are bridged in the build with Euribor and ECB HICP data."""
    import pandas as pd
    path = RAW / "fred_bundle.csv"
    df = pd.read_csv(path, index_col=0) if path.exists() else pd.DataFrame()
    got = 0
    for sid in FRED_LIVE:
        try:
            r = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", attempts=1, read_timeout=45)
            new = pd.read_csv(io.BytesIO(r.content), index_col=0, na_values=".")[sid]
            df = df.reindex(df.index.union(new.index))
            df[sid] = new.combine_first(df[sid]) if sid in df else new
            got += 1
        except Exception as e:
            print(f"  fred {sid}: {str(e)[:100]}", flush=True)
    if not got:
        raise ValueError("fred: keine Reihe erreichbar")
    df.index.name = "observation_date"
    save("fred_bundle.csv", df.sort_index().to_csv().encode(), b"observation_date")


def ecb() -> None:
    for fname, key in ECB.items():
        url = f"https://data-api.ecb.europa.eu/service/data/{key}?format=csvdata&detail=dataonly"
        save(fname, get(url).content, b"OBS_VALUE")


def bundesbank() -> None:
    url = ("https://api.statistiken.bundesbank.de/rest/download/BBSIS/"
           "M.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?format=csv&lang=en")
    save("bbk_zst_10y.csv", get(url).content, b"BBSIS")


def french() -> None:
    for z in FRENCH:
        r = get(f"https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{z}")
        save(z, r.content, b"PK")


def github_datasets() -> None:
    save("shiller.csv", get("https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv").content, b"SP500")
    save("gold_monthly.csv", get("https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv").content, b"Price")


def _yahoo_chart(t: str) -> list:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(t)}?range=max&interval=1mo"
    res = get(url).json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    cur = res["meta"].get("currency", "")
    return [[t, datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"), a, c, cur]
            for ts, a, c in zip(res["timestamp"], adj, q["close"]) if a is not None]


def _yahoo_yf(t: str) -> list:
    """Same rows through the yfinance package, which handles Yahoo's cookie
    check. Bars are converted to UTC, as in the chart API."""
    import yfinance as yf
    tk = yf.Ticker(t)
    h = tk.history(period="max", interval="1mo", auto_adjust=False, actions=False)
    if h.empty:
        raise ValueError("leer")
    idx = h.index.tz_convert("UTC") if h.index.tz is not None else h.index
    cur = (tk.history_metadata or {}).get("currency", "")
    return [[t, d.strftime("%Y-%m-%d"), float(a), float(c), cur]
            for d, a, c in zip(idx, h["Adj Close"], h["Close"]) if a == a]


def yahoo() -> None:
    """Monthly bars, one row per bar, UTC date of the bar. Tickers that fail
    keep their previous rows."""
    old = {}
    if (RAW / "yahoo_monthly.csv").exists():
        with open(RAW / "yahoo_monthly.csv") as f:
            for row in list(csv.reader(f))[1:]:
                old.setdefault(row[0], []).append(row)
    rows, fresh = [], 0
    for t in YAHOO:
        got = None
        for fn in (_yahoo_yf, _yahoo_chart):
            try:
                got = fn(t)
                break
            except Exception as e:  # keep the other tickers
                print(f"  yahoo {t} ({fn.__name__}): {str(e)[:100]}", flush=True)
        if got:
            rows += got
            fresh += 1
        else:
            rows += old.get(t, [])
        time.sleep(1)
    if fresh < len(YAHOO) - 3:
        raise ValueError(f"yahoo: nur {fresh} von {len(YAHOO)} Kursreihen aktualisiert")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ticker", "date", "adjclose", "close", "currency"])
    w.writerows(rows)
    save("yahoo_monthly.csv", buf.getvalue().encode(), b"ticker")


def ishares_credit() -> None:
    """Weighted average yield to maturity and effective duration of the euro
    IG corporate bond ETF, written to data/raw/credit_ytm.json."""
    html = get(ISHARES_IEAC + "?switchLocale=y&siteEntryPassthrough=true").text
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"\s+", " ", txt)
    ytm = re.search(r"Weighted Av(?:g|erage)\.? (?:YTM|Yield to Maturity).{0,60}?(?<![\d/.])(\d{1,2}\.\d{1,3}) ?%", txt, re.I)
    dur = re.search(r"Effective Duration.{0,60}?(?<![\d/.])(\d{1,2}\.\d{1,3})(?![\d/])", txt, re.I)
    if not ytm or not 0.5 < float(ytm.group(1)) < 10:
        raise ValueError("ishares: yield to maturity not found")
    out = {"ytm": float(ytm.group(1)) / 100, "duration": float(dur.group(1)) if dur else None,
           "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    (RAW / "credit_ytm.json").write_text(json.dumps(out))


def _period(label: str) -> str:
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{4})", label.strip())
    if not m or m.group(1) not in MONTHS_EN:
        raise ValueError(f"siblis: unbekanntes Datum {label!r}")
    return f"{m.group(2)}-{MONTHS_EN[m.group(1)]:02d}"


def parse_siblis(html: str, measure: str) -> list[list]:
    """First table of a Siblis country page: market, current value, value a
    year earlier. Returns rows [measure, market, YYYY-MM, value]."""
    out, cur = [], None
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>|\s+", " ", c).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
        cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
        if len(cells) == 4 and cells[0].lower() == "market":
            cur = (_period(cells[1]), _period(cells[2]))
            continue
        if cur is None:
            continue
        if len(cells) != 4:
            break
        for per, raw in zip(cur, cells[1:3]):
            try:
                v = float(raw.replace("%", "").replace(",", ""))
            except ValueError:
                continue
            out.append([measure, cells[0], per, v / 100 if measure == "dy" else v])
    if len(out) < 20:
        raise ValueError(f"siblis {measure}: nur {len(out)} Werte gelesen")
    return out


def siblis() -> None:
    """Country CAPE (monthly) and dividend yields (quarterly) from the free
    tables of Siblis Research. New readings are added to data/raw/siblis.csv,
    so the file builds up its own history."""
    import pandas as pd
    rows = []
    for measure, url in SIBLIS.items():
        rows += parse_siblis(get(url).text, measure)
    new = pd.DataFrame(rows, columns=["measure", "market", "period", "value"])
    path = RAW / "siblis.csv"
    if path.exists():
        new = pd.concat([pd.read_csv(path), new])
    new = new.drop_duplicates(["measure", "market", "period"], keep="last").sort_values(["measure", "period", "market"])
    save("siblis.csv", new.to_csv(index=False).encode(), b"measure")


def parse_ishares_geo(html: str) -> dict:
    """Country breakdown of an iShares fund page (top ten countries)."""
    d = html.replace("&quot;", '"')
    j = d.find('"countryPercent"')
    if j < 0:
        raise ValueError("ishares: Länderaufteilung nicht gefunden")
    seg = d[j:j + 8000]

    def field(name):
        m = re.search(r'"name":"' + name + r'"[\s\S]*?"value":(\[[^\]]*\]|\d+)', seg)
        if not m:
            raise ValueError(f"ishares: Feld {name} fehlt")
        return json.loads(m.group(1))

    names, weights, asof = field("type"), field("fund"), str(field("asOf"))
    if len(names) != len(weights) or not 90 < sum(weights) < 110:
        raise ValueError("ishares: Länderaufteilung unplausibel")
    rename = {"Korea (South)": "South Korea"}
    w = {rename.get(n, n): float(x) for n, x in zip(names, weights)
         if n != "Other" and not n.startswith("Cash")}
    return {"asof": f"{asof[:4]}-{asof[4:6]}-{asof[6:]}", "weights": w}


def ishares_countries() -> None:
    out = {k: parse_ishares_geo(get(u).text) for k, u in ISHARES_GEO.items()}
    (RAW / "country_weights.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


def parse_msci(text: str) -> dict:
    """Dividend yield, P/E, forward P/E and P/B from an MSCI index factsheet."""
    t = re.sub(r"\s+", " ", text)
    d = re.search(r"FUNDAMENTALS \(([A-Z]{3}) (\d{1,2}),? (\d{4})\)", t, re.I)
    i = t.find("Div Yld")
    if not d or i < 0:
        raise ValueError("msci: Kennzahlen nicht gefunden")
    nums = re.findall(r"(?<![\d.])(\d{1,3}\.\d{1,2})(?![\d.])", t[i:i + 300])
    if len(nums) < 4:
        raise ValueError("msci: zu wenige Kennzahlen")
    dy, pe, pef, pb = (float(x) for x in nums[:4])
    if not (0.2 < dy < 10 and 3 < pe < 80):
        raise ValueError(f"msci: Werte unplausibel ({dy}, {pe})")
    month = MONTHS_EN[d.group(1).title()]
    return {"date": f"{d.group(3)}-{month:02d}-{int(d.group(2)):02d}", "dy": round(dy / 100, 5),
            "pe": pe, "pe_fwd": pef, "pb": pb}


def msci() -> None:
    """Index fundamentals from the monthly MSCI factsheets."""
    from pypdf import PdfReader
    out = {}
    for k, url in MSCI.items():
        try:
            pdf = PdfReader(io.BytesIO(get(url).content))
            out[k] = parse_msci(" ".join(p.extract_text() or "" for p in pdf.pages))
            print(f"  msci {k}: {out[k]}", flush=True)
        except Exception as e:
            print(f"  msci {k}: {str(e)[:120]}", flush=True)
    if not out:
        raise ValueError("msci: kein Factsheet lesbar")
    path = RAW / "msci_fundamentals.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    (RAW / "msci_fundamentals.json").write_text(json.dumps({**old, **out}, indent=1))


SOURCES = [("EZB", ecb), ("Bundesbank", bundesbank), ("French", french),
           ("Shiller/Gold", github_datasets), ("Yahoo", yahoo), ("iShares", ishares_credit),
           ("Siblis", siblis), ("Länderanteile", ishares_countries), ("MSCI", msci), ("FRED", fred)]


def main() -> int:
    ok, status = 0, {}
    for name, fn in SOURCES:
        t0 = time.time()
        try:
            fn()
            ok += 1
            status[name] = "ok"
            print(f"ok     {name} ({time.time() - t0:.0f} s)", flush=True)
        except Exception as e:
            status[name] = f"Fehler: {str(e)[:120]}"
            print(f"FEHLER {name} ({time.time() - t0:.0f} s): {e}", flush=True)
    stamp = {"fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "sources_ok": ok,
             "sources": len(SOURCES), "status": status}
    (RAW / "fetch_log.json").write_text(json.dumps(stamp))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
