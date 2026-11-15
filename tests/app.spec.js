// @ts-check
import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const live = JSON.parse(fs.readFileSync('data/canton-prices.json', 'utf8'));
const history = JSON.parse(fs.readFileSync('data/price-history.json', 'utf8'));
const liveKey = live.updated.slice(0, 10);

// Auf dem Handy liegt die Seitenleiste als eingeklapptes Bottom Sheet am unteren Rand.
// Nur aufklappen, wenn es zu ist (ein Deeplink kann es schon geöffnet haben).
async function openSidebar(page) {
  const handle = page.locator('.aside-handle');
  if (await handle.isVisible() && (await handle.getAttribute('aria-expanded')) !== 'true') await handle.click();
}

test.beforeEach(async ({ page }) => {
  page.on('pageerror', e => { throw e; });
  await page.goto('/index.html');
  await expect(page.locator('#overlay')).toHaveClass(/hidden/, { timeout: 20_000 });
});

test('zeigt Datenstand und alle 26 Kantone aus den JSON-Daten', async ({ page }) => {
  const [y, m, d] = liveKey.split('-');
  await expect(page.locator('#date-chip')).toContainText(`${d}.${m}.${y}`);
  await expect(page.locator('#canton-list .c-row')).toHaveCount(26);
  const cheapest = Math.min(...Object.values(live.cantons).map(c => c.diesel));
  await expect(page.locator('#canton-list .c-row .c-price').first()).toHaveText(cheapest.toFixed(3));
});

test('Kantonsgrenzen kommen aus dem Repo, nicht von fremden Servern', async ({ page }) => {
  const geoRequests = [];
  page.on('request', r => { if (/cantons|geojson/i.test(r.url())) geoRequests.push(r.url()); });
  await page.reload();
  await expect(page.locator('#overlay')).toHaveClass(/hidden/, { timeout: 20_000 });
  await expect(page.locator('path.leaflet-interactive')).toHaveCount(26);
  expect(geoRequests.length).toBeGreaterThan(0);
  for (const url of geoRequests) expect(new URL(url).pathname).toBe('/data/cantons.topo.json');
});

test('lädt nichts von fremden Servern ausser OSM-Kartenkacheln', async ({ page }) => {
  const foreign = [];
  page.on('request', r => {
    const { hostname } = new URL(r.url());
    if (!['localhost', '127.0.0.1'].includes(hostname) && !hostname.endsWith('tile.openstreetmap.org')) foreign.push(r.url());
  });
  await page.reload();
  await expect(page.locator('#overlay')).toHaveClass(/hidden/, { timeout: 20_000 });
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Genf' }).click();
  await page.locator('.chart-btn').click();
  await expect(page.locator('#chart-modal')).toHaveClass(/open/);
  await page.evaluate(() => document.fonts.ready);
  expect(foreign).toEqual([]);
  expect(await page.evaluate(() => document.fonts.check("12px 'DM Mono'") && document.fonts.check("700 12px 'Barlow Condensed'"))).toBe(true);
});

test('Genf hat eigene Stationsdaten (Detailansicht)', async ({ page }) => {
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Genf' }).click();
  await expect(page.locator('#detail-name')).toHaveText('Genf');
  await expect(page.locator('#detail-price')).toHaveText(live.cantons.GE.diesel.toFixed(3));
  await expect(page.locator('.info-badge')).toContainText(`${live.cantons.GE.n_diesel} Stationen`);
  await expect(page.locator('#detail-block')).not.toContainText(/\b(null|undefined|NaN)\b/);
});

test('Zeitreise: nur Tage mit Daten wählbar, zeigt Werte des Tages', async ({ page }) => {
  const older = history.entries.find(e => e.geo === undefined && e.date > '2026-03-10');
  await page.locator('#date-chip').click();
  // Tage ohne Eintrag (z. B. vor Datenbeginn) sind gesperrt
  await expect(page.locator('.cal-day.available').first()).toBeVisible();
  const available = await page.locator('.cal-day.available, .cal-day.selected').count();
  const unavailable = await page.locator('.cal-day.unavailable').count();
  expect(available + unavailable).toBeGreaterThan(27);

  // auf einen alten Tag wechseln und Karte prüfen
  const [y, m, d] = older.date.split('-').map(Number);
  await page.evaluate(([y, m, d]) => onSelectDate(new Date(y, m - 1, d)), [y, m, d]);
  const expected = Math.min(...Object.values(older.cantons).map(c => c.diesel));
  await expect(page.locator('#canton-list .c-row .c-price').first()).toHaveText(expected.toFixed(3));

  // zurück zu «heute»: Live-Preise sind wieder da
  const [ly, lm, ld] = liveKey.split('-').map(Number);
  await page.evaluate(([y, m, d]) => onSelectDate(new Date(y, m - 1, d)), [ly, lm, ld]);
  const cheapest = Math.min(...Object.values(live.cantons).map(c => c.diesel));
  await expect(page.locator('#canton-list .c-row .c-price').first()).toHaveText(cheapest.toFixed(3));
});

test('Chart: nur echte Werte, keine Schätzung', async ({ page }) => {
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Genf' }).click();
  await page.locator('.chart-btn').click();
  await expect(page.locator('#chart-modal')).toHaveClass(/open/);
  const text = await page.locator('#chart-estimate').textContent();
  expect(text).not.toMatch(/geschätzt/i);
  // alle Datenpunkte liegen im realen Preisbereich (keine ~1.78-Schätzkurve)
  const ys = await page.evaluate(() => chartInstance.data.datasets[0].data);
  expect(ys.length).toBeGreaterThan(5);
  for (const v of ys) expect(v).toBeGreaterThan(1.9);
});

