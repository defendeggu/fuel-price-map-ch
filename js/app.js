'use strict';
/* TreibstoffKarte CH – Frontend.
   Keine Inline-Handler und kein innerHTML mit Daten: alle Inhalte werden per DOM gebaut,
   damit die Content-Security-Policy in index.html streng bleiben kann (script-src 'self'). */

/* ── CANTON META ─────────────────────────────────────────────── */
const NAMES = {
  ZH:'Zürich', BE:'Bern', LU:'Luzern', UR:'Uri', SZ:'Schwyz',
  OW:'Obwalden', NW:'Nidwalden', GL:'Glarus', ZG:'Zug', FR:'Fribourg',
  SO:'Solothurn', BS:'Basel-Stadt', BL:'Basel-Landschaft', SH:'Schaffhausen',
  AR:'Appenzell A.Rh.', AI:'Appenzell I.Rh.', SG:'St. Gallen', GR:'Graubünden',
  AG:'Aargau', TG:'Thurgau', TI:'Tessin', VD:'Waadt', VS:'Wallis',
  NE:'Neuenburg', GE:'Genf', JU:'Jura'
};
const FUELS = ['diesel', 'benzin'];

/* ── PRICE DATA ──────────────────────────────────────────────────
   Keine eingebauten Preise: alles kommt aus data/canton-prices.json (aktueller Stand)
   und data/price-history.json (Tagesverlauf). Fehlt die Datei, zeigt die Seite einen Fehler.
──────────────────────────────────────────────────────────────── */
const PRICES = { diesel: {}, benzin: {} };   // aktueller Stand (live)
let liveMeta   = {};     // {kz: {n_diesel, min_diesel, max_diesel, …}} – nur aktueller Stand
let liveMethod = null;   // Berechnungsmethode des aktuellen Stands (z. B. 'trim10')
let latestKey  = null;   // Datum des aktuellen Stands, 'YYYY-MM-DD' (UTC-Datum des Scrapers)

/* ── DOM-HELFER ──────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

// el('div', {class:'x', dataset:{k:'ZH'}, style:{color:'red'}}, 'Text', childNode, …)
// Text wird immer als Textknoten eingefügt (kein HTML-Parsing).
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k === 'style') Object.assign(node.style, v);   // CSSOM, von der CSP erlaubt
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}
// Wie replaceChildren, aber ohne leere Einträge (null/false würden sonst als Text erscheinen).
function put(node, ...children) {
  node.replaceChildren(...children.flat().filter(c => c != null && c !== false));
}

/* ── DATUMS-HELFER ───────────────────────────────────────────── */
function dateKey(d) {
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}
function parseKey(s) { const [y,m,d] = s.split('-').map(Number); return new Date(y, m-1, d); }
function fmtDate(d, opts) { return d.toLocaleDateString('de-CH', opts || {day:'2-digit',month:'2-digit',year:'numeric'}); }
function addDays(key, n) { const d = parseKey(key); d.setDate(d.getDate() + n); return dateKey(d); }

let fuel = 'diesel';
// displayPrices ist die Arbeitskopie für das gewählte Datum
let displayPrices = { diesel: {}, benzin: {} };
function prices() { return displayPrices[fuel]; }
function otherFuel() { return fuel === 'diesel' ? 'benzin' : 'diesel'; }
function fuelLabel(f) { return f === 'diesel' ? 'Diesel' : 'Benzin 95'; }

/* ── MAP INIT ─────────────────────────────────────────────────── */
const map = L.map('map', { center:[46.80,8.25], zoom:8, zoomControl:true, attributionControl:false });
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  { subdomains:'abc', maxZoom:19, attribution:'&copy; OpenStreetMap' }).addTo(map);
L.control.attribution({ position:'bottomright', prefix:false }).addTo(map);

/* ── COLOR SCALE ──────────────────────────────────────────────── */
let pMin, pMax;
function getColor(p) {
  if (!p || isNaN(p)) return '#27323f';
  const t = Math.max(0, Math.min(1, (p - pMin) / (pMax - pMin || .01)));
  const stops = [[56,189,248],[52,211,153],[250,204,21],[249,115,22],[239,68,68]];
  const s = t * (stops.length-1), i = Math.min(Math.floor(s), stops.length-2), f = s-i;
  return `rgb(${Math.round(stops[i][0]+(stops[i+1][0]-stops[i][0])*f)},${
               Math.round(stops[i][1]+(stops[i+1][1]-stops[i][1])*f)},${
               Math.round(stops[i][2]+(stops[i+1][2]-stops[i][2])*f)})`;
}

/* ── PROPERTY HELPERS ─────────────────────────────────────────── */
function kuerzel(props) { return String(props.id || '').toUpperCase(); }
function fullName(k) { return NAMES[k] || k; }

