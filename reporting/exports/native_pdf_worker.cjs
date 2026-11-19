'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const MAX_INPUT = 48 * 1024 * 1024;
const MAX_PDF = 8 * 1024 * 1024;
// 2 × the largest completed measurement: 63 pages, annual 10,000 modules / 31 inverters / 556 strings (en).
// The independent memory guard is calibrated separately; no content is truncated to fit.
const MAX_PAGES = 126;
const PLAYWRIGHT_VERSION = '1.64.1';
function fail(code) { throw new Error(code); }
function reportHTML(p) {
  const keys = ['locale','watermark','snapshot_json','snapshot_sha256','plan_figure_png'];
  if (!p || typeof p !== 'object' || Array.isArray(p) || Object.keys(p).sort().join() !== keys.sort().join()
      || !['en','id'].includes(p.locale) || p.watermark !== 'free_community'
      || typeof p.snapshot_json !== 'string' || !/^[0-9a-f]{64}$/.test(p.snapshot_sha256)) fail('PDF_INVALID_SNAPSHOT');
  const raw = Buffer.from(p.snapshot_json, 'utf8');
  if (crypto.createHash('sha256').update(raw).digest('hex') !== p.snapshot_sha256) fail('PDF_SNAPSHOT_DIGEST');
  let snapshot;
  try { snapshot = JSON.parse(p.snapshot_json); } catch { fail('PDF_INVALID_SNAPSHOT'); }
  snapshot.snapshot_sha256 = p.snapshot_sha256;
  const root = process.env.RAWIBUMI_PDF_RUNTIME_ROOT;
  if (!root || !path.isAbsolute(root)) fail('PDF_RUNTIME_UNAVAILABLE');
  const bundle = path.join(root, 'dist/report-render/report-render.cjs');
  try {
    if (!fs.realpathSync(bundle).startsWith(fs.realpathSync(root)+path.sep)) fail('PDF_RUNTIME_UNAVAILABLE');
    const renderer = require(bundle);
    const html = renderer.renderReport(snapshot, { locale: p.locale, planFigurePng: p.plan_figure_png, watermark: p.watermark });
    if (typeof html !== 'string' || !html.startsWith('<!doctype html>')) fail('PDF_RENDER_FAILED');
    return html;
  } catch (error) {
    if (/^PDF_[A-Z_]+$/.test(error.message)) throw error;
    fail('PDF_REPORT_RENDER_FAILED');
  }
}

function runtime() {
  if (Number(process.versions.node.split('.')[0]) < 22) fail('PDF_NODE_VERSION');
  const root = process.env.RAWIBUMI_PDF_RUNTIME_ROOT;
  const executablePath = process.env.RAWIBUMI_PDF_CHROMIUM_EXECUTABLE;
  if (!root || !path.isAbsolute(root) || !executablePath || !path.isAbsolute(executablePath)) fail('PDF_RUNTIME_UNAVAILABLE');
  try {
    const realRoot = fs.realpathSync(root);
    const modulePath = name => {
      const location = fs.realpathSync(path.join(realRoot, 'node_modules', name));
      if (!location.startsWith(realRoot + path.sep)) fail('PDF_RUNTIME_UNAVAILABLE');
      if (JSON.parse(fs.readFileSync(path.join(location, 'package.json'), 'utf8')).version !== PLAYWRIGHT_VERSION) {
        fail('PDF_RUNTIME_VERSION');
      }
      return location;
    };
    const playwright = modulePath('playwright');
    const core = modulePath('playwright-core');
    fs.accessSync(executablePath, fs.constants.X_OK);
    const browsers = JSON.parse(fs.readFileSync(path.join(core, 'browsers.json'), 'utf8')).browsers;
    const browserVersion = browsers.find(b => b.name === 'chromium').browserVersion;
    if (!browserVersion) fail('PDF_RUNTIME_VERSION');
    return { chromium: require(playwright).chromium, executablePath, browserVersion };
  } catch (error) {
    if (/^PDF_[A-Z_]+$/.test(error.message)) throw error;
    fail('PDF_RUNTIME_UNAVAILABLE');
  }
}

async function render(p) {
  const html = reportHTML(p);
  const { chromium, executablePath, browserVersion } = runtime();
  let browser;
  let blocked = 0;
  try {
    // Playwright otherwise defaults to disabling Chromium's sandbox. Requiring
    // it explicitly means unsupported hosts fail closed; no fallback flags.
    try {
      browser = await chromium.launch({ executablePath, headless: true, chromiumSandbox: true,
        timeout: 15000, args: ['--disable-background-networking', '--disable-component-update', '--no-first-run'] });
    } catch { fail('PDF_CHROMIUM_LAUNCH'); }
    if (browser.version() !== browserVersion) fail('PDF_CHROMIUM_VERSION');
    const context = await browser.newContext({ javaScriptEnabled: false, serviceWorkers: 'block',
      offline: true, acceptDownloads: false, locale: p.locale === 'id' ? 'id-ID' : 'en-US' });
    // Match and abort every page-originated resource scheme. Count only: never
    // copy hostile URLs or machine paths to stderr. Any attempt rejects output.
    await context.route('**/*', async route => { blocked += 1; await route.abort('blockedbyclient'); });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    await page.setContent(html, { waitUntil: 'load', timeout: 10000 });
    const pdf = await page.pdf({ format: 'A4', printBackground: true,
      margin: { top: '16mm', bottom: '18mm', left: '16mm', right: '16mm' },
      displayHeaderFooter: true, headerTemplate: '<span></span>',
      footerTemplate: '<div style="width:100%;text-align:center;font:8px sans-serif;color:#52635f"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
      tagged: true, outline: true, timeout: 10000 });
    if (blocked) fail('PDF_RESOURCE_REQUEST_BLOCKED');
    if (pdf.length > MAX_PDF || pdf.subarray(0, 5).toString('ascii') !== '%PDF-') fail('PDF_OUTPUT_LIMIT');
    // Chromium currently writes page dictionaries outside compressed streams.
    // Fail closed if that representation changes; never print only pageRanges
    // (which would silently truncate scientific/provenance content).
    const pages = (pdf.toString('latin1').match(/\/Type\s*\/Page\b/g) || []).length;
    if (pages < 1 || pages > MAX_PAGES) fail('PDF_PAGE_LIMIT');
    return pdf;
  } finally {
    if (browser) await browser.close();
  }
}

async function main() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > MAX_INPUT) fail('PDF_INPUT_LIMIT');
    chunks.push(chunk);
  }
  let projection;
  try { projection = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { fail('PDF_INVALID_SNAPSHOT'); }
  const pdf = await render(projection);
  await new Promise((resolve, reject) => process.stdout.write(pdf, error => error ? reject(error) : resolve()));
}

module.exports = { reportHTML, render };
if (require.main === module) {
  const deadline = setTimeout(() => { process.stderr.write('PDF_WORKER_TIMEOUT\n'); process.exit(1); }, 35000);
  main().catch(error => {
    process.stderr.write((/^PDF_[A-Z_]+$/.test(error.message) ? error.message : 'PDF_RENDER_FAILED') + '\n');
    process.exitCode = 1;
  }).finally(() => clearTimeout(deadline));
}