test('Content-Security-Policy: keine Verstösse bei Karte, Kalender und Chart', async ({ page }) => {
  await page.addInitScript(() => {
    window.__csp = [];
    document.addEventListener('securitypolicyviolation', e => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  await page.reload();
  await expect(page.locator('#overlay')).toHaveClass(/hidden/, { timeout: 20_000 });
  await page.locator('#date-chip').click();
  await expect(page.locator('#calendar-popup')).toHaveClass(/open/);
  await page.keyboard.press('Escape');
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Zürich' }).click();
  await page.locator('.chart-btn').click();
  await page.locator('#chart-compare').selectOption('CH');
  await expect(page.locator('#chart-legend')).toContainText('CH');
  expect(await page.evaluate(() => window.__csp)).toEqual([]);
});

test('Tastatur: Kanton wählen, Chart öffnen, mit Escape schliessen', async ({ page, isMobile }) => {
  test.skip(isMobile, 'Tastaturbedienung nur auf dem Desktop geprüft');
  await page.locator('#canton-list .c-row', { hasText: 'Genf' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#detail-name')).toHaveText('Genf');
  await page.locator('.chart-btn').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#chart-modal')).toHaveClass(/open/);
  await expect(page.locator('#chart-close')).toBeFocused();
  // Fokus bleibt im Dialog
  for (let i = 0; i < 10; i++) await page.keyboard.press('Tab');
  expect(await page.evaluate(() => document.getElementById('chart-modal').contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.locator('#chart-modal')).not.toHaveClass(/open/);
  await expect(page.locator('.chart-btn')).toBeFocused();
});

test('Tastatur: Kalender per Tastatur bedienbar', async ({ page, isMobile }) => {
  test.skip(isMobile, 'Tastaturbedienung nur auf dem Desktop geprüft');
  await page.locator('#date-chip').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#calendar-popup')).toHaveClass(/open/);
  await expect(page.locator('.cal-day.selected')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator('#calendar-popup')).not.toHaveClass(/open/);
  await expect(page.locator('#date-chip')).toBeFocused();
});

test('Deeplink: Kanton, Sorte und Datum aus der URL', async ({ page }) => {
  const older = history.entries.find(e => e.geo === undefined && e.date > '2026-03-10');
  await page.goto(`/index.html#GE/benzin/${older.date}`);
  await page.reload();
  await expect(page.locator('#overlay')).toHaveClass(/hidden/, { timeout: 20_000 });
  await expect(page.locator('#btn-benzin')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#detail-name')).toHaveText('Genf');
  await expect(page.locator('#detail-price')).toHaveText(older.cantons.GE.benzin.toFixed(3));
  const [y, m, d] = older.date.split('-');
  await expect(page.locator('#date-chip')).toContainText(`${d}.${m}.${y}`);
});

test('Deeplink: Auswahl schreibt die URL, Hash-Wechsel wird übernommen', async ({ page }) => {
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Zürich' }).click();
  await expect(page).toHaveURL(/#ZH\/diesel$/);
  await page.evaluate(() => { location.hash = '#BE/benzin'; });
  await expect(page.locator('#detail-name')).toHaveText('Bern');
  await expect(page.locator('#btn-benzin')).toHaveClass(/active/);
});

test('Spanne der Stationspreise im aktuellen Stand', async ({ page }) => {
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Zürich' }).click();
  const zh = live.cantons.ZH;
  await expect(page.locator('#detail-range')).toContainText(`${zh.min_diesel.toFixed(2)} – ${zh.max_diesel.toFixed(2)}`);
});

test('Vortagesvergleich nur zwischen Tagen derselben Methode', async ({ page }) => {
  // künstlicher Vortag mit derselben Methode: ZH 2 Rappen günstiger
  const prev = liveKey.replace(/\d{2}$/, d => String(+d - 1).padStart(2, '0'));
  const cantons = Object.fromEntries(Object.entries(live.cantons).map(([k, v]) => [k, { diesel: v.diesel, benzin: v.benzin }]));
  cantons.ZH = { ...cantons.ZH, diesel: +(live.cantons.ZH.diesel - 0.02).toFixed(3) };
  const entries = history.entries.filter(e => e.date < prev).concat(
    { date: prev, source: 'tcs', geo: true, method: live.method, cantons },
    history.entries.filter(e => e.date >= liveKey));
  await page.route('**/data/price-history.json', r => r.fulfill({ json: { entries } }));
  await page.reload();
  await expect(page.locator('#overlay')).toHaveClass(/hidden/, { timeout: 20_000 });
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Zürich' }).click();
  await expect(page.locator('#detail-delta')).toContainText('Vortag +2.0 Rp');

  // gleicher Vortag, aber andere Methode → kein Vergleich
  entries.find(e => e.date === prev).method = 'median';
  await page.reload();
  await expect(page.locator('#overlay')).toHaveClass(/hidden/, { timeout: 20_000 });
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Zürich' }).click();
  await expect(page.locator('#detail-name')).toHaveText('Zürich');
  await expect(page.locator('#detail-delta')).toHaveCount(0);
});

test('Chart: Vergleich mit CH-Median und anderem Kanton', async ({ page }) => {
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Genf' }).click();
  await page.locator('.chart-btn').click();
  await page.locator('#chart-compare').selectOption('TI');
  await expect(page.locator('#chart-legend')).toContainText('Tessin (TI)');
  const ds = await page.evaluate(() => chartInstance.data.datasets.map(d => d.label));
  expect(ds).toEqual(['GE Diesel', 'Tessin (TI)']);
  const ti = await page.evaluate(() => chartInstance.data.datasets[1].data.at(-1));
  expect(ti).toBeCloseTo(live.cantons.TI.diesel, 3);
});
