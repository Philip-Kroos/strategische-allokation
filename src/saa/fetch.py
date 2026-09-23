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
            r = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", attempts=2, read_timeout=40)
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


SOURCES = [("EZB", ecb), ("Bundesbank", bundesbank), ("French", french),
           ("Shiller/Gold", github_datasets), ("Yahoo", yahoo), ("iShares", ishares_credit), ("FRED", fred)]


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
