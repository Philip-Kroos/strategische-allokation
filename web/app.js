"use strict";
(function () {
  const M = JSON.parse(document.getElementById("model").textContent);
  const A = M.assets;
  const K = A.map(a => a.key);
  const N = K.length;
  const idx = Object.fromEntries(K.map((k, i) => [k, i]));

  // ---------------------------------------------------------------- formatting
  const nf = (d) => new Intl.NumberFormat("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
  // typographic minus; a value that rounds to zero carries no sign
  const minus = (t) => { t = t.replace("-", "−"); return /^−0(,0+)?$/.test(t) ? t.slice(1) : t; };
  const pct = (x, d = 1) => (x == null || isNaN(x)) ? "–" : minus(nf(d).format(x * 100)) + " %";
  const spct = (x, d = 1) => {
    const t = nf(d).format(Math.abs(x * 100));
    return (/^0(,0+)?$/.test(t) ? "" : x > 0 ? "+" : x < 0 ? "−" : "") + t + " %";
  };
  const num = (x, d = 2) => minus(nf(d).format(x));
  const bridgeText = () => {
    const b = (M.meta && M.meta.equity_bridge) || {};
    const months = [...new Set(Object.values(b).flatMap((v) => v.months))].sort();
    if (!months.length) return "";
    const list = months.map((m) => monthName(m)).join(" und ");
    return ` Die French Data Library veröffentlicht mit ein bis zwei Monaten Verzug. ${list} ${months.length > 1 ? "sind" : "ist"} deshalb mit Renditen börsengehandelter Index-ETFs in EUR überbrückt (iShares STOXX Europe 600, Core S&amp;P 500, MSCI EM). Sobald die Indexdaten vorliegen, ersetzen sie die Überbrückung.`;
  };
  const eur = (x) => {
    const a = Math.abs(x);
    if (a >= 1e6) return nf(1).format(x / 1e6) + " Mio. €";
    if (a >= 1e3) return nf(0).format(x / 1e3) + " Tsd. €";
    return nf(0).format(x) + " €";
  };
  const monthName = (ym) => {
    const [y, m] = ym.split("-").map(Number);
    return ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."][m - 1] + " " + y;
  };
  const color = (k) => `var(--c-${k})`;
  const name = (k) => A[idx[k]].name;
  const SHORT = { cash: "Geldmarkt", bund: "Bundesanleihen", credit: "Unternehmensanl. IG", eq_eu: "Aktien Europa", eq_us: "Aktien USA", eq_em: "Schwellenländer", gold: "Gold" };

  // ---------------------------------------------------------------- linear algebra
  const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);
  const mv = (S, w) => S.map(r => dot(r, w));
  const quad = (S, w) => dot(w, mv(S, w));
  function solveLin(Amat, b) {
    const n = b.length, Mx = Amat.map((r, i) => [...r, b[i]]);
    for (let c = 0; c < n; c++) {
      let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(Mx[r][c]) > Math.abs(Mx[p][c])) p = r;
      [Mx[c], Mx[p]] = [Mx[p], Mx[c]];
      for (let r = 0; r < n; r++) if (r !== c) { const f = Mx[r][c] / Mx[c][c]; for (let j = c; j <= n; j++) Mx[r][j] -= f * Mx[c][j]; }
    }
    return Mx.map((r, i) => r[n] / r[i]);
  }

  // ---------------------------------------------------------------- state
  const REF = { cash: 0.05, bund: 0.20, credit: 0.15, eq_eu: 0.22, eq_us: 0.23, eq_em: 0.08, gold: 0.07 };
  const wRef = K.map(k => REF[k]);
  const LB = K.map(() => 0);
  const UB = K.map(k => ({ cash: 0.40, bund: 0.60, credit: 0.30, eq_eu: 0.40, eq_us: 0.45, eq_em: 0.15, gold: 0.10 })[k]);
  const baseExp = A.map(a => a.expected);
  const state = { vol: 0.08, regime: "pos", conf: 0.25, exp: baseExp.slice(), edit: false, w0: 1e7, wd: 0.03, h: 20 };

  const SIG = { all: M.cov.all, pos: M.cov.pos, neg: M.cov.neg };
  const REGIME_LABEL = { pos: "Inflationsregime", all: "Gesamtstichprobe", neg: "Wachstumsregime" };

  // arithmetic expected returns from geometric CMA: mu_a = mu_g + sigma^2/2
  const arith = (exp, S) => exp.map((g, i) => g + S[i][i] / 2);

  function blendedMu(S) {
    const mu = arith(state.exp, S);
    const rf = mu[idx.cash];
    const vRef = quad(S, wRef);
    const delta = Math.max((dot(mu, wRef) - rf) / vRef, 0.5);
    const pi = mv(S, wRef).map(x => rf + delta * x);
    return mu.map((m, i) => state.conf * m + (1 - state.conf) * pi[i]);
  }

  // projection onto {sum w = 1, LB <= w <= UB}
  function project(v) {
    let lo = Math.min(...v.map((x, i) => x - UB[i])), hi = Math.max(...v.map((x, i) => x - LB[i]));
    for (let it = 0; it < 60; it++) {
      const t = (lo + hi) / 2;
      const s = v.reduce((a, x, i) => a + Math.min(UB[i], Math.max(LB[i], x - t)), 0);
      if (s > 1) lo = t; else hi = t;
    }
    const t = (lo + hi) / 2;
    return v.map((x, i) => Math.min(UB[i], Math.max(LB[i], x - t)));
  }
  // Exact solver for  max mu'w - lam/2 w'Sw  s.t. sum w = 1, LB <= w <= UB.
  // Primal active-set method (Nocedal and Wright, Algorithm 16.3) on the
  // equivalent minimisation f(w) = -mu'w + lam/2 w'Sw. Starts from a feasible
  // point, moves along the equality-constrained Newton step, adds blocking
  // bounds and drops bounds with negative multipliers. Exact for seven assets.
  function solveQP(mu, S, lam, wStart) {
    let w = project(wStart ? wStart.slice() : K.map(() => 1 / N));
    const act = K.map((_, i) => (w[i] <= LB[i] + 1e-12 ? -1 : w[i] >= UB[i] - 1e-12 ? 1 : 0));
    for (let iter = 0; iter < 200; iter++) {
      const Sw = mv(S, w);
      const g = K.map((_, i) => -mu[i] + lam * Sw[i]);
      const F = K.map((_, i) => i).filter(i => act[i] === 0);
      let p = K.map(() => 0), nu;
      if (F.length) {
        const n = F.length, Am = [], bb = [];
        F.forEach(i => { Am.push([...F.map(j => lam * S[i][j]), 1]); bb.push(-g[i]); });
        Am.push([...F.map(() => 1), 0]); bb.push(0);
        const sol = solveLin(Am, bb);
        F.forEach((i, k) => { p[i] = sol[k]; });
        nu = sol[n];
      } else {
        nu = -K.reduce((s2, _, i) => s2 + g[i], 0) / N;
      }
      const pmax = Math.max(...p.map(Math.abs));
      if (pmax < 1e-11) {
        // multipliers: at LB need g_i + nu >= 0, at UB need g_i + nu <= 0
        let rel = -1, worst = -1e-12;
        K.forEach((_, i) => {
          if (act[i] === 0) return;
          const m = act[i] === -1 ? g[i] + nu : -(g[i] + nu);
          if (m < worst) { worst = m; rel = i; }
        });
        if (rel < 0) return w;
        act[rel] = 0;
        continue;
      }
      let alpha = 1, block = -1;
      F.forEach(i => {
        if (p[i] > 1e-15) { const a2 = (UB[i] - w[i]) / p[i]; if (a2 < alpha) { alpha = a2; block = i; } }
        else if (p[i] < -1e-15) { const a2 = (LB[i] - w[i]) / p[i]; if (a2 < alpha) { alpha = a2; block = i; } }
      });
      alpha = Math.max(0, alpha);
      w = w.map((x, i) => x + alpha * p[i]);
      if (block >= 0) { act[block] = p[block] > 0 ? 1 : -1; w[block] = p[block] > 0 ? UB[block] : LB[block]; }
    }
    return w;
  }
  function targetVol(mu, S, target) {
    let lo = Math.log(0.2), hi = Math.log(20000), w = null;
    const wHi = solveQP(mu, S, Math.exp(lo));
    if (Math.sqrt(quad(S, wHi)) <= target) return { w: wHi, bound: "max" };
    const wLo = solveQP(mu, S, Math.exp(hi));
    if (Math.sqrt(quad(S, wLo)) >= target) return { w: wLo, bound: "min" };
    w = wHi;
    for (let it = 0; it < 34; it++) {
      const mid = (lo + hi) / 2;
      w = solveQP(mu, S, Math.exp(mid), w);
      if (Math.sqrt(quad(S, w)) > target) lo = mid; else hi = mid;
    }
    return { w, bound: null };
  }
  function frontier(mu, S) {
    const pts = [];
    let w = null;
    for (let j = 0; j <= 40; j++) {
      const lam = Math.exp(Math.log(0.2) + (Math.log(20000) - Math.log(0.2)) * j / 40);
      w = solveQP(mu, S, lam, w);
      pts.push(w);
    }
    return pts;
  }

  // ---------------------------------------------------------------- portfolio metrics
  const H = M.history;
  const T = H.returns[K[0]].length;
  function histPath(w) {
    let v = 1, peak = 1, mdd = 0, worst12 = 0;
    const path = [];
    for (let t = 0; t < T; t++) {
      let r = 0; for (let i = 0; i < N; i++) r += w[i] * H.returns[K[i]][t];
      v *= 1 + r; path.push(v);
      peak = Math.max(peak, v); mdd = Math.min(mdd, v / peak - 1);
      if (t >= 12) worst12 = Math.min(worst12, v / path[t - 12] - 1);
    }
    return { mdd, worst12, cagr: Math.pow(v, 12 / T) - 1 };
  }
  function metrics(w, S) {
    const muA = arith(state.exp, S);
    const vol = Math.sqrt(quad(S, w));
    const ea = dot(muA, w);
    const eg = ea - vol * vol / 2;
    const rf = state.exp[idx.cash];
    const es = -(ea - 2.0627 * vol); // expected shortfall 95 %, 1 year, normal
    const Sw = mv(S, w);
    const rc = w.map((x, i) => x * Sw[i] / (vol * vol));
    return { vol, eg, ea, sharpe: (eg - rf) / vol, es, rc, ...histPath(w) };
  }
  function stressHist(w, win) {
    const start = H.start.split("-").map(Number);
    const off = (ym) => { const [y, m] = ym.split("-").map(Number); return (y - start[0]) * 12 + (m - start[1]); };
    let v = 1;
    for (let t = off(win.from); t <= off(win.to); t++) { let r = 0; for (let i = 0; i < N; i++) r += w[i] * H.returns[K[i]][t]; v *= 1 + r; }
    return v - 1;
  }
  const rateShock = -M.meta.bund_mod_duration * 0.01;
  const SCEN = [
    { name: "Zinsanstieg um 100 Basispunkte", shocks: { bund: rateShock } },
    { name: "Aktien Europa −25 %", shocks: { eq_eu: -0.25 } },
    { name: "Stagflation: Zinsanstieg und Aktien −20 %", shocks: { bund: rateShock, eq_eu: -0.20 } },
    { name: "Flucht in Sicherheit: Zinsen −75 Bp., Aktien −20 %", shocks: { bund: -0.75 * rateShock, eq_eu: -0.20 } },
  ];
  function scenario(w, S, shocks) {
    const sIdx = Object.keys(shocks).map(k => idx[k]);
    const sVal = Object.keys(shocks).map(k => shocks[k]);
    const Sss = sIdx.map(i => sIdx.map(j => S[i][j]));
    const x = solveLin(Sss, sVal);
    const r = K.map((_, i) => sIdx.includes(i) ? sVal[sIdx.indexOf(i)] : sIdx.reduce((s, j, a) => s + S[i][j] * x[a], 0));
    return { total: dot(w, r), r };
  }

  // ---------------------------------------------------------------- Monte Carlo
  function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function simulate(w, S) {
    const m = metrics(w, S);
    const infl = M.meta.inflation.value, cost = 0.005;
    // Uncertainty of the decade mean: the CMA bands (1 SD of a 10-year
    // outcome) contain both parameter uncertainty and ordinary return noise.
    // The noise part (sigma^2/10) is simulated year by year, so only the
    // remainder is drawn once per path as a persistent drift shift.
    const bandHalf = A.map(a => (a.band[1] - a.band[0]) / 2);
    const u = Math.abs(dot(w, bandHalf));
    const realMu = (1 + m.eg - cost) / (1 + infl) - 1;
    const logMu = Math.log(1 + realMu), sig = m.vol;
    const muSd = Math.sqrt(Math.max(u * u - sig * sig / 10, 0));
    const P = 3000, Hh = state.h, rand = rng(20260923);
    const gauss = () => { let u = 0, v = 0; while (u === 0) u = rand(); v = rand(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
    const paths = Array.from({ length: Hh + 1 }, () => new Float64Array(P));
    let preserved = 0, depleted = 0;
    const wdAmt = state.wd * state.w0;
    for (let p = 0; p < P; p++) {
      let W = state.w0; paths[0][p] = W;
      const drift = logMu + gauss() * muSd;
      for (let t = 1; t <= Hh; t++) {
        W = Math.max(0, W - wdAmt);
        W *= Math.exp(drift + sig * gauss()); // drift = log of the geometric mean, already net of volatility drag
        paths[t][p] = W;
      }
      if (W >= state.w0) preserved++;
      if (W <= 0) depleted++;
    }
    const q = (arr, pp) => { const s = Array.from(arr).sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor(pp * s.length))]; };
    const bands = paths.map(arr => [0.05, 0.25, 0.5, 0.75, 0.95].map(pp => q(arr, pp)));
    return { bands, pPreserve: preserved / P, pDeplete: depleted / P, realMu, sig, muSd };
  }

  // ---------------------------------------------------------------- SVG helpers
  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  function txt(parent, x, y, s, attrs = {}) { const t = el("text", { x, y, ...attrs }, parent); t.textContent = s; return t; }
  const lin = (d0, d1, r0, r1) => { const f = (x) => r0 + (x - d0) / (d1 - d0) * (r1 - r0); f.inv = (y) => d0 + (y - r0) / (r1 - r0) * (d1 - d0); return f; };
  function ticks(a, b, n) {
    const step0 = (b - a) / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map(s => s * mag).find(s => s >= step0);
    const out = []; for (let v = Math.ceil(a / step - 1e-9) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function frame(host, W, Hh, m) {
    host.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${Hh}`, role: "img" }, host);
    return { svg, x0: m.l, x1: W - m.r, y0: Hh - m.b, y1: m.t };
  }
  const tip = document.getElementById("tip");
  function hover(node, html) {
    const show = (e) => { tip.innerHTML = html(); tip.classList.add("on"); move(e); };
    const move = (e) => {
      const pt = e.touches ? e.touches[0] : e;
      const x = Math.min(window.innerWidth - tip.offsetWidth - 8, pt.clientX + 14);
      tip.style.left = x + "px"; tip.style.top = (pt.clientY + 14) + "px";
    };
    node.addEventListener("mouseenter", show); node.addEventListener("mousemove", move);
    node.addEventListener("mouseleave", () => tip.classList.remove("on"));
    node.addEventListener("touchstart", show, { passive: true });
    node.style.cursor = "default";
  }
  const width = (id) => Math.max(320, Math.min(1080, document.getElementById(id).clientWidth || 700));

  // ---------------------------------------------------------------- figure 1: CMA
  function drawCMA() {
    const W = width("fig-cma"), rowH = 34, m = { l: Math.min(210, W * 0.38), r: 20, t: 8, b: 30 };
    const Hh = m.t + m.b + rowH * N;
    const f = frame(document.getElementById("fig-cma"), W, Hh, m);
    const lo = -0.04, hi = 0.13;
    const x = lin(lo, hi, f.x0, f.x1);
    ticks(lo, hi, 6).forEach(t => {
      el("line", { x1: x(t), x2: x(t), y1: f.y1, y2: f.y0, class: t === 0 ? "zero" : "grid" }, f.svg);
      txt(f.svg, x(t), f.y0 + 18, pct(t, 0), { "text-anchor": "middle" });
    });
    A.forEach((a, i) => {
      const y = m.t + rowH * i + rowH / 2, e = state.exp[i];
      const shift = e - a.expected;
      el("rect", { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: "transparent" }, f.svg);
      el("circle", { cx: 8, cy: y - 4, r: 4.5, fill: color(a.key) }, f.svg);
      txt(f.svg, 18, y, a.name, { class: "lbl", "font-size": 12.5 });
      el("line", { x1: x(a.band[0] + shift), x2: x(a.band[1] + shift), y1: y, y2: y, stroke: color(a.key), "stroke-width": 2, "stroke-linecap": "round", opacity: .45 }, f.svg);
      el("circle", { cx: x(a.hist_geo), cy: y, r: 4.5, fill: "var(--bg)", stroke: "var(--ink2)", "stroke-width": 1.5 }, f.svg);
      el("circle", { cx: x(e), cy: y, r: 5.5, fill: color(a.key), stroke: "var(--bg)", "stroke-width": 2 }, f.svg);
      txt(f.svg, x(e), y - 10, pct(e), { "text-anchor": "middle", class: "lbl-strong", "font-size": 11 });
      const hit = el("rect", { x: f.x0, y: y - rowH / 2, width: f.x1 - f.x0, height: rowH, fill: "transparent" }, f.svg);
      hover(hit, () => `<b>${a.name}</b><br>Erwartet ${pct(e)} p. a. (Bandbreite ${pct(a.band[0] + shift)} bis ${pct(a.band[1] + shift)})<br>Realisiert 1990–2026 ${pct(a.hist_geo)} p. a.`);
    });
  }

  function herleitung(a) {
    const d = a.detail;
    if (a.key === "cash") return `Pfad von €STR ${pct(d.current, 2)} zu neutral ${pct(d.neutral, 2)}`;
    if (a.key === "bund") return `Startrendite 10 J. ${pct(d.yield, 2)}`;
    if (a.key === "credit") return `Verfallrendite ${pct(d.ytm, 2)} − Verluste ${pct(d.loss, 2)}`;
    if (a.key === "gold") return `Inflation ${pct(M.meta.inflation.value, 1)}, real ${spct(d.real, 1)}`;
    return `CAPE ${num(d.cape, 1)}: Regression ${pct(d.m1_regression_real)} real. Bausteine ${pct(d.m2_building_blocks_real)} real = Dividende ${pct(d.dy)} ${d.net_buyback >= 0 ? "+" : "−"} Rückkäufe netto ${pct(Math.abs(d.net_buyback))} + Wachstum ${pct(d.g_real)} ${d.reprice >= 0 ? "+" : "−"} Bewertung ${pct(Math.abs(d.reprice))}`;
  }
  function drawTable() {
    const tb = document.querySelector("#tbl-cma tbody");
    tb.innerHTML = "";
    A.forEach((a, i) => {
      const e = state.exp[i], shift = e - a.expected;
      const tr = document.createElement("tr");
      const infl = M.meta.inflation.value;
      tr.innerHTML = `<td><span class="sw" style="background:${color(a.key)}"></span>${a.name}</td>
        <td>${state.edit ? `<input class="cma" id="cma-${a.key}" type="number" step="0.1" value="${(e * 100).toFixed(2)}" aria-label="Erwartete Rendite ${a.name}">` : pct(e, 2)}</td>
        <td>${pct((1 + e) / (1 + infl) - 1, 2)}</td>
        <td>${pct(a.band[0] + shift)} bis ${pct(a.band[1] + shift)}</td>
        <td>${pct(Math.sqrt(SIG.all[i][i]))}</td>
        <td>${pct(a.hist_geo)}</td>
        <td class="derive">${herleitung(a)}</td>`;
      tb.appendChild(tr);
    });
    if (state.edit) tb.querySelectorAll("input.cma").forEach((inp, i) => inp.addEventListener("change", () => {
      const v = parseFloat(inp.value.replace(",", "."));
      if (!isNaN(v)) { state.exp[i] = v / 100; renderAll(true); }
    }));
  }

  // ---------------------------------------------------------------- figure 2: CAPE
  function drawCape() {
    const W = width("fig-cape"), Hh = Math.round(W * 0.72), m = { l: 44, r: 14, t: 16, b: 38 };
    const f = frame(document.getElementById("fig-cape"), W, Hh, m);
    const x = lin(5, 45, f.x0, f.x1), y = lin(-0.06, 0.18, f.y0, f.y1);
    ticks(-0.06, 0.18, 6).forEach(t => { el("line", { x1: f.x0, x2: f.x1, y1: y(t), y2: y(t), class: t === 0 ? "zero" : "grid" }, f.svg); txt(f.svg, f.x0 - 6, y(t) + 4, pct(t, 0), { "text-anchor": "end" }); });
    ticks(5, 45, 8).forEach(t => txt(f.svg, x(t), f.y0 + 16, num(t, 0), { "text-anchor": "middle" }));
    txt(f.svg, (f.x0 + f.x1) / 2, Hh - 4, "CAPE zu Beginn der Dekade", { "text-anchor": "middle", class: "lbl" });
    const g = el("g", {}, f.svg);
    M.cape.points.forEach(([d, c, r]) => {
      if (c < 5 || c > 45) return;
      const p = el("circle", { cx: x(c), cy: y(r), r: 2.6, fill: "var(--c-bund)", "fill-opacity": .32 }, g);
      hover(p, () => `<b>${monthName(d)}</b><br>CAPE ${num(c, 1)}<br>Reale Rendite der Folgedekade ${pct(r)} p. a.`);
    });
    let dpath = "";
    for (let c = 6; c <= 45; c += 0.5) dpath += (dpath ? "L" : "M") + x(c).toFixed(1) + "," + y(M.cape.alpha + M.cape.beta / c).toFixed(1);
    el("path", { d: dpath, fill: "none", stroke: "var(--ink)", "stroke-width": 2 }, f.svg);
    const cur = [["eq_eu", "Europa"], ["eq_em", "Schwellenl."], ["eq_us", "USA"]];
    cur.forEach(([k, lab], j) => {
      const c = M.cape.current[k], pr = M.cape.alpha + M.cape.beta / c;
      el("line", { x1: x(c), x2: x(c), y1: f.y1, y2: f.y0, stroke: color(k), "stroke-width": 1.5 }, f.svg);
      el("circle", { cx: x(c), cy: y(pr), r: 5, fill: color(k), stroke: "var(--bg)", "stroke-width": 2 }, f.svg);
      txt(f.svg, x(c) + 5, f.y1 + 12 + j * 14, `${lab} ${num(c, 1)}`, { class: "lbl-strong", "font-size": 11 });
    });
  }

  // ---------------------------------------------------------------- figure 3: bonds
  function drawBond() {
    const W = width("fig-bond"), Hh = Math.round(W * 0.72), m = { l: 44, r: 14, t: 16, b: 38 };
    const f = frame(document.getElementById("fig-bond"), W, Hh, m);
    const x = lin(0, 0.11, f.x0, f.x1), y = lin(-0.03, 0.12, f.y0, f.y1);
    ticks(-0.03, 0.12, 5).forEach(t => { el("line", { x1: f.x0, x2: f.x1, y1: y(t), y2: y(t), class: t === 0 ? "zero" : "grid" }, f.svg); txt(f.svg, f.x0 - 6, y(t) + 4, pct(t, 0), { "text-anchor": "end" }); });
    ticks(0, 0.11, 6).forEach(t => txt(f.svg, x(t), f.y0 + 16, pct(t, 0), { "text-anchor": "middle" }));
    txt(f.svg, (f.x0 + f.x1) / 2, Hh - 4, "Rendite 10 J. zu Beginn der Dekade", { "text-anchor": "middle", class: "lbl" });
    el("line", { x1: x(0), y1: y(0), x2: x(0.11), y2: y(0.11), stroke: "var(--ink)", "stroke-width": 1.5, "stroke-dasharray": "0" , opacity: .9}, f.svg);
    txt(f.svg, x(0.098), y(0.105) - 6, "45°-Linie", { class: "lbl", "text-anchor": "end" });
    M.bonds.points.forEach(([d, s, r]) => {
      const p = el("circle", { cx: x(s), cy: y(r), r: 2.6, fill: "var(--c-bund)", "fill-opacity": .45 }, f.svg);
      hover(p, () => `<b>${monthName(d)}</b><br>Startrendite ${pct(s, 2)}<br>Rendite der Folgedekade ${pct(r, 2)} p. a.`);
    });
    const now = state.exp[idx.bund];
    el("line", { x1: x(now), x2: x(now), y1: f.y1, y2: f.y0, stroke: "var(--c-bund)", "stroke-width": 1.5 }, f.svg);
    el("circle", { cx: x(now), cy: y(now), r: 5, fill: "var(--c-bund)", stroke: "var(--bg)", "stroke-width": 2 }, f.svg);
    txt(f.svg, x(now) + 6, f.y1 + 12, `Heute ${pct(now, 1)}`, { class: "lbl-strong" });
  }

  // ---------------------------------------------------------------- figure 4: rolling correlation
  function drawCorr() {
    const W = width("fig-corr"), Hh = Math.max(220, Math.round(W * 0.3)), m = { l: 40, r: 58, t: 14, b: 26 };
    const f = frame(document.getElementById("fig-corr"), W, Hh, m);
    const pts = M.stock_bond_corr;
    const t0 = +pts[0][0].slice(0, 4) + (+pts[0][0].slice(5) - 1) / 12, t1 = +pts[pts.length - 1][0].slice(0, 4) + (+pts[pts.length - 1][0].slice(5) - 1) / 12;
    const tx = (d) => +d.slice(0, 4) + (+d.slice(5) - 1) / 12;
    const x = lin(t0, t1, f.x0, f.x1), y = lin(-0.8, 0.8, f.y0, f.y1);
    [-0.8, -0.4, 0, 0.4, 0.8].forEach(t => { el("line", { x1: f.x0, x2: f.x1, y1: y(t), y2: y(t), class: t === 0 ? "zero" : "grid" }, f.svg); txt(f.svg, f.x0 - 6, y(t) + 4, num(t, 1), { "text-anchor": "end" }); });
    for (let yr = 1995; yr <= 2025; yr += 5) txt(f.svg, x(yr), f.y0 + 17, yr, { "text-anchor": "middle" });
    // shade positive stretches
    let run = null;
    pts.forEach(([d, v], i) => {
      if (v > 0 && run === null) run = i;
      if ((v <= 0 || i === pts.length - 1) && run !== null) {
        const e = v <= 0 ? i : i;
        el("rect", { x: x(tx(pts[run][0])), y: f.y1, width: Math.max(1, x(tx(pts[e][0])) - x(tx(pts[run][0]))), height: f.y0 - f.y1, fill: "var(--c-eq_eu)", "fill-opacity": .09 }, f.svg);
        run = null;
      }
    });
    let d = "";
    pts.forEach(([t, v]) => { d += (d ? "L" : "M") + x(tx(t)).toFixed(1) + "," + y(v).toFixed(1); });
    el("path", { d, fill: "none", stroke: "var(--ink)", "stroke-width": 2, "stroke-linejoin": "round" }, f.svg);
    const last = pts[pts.length - 1];
    el("circle", { cx: x(tx(last[0])), cy: y(last[1]), r: 4.5, fill: "var(--ink)", stroke: "var(--bg)", "stroke-width": 2 }, f.svg);
    txt(f.svg, x(tx(last[0])) + 8, y(last[1]) + 4, num(last[1], 2), { class: "lbl-strong" });
    txt(f.svg, f.x0 + 6, y(0.8) + 13, "Positive Korrelation: Inflationsregime", { class: "lbl" });
    txt(f.svg, f.x0 + 6, y(-0.8) - 6, "Negative Korrelation: Anleihen sichern ab", { class: "lbl" });
    // hover layer
    const hit = el("rect", { x: f.x0, y: f.y1, width: f.x1 - f.x0, height: f.y0 - f.y1, fill: "transparent" }, f.svg);
    const cross = el("line", { y1: f.y1, y2: f.y0, stroke: "var(--muted)", "stroke-width": 1, opacity: 0 }, f.svg);
    let cur = null;
    hit.addEventListener("mousemove", (e) => {
      const r = f.svg.getBoundingClientRect(), sx = (e.clientX - r.left) * W / r.width;
      const tt = x.inv(sx); cur = pts.reduce((b, p) => Math.abs(tx(p[0]) - tt) < Math.abs(tx(b[0]) - tt) ? p : b);
      cross.setAttribute("x1", x(tx(cur[0]))); cross.setAttribute("x2", x(tx(cur[0]))); cross.setAttribute("opacity", 1);
    });
    hit.addEventListener("mouseleave", () => cross.setAttribute("opacity", 0));
    hover(hit, () => cur ? `<b>${monthName(cur[0])}</b><br>Korrelation ${num(cur[1], 2)}` : "");
    const nPos = M.cov.info.pos.n_months, nNeg = M.cov.info.neg.n_months;
    document.getElementById("cap-corr").innerHTML = `Aktuell <b>${num(last[1], 2)}</b> (${monthName(last[0])}). Schattiert: Phasen mit positiver Korrelation, ${nPos} von ${nPos + nNeg} Monaten. Korrelation Aktien Europa zu Bundesanleihen im Inflationsregime <b>${num(corrOf("pos", "eq_eu", "bund"), 2)}</b>, im Wachstumsregime <b>${num(corrOf("neg", "eq_eu", "bund"), 2)}</b>.`;
  }
  function corrOf(r, a, b) { const S = SIG[r], i = idx[a], j = idx[b]; return S[i][j] / Math.sqrt(S[i][i] * S[j][j]); }

  // ---------------------------------------------------------------- portfolio figures
  function drawWeights(w, rc) {
    const W = width("fig-weights"), rowH = 30, m = { l: Math.min(150, W * 0.36), r: 14, t: 24, b: 8 };
    const Hh = m.t + m.b + rowH * N;
    const f = frame(document.getElementById("fig-weights"), W, Hh, m);
    const gap = 16, colW = (f.x1 - f.x0 - gap) / 2;
    const xw = lin(0, 0.6, f.x0, f.x0 + colW), xr = lin(0, 0.6, f.x0 + colW + gap, f.x1);
    txt(f.svg, f.x0, 12, "Gewicht", { class: "lbl-strong" });
    txt(f.svg, f.x0 + colW + gap, 12, "Risikobeitrag", { class: "lbl-strong" });
    A.forEach((a, i) => {
      const y = m.t + rowH * i + rowH / 2;
      el("circle", { cx: 8, cy: y - 4, r: 4.5, fill: color(a.key) }, f.svg);
      txt(f.svg, 18, y, SHORT[a.key], { class: "lbl", "font-size": 12 });
      const bw = Math.max(0, xw(w[i]) - xw(0));
      el("rect", { x: xw(0), y: y - 8, width: Math.max(bw, 0.5), height: 12, fill: color(a.key), rx: 2 }, f.svg);
      el("line", { x1: xw(wRef[i]), x2: xw(wRef[i]), y1: y - 11, y2: y + 7, stroke: "var(--ink)", "stroke-width": 1.5 }, f.svg);
      const lx = Math.max(xw(0) + bw, xw(wRef[i])) + 6;
      txt(f.svg, Math.min(lx, xw(0.6) - 2), y + 2, pct(w[i], 0), { class: "lbl-strong", "font-size": 11, "text-anchor": lx > xw(0.6) - 30 ? "end" : "start" });
      const rb = Math.max(0, xr(Math.max(rc[i], 0)) - xr(0));
      el("rect", { x: xr(0), y: y - 8, width: Math.max(rb, 0.5), height: 12, fill: color(a.key), rx: 2, opacity: .55 }, f.svg);
      txt(f.svg, Math.min(xr(0) + rb + 5, f.x1 - 2), y + 2, pct(rc[i], 0), { class: "lbl", "font-size": 11, "text-anchor": xr(0) + rb + 5 > f.x1 - 30 ? "end" : "start" });
      const hit = el("rect", { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: "transparent" }, f.svg);
      hover(hit, () => `<b>${a.name}</b><br>Gewicht ${pct(w[i])} (Referenz ${pct(wRef[i], 0)})<br>Anteil am Portfoliorisiko ${pct(rc[i])}<br>Obergrenze ${pct(UB[i], 0)}`);
    });
  }
  function drawFrontier(front, S, w, wR) {
    const W = width("fig-frontier"), Hh = Math.round(W * 0.78), m = { l: 44, r: 16, t: 14, b: 38 };
    const f = frame(document.getElementById("fig-frontier"), W, Hh, m);
    const muA = arith(state.exp, S);
    const pt = (ww) => { const v = Math.sqrt(quad(S, ww)); return [v, dot(muA, ww) - v * v / 2]; };
    const assetPts = K.map((k, i) => [Math.sqrt(S[i][i]), state.exp[i]]);
    const fp = front.map(pt).sort((a, b) => a[0] - b[0]);
    const ymax = Math.max(0.07, ...assetPts.map(p => p[1]), ...fp.map(p => p[1])) + 0.005;
    const ymin = Math.min(0.0, ...assetPts.map(p => p[1])) - 0.002;
    const x = lin(0, 0.22, f.x0, f.x1), y = lin(ymin, ymax, f.y0, f.y1);
    ticks(ymin, ymax, 5).forEach(t => { el("line", { x1: f.x0, x2: f.x1, y1: y(t), y2: y(t), class: t === 0 ? "zero" : "grid" }, f.svg); txt(f.svg, f.x0 - 6, y(t) + 4, pct(t, 0), { "text-anchor": "end" }); });
    ticks(0, 0.22, 6).forEach(t => txt(f.svg, x(t), f.y0 + 16, pct(t, 0), { "text-anchor": "middle" }));
    txt(f.svg, (f.x0 + f.x1) / 2, Hh - 4, "Volatilität p. a.", { "text-anchor": "middle", class: "lbl" });
    let d = ""; fp.forEach(p => d += (d ? "L" : "M") + x(p[0]).toFixed(1) + "," + y(p[1]).toFixed(1));
    el("path", { d, fill: "none", stroke: "var(--ink)", "stroke-width": 2 }, f.svg);
    assetPts.forEach((p, i) => {
      el("circle", { cx: x(p[0]), cy: y(p[1]), r: 4.5, fill: color(K[i]), stroke: "var(--bg)", "stroke-width": 2 }, f.svg);
      const short = { cash: "Geldmarkt", bund: "Bund", credit: "Credit", eq_eu: "Europa", eq_us: "USA", eq_em: "EM", gold: "Gold" }[K[i]];
      txt(f.svg, x(p[0]) + 7, y(p[1]) + 4, short, { class: "lbl", "font-size": 10.5 });
    });
    const r = pt(wR);
    el("rect", { x: x(r[0]) - 4.5, y: y(r[1]) - 4.5, width: 9, height: 9, fill: "var(--bg)", stroke: "var(--ink)", "stroke-width": 1.5 }, f.svg);
    txt(f.svg, x(r[0]) + 8, y(r[1]) + 14, "Referenz", { class: "lbl" });
    const p = pt(w);
    el("circle", { cx: x(p[0]), cy: y(p[1]), r: 7, fill: "var(--accent)", stroke: "var(--bg)", "stroke-width": 2 }, f.svg);
    txt(f.svg, x(p[0]) - 9, y(p[1]) - 9, "Portfolio", { class: "lbl-strong", "text-anchor": "end" });
  }

  // ---------------------------------------------------------------- fan chart
  function drawFan(sim) {
    const W = width("fig-fan"), Hh = Math.max(240, Math.round(W * 0.36)), m = { l: 64, r: 70, t: 12, b: 28 };
    const f = frame(document.getElementById("fig-fan"), W, Hh, m);
    const B = sim.bands, Hy = B.length - 1;
    const ymax = Math.max(state.w0 * 1.2, ...B.map(b => b[4])) * 1.02;
    const x = lin(0, Hy, f.x0, f.x1), y = lin(0, ymax, f.y0, f.y1);
    ticks(0, ymax, 5).forEach(t => { el("line", { x1: f.x0, x2: f.x1, y1: y(t), y2: y(t), class: t === 0 ? "zero" : "grid" }, f.svg); txt(f.svg, f.x0 - 6, y(t) + 4, eur(t).replace(" Mio. €", " Mio."), { "text-anchor": "end" }); });
    ticks(0, Hy, Math.min(Hy, 6)).forEach(t => txt(f.svg, x(t), f.y0 + 17, t === 0 ? "heute" : `${t} J.`, { "text-anchor": "middle" }));
    const band = (a, b, op) => {
      let d = ""; B.forEach((q, t) => d += (t ? "L" : "M") + x(t).toFixed(1) + "," + y(q[a]).toFixed(1));
      for (let t = Hy; t >= 0; t--) d += "L" + x(t).toFixed(1) + "," + y(B[t][b]).toFixed(1);
      el("path", { d: d + "Z", fill: "var(--accent)", "fill-opacity": op }, f.svg);
    };
    band(0, 4, 0.12); band(1, 3, 0.2);
    el("line", { x1: f.x0, x2: f.x1, y1: y(state.w0), y2: y(state.w0), stroke: "var(--ink2)", "stroke-width": 1, "stroke-dasharray": "3 3" }, f.svg);
    txt(f.svg, f.x0 + 4, y(state.w0) - 5, "Anfangsvermögen, real", { class: "lbl" });
    let d = ""; B.forEach((q, t) => d += (t ? "L" : "M") + x(t).toFixed(1) + "," + y(q[2]).toFixed(1));
    el("path", { d, fill: "none", stroke: "var(--accent)", "stroke-width": 2 }, f.svg);
    const lastQ = B[Hy];
    [[4, "95 %"], [2, "Median"], [0, "5 %"]].forEach(([k, lab]) => txt(f.svg, f.x1 + 6, y(lastQ[k]) + 4, lab, { class: k === 2 ? "lbl-strong" : "lbl" }));
    const hit = el("rect", { x: f.x0, y: f.y1, width: f.x1 - f.x0, height: f.y0 - f.y1, fill: "transparent" }, f.svg);
    const cross = el("line", { y1: f.y1, y2: f.y0, stroke: "var(--muted)", "stroke-width": 1, opacity: 0 }, f.svg);
    let cur = 0;
    hit.addEventListener("mousemove", (e) => { const r = f.svg.getBoundingClientRect(); cur = Math.round(x.inv((e.clientX - r.left) * W / r.width)); cur = Math.max(0, Math.min(Hy, cur)); cross.setAttribute("x1", x(cur)); cross.setAttribute("x2", x(cur)); cross.setAttribute("opacity", 1); });
    hit.addEventListener("mouseleave", () => cross.setAttribute("opacity", 0));
    hover(hit, () => `<b>Jahr ${cur}</b><br>95 %: ${eur(B[cur][4])}<br>75 %: ${eur(B[cur][3])}<br>Median: ${eur(B[cur][2])}<br>25 %: ${eur(B[cur][1])}<br>5 %: ${eur(B[cur][0])}`);
  }

  // ---------------------------------------------------------------- tables: stress
  function drawStress(w, S) {
    const th = document.querySelector("#tbl-hist thead"), tb = document.querySelector("#tbl-hist tbody");
    th.innerHTML = `<tr><th>Episode</th><th>Zeitraum</th><th>Portfolio</th><th>Referenz</th>${K.map(k => `<th title="${name(k)}"><span class="sw" style="background:${color(k)}"></span>${({ cash: "Geldm.", bund: "Bund", credit: "Credit", eq_eu: "Europa", eq_us: "USA", eq_em: "EM", gold: "Gold" })[k]}</th>`).join("")}</tr>`;
    tb.innerHTML = "";
    M.stress.forEach(s => {
      const p = stressHist(w, s), r = stressHist(wRef, s);
      const cls = (v) => v < 0 ? "neg" : "";
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${s.name}${s.credit_reconstructed ? '<sup class="muted">*</sup>' : ""}</td><td class="muted">${monthName(s.from)} bis ${monthName(s.to)}</td>
        <td class="${cls(p)}"><b>${spct(p)}</b></td><td class="${cls(r)}">${spct(r)}</td>
        ${K.map(k => `<td class="${cls(s.returns[k])}">${spct(s.returns[k], 0)}</td>`).join("")}`;
      tb.appendChild(tr);
    });
    const th2 = document.querySelector("#tbl-hyp thead"), tb2 = document.querySelector("#tbl-hyp tbody");
    th2.innerHTML = `<tr><th>Schock</th><th>Inflationsregime</th><th>Gesamt</th><th>Wachstumsregime</th><th>Referenz, Inflationsregime</th></tr>`;
    tb2.innerHTML = "";
    SCEN.forEach(sc => {
      const v = ["pos", "all", "neg"].map(r => scenario(w, SIG[r], sc.shocks).total);
      const ref = scenario(wRef, SIG.pos, sc.shocks).total;
      const cls = (x) => x < 0 ? "neg" : "pos";
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${sc.name}</td>${v.map((x, j) => `<td class="${cls(x)}">${j === ["pos", "all", "neg"].indexOf(state.regime) ? "<b>" + spct(x) + "</b>" : spct(x)}</td>`).join("")}<td class="${cls(ref)}">${spct(ref)}</td>`;
      tb2.appendChild(tr);
    });
    document.getElementById("stress-note").innerHTML = `* Unternehmensanleihen vor ${monthName(M.meta.credit_observed_from)} rekonstruiert aus Geldmarkt, Bundesanleihen und Aktien Europa (R² ${num(M.meta.credit_backfill.r2, 2)}). Die Rekonstruktion bildet Spread-Bewegungen nur teilweise ab und ist für diese Episoden nur grob. Ein Zinsschock von 100 Bp. entspricht bei einer modifizierten Duration von ${num(M.meta.bund_mod_duration, 1)} einem Kursverlust der Bundesanleihe von ${pct(-rateShock)}. Fettgedruckt ist das im Portfolio gewählte Regime.`;
  }

  // ---------------------------------------------------------------- method text
  function method() {
    const c = M.cape, b = M.bonds, g = M.gold;
    const src = (a) => A[idx[a]].detail;
    document.getElementById("method-body").innerHTML = `
      <h3>Daten</h3>
      <ul>
        <li>Aktien: Marktrenditen des Kenneth R. French Data Library für USA (seit 1926), Europa (seit 1990) und Schwellenländer (seit 1989), in USD, umgerechnet mit EZB-Referenzkursen, vor 1999 D-Mark zum Kurs 1,95583.${bridgeText()}</li>
        <li>Bundesanleihen: Monatsend-Rendite 10 J. der Bundesbank-Zinsstrukturkurve (Svensson) seit 1972. Die Rendite einer rollierenden 10-jährigen Parianleihe wird exakt aus Kupon und Kursänderung berechnet, nicht über eine Durationsnäherung.</li>
        <li>Unternehmensanleihen: iShares Core € Corp Bond (Bloomberg Euro Corporate Index) seit ${monthName(M.meta.credit_observed_from)}. Für die Zeit davor und für die Kovarianzschätzung dient die Projektion nach Stambaugh (1997).</li>
        <li>Geldmarkt: 3-Monats-Zins Deutschland (OECD via FRED), für die jüngsten Monate 3-Monats-Euribor der EZB. Gold: Monatsendkurs des COMEX-Futures (GC=F) ab ${monthName(M.meta.gold_eom_from)}, einzelne fehlende Monate aus Weltbank-Monatsdurchschnitten interpoliert. Davor nur Weltbank-Monatsdurchschnitte, die die Schwankung leicht glätten. Inflation: VPI Deutschland, ab 2025 HVPI.</li>
        <li>Aktualisierung: Alle Reihen werden zweimal im Monat, am 6. und am 20., automatisch neu geladen und das Modell neu gerechnet. CAPE und Dividendenrenditen der Regionen stammen aus Stichtagswerten (CAPE ${monthName(M.meta.anchors.cape_month)}) und werden bis zur nächsten Pflege mit der Kursentwicklung fortgeschrieben.</li>
        <li>Stichprobe für Risiko und Stresstests: ${monthName(M.meta.sample[0])} bis ${monthName(M.meta.sample[1])}, ${M.cov.info.all.n_months} Monate.</li>
      </ul>
      <p>Kontrolle gegen investierbare ETFs in EUR: Die konstruierten Reihen laufen eng mit den Fonds. Die Indexreihen liegen ohne Kosten und Quellensteuern und mit breiterem Aktienuniversum etwas über den Fondsrenditen.</p>
      <div class="tablewrap"><table>
        <thead><tr><th>Reihe</th><th>Vergleichs-ETF</th><th>Zeitraum</th><th>Korrelation</th><th>Rendite Modell p. a.</th><th>Rendite ETF p. a.</th></tr></thead>
        <tbody>${M.validation.map(v => `<tr><td>${name(v.key)}</td><td style="white-space:normal">${v.etf}</td><td>${monthName(v.from)} bis ${monthName(v.to)}</td><td>${num(v.corr, 2)}</td><td>${pct(v.geo_model)}</td><td>${pct(v.geo_etf)}</td></tr>`).join("")}</tbody>
      </table></div>
      <p class="small sans ink2" style="margin-top:.6rem">Bundesanleihen: Der Vergleichsfonds enthält alle Laufzeiten und hat eine kürzere Duration als die 10-jährige Modellanleihe. Daher die niedrigere Korrelation.</p>
      <h3>Renditeannahmen</h3>
      <p>Die CAPE-Regression nutzt Shillers Monatsdaten für die USA von ${c.sample[0].slice(0, 4)} bis ${c.sample[1].slice(0, 4)} (Startzeitpunkte). Geschätzt wird die reale Rendite der Folgedekade auf 1/CAPE: Steigung ${num(c.beta, 2)} (HAC-Standardfehler ${num(c.se_beta, 2)}, Newey-West mit 120 Lags), R² ${num(c.r2, 2)}. Wegen überlappender Zehnjahresfenster enthält die Stichprobe nur etwa ${num(c.n_indep, 0)} unabhängige Beobachtungen. Ein Out-of-sample-Test ab ${c.oos_start.slice(0, 4)}, der nur zum jeweiligen Zeitpunkt bekannte Daten nutzt, ergibt ein R² von ${num(c.oos_r2, 2)} gegenüber dem historischen Mittel. Der Standardfehler einer einzelnen Dekade liegt bei ${pct(c.resid_sd)} p. a. Das ist die Bandbreite in Tabelle 3.</p>
      <p>Die Bausteinrechnung folgt dem Grinold-Kroner-Schema: Dividendenrendite plus Nettorückkaufrendite (abzüglich Verwässerung durch Neuemissionen) plus reales Wachstum der Gesamtgewinne plus Bewertungsänderung. Für die Bewertung wird angenommen, dass sich die Hälfte der Lücke zwischen heutigem und langfristigem CAPE über zehn Jahre schließt.</p>
      <div class="tablewrap"><table>
        <thead><tr><th>Region</th><th>CAPE</th><th>Fairer CAPE</th><th>Dividende</th><th>Rückkäufe netto</th><th>Wachstum real</th><th>Bewertung p. a.</th><th>Bausteine real</th></tr></thead>
        <tbody>${["eq_eu", "eq_us", "eq_em"].map(k => { const d = src(k); return `<tr><td>${name(k)}</td><td>${num(d.cape, 1)}</td><td>${num(d.cape_fair, 0)}</td><td>${pct(d.dy, 2)}</td><td>${spct(d.net_buyback, 1)}</td><td>${pct(d.g_real, 1)}</td><td>${spct(d.reprice, 1)}</td><td>${pct(d.m2_building_blocks_real, 1)}</td></tr>`; }).join("")}</tbody>
      </table></div>
      <p class="small sans ink2" style="margin-top:.6rem">Rückkäufe netto: in den USA etwa die Hälfte der Bruttorückkäufe von rund 1,8 % des Börsenwerts, in Europa ebenso. Schwellenländer verwässern durch Neuemissionen, daher negativ. Wachstum: reales Potenzialwachstum der Region. Fairer CAPE der USA: Median seit 1950 (20,9).</p>
      <p>Der Schwellenländer-CAPE ist aus Länderwerten aggregiert und deckt 80 % des Index ab. Zusammen mit der Verwässerungsannahme ist er die unsicherste Eingabe des Modells.</p>
      <p>Für Bundesanleihen erklärt die Startrendite ${num(b.r2 * 100, 0)} % der Streuung der Folgerenditen (${b.sample[0].slice(0, 4)} bis ${b.sample[1].slice(0, 4)}, Steigung ${num(b.slope, 2)}). Der mittlere absolute Fehler beträgt ${num(b.mae * 100, 1)} Prozentpunkte. Gold liegt real auf dem ${num(g.percentile * 100, 0)}. Perzentil seit 1975, beim ${num(g.ratio_to_median, 1)}-fachen des Medians. Das begründet die leicht negative reale Annahme.</p>
      <h3>Risiko und Portfoliokonstruktion</h3>
      <p>Kovarianzen stammen aus Monatsrenditen in EUR mit Ledoit-Wolf-Schrumpfung zur konstanten Korrelation. Die Regime entstehen aus dem Vorzeichen der rollierenden 36-Monats-Korrelation zwischen Aktien Europa und Bundesanleihen. Erwartete arithmetische Renditen ergeben sich aus den geometrischen Annahmen plus halber Varianz. Der Anker ist ein Referenzportfolio aus 53 % Aktien (22 % Europa, 23 % USA, 8 % Schwellenländer), 35 % Anleihen, 5 % Geldmarkt und 7 % Gold. Seine implizierten Gleichgewichtsrenditen werden mit den Kapitalmarktannahmen gemischt. Die Optimierung löst das quadratische Problem mit Obergrenzen je Klasse und ohne Leerverkäufe. Ausgewiesene erwartete Renditen stammen immer aus den Kapitalmarktannahmen, nicht aus der Mischung.</p>
      <h3>Taktische Signale und Portfolio-Check</h3>
      <p>Bewertung: Aktien über den Abstand zwischen heutigem und fairem CAPE (logarithmisch, ein Faktor 1,5 entspricht dem vollen Ausschlag). Bundesanleihen über die Realrendite im Vergleich zu den Realrenditen seit 1990. Unternehmensanleihen über den Aufschlag zur AAA-Kurve gegenüber einem Normalwert von 1,2 Prozentpunkten. Gold über das Perzentil des realen Preises seit 1975. Trend: Überrendite der letzten zwölf Monate gegenüber Geldmarkt, geteilt durch die Volatilität der letzten 36 Monate, begrenzt auf ±1,5 und auf ±1 skaliert.</p>
      <p>Die Bewertung wirkt nur strategisch, über die erwarteten Renditen im Optimierer. Der Trend verschiebt die strategische Quote um bis zu ±5 Prozentpunkte bei Aktien und Bundesanleihen und ±3 Prozentpunkte bei Unternehmensanleihen, Schwellenländern und Gold. Im Test wurden Bewertungssignale ohne Vorwissen gebildet: fairer CAPE als laufender Median seit 1950, Perzentile nur aus bis dahin bekannten Daten. Für Europa, Schwellenländer und Unternehmensanleihen fehlt eine lange Bewertungshistorie, dort testet die Bewertungsvariante nichts.</p>
      <p>Der Portfolio-Check zerlegt Fonds anhand gerundeter Länderanteile. Einzelaktien und enge Indizes erhalten ein titelspezifisches Zusatzrisiko (Einzelaktie 30 % p. a., Nasdaq-100 10 %, DAX 8 %, EURO STOXX 50 5 %), aber keine eigene Renditeerwartung. Das Modellportfolio hat dasselbe Marktrisiko wie das Depot, weicht je Anlageklasse höchstens 10 Prozentpunkte vom Referenzportfolio ab und enthält die taktischen Verschiebungen.</p>
      <h3>Was das Modell nicht leistet</h3>
      <ul>
        <li>Es ist kein Timing-Instrument. Bewertungskennzahlen erklären Dekaden, kaum einzelne Jahre.</li>
        <li>Die CAPE-Regression ist auf US-Daten geschätzt und auf andere Regionen übertragen. Strukturelle Unterschiede in Sektormix und Bilanzierung bleiben unberücksichtigt.</li>
        <li>Die Regime sind am Ergebnis selbst abgegrenzt (Vorzeichen der Korrelation). Das beschreibt vergangene Phasen gut, sagt aber nicht voraus, wann ein Regimewechsel kommt.</li>
        <li>Normalverteilte Renditen unterschätzen extreme Verluste. Die historischen Stresstests ergänzen die Kennzahlen deshalb.</li>
        <li>Illiquide Anlagen, die in Family Offices großes Gewicht haben (Private Equity, direkte Immobilien), fehlen mangels verlässlicher öffentlicher Daten.</li>
        <li>Steuern, Währungsabsicherung und Rebalancing-Kosten sind nicht modelliert. Die Projektion zieht pauschal 0,5 % Kosten p. a. ab.</li>
      </ul>`;
  }

  // ---------------------------------------------------------------- render
  let lastPF = null;
  function renderPortfolio() {
    const S = SIG[state.regime];
    const mu = blendedMu(S);
    const sol = targetVol(mu, S, state.vol);
    const w = sol.w, mt = metrics(w, S), mr = metrics(wRef, S);
    lastPF = { w, mt, S };
    document.getElementById("out-vol").textContent = pct(state.vol, 1);
    document.getElementById("out-conf").textContent = nf(0).format(state.conf * 100) + " %";
    const eqShare = w[idx.eq_eu] + w[idx.eq_us] + w[idx.eq_em];
    document.getElementById("hint-vol").textContent = `Aktienquote ${pct(eqShare, 0)}. ` + (sol.bound === "max" ? "Obergrenzen erlauben kein höheres Risiko." : sol.bound === "min" ? "Niedrigeres Risiko ist mit den Grenzen nicht erreichbar." : "Referenzportfolio: " + pct(mr.vol, 1) + ".");
    document.getElementById("hint-regime").textContent = `${REGIME_LABEL[state.regime]}: Korrelation Aktien zu Bunds ${num(corrOf(state.regime, "eq_eu", "bund"), 2)}. ${state.regime === "pos" ? "Entspricht der aktuellen Lage." : ""}`;
    const stat = (v, k, sub) => `<div class="stat"><div class="v">${v}${sub ? `<small>${sub}</small>` : ""}</div><div class="k">${k}</div></div>`;
    document.getElementById("pf-stats").innerHTML =
      stat(pct(mt.eg), "Erwartete Rendite p. a., nominal", "Ref. " + pct(mr.eg)) +
      stat(pct(mt.vol), "Volatilität p. a.", "Ref. " + pct(mr.vol)) +
      stat(num(mt.sharpe, 2), "Sharpe-Ratio über Geldmarkt", "Ref. " + num(mr.sharpe, 2)) +
      stat(spct(-mt.es), "Expected Shortfall 95 %, 1 Jahr", "Ref. " + spct(-mr.es)) +
      stat(spct(mt.mdd), "Max. Drawdown 1990–2026, historisch", "Ref. " + spct(mr.mdd));
    drawWeights(w, mt.rc);
    drawFrontier(frontier(mu, S), S, w, wRef);
    const top = K.map((k, i) => [k, w[i] - wRef[i]]).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 2);
    document.getElementById("pf-note").innerHTML = `Größte Abweichungen zum Referenzportfolio: ${top.map(([k, d]) => `${name(k)} ${spct(d, 0)}`).join(", ")}. Erwartete reale Rendite nach Inflation ${pct((1 + mt.eg) / (1 + M.meta.inflation.value) - 1)} p. a. Die historische Rendite dieser Gewichte 1990–2026 wäre ${pct(mt.cagr)} p. a. gewesen, mit dem schlechtesten 12-Monats-Ergebnis von ${spct(mt.worst12)}.`;
    renderKeyfigs(mt);
    renderMC();
    drawStress(w, S);
  }
  function renderMC() {
    if (!lastPF) return;
    document.getElementById("out-wd").textContent = pct(state.wd, 2).replace(",00", "");
    document.getElementById("out-h").textContent = state.h + " Jahre";
    const sim = simulate(lastPF.w, lastPF.S);
    const endB = sim.bands[state.h];
    const stat = (v, k) => `<div class="stat"><div class="v">${v}</div><div class="k">${k}</div></div>`;
    document.getElementById("mc-stats").innerHTML =
      stat(pct(sim.pPreserve, 0), `Wahrscheinlichkeit, nach ${state.h} Jahren real mindestens das Anfangsvermögen zu halten`) +
      stat(eur(endB[2]), "Median Endvermögen, real") +
      stat(eur(endB[0]), "Ungünstiges Szenario (5 %-Quantil), real") +
      stat(eur(state.wd * state.w0), "Entnahme p. a., in heutiger Kaufkraft") +
      stat(pct(sim.realMu), "Erwartete reale Rendite nach Kosten");
    drawFan(sim);
  }
  function renderKeyfigs(mt) {
    const eu = A[idx.eq_eu], us = A[idx.eq_us];
    const corr = M.stock_bond_corr[M.stock_bond_corr.length - 1][1];
    const kf = (v, k) => `<div class="keyfig"><div class="v">${v}</div><div class="k">${k}</div></div>`;
    document.getElementById("keyfigs").innerHTML =
      kf(pct(state.exp[idx.bund]), "Erwartete Rendite Bundesanleihen 10 J., p. a.") +
      kf(pct(state.exp[idx.eq_us]) + " / " + pct(state.exp[idx.eq_eu]), "Aktien USA und Europa, erwartet p. a. in EUR") +
      kf((corr > 0 ? "+" : "−") + num(Math.abs(corr), 2), "Korrelation Aktien zu Bunds, 36 Monate") +
      kf(pct(mt.eg), `Portfolio mit ${pct(state.vol, 0)} Volatilität, erwartet p. a.`);
  }
  function renderAll(fromEdit) {
    drawCMA(); if (!fromEdit) drawTable();
    drawCape(); drawBond(); drawCorr();
    renderPortfolio();
    document.getElementById("cap-cape").innerHTML = `Jeder Punkt ist ein Startquartal ${M.cape.sample[0].slice(0, 4)} bis ${M.cape.sample[1].slice(0, 4)}. Linie: Regression auf 1/CAPE, R² <b>${num(M.cape.r2, 2)}</b>, out of sample <b>${num(M.cape.oos_r2, 2)}</b>. Senkrechte Linien: heutige Bewertung je Region, Punkt: implizierte reale Rendite.`;
    document.getElementById("cap-bond").innerHTML = `Rollierende Parianleihe mit 10 Jahren Laufzeit, Startmonate ${M.bonds.sample[0].slice(0, 4)} bis ${M.bonds.sample[1].slice(0, 4)}. Die Punkte liegen eng an der 45°-Linie: R² <b>${num(M.bonds.r2, 2)}</b>, mittlerer Fehler ${num(M.bonds.mae * 100, 1)} Prozentpunkte.`;
  }

  // ---------------------------------------------------------------- wiring
  document.getElementById("asof").textContent = "Stand " + new Date(M.meta.as_of).toLocaleDateString("de-DE", { day: "numeric", month: "long", year: "numeric" });
  document.getElementById("foot-build").textContent = `Daten bis ${monthName(M.meta.sample[1])}, Marktstand ${new Date(M.meta.as_of).toLocaleDateString("de-DE")}`;
  const on = (id, ev, fn) => document.getElementById(id).addEventListener(ev, fn);
  on("in-vol", "input", (e) => { state.vol = +e.target.value / 100; renderPortfolio(); });
  on("in-conf", "input", (e) => { state.conf = +e.target.value / 100; renderPortfolio(); });
  document.querySelectorAll("#seg-regime button").forEach(b => b.addEventListener("click", () => {
    state.regime = b.dataset.v;
    document.querySelectorAll("#seg-regime button").forEach(x => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    renderPortfolio();
  }));
  on("in-wd", "input", (e) => { state.wd = +e.target.value / 100; renderMC(); });
  on("in-h", "input", (e) => { state.h = +e.target.value; renderMC(); });
  on("in-w0", "change", (e) => {
    const v = parseFloat(e.target.value.replace(/\./g, "").replace(",", "."));
    if (v > 0) { state.w0 = v; e.target.value = nf(0).format(v); renderMC(); } else e.target.value = nf(0).format(state.w0);
  });
  on("btn-edit", "click", () => {
    state.edit = !state.edit;
    document.getElementById("btn-edit").setAttribute("aria-pressed", String(state.edit));
    document.getElementById("btn-edit").textContent = state.edit ? "Bearbeitung beenden" : "Eigene Annahmen eintragen";
    document.getElementById("edit-hint").hidden = !state.edit;
    document.getElementById("btn-reset").hidden = false;
    drawTable();
  });
  on("btn-reset", "click", () => { state.exp = baseExp.slice(); drawTable(); renderAll(true); });
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => renderAll(true), 150); });
  // portfolio check and tactical signals (web/check.js is inserted here)
  method();
  renderAll(false);
})();