/* ── GEO ──────────────────────────────────────────────────────── */
// Kantonsgrenzen liegen im Repo (dieselbe Datei nutzt der Scraper für die Zuordnung).
// TopoJSON, Kantonskürzel als id auf jeder Geometrie.
const GEO_URL = './data/cantons.topo.json';

async function fetchGeo() {
  ovMsg('Lade Kantonsgeometrien…');
  const res = await fetch(GEO_URL);
  if (!res.ok) throw new Error('Kantonsgrenzen nicht ladbar: ' + GEO_URL + ' → HTTP ' + res.status);
  const topo = await res.json();
  const geo = topojson.feature(topo, topo.objects.cantons);
  // id steht auf der Geometrie, nicht in properties – für kuerzel() übernehmen
  geo.features.forEach(f => { f.properties = { ...(f.properties || {}), id: f.id }; });
  if (geo.features.length !== 26) throw new Error('Kantonsgrenzen unvollständig: ' + geo.features.length + ' Kantone');
  return geo;
}

/* ── LAYER ────────────────────────────────────────────────────── */
let geoLayer = null, active = null;
const HIGHLIGHT = { weight:2.5, fillOpacity:.95, color:'#fff' };

function buildLayer(geo) {
  geoLayer = L.geoJSON(geo, {
    style(f) {
      const v = prices()[kuerzel(f.properties)];
      return { fillColor:getColor(v), fillOpacity: v ? 0.80 : 0.12, color:'#0d1117', weight:1.5 };
    },
    onEachFeature(f, layer) {
      refreshTooltip(layer);
      layer.on({
        mouseover(e) { e.target.setStyle(HIGHLIGHT); e.target.bringToFront(); },
        mouseout(e)  { if (active !== e.target) geoLayer.resetStyle(e.target); },
        click()      { selectCanton(kuerzel(f.properties), { zoom: false }); },
      });
    }
  }).addTo(map);
}

function layerFor(k) {
  let found = null;
  geoLayer?.eachLayer(l => { if (kuerzel(l.feature.properties) === k) found = l; });
  return found;
}

function refreshTooltip(layer) {
  const k = kuerzel(layer.feature.properties);
  const p = prices()[k];
  layer.bindTooltip(
    el('span', {}, el('b', {}, fullName(k)), ` (${k})   ${p ? p.toFixed(3) + ' CHF/L' : 'k.A.'}`),
    { sticky:true, direction:'top', offset:[0,-4] }
  );
}

function recolor() {
  updateLegend();
  geoLayer?.eachLayer(l => {
    const v = prices()[kuerzel(l.feature.properties)];
    l.setStyle({ fillColor:getColor(v), fillOpacity: v ? 0.80 : 0.12 });
    if (l === active) l.setStyle(HIGHLIGHT);
    refreshTooltip(l);
  });
  renderList();
  if (active) showDetail(kuerzel(active.feature.properties));
}

/* ── VERÄNDERUNG GGÜ. FRÜHEREN TAGEN ─────────────────────────────
   Verglichen wird nur mit Einträgen derselben Berechnungsmethode (method),
   sonst entstünden durch Methodenwechsel Scheinveränderungen. */
function entryFor(key) {
  if (key === latestKey) return { date: latestKey, method: liveMethod, cantons: null };
  return historyByDate.get(key) || null;
}
function priceIn(entry, k, f) {
  if (!entry) return null;
  if (entry.date === latestKey) return PRICES[f][k] ?? null;
  return entry.cantons?.[k]?.[f] ?? null;
}
// Sucht den Vergleichstag: frühestens `days` Tage zurück, höchstens `days + slack`.
function compareEntry(key, days, slack) {
  const cur = entryFor(key);
  if (!cur?.method) return null;
  for (let i = days; i <= days + slack; i++) {
    const e = entryFor(addDays(key, -i));
    if (e) return e.method === cur.method ? e : null;
  }
  return null;
}
function delta(k, f, days, slack) {
  const key = dateKey(selectedDate);
  const base = compareEntry(key, days, slack);
  const now = priceIn(entryFor(key), k, f), then = priceIn(base, k, f);
  if (now == null || then == null) return null;
  return { rp: (now - then) * 100, since: base.date };
}
function deltaNode(d, cls) {
  const rp = Math.round(d.rp * 10) / 10;
  const dir = rp > 0 ? 'up' : rp < 0 ? 'down' : 'flat';
  const sign = rp > 0 ? '+' : rp < 0 ? '−' : '±';
  return el('span', { class: `delta ${dir} ${cls || ''}`, title: `seit ${fmtDate(parseKey(d.since))}` },
            `${sign}${Math.abs(rp).toFixed(1)}`);
}

