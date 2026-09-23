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

FRED_IDS = [
    "IRLTLT01DEM156N", "IR3TIB01DEM156N", "EXGEUS", "EXUSEU", "DEUCPIALLMINMEI",
    "CP0000DEM086NEST", "CP0000EZ19M086NEST", "CPIAUCSL", "GS10", "TB3MS", "USREC", "IRLTLT01EZM156N",
]
ECB = {
    "ecb_yc_aaa.csv": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y+SR_2Y+SR_5Y+SR_10Y",
    "ecb_euribor3m.csv": "FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA",
    "ecb_hicp.csv": "ICP/M.DE+U2.N.000000.4.INX",
    "ecb_eurusd.csv": "EXR/M.USD.EUR.SP00.E",
}
FRENCH = ["F-F_Research_Data_Factors_CSV.zip", "Europe_3_Factors_CSV.zip",
          "Emerging_5_Factors_CSV.zip", "Developed_ex_US_3_Factors_CSV.zip"]
YAHOO = ["IEAC.L", "EUNH.DE", "EXSA.DE", "SXR8.DE", "EEM", "IEMM.AS", "GC=F",
         "^GSPC", "^STOXX", "IWDA.AS", "IBCI.AS"]
ISHARES_IEAC = "https://www.ishares.com/uk/individual/en/products/251726/ishares-euro-corporate-bond-ucits-etf"


def get(url: str, **kw) -> requests.Response:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def save(name: str, content: bytes, must_contain: bytes | None = None, min_bytes: int = 200) -> None:
    if len(content) < min_bytes or (must_contain and must_contain not in content):
        raise ValueError(f"{name}: response does not look like data ({len(content)} bytes)")
    (RAW / name).write_bytes(content)


def fred() -> None:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + ",".join(FRED_IDS)
    save("fred_bundle.csv", get(url).content, b"observation_date")
    save("fred_estr.csv", get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=ECBESTRVOLWGTTRMDMNRT").content,
         b"observation_date")


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


def yahoo() -> None:
    """Monthly bars from the chart API, one row per bar, UTC date of the bar."""
    rows = []
    for t in YAHOO:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(t)}?range=max&interval=1mo"
        try:
            res = get(url).json()["chart"]["result"][0]
        except Exception as e:  # keep the other tickers
            print(f"  yahoo {t}: {e}")
            continue
        q = res["indicators"]["quote"][0]
        adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
        cur = res["meta"].get("currency", "")
        for ts, a, c in zip(res["timestamp"], adj, q["close"]):
            if a is None:
                continue
            d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append([t, d, a, c, cur])
        time.sleep(1)
    if len({r[0] for r in rows}) < len(YAHOO) - 3:
        raise ValueError("yahoo: too many tickers missing")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ticker", "date", "adjclose", "close", "currency"])
    w.writerows(rows)
    save("yahoo_monthly.csv", buf.getvalue().encode(), b"ticker")


def ishares_credit() -> None:
    """Weighted average yield to maturity and effective duration of the euro
    IG corporate bond ETF, written to data/raw/credit_ytm.json."""
    html = get(ISHARES_IEAC).text
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"\s+", " ", txt)
    ytm = re.search(r"Weighted Avg(?:erage)? YTM(?: as of)? [0-9A-Za-z/]+ ([0-9]+\.[0-9]+)%", txt)
    dur = re.search(r"Effective Duration(?: as of)? [0-9A-Za-z/]+ ([0-9]+\.[0-9]+)", txt)
    if not ytm:
        raise ValueError("ishares: yield to maturity not found")
    out = {"ytm": float(ytm.group(1)) / 100, "duration": float(dur.group(1)) if dur else None,
           "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    (RAW / "credit_ytm.json").write_text(json.dumps(out))


SOURCES = [("FRED", fred), ("EZB", ecb), ("Bundesbank", bundesbank), ("French", french),
           ("Shiller/Gold", github_datasets), ("Yahoo", yahoo), ("iShares", ishares_credit)]


def main() -> int:
    ok = 0
    for name, fn in SOURCES:
        try:
            fn()
            ok += 1
            print(f"ok     {name}")
        except Exception as e:
            print(f"FEHLER {name}: {e}")
    stamp = {"fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "sources_ok": ok, "sources": len(SOURCES)}
    (RAW / "fetch_log.json").write_text(json.dumps(stamp))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
