"""Kurzes Arbeitspapier aus dem Modelloutput.

    python paper/build_paper.py  ->  paper/paper.html, im Browser als PDF drucken (A4)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
M = json.loads((ROOT / "docs" / "data" / "model.json").read_text())
EXT = json.loads((ROOT / "paper" / "positions.json").read_text())

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def pct(x, d=1, sign=False):
    s = f"{x * 100:+.{d}f}" if sign else f"{x * 100:.{d}f}"
    return s.replace("-", "−").replace(".", ",") + " %"


def num(x, d=2):
    return f"{x:.{d}f}".replace("-", "−").replace(".", ",")


def month(ym):
    y, m = ym.split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


A = {a["key"]: a for a in M["assets"]}
S = M["signals"]
BT, V = S["backtest"], S["variants"]
CL = S["classes"]
corr = M["stock_bond_corr"]
corr_now = corr[-1][1]
cov_pos = M["cov"]["pos"]
K = [a["key"] for a in M["assets"]]


# ------------------------------------------------------------------ charts
def svg_returns() -> str:
    order = ["cash", "bund", "credit", "eq_eu", "eq_us", "eq_em", "gold"]
    short = {"cash": "Geldmarkt", "bund": "Bundesanleihen", "credit": "Unternehmensanl. IG",
             "eq_eu": "Aktien Europa", "eq_us": "Aktien USA", "eq_em": "Schwellenländer", "gold": "Gold"}
    W, H, L, R, T, rh = 330, 196, 112, 14, 22, 23
    x = lambda v: L + (v / 0.12) * (W - L - R)
    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    for t in (0, 0.04, 0.08, 0.12):
        out.append(f'<line x1="{x(t):.1f}" y1="{T - 6}" x2="{x(t):.1f}" y2="{T + rh * 7}" class="grid"/>')
        out.append(f'<text x="{x(t):.1f}" y="{T + rh * 7 + 12}" class="ax" text-anchor="middle">{int(t * 100)} %</text>')
    for i, k in enumerate(order):
        a = A[k]
        y = T + i * rh + rh / 2
        out.append(f'<text x="{L - 6}" y="{y + 3.5}" class="lab" text-anchor="end">{short[k]}</text>')
        out.append(f'<rect x="{x(0):.1f}" y="{y - 6}" width="{x(a["expected"]) - x(0):.1f}" height="12" class="bar"/>')
        out.append(f'<circle cx="{x(a["hist_geo"]):.1f}" cy="{y}" r="3.6" class="hist"/>')
        clear = abs(a["expected"] - a["hist_geo"]) > 0.015 or a["expected"] > a["hist_geo"]
        lx = x(a["expected"]) + 4 if clear else x(max(a["expected"], a["hist_geo"])) + 6
        out.append(f'<text x="{lx:.1f}" y="{y + 3.5}" class="val">{pct(a["expected"])}</text>')
    out.append(f'<rect x="{L}" y="4" width="10" height="8" class="bar"/><text x="{L + 14}" y="11.5" class="ax">Erwartet, 10 Jahre</text>')
    out.append(f'<circle cx="{L + 112}" cy="8" r="3.6" class="hist"/><text x="{L + 119}" y="11.5" class="ax">Realisiert {M["meta"]["sample"][0][:4]}–{M["meta"]["sample"][1][:4]}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_corr() -> str:
    W, H, L, R, T, B = 330, 196, 30, 30, 12, 22
    n = len(corr)
    x = lambda i: L + i / (n - 1) * (W - L - R)
    y = lambda v: T + (0.8 - v) / 1.6 * (H - T - B)
    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    # shade positive-correlation months
    i = 0
    while i < n:
        if corr[i][1] > 0:
            j = i
            while j + 1 < n and corr[j + 1][1] > 0:
                j += 1
            out.append(f'<rect x="{x(i):.1f}" y="{T}" width="{max(x(j) - x(i), 0.8):.1f}" height="{H - T - B}" class="shade"/>')
            i = j + 1
        else:
            i += 1
    for v in (-0.8, -0.4, 0, 0.4, 0.8):
        out.append(f'<line x1="{L}" y1="{y(v):.1f}" x2="{W - R}" y2="{y(v):.1f}" class="{"zero" if v == 0 else "grid"}"/>')
        out.append(f'<text x="{L - 4}" y="{y(v) + 3:.1f}" class="ax" text-anchor="end">{num(v, 1)}</text>')
    for yr in (1995, 2000, 2005, 2010, 2015, 2020, 2025):
        idx = next((k for k, (d, _) in enumerate(corr) if d.startswith(str(yr))), None)
        if idx is not None:
            out.append(f'<text x="{x(idx):.1f}" y="{H - 8}" class="ax" text-anchor="middle">{yr}</text>')
    pts = " ".join(f"{x(k):.1f},{y(v):.1f}" for k, (_, v) in enumerate(corr))
    out.append(f'<polyline points="{pts}" class="line"/>')
    out.append(f'<circle cx="{x(n - 1):.1f}" cy="{y(corr_now):.1f}" r="2.8" class="dot"/>')
    out.append(f'<text x="{x(n - 1) + 4:.1f}" y="{y(corr_now) + 3:.1f}" class="val">{num(corr_now)}</text>')
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------------------------ positioning
rows = {r[0]: r for r in EXT["rows"]}
names = {a["key"]: a["name"] for a in M["assets"]}
w_ref = np.array([S["ref"][k] for k in K])


def weights(col):
    return np.array([float(rows[names[k]][col].replace(" %", "").replace("−", "-")) / 100 for k in K])


w_str, w_tac = weights(4), weights(5)
mu = np.array([A[k]["expected"] for k in K])
C = np.array(cov_pos) * 12 if np.array(cov_pos)[3][3] < 0.01 else np.array(cov_pos)
stat = lambda w: (float(w @ mu), float(np.sqrt(w @ C @ w)))
er_ref, vol_ref = stat(w_ref)
er_tac, vol_tac = stat(w_tac / w_tac.sum())

SHORT = {"bund": "Bundesanleihen", "credit": "Euro-Unternehmensanleihen", "eq_eu": "Aktien Europa",
         "eq_us": "Aktien USA", "eq_em": "Aktien Schwellenländer", "gold": "Gold", "cash": "Geldmarkt"}
REGION = {"eq_eu": "Europa", "eq_us": "USA", "eq_em": "Schwellenländer"}
EQ = ["eq_eu", "eq_us", "eq_em"]
tr = {k: CL[k]["trend"] for k in K}
act = {k: w_tac[i] - S["ref"][k] for i, k in enumerate(K)}
tilt = {k: w_tac[i] - w_str[i] for i, k in enumerate(K)}
pos_regime = corr_now > 0


def join(xs):
    xs = list(xs)
    return "" if not xs else xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " und " + xs[-1]


def trend_word(k):
    t = tr[k]
    return "Trend positiv." if t > 0.2 else "Trend negativ." if t < -0.2 else "Trend ohne klare Richtung."


def since_regime():
    i = len(corr) - 1
    while i > 0 and (corr[i - 1][1] > 0) == pos_regime:
        i -= 1
    return corr[i][0]


best_eq = max(EQ, key=lambda k: A[k]["expected"])
worst_eq = min(EQ, key=lambda k: A[k]["expected"])
top = A["eq_em"]["detail"].get("top_countries") or []
spread = CL["credit"]["detail"]["spread"]
why = {
    "bund": f"Startrendite {pct(A['bund']['expected'])}, real {pct(CL['bund']['detail']['real_yield'])}. {trend_word('bund')}"
            + (" Absicherung schwächer." if pos_regime else " Sichert Aktienrisiken ab."),
    "credit": f"Rendite {pct(A['credit']['expected'])} bei halber Duration. "
              + ("Spreads eng, Gesamtrendite trotzdem über Bunds." if spread < CL["credit"]["detail"]["normal"]
                 else "Spreads über dem Normalniveau."),
    "eq_eu": f"CAPE {num(A['eq_eu']['detail']['cape'], 1)}, "
             + ("höchste erwartete Rendite. " if best_eq == "eq_eu" else f"erwartet {pct(A['eq_eu']['expected'])}. ")
             + trend_word("eq_eu"),
    "eq_us": f"CAPE {num(A['eq_us']['detail']['cape'], 1)}, erwartet {pct(A['eq_us']['expected'])}. " + trend_word("eq_us"),
    "eq_em": (f"{top[0][0]} und {top[1][0]} machen {pct(top[0][1] + top[1][1], 0)} des Index aus. " if len(top) > 1 else "")
             + trend_word("eq_em"),
    "gold": f"Real am {int(round(CL['gold']['detail']['pct'] * 100))}. Perzentil seit 1975. " + trend_word("gold"),
    "cash": "Restgröße.",
}
over = [SHORT[k] for k in sorted(K, key=lambda k: -act[k]) if k != "cash" and act[k] > 0.015]
under = [SHORT[k] for k in sorted(K, key=lambda k: act[k]) if k != "cash" and act[k] < -0.015]
kp4 = "Positionierung:</b> " + (f"{join(over)} über" if over else "")
kp4 += (", " if over and under else "") + (f"{join(under)} unter dem Referenzportfolio." if under else " dem Referenzportfolio.")
if not over and not under:
    kp4 = "Positionierung:</b> Nahe am Referenzportfolio."
risk_word = "ähnlichem" if abs(vol_tac - vol_ref) < 0.01 else ("etwas höherem" if vol_tac > vol_ref else "etwas niedrigerem")
kp4 += f" Erwartete Rendite {pct(er_tac)} statt {pct(er_ref)} p. a. bei {risk_word} Risiko."

gap = A[best_eq]["expected"] - A[worst_eq]["expected"]
cheap_explains = A[worst_eq]["detail"]["cape"] > A[best_eq]["detail"]["cape"]
all_below = all(A[k]["expected"] < A[k]["hist_geo"] for k in EQ)
kp1_head = ("Die Renditeerwartungen liegen unter der Vergangenheit und sind ungleich verteilt." if all_below and gap > 0.01
            else "Die Renditeerwartungen sind ungleich verteilt." if gap > 0.01
            else "Die Renditeerwartungen liegen unter der Vergangenheit." if all_below
            else "Die Renditeerwartungen je Region liegen nah beieinander.")
kp1 = (f"<b>{kp1_head}</b> Für {SHORT[best_eq]} erwarten wir {pct(A[best_eq]['expected'])} p. a. in Euro über zehn Jahre, "
       f"für {SHORT[worst_eq]} {pct(A[worst_eq]['expected'])}.")
if cheap_explains and gap > 0.01:
    kp1 += (f" Der Abstand kommt vor allem aus der Bewertung: CAPE {num(A[worst_eq]['detail']['cape'], 1)} "
            f"gegenüber {num(A[best_eq]['detail']['cape'], 1)}.")

vb, vt = V["bewertung"], V["trend"]
if vb["excess_pa"] < 0 < vt["excess_pa"]:
    kp2 = (f"<b>Bewertung taugt nicht zum Timing.</b> Als Monatssignal hätte sie seit {BT['start'][:4]} {pct(-vb['excess_pa'])} p. a. gekostet. "
           f"Das Trendsignal hat {pct(vt['excess_pa'])} p. a. gebracht (t-Wert {num(vt['t_stat'], 1)}). "
           "Bewertung steuert deshalb die strategische Quote, Trend die taktische Abweichung.")
else:
    kp2 = (f"<b>Bewertung und Trend wirken auf verschiedenen Horizonten.</b> Als Monatssignal brachte Bewertung seit {BT['start'][:4]} "
           f"{pct(vb['excess_pa'], 1, True)} p. a., Trend {pct(vt['excess_pa'], 1, True)} p. a. (t-Wert {num(vt['t_stat'], 1)}). "
           "Bewertung steuert die strategische Quote, Trend die taktische Abweichung.")

since = since_regime()
if pos_regime:
    kp3 = (f"<b>Anleihen sichern schwächer ab.</b> Aktien und Bundesanleihen laufen seit {month(since)} gleichgerichtet, "
           f"die 36-Monats-Korrelation liegt bei {num(corr_now)}. Wir rechnen mit den Korrelationen dieses Inflationsregimes.")
    s3_title = "Das Korrelationsregime hat gedreht"
    s3_hist = f"So war es in den 1990er Jahren, und so ist es wieder seit {month(since)} (Abbildung 2)."
    s3_use = "Für die aktuelle Allokation rechnen wir mit dem Inflationsregime."
    s3_cons = (f"Die Konsequenz: Bundesanleihen verdienen ihren Platz über die Rendite, weniger über die Absicherung. "
               f"Euro-Unternehmensanleihen bieten {pct(A['credit']['expected'] - A['bund']['expected'])} mehr bei rund halber Duration.")
    s5_regime = ("<b>Regime.</b> Kippt die Korrelation zurück ins Negative, etwa in einer Rezession mit fallender Inflation, "
                 "gewinnen Bundesanleihen an Wert. Dann spricht mehr für längere Laufzeiten.")
else:
    kp3 = (f"<b>Anleihen sichern wieder ab.</b> Aktien und Bundesanleihen laufen seit {month(since)} gegenläufig, "
           f"die 36-Monats-Korrelation liegt bei {num(corr_now)}. Wir rechnen mit den Korrelationen dieses Wachstumsregimes.")
    s3_title = "Anleihen sichern wieder ab"
    s3_hist = f"Von 2022 an liefen beide gleichgerichtet. Seit {month(since)} ist die Korrelation wieder negativ (Abbildung 2)."
    s3_use = "Für die aktuelle Allokation rechnen wir mit dem Wachstumsregime."
    s3_cons = (f"Die Konsequenz: Bundesanleihen dämpfen Aktienverluste wieder. "
               f"Euro-Unternehmensanleihen bieten {pct(A['credit']['expected'] - A['bund']['expected'])} mehr Rendite, sichern aber weniger ab.")
    s5_regime = ("<b>Regime.</b> Kehrt die Inflation zurück, laufen Aktien und Anleihen wieder gleichgerichtet. "
                 "Dann verlieren lange Laufzeiten ihre Schutzwirkung.")

# paragraph after the positioning table
a_sorted = sorted([k for k in K if k != "cash"], key=lambda k: act[k])
big_over, big_under = a_sorted[-1], a_sorted[0]
s4 = []
if act[big_over] > 0.015 and act[big_under] < -0.015:
    s4.append(f"Die größte Verschiebung ist {SHORT[big_over]} ({pct(act[big_over], 0, True)}) gegen {SHORT[big_under]} "
              f"({pct(act[big_under], 0, True)}).")
def pts(x):
    n = int(round(abs(x) * 100))
    return f"{n} Punkt" if n == 1 else f"{n} Punkte"


ups = [f"{SHORT[k]} um {pts(tilt[k])}" for k in sorted(K, key=lambda k: -tilt[k]) if k != "cash" and tilt[k] >= 0.015]
dns = [f"{SHORT[k]} um {pts(tilt[k])}" for k in sorted(K, key=lambda k: tilt[k]) if k != "cash" and tilt[k] <= -0.015]
if ups or dns:
    s4.append("Der Trend " + " und ".join(x for x in [f"erhöht {join(ups)}" if ups else "", f"senkt {join(dns)}" if dns else ""] if x) + ".")
if CL["gold"]["val"] < -0.5 and tr["gold"] > 0.5:
    s4.append("Bei Gold spricht die Bewertung dagegen, der Trend dafür. Der Trend hält eine kleine Position, statt sie ganz abzubauen.")
s4 = " ".join(s4)

usd = lambda w: float(w[K.index("eq_us")] + w[K.index("gold")])
s5_usd = (f"<b>Dollar.</b> US-Aktien und Gold sind ungesichert. Ein um 10 % stärkerer Euro kostet ein Depot mit 45 % Dollar-Anlagen rund 4,5 %. "
          f"Das Modellportfolio hält {pct(usd(w_tac), 0)} in Dollar-Anlagen, das Referenzportfolio {pct(usd(w_ref), 0)}.")
CUR = M.get("currency")
if CUR:
    _r0, _r1 = CUR["rows"][0], CUR["rows"][-1]
    s5_usd += f" Eine Absicherung kostet heute {pct(CUR['carry_now'])} p. a. auf den gesicherten Teil"
    s5_usd += (" und hätte in der Finanzkrise nicht geholfen." if _r1["episodes"]["Finanzkrise"] < _r0["episodes"]["Finanzkrise"] else ".")

bt_up = BT["excess_pa"] > 0
s2_trend = (f"Das Trendsignal misst die Überrendite der letzten zwölf Monate über Geldmarkt, geteilt durch die Schwankung. "
            f"Es hat die Rendite um {pct(abs(BT['excess_pa']))} p. a. {'erhöht' if bt_up else 'gesenkt'}, bei einem Tracking Error von {pct(BT['te'])}. "
            f"In {int(round(BT['hit_years'] * 100))} % der Jahre lag das Portfolio mit Trend vor der Referenz, der maximale Verlust "
            f"{'sank' if BT['tactical']['mdd'] > BT['reference']['mdd'] else 'stieg'} von {pct(BT['reference']['mdd'])} auf {pct(BT['tactical']['mdd'])}.")
RB = S.get("robustness") or []
if RB:
    npos = sum(1 for r in RB if r["excess_pa"] > 0)
    ts = [r["t_stat"] for r in RB]
    s2_trend += (f" Das Ergebnis hält in {npos} von {len(RB)} Varianten des Tests: anderer Rückblick, andere Kosten, halbe und doppelte "
                 f"Verschiebung, spätere Umsetzung und beide Hälften der Stichprobe (t-Werte {num(min(ts), 1)} bis {num(max(ts), 1)}).")
y0, y1 = M["meta"]["sample"][0][:4], M["meta"]["sample"][1][:4]
s1_last = (f"Das Ergebnis liegt für {'jede Aktienregion' if all_below else 'die meisten Aktienregionen'} unter der Rendite seit {y0} (Abbildung 1). "
           "Die hohen Renditen der Vergangenheit kamen zu einem großen Teil aus steigenden Bewertungen. Das lässt sich nicht fortschreiben. "
           "Fremdwährungen rechnen wir ungesichert und ohne erwartete Wechselkursänderung.")
cape_fit, bond_fit = M["cape"], M["bonds"]

pos_rows = "".join(
    f"<tr><td>{names[k]}</td><td>{pct(S['ref'][k], 0)}</td><td>{pct(w_str[i], 0)}</td>"
    f"<td><b>{pct(w_tac[i], 0)}</b></td><td class='{'pos' if w_tac[i] - S['ref'][k] > 0.005 else 'neg' if w_tac[i] - S['ref'][k] < -0.005 else ''}'>"
    f"{pct(w_tac[i] - S['ref'][k], 0, True) if abs(w_tac[i] - S['ref'][k]) > 0.005 else '±0 %'}</td><td class='why'>{why[k]}</td></tr>"
    for i, k in enumerate(K) if k != "cash")

var_rows = "".join(
    f"<tr><td>{l}</td><td class='{'neg' if v['excess_pa'] < 0 else 'pos'}'>{pct(v['excess_pa'], 1, True)}</td>"
    f"<td>{num(v['ir'])}</td><td>{num(v['t_stat'], 1)}</td></tr>"
    for l, v in (("Trend", V["trend"]), ("Bewertung", V["bewertung"]), ("Beide je zur Hälfte", V["kombiniert"])))

eu, us, em = A["eq_eu"], A["eq_us"], A["eq_em"]
d = lambda a: a["detail"]
as_of = M["meta"]["as_of"]
stand = f"{MONTHS[int(as_of[5:7]) - 1]} {as_of[:4]}"
sig_month = month(S["as_of"])
bt_span = f"{month(BT['start'])} bis {month(BT['end'])}"
n_pos = sum(1 for _, v in corr if v > 0)


def regime_corr(reg, a="eq_eu", b="bund"):
    c = np.array(M["cov"][reg]); i, j = K.index(a), K.index(b)
    return c[i][j] / np.sqrt(c[i][i] * c[j][j])
URL = "philip-kroos.github.io/strategische-allokation"
_tf = ROOT / "docs" / "data" / "track.json"
_tr = json.loads(_tf.read_text()) if _tf.exists() else {}
if _tr.get("positions"):
    _d = _tr["start"]
    track_line = (f"Seit dem {int(_d[8:])}. {MONTHS[int(_d[5:7]) - 1]} {_d[:4]} speichert das Modell jede Positionierung unveränderlich; "
                  "die Wertentwicklung dieses Protokolls steht auf der Seite. ")
else:
    track_line = ""

HTML = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<title>Bewertung für die Strategie, Trend für die Taktik</title>
<meta name="author" content="Philip Kroos">
<style>
@font-face{{font-family:"SS4";src:url("fonts/source-serif-4-latin-400-normal.woff2")}}
@font-face{{font-family:"SS4";font-style:italic;src:url("fonts/source-serif-4-latin-400-italic.woff2")}}
@font-face{{font-family:"SS4";font-weight:600;src:url("fonts/source-serif-4-latin-600-normal.woff2")}}
@font-face{{font-family:"SS4";font-weight:700;src:url("fonts/source-serif-4-latin-700-normal.woff2")}}
@font-face{{font-family:"SS3";src:url("fonts/source-sans-3-latin-400-normal.woff2")}}
@font-face{{font-family:"SS3";font-weight:600;src:url("fonts/source-sans-3-latin-600-normal.woff2")}}
@page{{size:A4;margin:15mm 16mm 14mm 16mm}}
:root{{--ink:#1b1f24;--mute:#5d6570;--rule:#c9cdd2;--acc:#1f4e79;--pos:#1e7a46;--neg:#a8322d;--shade:#eef1f5}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:"SS4",Georgia,serif;font-size:9.3pt;line-height:1.38;color:var(--ink);hyphens:auto;-webkit-hyphens:auto}}
.sans{{font-family:"SS3",Helvetica,sans-serif}}
header{{border-bottom:1.2pt solid var(--ink);padding-bottom:5pt;margin-bottom:8pt}}
.kicker{{font-family:"SS3";font-size:7.6pt;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);display:flex;justify-content:space-between}}
h1{{font-size:19pt;line-height:1.15;margin:4pt 0 2pt;font-weight:600;letter-spacing:-.01em}}
.sub{{font-size:10.5pt;color:var(--mute);font-style:italic;margin:0}}
h2{{font-family:"SS3";font-size:10pt;font-weight:600;margin:9pt 0 3pt;color:var(--acc)}}
h2 .no{{color:var(--mute);font-weight:400;margin-right:4pt}}
p{{margin:0 0 4.5pt;text-align:left}}
.key{{background:var(--shade);padding:6pt 9pt 4pt;margin:0 0 6pt;border-left:2.2pt solid var(--acc)}}
.key .t{{font-family:"SS3";font-weight:600;font-size:8pt;text-transform:uppercase;letter-spacing:.06em;color:var(--acc);margin-bottom:2pt}}
.key ol{{margin:0;padding-left:13pt}} .key li{{margin-bottom:2.5pt}}
.fig{{float:right;width:47%;margin:1pt 0 4pt 12pt}} .side{{float:right;width:50%;margin:1pt 0 4pt 12pt}} h2{{clear:both}} footer{{clear:both}}
figure{{margin:2pt 0 6pt}}
figcaption,.cap{{font-family:"SS3";font-size:7.8pt;color:var(--mute);line-height:1.3;margin-bottom:2pt}}
figcaption b,.cap b{{color:var(--ink)}}
svg{{width:100%;height:auto;font-family:"SS3"}}
svg .grid{{stroke:#e2e5e9;stroke-width:.6}} svg .zero{{stroke:#8a9098;stroke-width:.7}}
svg .ax{{font-size:7px;fill:#6b727b}} svg .lab{{font-size:7.6px;fill:#1b1f24}} svg .val{{font-size:7.2px;fill:#1b1f24;font-weight:600}}
svg .bar{{fill:#1f4e79}} svg .hist{{fill:#fff;stroke:#a8322d;stroke-width:1.4}}
svg .shade{{fill:#f3e3e2}} svg .line{{fill:none;stroke:#1f4e79;stroke-width:1.1}} svg .dot{{fill:#1f4e79}}
table{{width:100%;border-collapse:collapse;font-family:"SS3";font-size:8pt;margin:2pt 0 4pt}}
th{{font-weight:400;color:var(--mute);text-align:right;border-bottom:.8pt solid var(--ink);padding:2pt 4pt}}
td{{text-align:right;padding:2.2pt 4pt;border-bottom:.4pt solid var(--rule);font-variant-numeric:tabular-nums}}
th:first-child,td:first-child{{text-align:left;padding-left:0}}
td.why,th.why{{text-align:left;color:#3a4048;font-size:7.6pt}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
.note{{font-family:"SS3";font-size:7.4pt;color:var(--mute);line-height:1.35}}
footer{{margin-top:8pt;border-top:.6pt solid var(--rule);padding-top:4pt}}
.brk{{break-before:page}}
</style></head><body>
<header>
  <div class="kicker"><span>Arbeitspapier · Asset-Allokation</span><span>Stand {stand}</span></div>
  <h1>Bewertung für die Strategie, Trend für die Taktik</h1>
  <p class="sub">Renditeerwartungen, Korrelationsregime und Positionierung für den Euro-Anleger</p>
  <div class="kicker" style="margin-top:4pt"><span>Philip Kroos</span><span>{URL}</span></div>
</header>

<div class="key"><div class="t">Kernaussagen</div><ol>
<li>{kp1}</li>
<li>{kp2}</li>
<li>{kp3}</li>
<li><b>{kp4}</li>
</ol></div>

<h2><span class="no">1</span>Was die nächsten zehn Jahre bringen können</h2>
<figure class="fig"><figcaption><b>Abbildung 1</b> Erwartete Rendite p. a. über zehn Jahre und realisierte Rendite {y0} bis {y1}, nominal in EUR</figcaption>{svg_returns()}</figure>
<p>Für Anleihen ist die heutige Rendite der beste Schätzer der Rendite des nächsten Jahrzehnts. Bei zehnjährigen Bundesanleihen erklärt sie seit 1972 rund {num(bond_fit['r2'] * 100, 0)} % der Streuung der Folgerenditen. Heute sind das {pct(A['bund']['expected'])}, bei Euro-Unternehmensanleihen nach erwarteten Ausfällen {pct(A['credit']['expected'])}.</p>
<p>Für Aktien mitteln wir zwei Verfahren. Das erste regressiert die reale Rendite der Folgedekade auf die Ertragsrendite 1/CAPE (Shiller-Daten 1881 bis 2013, R² {num(cape_fit['r2'])}, außerhalb der Stichprobe {num(cape_fit['oos_r2'])}). Das zweite addiert Dividendenrendite, Nettorückkäufe und reales Gewinnwachstum und zieht eine teilweise Rückkehr der Bewertung zum fairen Niveau ab. Für die USA ergeben beide {pct(d(us)['m1_regression_real'])} und {pct(d(us)['m2_building_blocks_real'])} real, für Europa {pct(d(eu)['m1_regression_real'])} und {pct(d(eu)['m2_building_blocks_real'])}.</p>
<p>{s1_last}</p>

<h2><span class="no">2</span>Warum Bewertung kein Timing-Signal ist</h2>
<div class="side">
<div class="cap"><b>Tabelle 1</b> Mehrrendite gegenüber dem Referenzportfolio, {bt_span}, nach Kosten</div>
<table><thead><tr><th>Monatssignal</th><th>p. a.</th><th>Information Ratio</th><th>t-Wert</th></tr></thead><tbody>{var_rows}</tbody></table>
<p class="note">Referenzportfolio: Geldmarkt 5 %, Bundesanleihen 20 %, Unternehmensanleihen 15 %, Aktien Europa 22 %, USA 23 %, Schwellenländer 8 %, Gold 7 %. Das Bewertungssignal deckt Aktien USA, Bundesanleihen und Gold ab, für die lange Historien ohne Blick in die Zukunft vorliegen.</p>
</div>
<p>Bewertung sagt viel über das nächste Jahrzehnt und wenig über den nächsten Monat. Teure Märkte werden oft über Jahre noch teurer, der US-Markt ab 1995 und wieder ab 2013. Wer monatlich nach Bewertung umschichtet, steigt zu früh aus.</p>
<p>Wir haben das getestet. Ein Referenzportfolio wird jeden Monat um bis zu fünf Prozentpunkte je Anlageklasse verschoben, nach Signalen, die nur Daten des Vormonats nutzen. Faire Werte und Perzentile sind zu jedem Zeitpunkt nur aus der bis dahin bekannten Historie geschätzt. Kosten: 10 Basispunkte je Umschichtung. Zeitraum {bt_span}.</p>
<p>{s2_trend}</p>
<p>{'Die Folgerung ist eine Arbeitsteilung.' if vb['excess_pa'] < 0 < vt['excess_pa'] else 'Das Modell hält an der Arbeitsteilung fest.'} Bewertung geht über die erwarteten Renditen in die strategische Quote ein. Trend verschiebt diese Quote taktisch. Der Zwölfmonatszeitraum ist der übliche Standard und nicht auf diese Daten optimiert.</p>

<h2><span class="no">3</span>{s3_title}</h2>
<figure class="fig"><figcaption><b>Abbildung 2</b> Rollierende 36-Monats-Korrelation, Aktien Europa gegenüber Bundesanleihen 10 J., Monatsrenditen in EUR. Rot: positive Korrelation ({n_pos} von {len(corr)} Monaten)</figcaption>{svg_corr()}</figure>
<p>Die Absicherung durch Staatsanleihen hängt davon ab, welche Schocks die Märkte treiben. Bei Wachstumsschocks fallen Aktien und Zinsen gemeinsam, Anleihen gewinnen. Bei Inflationsschocks steigen die Zinsen, und beide verlieren. {s3_hist}</p>
<p>Wir schätzen deshalb getrennte Kovarianzmatrizen für beide Regime, nach dem Vorzeichen der rollierenden Korrelation. Im Inflationsregime liegt die Korrelation von europäischen Aktien und Bunds bei {num(regime_corr('pos'))}, im Wachstumsregime bei {num(regime_corr('neg'))}. {s3_use}</p>
<p>{s3_cons} Ein Zinsanstieg um einen Prozentpunkt kostet Bunds etwa {pct(M['meta']['bund_mod_duration'] / 100, 0)}, den Unternehmensanleihen-Index etwa 4 %.</p>

<h2><span class="no">4</span>Positionierung</h2>
<p>Das Modellportfolio maximiert die erwartete Rendite bei 8 % Volatilität. Die Renditeannahmen werden im Stil von Black und Litterman an das Referenzportfolio gebunden, jede Anlageklasse darf höchstens zehn Prozentpunkte abweichen. Darauf kommt die taktische Verschiebung aus dem Trend, Signale zum {sig_month}.</p>
<table><thead><tr><th>Anlageklasse</th><th>Referenz</th><th>Strategisch</th><th>Mit Trend</th><th>Abweichung</th><th class="why">Begründung</th></tr></thead><tbody>{pos_rows}</tbody></table>
<p>{s4}</p>

<h2><span class="no">5</span>Risiken der Einschätzung</h2>
<p>{s5_usd} <b>Trendwenden.</b> Nach scharfen Einbrüchen erholen sich Märkte oft schneller, als das Zwölfmonatssignal reagiert, so 2009 und 2020. Die Mehrrendite kommt aus längeren Phasen, nicht aus Wendepunkten. <b>Schätzfehler.</b> Die Bandbreite der erwarteten Rendite ist für Aktien groß, für die USA {pct(us['band'][0])} bis {pct(us['band'][1])} p. a. Die Begrenzung auf zehn Prozentpunkte je Anlageklasse trägt dem Rechnung. {s5_regime}</p>

<footer class="note">
<b>Methode.</b> Monatsrenditen in EUR {M['meta']['sample'][0][:4]} bis {M['meta']['sample'][1][:4]}. Aktien: Kenneth R. French Data Library, in Euro umgerechnet. Bundesanleihen: Zinsstruktur der Bundesbank, Monatsende, als Parianleihe mit zehn Jahren Laufzeit. Unternehmensanleihen: ETF-Kurse ab 2009, davor aus Zinsen und Aktien rekonstruiert. Kovarianzen mit Ledoit-Wolf-Schrumpfung, kürzere Historien per Stambaugh-Projektion. Portfolio mit exaktem Active-Set-Löser. Die Daten und dieses Papier werden zweimal im Monat automatisch aktualisiert. {track_line}Modell, Daten und Code: {URL}. Keine Anlageberatung.
</footer>
</body></html>"""

(ROOT / "paper" / "paper.html").write_text(HTML)
print("paper.html", f"ER ref {er_ref:.4f} vol {vol_ref:.4f} | tac {er_tac:.4f} vol {vol_tac:.4f}")