/* ── DETAIL CARD ──────────────────────────────────────────────── */
function selectCanton(k, { zoom = true } = {}) {
  const layer = layerFor(k);
  if (!layer) return;
  if (active && active !== layer) geoLayer.resetStyle(active);
  active = layer;
  layer.setStyle(HIGHLIGHT);
  layer.bringToFront();
  if (zoom) map.fitBounds(layer.getBounds(), { padding:[40,40], maxZoom:11 });
  showDetail(k);
  openAside();
  writeHash();
}

function showDetail(k) {
  const p = prices();
  const price = p[k];
  const sorted = Object.entries(p).sort((a,b)=>a[1]-b[1]);
  const rank = sorted.findIndex(([key])=>key===k)+1;
  const badge = rank <= 5 ? '✅ günstig' : rank >= sorted.length-4 ? '🔴 teuer' : '🟡 Mittelfeld';
  const other = displayPrices[otherFuel()][k];
  const meta = selectedIsLatest ? liveMeta[k] : null;
  const n = meta?.['n_' + fuel];
  const lo = meta?.['min_' + fuel], hi = meta?.['max_' + fuel];
  const dDay = delta(k, fuel, 1, 3), dWeek = delta(k, fuel, 7, 2);

  put($('detail-block'),
    el('div', { class: 's-label' }, 'Ausgewählter Kanton'),
    el('div', { id: 'detail-name' }, fullName(k)),
    el('div', { id: 'detail-abbr' }, k),
    ...(price ? [
      el('div', { id: 'detail-price', style: { color: getColor(price) } }, price.toFixed(3)),
      el('div', { id: 'detail-unit' }, `CHF / Liter ${fuelLabel(fuel)}`),
      el('div', { id: 'detail-rank' }, `Rang ${rank} / ${sorted.length}  ·  ${badge}`),
      (dDay || dWeek) && el('div', { id: 'detail-delta' },
        dDay  && el('span', {}, 'Vortag ', deltaNode(dDay), ' Rp'),
        dWeek && el('span', {}, 'Woche ', deltaNode(dWeek), ' Rp')),
      (lo != null && hi != null) && rangeNode(lo, hi, price),
      el('div', { id: 'detail-other' }, `${fuelLabel(otherFuel())}: ${other ? other.toFixed(3) + ' CHF/L' : 'k.A.'}`),
      n && el('div', { class: 'info-badge' }, `Mittelwert aus ${n} Stationen`),
      el('button', { class: 'chart-btn', type: 'button', onclick: () => openChart(k) }, 'Preisverlauf →'),
    ] : [
      el('div', { class: 'no-price' }, 'Kein Preis verfügbar'),
    ])
  );
  document.querySelectorAll('#canton-list .c-row').forEach(r => {
    const on = r.dataset.k === k;
    r.classList.toggle('active', on);
    r.setAttribute('aria-current', on ? 'true' : 'false');
  });
}

function rangeNode(lo, hi, price) {
  const pos = hi > lo ? Math.max(0, Math.min(100, (price - lo) / (hi - lo) * 100)) : 50;
  return el('div', { id: 'detail-range' },
    el('div', {}, `Stationen: ${lo.toFixed(2)} – ${hi.toFixed(2)} CHF/L`),
    el('div', { class: 'range-bar', 'aria-hidden': 'true' }, el('span', { style: { left: `calc(${pos}% - 1px)` } })),
  );
}

/* ── LEGEND ───────────────────────────────────────────────────── */
function updateLegend() {
  const vals = Object.values(prices()).filter(v=>!isNaN(v));
  if (!vals.length) return;
  // Skala auf 10.–90. Perzentil begrenzen: ein einzelner Ausreisserkanton (z. B. TI)
  // soll nicht alle übrigen Kantone in ein schmales Farbband drücken.
  const sorted = [...vals].sort((a,b)=>a-b);
  const q = f => { const x = f*(sorted.length-1), i = Math.floor(x);
                   return sorted[i] + ((sorted[i+1] ?? sorted[i]) - sorted[i]) * (x-i); };
  pMin = q(0.1); pMax = q(0.9);
  if (pMax - pMin < 0.005) { pMin = sorted[0]; pMax = sorted[sorted.length-1]; }
  const clipLo = sorted[0] < pMin - 1e-9, clipHi = sorted[sorted.length-1] > pMax + 1e-9;
  $('l-min').textContent = (clipLo ? '≤ ' : '') + pMin.toFixed(3);
  $('l-mid').textContent = ((pMin+pMax)/2).toFixed(3);
  $('l-max').textContent = (clipHi ? '≥ ' : '') + pMax.toFixed(3);
}

