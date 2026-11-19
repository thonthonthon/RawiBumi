// Real Chromium + production frontend + real API; no physics mocked in browser.
import assert from 'node:assert/strict';
import fs from 'node:fs';
const { chromium } = await import(process.env.RAWIBUMI_PLAYWRIGHT_MODULE || 'playwright');
const { origin, detailed, blocked, fallback, legacy, daylight } = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', e => { errors.push(e.message); console.error('Browser page error:', e.message); });
const launches = [];
page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/simulate')) launches.push(r.postDataJSON()); });
async function open(pid) {
  console.log("Opening", pid);
  await page.goto(`${origin}/?open=${pid}&step=simulate`);
  await page.getByRole('button', { name: 'Validate and run', exact: true }).waitFor();
  const execution = page.getByRole('button', { name: 'Execution options', exact: true });
  if (await execution.getAttribute('aria-expanded') === 'false') await execution.click();
}
async function run() {
  const response = page.waitForResponse(r => r.url().endsWith('/simulate') && r.request().method() === 'POST', { timeout: 600000 });
  await page.getByRole('button', { name: 'Validate and run', exact: true }).click();
  const record = await (await response).json();
  console.log("Run", record.status);
  assert.ok(['completed', 'completed_with_warnings'].includes(record.status), JSON.stringify(record));
  return record;
}
try {
  await open(legacy);
  assert.equal(await page.getByLabel('Electrical shading execution', { exact: true }).inputValue(), 'legacy');
  const legacyRun = await run();
  assert.deepEqual(launches.at(-1), {});
  assert.ok(!legacyRun.detailed_electrical_shading);
  await open(blocked);
  await page.getByLabel('Electrical shading execution', { exact: true }).selectOption('detailed');
  await page.getByText('active module has no frozen electrical selection', { exact: true }).waitFor();
  assert.ok(await page.getByRole('button', { name: 'Validate and run', exact: true }).isDisabled());
  assert.equal(launches.length, 1);
  await open(detailed);
  await page.getByLabel('Electrical shading execution', { exact: true }).selectOption('detailed');
  const detailedRun = await run();
  assert.deepEqual(launches.at(-1), { electrical_shading_configuration: { requested_fidelity: 'level_2_bypass_substring', fallback_policy: 'fail_closed' } });
  { const toggle = page.getByRole('button', { name: 'Detailed electrical shading', exact: true });
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click(); }
  await page.getByRole('heading', { name: 'Detailed Electrical Shading', exact: true }).waitFor();
  assert.ok((await page.locator('[aria-label="Detailed Electrical Shading"]').innerText()).includes('not applicable'));
  const identityText = await page.locator('[aria-label="Electrical execution identity"]').innerText();
  const before = launches.length;
  await page.goto(`${origin}/?open=${detailed}&step=results`);
  { const toggle = page.getByRole('button', { name: 'Detailed electrical shading', exact: true });
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click(); }
  await page.getByRole('heading', { name: 'Detailed Electrical Shading', exact: true }).waitFor();
  assert.equal(await page.locator('[aria-label="Electrical execution identity"]').innerText(), identityText);
  await page.reload();
  { const toggle = page.getByRole('button', { name: 'Detailed electrical shading', exact: true });
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click(); }
  await page.getByRole('heading', { name: 'Detailed Electrical Shading', exact: true }).waitFor();
  assert.equal(launches.length, before, 'reload/reopen cannot launch computation');
  const result = await page.request.get(`${origin}/api/projects/${detailed}/runs/${detailedRun.simulation_run_id}/result`);
  assert.deepEqual((await result.json()).detailed_electrical_shading, detailedRun.detailed_electrical_shading);
  await open(fallback);
  await page.getByLabel('Electrical shading execution', { exact: true }).selectOption('detailed');
  await page.getByLabel('Fallback policy', { exact: true }).selectOption('explicit_lower_fidelity');
  await page.getByText(/Ready · explicit_fallback_available/).waitFor();
  const fallbackRun = await run();
  assert.equal(fallbackRun.detailed_electrical_shading.execution_identity.fallback_applied, true);
  await page.getByText(/Fallback occurred: yes/).waitFor();
  assert.ok((await page.locator('[aria-label="Electrical execution identity"]').innerText()).includes('level_0_geometric_only'));
  assert.deepEqual(detailedRun.detailed_electrical_shading.diagnostic_artifacts.artifacts, []);
  if (daylight) {
    await open(daylight);
    await page.getByLabel('Electrical shading execution', { exact: true }).selectOption('detailed');
    const daylightRun = await run();
    { const toggle = page.getByRole('button', { name: 'Detailed electrical shading', exact: true });
      if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click(); }
    await page.getByRole('heading', { name: 'Detailed Electrical Shading', exact: true }).waitFor();
    const identity = daylightRun.detailed_electrical_shading.execution_identity;
    assert.equal(identity.requested_fidelity, 'level_2_bypass_substring');
    assert.equal(identity.resolved_fidelity, 'level_2_bypass_substring');
    assert.equal(identity.runtime_support_result, 'pcc_complete');
    assert.ok(daylightRun.summary_result.total_energy_wh > 0);
    const channels = daylightRun.detailed_electrical_shading.attribution_energy_summary.periods[0].channels;
    assert.ok(Object.values(channels).some(c => c.applicable_duration_seconds > 0));
    assert.deepEqual(daylightRun.detailed_electrical_shading.diagnostic_artifacts.artifacts, []);
  }
  assert.deepEqual(errors, []);
  console.log('Browser launch: legacy, blocked, detailed dark, attribution navigation, persisted reload/reopen, explicit fallback and daylight detailed passed.');
} catch (error) {
  fs.writeFileSync("/tmp/rawibumi-closure-browser-failure.html", await page.content().catch(() => "Page unavailable"));
  throw error;
} finally { await browser.close(); }
