// @ts-check
import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const live = JSON.parse(fs.readFileSync('data/canton-prices.json', 'utf8'));
const history = JSON.parse(fs.readFileSync('data/price-history.json', 'utf8'));
const liveKey = live.updated.slice(0, 10);

// Auf dem Handy liegt die Seitenleiste als eingeklapptes Bottom Sheet am unteren Rand.
async function openSidebar(page) {
  const handle = page.locator('.aside-handle');
  if (await handle.isVisible()) await handle.click();
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

test('Genf hat eigene Stationsdaten (Detailansicht)', async ({ page }) => {
  await openSidebar(page);
  await page.locator('#canton-list .c-row', { hasText: 'Genf' }).click();
  await expect(page.locator('#detail-name')).toHaveText('Genf');
  await expect(page.locator('#detail-price')).toHaveText(live.cantons.GE.diesel.toFixed(3));
  await expect(page.locator('.info-badge')).toContainText(`${live.cantons.GE.n_diesel} Stationen`);
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