/* ── LIST ─────────────────────────────────────────────────────── */
function renderList() {
  const activeKey = active ? kuerzel(active.feature.properties) : null;
  const sorted = Object.entries(prices()).filter(([k])=>NAMES[k]).sort((a,b)=>a[1]-b[1]);
  $('canton-list').replaceChildren(...sorted.map(([k, p]) => {
    const d = delta(k, fuel, 1, 3);
    return el('button', {
        class: 'c-row' + (k === activeKey ? ' active' : ''), type: 'button', dataset: { k },
        'aria-current': k === activeKey ? 'true' : 'false',
        'aria-label': `${NAMES[k]}, ${p.toFixed(3)} CHF pro Liter` + (d ? `, ${d.rp >= 0 ? 'plus' : 'minus'} ${Math.abs(d.rp).toFixed(1)} Rappen seit Vortag` : ''),
      },
      el('span', { class: 'c-swatch', style: { background: getColor(p) } }),
      el('span', { class: 'c-abbr' }, k),
      el('span', { class: 'c-name' }, NAMES[k]),
      el('span', { class: 'c-delta', 'aria-hidden': 'true' }, d && deltaNode(d)),
      el('span', { class: 'c-price', style: { color: getColor(p) } }, p.toFixed(3)),
    );
  }));
}

/* ── FUEL TOGGLE ──────────────────────────────────────────────── */
function setFuel(f) {
  if (!FUELS.includes(f)) return;
  fuel = f;
  for (const x of FUELS) {
    $('btn-' + x).classList.toggle('active', x === f);
    $('btn-' + x).setAttribute('aria-pressed', x === f ? 'true' : 'false');
  }
  recolor(); setDate(); writeHash();
}

/* ── PRICE HISTORY ────────────────────────────────────────────── */
let priceHistory = null;            // geladen aus data/price-history.json
let historyByDate = new Map();      // 'YYYY-MM-DD' → Eintrag

async function loadPriceHistory() {
  try {
    const res = await fetch('./data/price-history.json');
    if (!res.ok) return;
    priceHistory = await res.json();
    historyByDate = new Map((priceHistory.entries || []).map(e => [e.date, e]));
  } catch(e) {
    console.warn('price-history.json nicht verfügbar:', e.message);
  }
}

// Ab diesem Datum ordnet der Scraper Stationen per Koordinate dem Kanton zu (davor: PLZ, ungenau).
function firstGeoDate() {
  return (priceHistory?.entries || []).find(e => e.geo)?.date || null;
}

// Landeswert eines Tages: Median der Kantonswerte (wie "national" im Scraper).
function nationalOf(cantons, f) {
  const v = Object.values(cantons || {}).map(c => c[f]).filter(x => x != null).sort((a,b)=>a-b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m-1] + v[m]) / 2;
}
function seriesValue(entry, key, f) {
  return key === 'CH' ? nationalOf(entry.cantons, f) : entry.cantons?.[key]?.[f];
}

// Echte Tageswerte im gewählten Zeitraum, auf höchstens ~90 Punkte ausgedünnt.
function getHistoryPoints(canton, rangeMonths, compare) {
  const entries = priceHistory?.entries || [];
  const endKey  = latestKey || entries[entries.length - 1]?.date;
  if (!endKey) return [];
  const end = parseKey(endKey), start = new Date(end);
  start.setMonth(start.getMonth() - rangeMonths);
  const inRange = entries.filter(e => e.cantons?.[canton] && parseKey(e.date) >= start && parseKey(e.date) <= end);
  const step = Math.max(1, Math.ceil(inRange.length / 90));
  return inRange
    .filter((e, i) => (inRange.length - 1 - i) % step === 0)
    .map(e => ({
      date: e.date,
      label: fmtDate(parseKey(e.date), {day:'2-digit', month:'2-digit', year: rangeMonths > 6 ? '2-digit' : undefined}),
      diesel: e.cantons[canton].diesel,
      benzin: e.cantons[canton].benzin,
      compare: compare ? seriesValue(e, compare, fuel) : null,
      preGeo: !e.geo,
      step,
    }));
}

/* ── CHART MODAL ──────────────────────────────────────────────── */
let chartInstance      = null;
let chartCanton        = null;
let chartCompare       = '';      // '' = kein Vergleich, 'CH' = Landeswert, sonst Kantonskürzel
let chartRangeMonths   = 3;
let chartOpener        = null;    // Element, das den Fokus nach dem Schliessen zurückbekommt

const SERIES_COLORS = {
  diesel:  ['#f97316', 'rgba(249,115,22,.08)'],
  benzin:  ['#38bdf8', 'rgba(56,189,248,.06)'],
  compare: ['#a78bfa', 'rgba(167,139,250,.04)'],
};

