  // ================================================================ tactical signals
  const SGN = M.signals, CL = SGN.classes;
  const TILT = SGN.tilt;
  const BAND = 0.10;
  function grade(s) {
    if (s > 0.5) return { t: "deutlich übergewichten", c: "up" };
    if (s > 0.2) return { t: "übergewichten", c: "up" };
    if (s < -0.5) return { t: "deutlich untergewichten", c: "dn" };
    if (s < -0.2) return { t: "untergewichten", c: "dn" };
    return { t: "neutral", c: "nt" };
  }
  const pill = (s) => { const g = grade(s); return `<span class="pill ${g.c}">${g.t}</span>`; };
  const bar = (v) => {
    const w = Math.abs(v) * 50, left = v >= 0 ? 50 : 50 - w;
    return `<span class="bar" title="${num(v, 2)}"><i style="left:${left}%;width:${w}%;background:${v >= 0 ? "var(--pos)" : "var(--neg)"}"></i></span>`;
  };
  // add tactical tilts to a weight vector; cash absorbs the difference
  function applyTilt(w) {
    const out = w.map((x, i) => K[i] === "cash" ? x : Math.max(0, x + TILT[K[i]] * CL[K[i]].score));
    const risky = out.reduce((s, x, i) => s + (K[i] === "cash" ? 0 : x), 0);
    if (risky > 1) { const f = 1 / risky; out.forEach((x, i) => { out[i] = K[i] === "cash" ? 0 : x * f; }); }
    else out[idx.cash] = 1 - risky;
    return out;
  }

  // Model portfolio at a given risk: strategic weights from the ten-year
  // expected returns (valuation), active bets limited to +/-BAND around the
  // reference portfolio, then the tactical trend tilt on top.
  function modelWeights(vol) {
    const S = SIG[CUR], cf = state.conf; state.conf = 0.25;
    const lb0 = LB.slice(), ub0 = UB.slice();
    K.forEach((k, i) => {
      if (k === "cash" || k === "bund") { LB[i] = 0; UB[i] = 0.7; }
      else { LB[i] = Math.max(0, wRef[i] - BAND); UB[i] = Math.min(ub0[i], wRef[i] + BAND); }
    });
    const wS = targetVol(blendedMu(S), S, Math.min(Math.max(vol, 0.03), 0.15)).w;
    lb0.forEach((v, i) => { LB[i] = v; UB[i] = ub0[i]; });
    state.conf = cf;
    return { strat: wS, total: applyTilt(wS) };
  }
  const REFVOL = Math.sqrt(quad(SIG[CUR], wRef));
  const MODEL = modelWeights(REFVOL);
  window.SAA_MODEL = { keys: K, strat: MODEL.strat, total: MODEL.total, ref: wRef, vol: REFVOL };
  // stance per asset class: total active weight relative to the band
  const stance = (k) => (MODEL.total[idx[k]] - wRef[idx[k]]) / 0.08;

  // hedging the dollar share of the reference portfolio
  function drawCurrency() {
    const C = M.currency;
    if (!C) return;
    const R0 = C.rows[0], R1 = C.rows[C.rows.length - 1];
    const lab = (h) => h === 0 ? "Ungesichert" : h === 1 ? "Voll gesichert" : `${pct(h, 0)} gesichert`;
    document.querySelector("#tbl-fx thead").innerHTML = `<tr><th></th>${C.rows.map((r) => `<th>${lab(r.hedge)}</th>`).join("")}</tr>`;
    const row = (l, f, cls) => `<tr><td>${l}</td>${C.rows.map((r) => `<td${cls ? ` class="${cls(f(r))}"` : ""}>${typeof f(r) === "number" ? spct(f(r)) : f(r)}</td>`).join("")}</tr>`;
    const neg = (x) => x < 0 ? "neg" : "pos";
    const eps = Object.keys(R0.episodes);
    document.querySelector("#tbl-fx tbody").innerHTML =
      row("Erwartete Rendite p. a., 10 Jahre", (r) => pct(r.expected)) +
      row(`Rendite p. a. ${M.meta.sample[0].slice(0, 4)} bis ${M.meta.sample[1].slice(0, 4)}`, (r) => pct(r.hist)) +
      row("Volatilität p. a.", (r) => pct(r.vol)) +
      row("Max. Drawdown", (r) => r.mdd, neg) +
      eps.map((e) => row(e, (r) => r.episodes[e], neg)).join("");
    const worse = eps.filter((e) => R1.episodes[e] < R0.episodes[e]);
    const better = eps.filter((e) => R1.episodes[e] > R0.episodes[e]);
    let t = `Ein Euro-Anleger trägt bei US-Aktien und Gold das Dollarrisiko. Im Referenzportfolio sind das ${pct(C.usd_share, 0)}. Die Absicherung kostet heute die Zinsdifferenz: ${pct(C.bill_now)} für Dollar-Geldmarkt gegen ${pct(M.assets[idx.cash].detail.current)} für €STR, also ${pct(C.carry_now)} p. a. auf den gesicherten Teil. Über zehn Jahre setzt das Modell die Differenz der Zehnjahresrenditen an, ${pct(C.carry_10y)} p. a.`;
    const IN = { "Dotcom-Crash": "im Dotcom-Crash", "Finanzkrise": "in der Finanzkrise", "Zinswende": "in der Zinswende 2022" };
    const lst = (xs) => xs.map((e) => IN[e] || e).join(" und ");
    if (worse.length) { const w = lst(worse); t += ` Historisch hat der Dollar in Krisen oft stabilisiert: ${w.charAt(0).toUpperCase() + w.slice(1)} lag das voll gesicherte Portfolio schlechter.`; }
    if (better.length) t += ` Nur ${lst(better)} lief es gesichert besser.`;
    t += R1.expected < R0.expected - 0.001 && R1.vol > R0.vol - 0.005
      ? " Das Modell sichert deshalb nicht ab: Die Absicherung kostet Rendite und senkt die Schwankung kaum."
      : R1.expected < R0.expected - 0.001 ? ` Die Absicherung senkt die Schwankung um ${num((R0.vol - R1.vol) * 100, 1)} Prozentpunkte und kostet ${num((R0.expected - R1.expected) * 100, 1)} Prozentpunkte Rendite.` : "";
    document.getElementById("fx-text").textContent = t;
    document.getElementById("fx-note").textContent = `Gesicherte Monatsrendite = Dollarrendite plus Differenz der Geldmarktsätze (Euro minus Dollar). Zinsen: 3-Monats-T-Bills und Rendite 10-jähriger US-Staatsanleihen, zuletzt ${C.sources.join(" bzw. ")}. Die Korrelation zwischen Dollar und europäischen Aktien liegt bei ${num(C.corr_usd_equity, 2)}.`;
  }

  // live record of past positioning (data/track/positionen.csv)
  function drawTrack() {
    const el = document.getElementById("track-out");
    let T = {};
    try { T = JSON.parse(document.getElementById("track").textContent || "{}"); } catch (e) { T = {}; }
    const P = T.positions || [], Mo = T.months || [];
    if (!P.length) { el.innerHTML = `<p class="note">Das Protokoll beginnt mit dem nächsten automatischen Lauf.</p>`; return; }
    const d = (s) => new Date(s).toLocaleDateString("de-DE");
    let html = "";
    if (Mo.length) {
      const cm = Mo.reduce((v, m) => v * (1 + m[1]), 1) - 1, cr = Mo.reduce((v, m) => v * (1 + m[2]), 1) - 1;
      const hit = Mo.filter((m) => m[1] > m[2]).length;
      html += `<div class="stats" style="grid-template-columns:repeat(3,minmax(0,1fr))"><div class="stat"><div class="v">${spct(cm)}</div><div class="k">Modell seit ${monthName(Mo[0][0])}</div></div><div class="stat"><div class="v">${spct(cr)}</div><div class="k">Referenzportfolio</div></div><div class="stat"><div class="v">${spct(cm - cr)}</div><div class="k">Differenz, ${hit} von ${Mo.length} Monaten besser</div></div></div>`;
      html += `<div class="tablewrap"><table><caption>Wertentwicklung je Monat <span class="muted">in EUR, vor Kosten</span></caption><thead><tr><th>Monat</th><th>Modell</th><th>Referenz</th><th>Differenz</th></tr></thead><tbody>${Mo.slice().reverse().slice(0, 12).map((m) => `<tr><td>${monthName(m[0])}</td><td>${spct(m[1])}</td><td>${spct(m[2])}</td><td class="${Math.abs(m[1] - m[2]) < 0.0005 ? "" : m[1] > m[2] ? "pos" : "neg"}">${spct(m[1] - m[2])}</td></tr>`).join("")}</tbody></table></div>`;
    } else {
      html += `<p class="note">Protokoll seit ${d(T.start)}. Die erste Position gilt ab ${monthName(P[0].applies)}. Die Wertentwicklung erscheint hier, sobald dieser Monat abgeschlossen ist.</p>`;
    }
    const cols = ["bund", "credit", "eq_eu", "eq_us", "eq_em", "gold", "cash"];
    html += `<div class="tablewrap"><table><caption>Gespeicherte Positionen <span class="muted">Modellportfolio mit Trend, Referenzrisiko</span></caption><thead><tr><th>Entschieden</th><th>Gilt für</th>${cols.map((k) => `<th>${A[idx[k]].name.replace(" 10 J.", "").replace("Unternehmensanleihen EUR (IG)", "Unternehmensanl.").replace("Aktien ", "")}</th>`).join("")}</tr></thead><tbody>${P.slice().reverse().slice(0, 12).map((p) => `<tr><td>${d(p.decided)}</td><td>${monthName(p.applies)}</td>${cols.map((k) => `<td>${pct(p.model[k], 0)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    el.innerHTML = html;
  }

  // plus / minus points per asset class, formulated from the data
  function classPoints(k) {
    const c = CL[k], d = c.detail, a = A[idx[k]], cashE = state.exp[idx.cash];
    const P = [], Mi = [], I = [];
    const tr = c.ex12;
    if (k !== "cash") {
      if (c.trend > 0.2) P.push(`Trend positiv: ${spct(tr)} über Geldmarkt in den letzten zwölf Monaten.`);
      else if (c.trend < -0.2) Mi.push(`Trend negativ: ${spct(tr)} gegenüber Geldmarkt in den letzten zwölf Monaten.`);
      else I.push(`Trend ohne klare Richtung (${spct(tr)} über Geldmarkt in zwölf Monaten).`);
    }
    const prem = state.exp[idx[k]] - cashE;
    if (k === "eq_us" || k === "eq_eu" || k === "eq_em") {
      const txt = `CAPE ${num(d.cape, 1)} gegenüber einem fairen Wert von ${num(d.fair, 0)}.`;
      if (c.val < -0.5) Mi.push(`Bewertung hoch: ${txt}`); else if (c.val < -0.2) Mi.push(`Bewertung erhöht: ${txt}`); else P.push(`Bewertung angemessen: ${txt}`);
      (prem < 0.025 ? Mi : P).push(`Erwartete Rendite ${pct(state.exp[idx[k]])} p. a. über zehn Jahre, ${num(prem * 100, 1)} Prozentpunkte über Geldmarkt.`);
      const ad = A[idx[k]].detail;
      if (k === "eq_us") { Mi.push("Dollarrisiko: Kursgewinne können durch einen stärkeren Euro aufgezehrt werden."); P.push(`Aktienrückkäufe stützen die Ausschüttung (netto etwa ${pct(ad.net_buyback)} p. a.).`); }
      if (k === "eq_eu") { const dus = A[idx.eq_us].detail.dy; P.push(ad.dy > dus + 0.005 ? `Dividendenrendite ${pct(ad.dy)}, deutlich über den USA (${pct(dus)}).` : `Dividendenrendite ${pct(ad.dy)}.`); P.push("Überwiegend Euro, dazu Pfund, Franken und skandinavische Kronen. Weniger Währungsrisiko als bei US-Aktien."); if (state.exp[idx.eq_eu] > state.exp[idx.eq_us]) P.push(`Günstiger als die USA: erwartete Rendite ${pct(state.exp[idx.eq_eu])} gegenüber ${pct(state.exp[idx.eq_us])}.`); }
      if (k === "eq_em") { const tc = ad.top_countries; if (tc && tc.length > 1) Mi.push(`${tc[0][0]} und ${tc[1][0]} machen ${pct(tc[0][1] + tc[1][1], 0)} des Index aus. Ihre Bewertung bestimmt den Durchschnitt maßgeblich.`); Mi.push(`Verwässerung durch Kapitalerhöhungen kostet etwa ${pct(Math.abs(ad.net_buyback))} p. a.`); P.push(`Höchstes reales Wirtschaftswachstum (etwa ${pct(ad.g_real)}).`); }
    }
    if (k === "bund") {
      P.push(`Startrendite ${pct(state.exp[idx.bund])} ist die beste Schätzung der Rendite über zehn Jahre. Kein Ausfallrisiko.`);
      (c.val >= 0 ? P : Mi).push(`Realrendite ${pct(d.real_yield)} nach 2 % Inflation, Median seit 1990 ${pct(d.median)}.`);
      if (SGN.corr_now > 0) Mi.push(`Absicherung eingeschränkt: Aktien und Bunds laufen derzeit gleichgerichtet (Korrelation ${num(SGN.corr_now, 2)}). Bei Inflationsschocks verlieren beide.`);
      else P.push(`Gute Absicherung: Korrelation zu Aktien ${num(SGN.corr_now, 2)}.`);
      I.push(`Zinsanstieg um einen Prozentpunkt kostet etwa ${pct(-rateShock, 1)} Kurs.`);
    }
    if (k === "credit") {
      P.push(`Höchste laufende Rendite unter den Anleihen: ${pct(a.detail.ytm)} auf Verfall, Laufzeitrisiko moderat (Duration ${num(a.detail.duration, 1)}).`);
      (d.spread >= d.normal ? P : Mi).push(`Risikoaufschlag ${num(d.spread * 100, 1)} Prozentpunkte über AAA-Staatsanleihen, üblich sind rund ${num(d.normal * 100, 1)}. ${d.spread < d.normal ? "Wenig Puffer für eine Konjunkturschwäche." : ""}`);
      Mi.push("Fällt in Krisen mit Aktien, etwa −7 % im Corona-Schock und −15 % in der Zinswende 2022.");
    }
    if (k === "gold") {
      Mi.push(`Real auf dem ${num(d.pct * 100, 0)}. Perzentil seit 1975. Auf solchen Niveaus waren die Folgerenditen meist schwach.`);
      Mi.push("Kein laufender Ertrag. Erwartete Rendite real leicht negativ.");
      P.push("Krisenschutz: +35 % in der Finanzkrise, +15 % in der Euro-Schuldenkrise, positiv in der Zinswende 2022.");
    }
    if (k === "cash") {
      P.push(`Kein Kursrisiko, aktuell ${pct(cashE)} p. a.`);
      Mi.push(`Real nur ${pct(A[idx.cash].real)} p. a. Über lange Zeiträume der schwächste Baustein.`);
    }
    return { P, Mi, I };
  }

  function drawSignals() {
    const tb = document.querySelector("#tbl-sig tbody");
    document.getElementById("sig-cap").textContent = `Signale zum ${monthName(SGN.as_of)}, Skala −1 bis +1. Quoten für das Referenzrisiko von ${pct(REFVOL)} Volatilität. Strategisch: aus den Zehnjahresrenditen, höchstens ±10 Prozentpunkte vom Referenzportfolio, daher etwas enger als in Abschnitt 6.`;
    tb.innerHTML = K.map((k, i) => {
      const c = CL[k], st = MODEL.strat[i], tt = MODEL.total[i];
      return `<tr><td><span class="sw" style="background:${color(k)}"></span>${name(k)}</td>
        <td style="text-align:center">${k === "cash" ? "–" : bar(c.val)}</td>
        <td style="text-align:center">${k === "cash" ? "–" : bar(c.trend)}</td>
        <td>${pct(wRef[i], 0)}</td><td>${pct(st, 0)}</td><td><b>${pct(tt, 0)}</b></td>
        <td style="text-align:left">${k === "cash" ? '<span class="muted">Restgröße</span>' : pill(stance(k))}</td></tr>`;
    }).join("");
    const bt = SGN.backtest, T1 = bt.tactical, R1 = bt.reference;
    document.getElementById("bt-cap").textContent = `${monthName(bt.start)} bis ${monthName(bt.end)}, nach Kosten`;
    const row = (l, a, b, f) => `<tr><td>${l}</td><td><b>${f(a)}</b></td><td>${f(b)}</td></tr>`;
    document.querySelector("#tbl-bt tbody").innerHTML =
      row("Rendite p. a.", T1.cagr, R1.cagr, (x) => pct(x)) + row("Volatilität p. a.", T1.vol, R1.vol, (x) => pct(x)) +
      row("Sharpe-Ratio", T1.sharpe, R1.sharpe, (x) => num(x, 2)) + row("Max. Drawdown", T1.mdd, R1.mdd, (x) => spct(x));
    document.getElementById("bt-note").innerHTML = `Mehrrendite <b>${spct(bt.excess_pa)}</b> p. a. bei einem Tracking Error von ${pct(bt.te)}, Information Ratio ${num(bt.ir, 2)}, t-Wert ${num(bt.t_stat, 1)}. In ${nf(0).format(bt.hit_years * 100)} % der Jahre besser als die Referenz. Umschlag ${pct(bt.turnover_pa, 0)} p. a., Kosten ${nf(1).format(bt.cost * 1e4)} Basispunkte je Umschichtung. Signale jeweils mit Daten des Vormonats.`;
    const V = SGN.variants, vr = (l, v) => `<tr><td>${l}</td><td class="${v.excess_pa < 0 ? "neg" : "pos"}">${spct(v.excess_pa)}</td><td>${num(v.ir, 2).replace("-", "−")}</td><td>${num(v.t_stat, 1).replace("-", "−")}</td></tr>`;
    document.querySelector("#tbl-var tbody").innerHTML = vr("Trend", V.trend) + vr("Bewertung", V.bewertung) + vr("Beide je zur Hälfte", V.kombiniert);
    const RB = SGN.robustness || [];
    const halves = (rb) => {
      const a = rb[rb.length - 2], b = rb[rb.length - 1];
      if (!a || !b) return "";
      if (b.excess_pa <= 0) return "In der zweiten Hälfte der Stichprobe verschwindet der Effekt.";
      if (b.excess_pa < 0.7 * a.excess_pa) return "In der zweiten Hälfte der Stichprobe ist der Effekt kleiner, aber vorhanden.";
      return "Beide Hälften der Stichprobe zeigen einen ähnlichen Effekt.";
    };
    document.querySelector("#tbl-rob tbody").innerHTML = RB.map((v, i) => `<tr${i === 0 ? ' style="font-weight:600"' : ""}><td>${v.label}</td><td class="${v.excess_pa < 0 ? "neg" : "pos"}">${spct(v.excess_pa)}</td><td>${num(v.ir, 2)}</td><td>${num(v.t_stat, 1)}</td><td>${pct(v.hit_years, 0)}</td></tr>`).join("");
    if (RB.length) {
      const pos = RB.filter((v) => v.excess_pa > 0).length, ts = RB.map((v) => v.t_stat);
      document.getElementById("rob-note").textContent = `Die Mehrrendite ist in ${pos} von ${RB.length} Varianten positiv, die t-Werte liegen zwischen ${num(Math.min(...ts), 1)} und ${num(Math.max(...ts), 1)}. Der Zwölfmonatszeitraum ist der übliche Standard und wurde nicht auf diese Daten optimiert. ${halves(RB)}`;
    }
    drawBacktest();
    drawTrack();
    drawCurrency();
  }
  function drawBacktest() {
    const P = SGN.backtest.path;
    const W = width("fig-bt"), Hh = Math.round(W * 0.62), m = { l: 40, r: 70, t: 12, b: 26 };
    const f = frame(document.getElementById("fig-bt"), W, Hh, m);
    const tx = (d) => +d.slice(0, 4) + (+d.slice(5) - 1) / 12;
    const x = lin(tx(P[0][0]), tx(P[P.length - 1][0]), f.x0, f.x1);
    const ymax = Math.max(...P.map(p => Math.max(p[1], p[2]))) * 1.05;
    const y = lin(0, ymax, f.y0, f.y1);
    ticks(0, ymax, 5).forEach(t => { el("line", { x1: f.x0, x2: f.x1, y1: y(t), y2: y(t), class: t === 0 ? "zero" : "grid" }, f.svg); txt(f.svg, f.x0 - 6, y(t) + 4, num(t, 0), { "text-anchor": "end" }); });
    for (let yr = 1995; yr <= 2025; yr += 10) txt(f.svg, x(yr), f.y0 + 17, yr, { "text-anchor": "middle" });
    [[2, "var(--muted)", "Referenz"], [1, "var(--accent)", "Taktisch"]].forEach(([j, col, lab]) => {
      let d = ""; P.forEach(p => d += (d ? "L" : "M") + x(tx(p[0])).toFixed(1) + "," + y(p[j]).toFixed(1));
      el("path", { d, fill: "none", stroke: col, "stroke-width": 2 }, f.svg);
      const last = P[P.length - 1];
      el("circle", { cx: x(tx(last[0])), cy: y(last[j]), r: 4, fill: col, stroke: "var(--bg)", "stroke-width": 2 }, f.svg);
      txt(f.svg, x(tx(last[0])) + 8, y(last[j]) + 4, `${lab} ${num(last[j], 1)}`, { class: j === 1 ? "lbl-strong" : "lbl" });
    });
  }

  // ================================================================ portfolio check
  const INSTR = [
    { id: "world", label: "MSCI World (ETF)", map: { eq_us: 0.72, eq_eu: 0.28 }, note: "Zerlegt in rund 72 % USA und 28 % übrige Industrieländer. Japan, Kanada und Australien (zusammen etwa 11 %) rechnet das Modell mit Europa." },
    { id: "acwi", label: "MSCI ACWI / FTSE All-World (ETF)", map: { eq_us: 0.64, eq_eu: 0.25, eq_em: 0.11 }, note: "Zerlegt in rund 64 % USA, 25 % übrige Industrieländer und 11 % Schwellenländer." },
    { id: "sp500", label: "S&P 500 / MSCI USA (ETF)", map: { eq_us: 1 } },
    { id: "ndx", label: "Nasdaq-100 (ETF)", map: { eq_us: 1 }, idio: 0.10, note: "Starke Konzentration auf wenige Technologiewerte. Das Modell rechnet mit einem Zusatzrisiko von 10 % p. a. über dem US-Gesamtmarkt." },
    { id: "europe", label: "MSCI Europe / STOXX Europe 600 (ETF)", map: { eq_eu: 1 } },
    { id: "es50", label: "EURO STOXX 50 (ETF)", map: { eq_eu: 1 }, idio: 0.05, note: "Nur 50 Werte der Eurozone. Zusatzrisiko von 5 % p. a. gegenüber dem breiten Europa-Index." },
    { id: "dax", label: "DAX (ETF)", map: { eq_eu: 1 }, idio: 0.08, note: "Nur deutsche Werte. Zusatzrisiko von 8 % p. a. gegenüber dem breiten Europa-Index." },
    { id: "em", label: "MSCI Emerging Markets (ETF)", map: { eq_em: 1 } },
    { id: "bund", label: "Bundesanleihen (ETF oder direkt)", map: { bund: 1 } },
    { id: "egov", label: "Euro-Staatsanleihen (ETF)", map: { bund: 1 }, note: "Enthält Länder mit Risikoaufschlag wie Italien und Frankreich. Das Modell rechnet vereinfachend mit Bundesanleihen." },
    { id: "corp", label: "Euro-Unternehmensanleihen IG (ETF)", map: { credit: 1 } },
    { id: "cash", label: "Tagesgeld / Geldmarkt", map: { cash: 1 } },
    { id: "gold", label: "Gold (ETC oder physisch)", map: { gold: 1 } },
    { id: "stock", label: "Einzelaktie", map: null, idio: 0.30 },
  ];
  const REGION = { us: ["eq_us", "USA"], eu: ["eq_eu", "Europa"], em: ["eq_em", "Schwellenländer"] };
  const EXAMPLES = {
    welt: [["world", 55], ["em", 10], ["bund", 20], ["gold", 5], ["cash", 10]],
    usa: [["sp500", 40], ["ndx", 20], ["stock", 10, "Tesla", "us"], ["stock", 10, "Nvidia", "us"], ["gold", 5], ["cash", 15]],
    defensiv: [["cash", 30], ["bund", 30], ["corp", 20], ["world", 20]],
  };
  let rows = [];
  const byId = Object.fromEntries(INSTR.map(x => [x.id, x]));

  function rowHTML(r, i) {
    const opt = INSTR.map(x => `<option value="${x.id}"${x.id === r.id ? " selected" : ""}>${x.label}</option>`).join("");
    const det = r.id === "stock"
      ? `<input id="pc-name-${i}" type="text" placeholder="Name, z. B. Tesla" value="${(r.name || "").replace(/"/g, "&quot;")}" aria-label="Name der Aktie"><select id="pc-reg-${i}" aria-label="Region">${Object.entries(REGION).map(([v, [, l]]) => `<option value="${v}"${v === r.region ? " selected" : ""}>${l}</option>`).join("")}</select>`
      : `<span class="small muted" style="align-self:center">${byId[r.id].map ? Object.entries(byId[r.id].map).map(([k, v]) => `${SHORT[k]} ${nf(0).format(v * 100)} %`).join(", ") : ""}</span>`;
    return `<div class="pc-row"><select id="pc-id-${i}" aria-label="Position">${opt}</select><div class="det">${det}</div><input class="w" id="pc-w-${i}" type="text" inputmode="decimal" value="${nf(1).format(r.w).replace(",0", "")}" aria-label="Gewicht in Prozent"><button type="button" class="rm" data-i="${i}" aria-label="Position entfernen">×</button></div>`;
  }
  function renderRows() {
    const host = document.getElementById("pc-rows");
    host.innerHTML = rows.map(rowHTML).join("");
    rows.forEach((r, i) => {
      document.getElementById(`pc-id-${i}`).addEventListener("change", (e) => { r.id = e.target.value; if (r.id === "stock" && !r.region) r.region = "us"; renderRows(); runCheck(); });
      document.getElementById(`pc-w-${i}`).addEventListener("change", (e) => { const v = parseFloat(e.target.value.replace(",", ".")); r.w = isNaN(v) ? 0 : Math.max(0, v); runCheck(); });
      if (r.id === "stock") {
        document.getElementById(`pc-name-${i}`).addEventListener("change", (e) => { r.name = e.target.value.trim(); runCheck(); });
        document.getElementById(`pc-reg-${i}`).addEventListener("change", (e) => { r.region = e.target.value; runCheck(); });
      }
    });
    host.querySelectorAll(".rm").forEach(b => b.addEventListener("click", () => { rows.splice(+b.dataset.i, 1); renderRows(); runCheck(); }));
  }
  function loadExample(key) {
    rows = EXAMPLES[key].map(([id, w, nm, reg]) => ({ id, w, name: nm || "", region: reg || "us" }));
    renderRows(); runCheck();
  }
  const posMap = (r) => r.id === "stock" ? { [REGION[r.region][0]]: 1 } : byId[r.id].map;
  const posName = (r) => r.id === "stock" ? `${r.name || "Einzelaktie"} (${REGION[r.region][1]})` : byId[r.id].label.replace(" (ETF)", "");

  function runCheck() {
    const out = document.getElementById("pc-out");
    const tot = rows.reduce((s, r) => s + r.w, 0);
    document.getElementById("pc-sum").innerHTML = `Summe <b>${nf(1).format(tot)} %</b>${Math.abs(tot - 100) > 0.05 && tot > 0 ? " · wird auf 100 % skaliert" : ""}`;
    if (tot <= 0) { out.innerHTML = '<p class="note">Bitte mindestens eine Position mit Gewicht eintragen.</p>'; return; }
    const pos = rows.filter(r => r.w > 0).map(r => ({ ...r, share: r.w / tot }));
    const wU = K.map(() => 0);
    let idioVar = 0;
    pos.forEach(p => {
      Object.entries(posMap(p)).forEach(([k, v]) => { wU[idx[k]] += p.share * v; });
      const iv = (p.id === "stock" ? byId.stock.idio : byId[p.id].idio) || 0;
      idioVar += (p.share * iv) ** 2;
    });
    const S = SIG[CUR];
    const mU = metrics(wU, S);
    const volU = Math.sqrt(mU.vol * mU.vol + idioVar);
    const egU = mU.ea - volU * volU / 2;
    // model portfolio at the same systematic risk, strategic plus tactical
    const mw = modelWeights(mU.vol);
    const wT = mw.total;
    const mT = metrics(wT, S);
    const worst = (w) => M.stress.reduce((a, s) => { const v = stressHist(w, s); return v < a.v ? { v, n: s.name } : a; }, { v: 0, n: "" });
    const wsU = worst(wU), wsT = worst(wT);
    const rf = state.exp[idx.cash];

    // key findings
    const diffs = K.map((k, i) => ({ k, d: wU[i] - wT[i] })).filter(x => Math.abs(x.d) >= 0.03).sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
    const find = [];
    const eqU = wU[idx.eq_us] + wU[idx.eq_eu] + wU[idx.eq_em];
    find.push(`Das Depot entspricht einem Portfolio mit ${pct(eqU, 0)} Aktien und einer erwarteten Schwankung von ${pct(volU)} p. a.`);
    if (diffs.length) find.push(`Größte Abweichungen zum Modellportfolio: ${diffs.slice(0, 3).map(x => `${name(x.k)} ${spct(x.d, 0)}`).join(", ")}.`);
    else find.push("Das Depot liegt nah am Modellportfolio. Kein dringender Umschichtungsbedarf.");
    if (egU < mT.eg - 0.002) find.push(`Bei gleichem Marktrisiko erwartet das Modellportfolio ${spct(mT.eg - egU)} mehr Rendite pro Jahr.`);
    const usd = wU[idx.eq_us] + wU[idx.gold];
    if (usd > 0.4) find.push(`${pct(usd, 0)} des Depots sind Dollar-Anlagen (US-Aktien und Gold), ungesichert. Ein um 10 % stärkerer Euro kostet rund ${pct(usd * 0.1, 1)}.`);
    const bigStocks = pos.filter(p => p.id === "stock" && p.share > 0.05);
    const warn = [];
    bigStocks.forEach(p => warn.push(`${posName(p)} macht ${pct(p.share, 0)} des Depots aus. Für eine Einzelaktie empfiehlt das Modell höchstens 5 %. Ein Kurseinbruch um 50 % kostet das Depot ${pct(p.share * 0.5, 1)}.`));
    const stockSum = pos.filter(p => p.id === "stock").reduce((s, p) => s + p.share, 0);
    if (stockSum > 0.15) warn.push(`Einzelaktien zusammen ${pct(stockSum, 0)}. Ihr Eigenrisiko macht ${pct(idioVar / (volU * volU), 0)} des gesamten Depotrisikos aus und wird nicht durch höhere erwartete Rendite ausgeglichen.`);
    if (SGN.corr_now > 0 && wU[idx.bund] + wU[idx.credit] > 0.3) find.push(`Anleihen machen ${pct(wU[idx.bund] + wU[idx.credit], 0)} aus. Im aktuellen Regime sichern sie Aktienrisiken nur eingeschränkt ab.`);

    const stat = (v, k, sub) => `<div class="stat"><div class="v">${v}${sub ? `<small>${sub}</small>` : ""}</div><div class="k">${k}</div></div>`;
    let html = `<div class="pc-verdict"><h3>Ergebnis</h3><ul class="prose" style="padding-left:1.1rem;margin:0">${find.map(f => `<li style="margin-bottom:.35rem">${f}</li>`).join("")}</ul>${warn.map(w => `<div class="warn">${w}</div>`).join("")}</div>`;
    html += `<div class="stats">${stat(pct(egU), "Erwartete Rendite p. a., 10 Jahre", "Modell " + pct(mT.eg))}${stat(pct(volU), "Volatilität p. a.", "Modell " + pct(mT.vol))}${stat(num((egU - rf) / volU, 2), "Sharpe-Ratio", "Modell " + num((mT.eg - rf) / mT.vol, 2))}${stat(spct(mU.mdd), "Max. Drawdown 1990–2026", "Modell " + spct(mT.mdd))}${stat(spct(wsU.v), `Schlechteste Krise (${wsU.n})`, "Modell " + spct(wsT.v))}</div>`;

    // rebalancing table
    html += `<div class="tablewrap"><table><caption>Umschichtung auf Ebene der Anlageklassen <span class="muted">Modellportfolio mit gleichem Marktrisiko, strategisch plus taktisch, höchstens ±10 Prozentpunkte je Anlageklasse vom Referenzportfolio, Korrelationen des ${CUR === "pos" ? "Inflationsregimes" : "Wachstumsregimes"}</span></caption>
      <thead><tr><th>Anlageklasse</th><th>Ihr Depot</th><th>Modell</th><th>Differenz</th><th style="text-align:left">Vorschlag</th><th style="text-align:left">Signal</th></tr></thead><tbody>${K.map((k, i) => {
        const d = wT[i] - wU[i];
        const act = d > 0.03 ? "aufstocken" : d < -0.03 ? "reduzieren" : "halten";
        if (wU[i] < 0.005 && wT[i] < 0.005) return "";
        return `<tr><td><span class="sw" style="background:${color(k)}"></span>${name(k)}</td><td>${pct(wU[i], 0)}</td><td><b>${pct(wT[i], 0)}</b></td><td class="${d > 0.03 ? "pos" : d < -0.03 ? "neg" : ""}">${spct(d, 0)}</td><td style="text-align:left">${act}</td><td style="text-align:left">${k === "cash" ? '<span class="muted">Restgröße</span>' : pill(stance(k))}</td></tr>`;
      }).join("")}</tbody></table></div>`;

    // per position
    html += `<div class="pos-list">${pos.map(p => {
      const mp = posMap(p);
      const sc = Object.entries(mp).reduce((s, [k, v]) => s + v * stance(k), 0);
      const trendAct = Object.entries(mp).reduce((s, [k, v]) => s + v * (wT[idx[k]] - wU[idx[k]]) / Math.max(wU[idx[k]], 1e-9), 0);
      const tend = trendAct > 0.15 ? "aufstocken" : trendAct < -0.15 ? "reduzieren" : "halten";
      const cls = Object.entries(mp).filter(([, v]) => v >= 0.25).sort((a, b) => b[1] - a[1]);
      const pts = { P: [], Mi: [], I: [] };
      cls.forEach(([k]) => {
        const c = classPoints(k), pre = cls.length > 1 ? `${SHORT[k]}: ` : "";
        const take = cls.length > 1 ? 2 : 4;
        c.P.slice(0, take).forEach(t => pts.P.push(pre + t)); c.Mi.slice(0, take).forEach(t => pts.Mi.push(pre + t)); c.I.slice(0, 1).forEach(t => pts.I.push(pre + t));
      });
      if (p.id === "stock") {
        const risk = (p.share * byId.stock.idio) ** 2 / (volU * volU);
        pts.I.unshift(`Einzeltitel: Bewertet wird die Region ${REGION[p.region][1]}. Unternehmensspezifische Faktoren wie Produkte, Wettbewerb oder Management sind nicht Teil des Modells.`);
        pts.Mi.unshift(`Eigenrisiko: Bei einer angenommenen titelspezifischen Schwankung von 30 % p. a. stammt ${pct(risk, 0)} des Depotrisikos allein aus dieser Aktie.`);
      }
      if (byId[p.id].note) pts.I.push(byId[p.id].note);
      return `<div class="pos-card"><div class="t"><b>${posName(p)}</b>${pill(sc)}</div><div class="sub">${pct(p.share, 1)} des Depots · Modell: ${tend}</div><ul>${pts.P.map(t => `<li class="p">${t}</li>`).join("")}${pts.Mi.map(t => `<li class="m">${t}</li>`).join("")}${pts.I.map(t => `<li class="i">${t}</li>`).join("")}</ul></div>`;
    }).join("")}</div>`;

    const missing = K.filter((k, i) => wU[i] < 0.005 && wT[i] >= 0.05);
    if (missing.length) html += `<p class="note">Im Depot fehlen Bausteine, die das Modell mit mindestens 5 % gewichtet: ${missing.map(k => `${name(k)} (${pct(wT[idx[k]], 0)})`).join(", ")}.</p>`;
    html += `<p class="note">Modellsignale auf Basis öffentlicher Marktdaten, Stand ${monthName(SGN.as_of)}. Keine Anlageberatung und keine Empfehlung zum Kauf oder Verkauf einzelner Wertpapiere.</p>`;
    out.innerHTML = html;
  }

  document.getElementById("pc-add").addEventListener("click", () => { rows.push({ id: "world", w: 10, name: "", region: "us" }); renderRows(); runCheck(); });
  document.querySelectorAll("[data-example]").forEach(b => b.addEventListener("click", () => loadExample(b.dataset.example)));
  drawSignals();
  loadExample("welt");
  window.addEventListener("resize", () => { clearTimeout(window.__bt); window.__bt = setTimeout(drawBacktest, 150); });