function buildDataset(points, field, label, [color, bgColor]) {
  const n = points.length;
  const dashed = ctx => (points[ctx.p0DataIndex].preGeo || points[ctx.p1DataIndex].preGeo);
  return {
    label,
    data: points.map(p => p[field]),
    borderColor: color,
    backgroundColor: bgColor,
    borderWidth: 2,
    tension: 0.25,
    fill: field !== 'compare',
    spanGaps: true,
    pointRadius: points.map((_, i) => i === n-1 ? 6 : (n > 40 ? 0 : 3)),
    pointHoverRadius: 5,
    pointBackgroundColor: points.map((p, i) => i === n-1 ? color : 'transparent'),
    pointBorderColor: color,
    // gestrichelt, wo die Kantonszuordnung noch per PLZ erfolgte
    segment: { borderDash: ctx => dashed(ctx) ? [5,4] : [] },
  };
}

function compareLabel(key) { return key === 'CH' ? 'CH (Median der Kantone)' : `${fullName(key)} (${key})`; }

function renderChart() {
  const canton = chartCanton, rangeMonths = chartRangeMonths, cmp = chartCompare;
  const points = getHistoryPoints(canton, rangeMonths, cmp);
  const hasPreGeo = points.some(p => p.preGeo);
  const step = points[0]?.step || 1;

  $('chart-sub').textContent =
    `Preisverlauf · ${rangeMonths} Monat${rangeMonths>1?'e':''} · ${step === 1 ? 'Tageswerte' : 'jeder ' + step + '. Tag'} · CHF/L (getrimmter Mittelwert)`;

  const est = $('chart-estimate');
  if (!points.length) {
    est.textContent = '⚠ Keine Verlaufsdaten für diesen Zeitraum';
    est.style.color = '#f59e0b';
  } else if (hasPreGeo) {
    est.textContent = `⚠ Vor dem ${fmtDate(parseKey(firstGeoDate()))} wurden Stationen per PLZ dem Kanton zugeordnet (ungenau, z. B. Genf)`;
    est.style.color = '#f59e0b';
  } else {
    est.textContent = '✓ Echte Stationsdaten (benzin.tcs.ch), getrimmter Mittelwert pro Kanton';
    est.style.color = '#22c55e';
  }

  // Ohne Vergleich: Diesel und Benzin des Kantons. Mit Vergleich: gewählte Sorte, Kanton gegen Vergleich.
  const series = cmp
    ? [['' + fuel, `${canton} ${fuelLabel(fuel)}`, SERIES_COLORS[fuel]], ['compare', compareLabel(cmp), SERIES_COLORS.compare]]
    : FUELS.map(f => [f, fuelLabel(f), SERIES_COLORS[f]]);

  put($('chart-legend'),
    ...series.map(([, label, [color]]) =>
      el('div', { class: 'chart-legend-item' }, el('div', { class: 'chart-legend-dot', style: { background: color } }), label)),
    hasPreGeo && el('div', { class: 'chart-legend-item' }, el('span', { class: 'legend-dash', 'aria-hidden': 'true' }, '- - -'), 'PLZ-Zuordnung (ungenau)'),
  );

  if (chartInstance) { chartInstance.destroy(); chartInstance = null; }

  chartInstance = new Chart($('price-chart').getContext('2d'), {
    type: 'line',
    data: {
      labels: points.map(p => p.label),
      datasets: series.map(([field, label, colors]) => buildDataset(points, field, label, colors)),
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1c2230', borderColor: '#27323f', borderWidth: 1,
          titleColor: '#e6edf3', bodyColor: '#7d8590',
          titleFont: { family: "'DM Mono', monospace", size: 11 },
          bodyFont:  { family: "'DM Mono', monospace", size: 11 },
          callbacks: {
            label: ctx => ctx.parsed.y == null ? null : ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(3)} CHF/L`,
            afterBody: (items) => {
              const idx = items[0]?.dataIndex;
              return (idx != null && points[idx].preGeo) ? ['  ↳ PLZ-Zuordnung (ungenau)'] : [];
            },
          },
        },
      },
      scales: {
        x: { grid: { color: '#27323f' },
             ticks: { color: '#7d8590', font: { family: "'DM Mono', monospace", size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
        y: { grid: { color: '#27323f' },
             ticks: { color: '#7d8590', font: { family: "'DM Mono', monospace", size: 10 },
                      callback: v => v.toFixed(2) } },
      },
    },
  });
  $('price-chart').setAttribute('aria-label',
    `Preisverlauf ${series.map(s => s[1]).join(' und ')}, ${points.length} Datenpunkte`);
}

function fillCompareSelect(k) {
  const sel = $('chart-compare');
  sel.replaceChildren(
    el('option', { value: '' }, '—'),
    el('option', { value: 'CH' }, compareLabel('CH')),
    ...Object.keys(NAMES).filter(x => x !== k).sort((a, b) => NAMES[a].localeCompare(NAMES[b], 'de'))
      .map(x => el('option', { value: x }, `${NAMES[x]} (${x})`)),
  );
  if (chartCompare === k) chartCompare = '';
  sel.value = chartCompare;
}

function openChart(k) {
  chartCanton = k;
  chartOpener = document.activeElement;
  $('chart-canton-name').textContent = fullName(k) + ' (' + k + ')';
  fillCompareSelect(k);
  renderChart();
  const modal = $('chart-modal');
  modal.classList.add('open');
  modal.removeAttribute('aria-hidden');
  modal.inert = false;
  document.addEventListener('keydown', onModalKey);
  $('chart-close').focus();
}

function setChartRange(months) {
  chartRangeMonths = months;
  document.querySelectorAll('.range-btn').forEach(b => {
    b.classList.toggle('active', +b.dataset.m === months);
    b.setAttribute('aria-pressed', +b.dataset.m === months ? 'true' : 'false');
  });
  if (chartCanton) renderChart();
}

function closeChart() {
  const modal = $('chart-modal');
  if (!modal.classList.contains('open')) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
  modal.inert = true;
  document.removeEventListener('keydown', onModalKey);
  if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
  chartCanton = null;
  if (chartOpener?.isConnected) chartOpener.focus();
  else $('detail-block').querySelector('.chart-btn')?.focus();
}

// Escape schliesst, Tab bleibt im Dialog (Fokusfalle).
function onModalKey(e) {
  if (e.key === 'Escape') { e.preventDefault(); closeChart(); return; }
  if (e.key !== 'Tab') return;
  const focusables = [...$('chart-modal').querySelectorAll('button, select, [tabindex]:not([tabindex="-1"])')]
    .filter(x => !x.disabled && x.offsetParent !== null);
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

/* ── DATE PICKER ──────────────────────────────────────────────── */
const TODAY       = (() => { const d = new Date(); d.setHours(0,0,0,0); return d; })();
let   DATA_START  = null;   // frühester Tag mit Daten (nach dem Laden gesetzt)
let   DATA_END    = null;   // spätester Tag mit Daten

let selectedDate     = new Date(TODAY);
let selectedIsLatest = true;
let calMonth      = TODAY.getMonth();
let calYear       = TODAY.getFullYear();
let calIsOpen     = false;

// Nur Tage mit echtem Eintrag sind wählbar (Lücken im Verlauf bleiben gesperrt).
function hasData(date) {
  const k = dateKey(date);
  return k === latestKey || historyByDate.has(k);
}
function initDataRange() {
  const keys = [...historyByDate.keys(), ...(latestKey ? [latestKey] : [])].sort();
  if (!keys.length) return;
  DATA_START = parseKey(keys[0]);
  DATA_END   = parseKey(keys[keys.length - 1]);
  const days = new Set(keys).size;
  $('cal-range-hint').textContent = `Echtdaten: ${fmtDate(DATA_START)} – ${fmtDate(DATA_END)} · ${days} Tage`;
}

const MONTHS_DE = ['Januar','Februar','März','April','Mai','Juni',
                   'Juli','August','September','Oktober','November','Dezember'];

function toggleCalendar(e) {
  e.stopPropagation();
  calIsOpen ? closeCalendar() : openCalendar();
}

function openCalendar() {
  calMonth = selectedDate.getMonth();
  calYear  = selectedDate.getFullYear();
  renderCalendar();
  const chip = $('date-chip');
  const rect = chip.getBoundingClientRect();
  const popup = $('calendar-popup');
  popup.style.top = (rect.bottom + 6) + 'px';
  if (!isMobile()) popup.style.right = (window.innerWidth - rect.right) + 'px';
  popup.classList.add('open');
  chip.setAttribute('aria-expanded', 'true');
  calIsOpen = true;
  setTimeout(() => document.addEventListener('click', calOutsideClick), 0);
  (popup.querySelector('.cal-day.selected') || popup.querySelector('.cal-day:not(:disabled)'))?.focus();
}

function closeCalendar({ focusChip = false } = {}) {
  $('calendar-popup').classList.remove('open');
  $('date-chip').setAttribute('aria-expanded', 'false');
  document.removeEventListener('click', calOutsideClick);
  calIsOpen = false;
  if (focusChip) $('date-chip').focus();
}

function calOutsideClick(e) {
  if (!$('calendar-popup').contains(e.target)) closeCalendar();
}

function calNav(dir) {
  calMonth += dir;
  if (calMonth > 11) { calMonth = 0; calYear++; }
  if (calMonth < 0)  { calMonth = 11; calYear--; }
  renderCalendar();
}

function renderCalendar() {
  $('cal-month-label').textContent = MONTHS_DE[calMonth] + ' ' + calYear;

  const atStart = !DATA_START || calYear < DATA_START.getFullYear() ||
    (calYear === DATA_START.getFullYear() && calMonth <= DATA_START.getMonth());
  const atEnd = !DATA_END || calYear > DATA_END.getFullYear() ||
    (calYear === DATA_END.getFullYear() && calMonth >= DATA_END.getMonth());
  $('cal-prev').disabled = atStart;
  $('cal-next').disabled = atEnd;

  const offset   = (new Date(calYear, calMonth, 1).getDay() + 6) % 7;   // Montag zuerst
  const daysInMo = new Date(calYear, calMonth + 1, 0).getDate();
  const cells = Array.from({ length: offset }, () => el('div', { 'aria-hidden': 'true' }));

  for (let d = 1; d <= daysInMo; d++) {
    const date = new Date(calYear, calMonth, d);
    const inRange = hasData(date);
    const isToday = date.getTime() === TODAY.getTime();
    const isSel   = dateKey(date) === dateKey(selectedDate);
    let cls = 'cal-day';
    if (isSel)        cls += ' selected';
    else if (inRange) cls += ' available' + (isToday ? ' today' : '');
    else              cls += ' unavailable';
    cells.push(el('button', {
      class: cls, type: 'button', disabled: !inRange,
      'aria-label': fmtDate(date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) + (inRange ? '' : ', keine Daten'),
      'aria-pressed': isSel ? 'true' : 'false',
      dataset: { date: dateKey(date) },
    }, d));
  }
  $('cal-days').replaceChildren(...cells);
}

function onSelectDate(date) {
  selectedDate = date;
  closeCalendar({ focusChip: true });
  updatePricesForDate(date);
  setDate();
  writeHash();
}

/* ── PREISE FÜR GEWÄHLTES DATUM ───────────────────────────────── */
// Setzt displayPrices auf den Stand des Tages: aktueller Tag = Live-Daten, sonst Eintrag aus der Historie.
function updatePricesForDate(date) {
  const key = dateKey(date);
  selectedIsLatest = (key === latestKey);
  for (const f of FUELS) {
    displayPrices[f] = {};
    if (selectedIsLatest) {
      Object.assign(displayPrices[f], PRICES[f]);
    } else {
      const cantons = historyByDate.get(key)?.cantons || {};
      for (const [k, v] of Object.entries(cantons)) if (v[f] != null) displayPrices[f][k] = v[f];
    }
  }
  recolor();
}

/* ── DEEPLINKS ───────────────────────────────────────────────────
   #ZH/diesel/2026-11-01 – Teile optional, Reihenfolge egal. Ohne Datum = aktueller Stand. */
let applyingHash = false;

function writeHash() {
  if (applyingHash || !latestKey) return;
  const parts = [];
  if (active) parts.push(kuerzel(active.feature.properties));
  if (fuel !== 'diesel' || parts.length) parts.push(fuel);
  if (!selectedIsLatest) parts.push(dateKey(selectedDate));
  const hash = parts.length ? '#' + parts.join('/') : '';
  if (location.hash !== hash) history.replaceState(null, '', hash || location.pathname + location.search);
}

function applyHash() {
  const parts = decodeURIComponent(location.hash.slice(1)).split('/').filter(Boolean);
  const want = { canton: null, fuel: 'diesel', date: latestKey };
  for (const p of parts) {
    if (NAMES[p.toUpperCase()]) want.canton = p.toUpperCase();
    else if (FUELS.includes(p.toLowerCase())) want.fuel = p.toLowerCase();
    else if (/^\d{4}-\d{2}-\d{2}$/.test(p) && hasData(parseKey(p))) want.date = p;
  }
  applyingHash = true;
  try {
    if (want.fuel !== fuel) setFuel(want.fuel);
    if (want.date !== dateKey(selectedDate)) { selectedDate = parseKey(want.date); updatePricesForDate(selectedDate); setDate(); }
    if (want.canton) selectCanton(want.canton);
    else if (active) { geoLayer.resetStyle(active); active = null; resetDetail(); renderList(); }
  } finally {
    applyingHash = false;
  }
}

function resetDetail() {
  $('detail-block').replaceChildren(
    el('div', { class: 's-label' }, 'Ausgewählter Kanton'),
    el('div', { class: 'placeholder' }, 'Kanton auf der Karte oder in der Liste wählen'));
}

/* ── MOBILE ASIDE ─────────────────────────────────────────────── */
function isMobile() { return window.innerWidth < 768; }
function setAside(open) {
  $('aside').classList.toggle('sheet-open', open);
  $('aside-handle').setAttribute('aria-expanded', open ? 'true' : 'false');
}
function toggleAside() { setAside(!$('aside').classList.contains('sheet-open')); }
function openAside() { if (isMobile()) setAside(true); }

/* ── HELPERS ──────────────────────────────────────────────────── */
function ovMsg(t) { $('ov-msg').textContent = t; }
function setDate() {
  const chip = $('date-chip');
  const ageDays = latestKey ? Math.round((TODAY - parseKey(latestKey)) / 86400000) : 0;
  const stale = selectedIsLatest && ageDays > 2;   // Scraper hat seit > 2 Tagen nichts geliefert
  chip.textContent = 'Stand: ' + fmtDate(selectedDate) + (stale ? ' ⚠' : '');
  chip.classList.toggle('stale', stale);
  chip.title = stale ? `Letzte Daten sind ${ageDays} Tage alt` : '';
  chip.setAttribute('aria-label', `Datenstand ${fmtDate(selectedDate)}${stale ? ', veraltet' : ''}. Anderen Tag wählen`);
}
function toast(msg, ms=8000) {
  const t = $('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(()=>t.style.display='none', ms);
}

/* ── LIVE PREISE LADEN ────────────────────────────────────────── */
async function loadLivePrices() {
  const res = await fetch('./data/canton-prices.json');
  if (!res.ok) throw new Error('Preisdaten nicht ladbar (HTTP ' + res.status + ')');
  const data = await res.json();
  if (!data.cantons || !Object.keys(data.cantons).length) throw new Error('Preisdaten leer');

  for (const [k, v] of Object.entries(data.cantons)) {
    for (const f of FUELS) PRICES[f][k] = v[f];
    liveMeta[k] = v;
  }
  displayPrices = { diesel: {...PRICES.diesel}, benzin: {...PRICES.benzin} };
  liveMethod = data.method || null;

  latestKey    = String(data.updated).slice(0, 10);
  selectedDate = parseKey(latestKey);   // «Stand» zeigt den Datenstand, nicht das heutige Datum
  selectedIsLatest = true;
  $('source-date').textContent = ' · Stand ' + fmtDate(selectedDate);
}

/* ── EVENTS ───────────────────────────────────────────────────── */
function bindEvents() {
  for (const f of FUELS) $('btn-' + f).addEventListener('click', () => setFuel(f));
  $('date-chip').addEventListener('click', toggleCalendar);
  $('cal-prev').addEventListener('click', () => calNav(-1));
  $('cal-next').addEventListener('click', () => calNav(1));
  $('cal-days').addEventListener('click', e => {
    const b = e.target.closest('.cal-day');
    if (b && !b.disabled && !b.classList.contains('selected')) onSelectDate(parseKey(b.dataset.date));
  });
  $('calendar-popup').addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); closeCalendar({ focusChip: true }); }
  });
  $('canton-list').addEventListener('click', e => {
    const row = e.target.closest('.c-row');
    if (row) selectCanton(row.dataset.k);
  });
  $('chart-modal').addEventListener('click', e => { if (e.target === $('chart-modal')) closeChart(); });
  $('chart-close').addEventListener('click', closeChart);
  document.querySelectorAll('.range-btn').forEach(b => b.addEventListener('click', () => setChartRange(+b.dataset.m)));
  $('chart-compare').addEventListener('change', e => { chartCompare = e.target.value; renderChart(); });
  $('aside-handle').addEventListener('click', toggleAside);
  window.addEventListener('hashchange', applyHash);
}

/* ── BOOT ─────────────────────────────────────────────────────── */
(async () => {
  bindEvents();
  try {
    const [geo] = await Promise.all([fetchGeo(), loadLivePrices(), loadPriceHistory()]);
    ovMsg('Karte wird gerendert…');
    initDataRange();
    updateLegend();
    buildLayer(geo);
    renderList(); setDate();
    applyHash();
    $('status-dot').className = '';
    $('status-dot').title = 'Daten geladen';
  } catch(e) {
    console.error(e);
    $('status-dot').className = 'error';
    $('status-dot').title = 'Fehler beim Laden';
    toast('⚠️ ' + e.message + '\n\nHinweis: Beim lokalen Öffnen (file://) können CORS-Fehler auftreten. Bitte über einen Webserver oder GitHub Pages öffnen.');
  } finally {
    $('overlay').classList.add('hidden');
  }
})();
