import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createServer } from 'vite';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
try {
  const { DetailedElectricalShading, AttributionPeriodTable, signedEnergy, coveragePercentage } = await server.ssrLoadModule('/src/results/DetailedElectricalShading.tsx');
  const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  for (const [name, result] of Object.entries(cases)) {
    const before = JSON.stringify(result);
    const html = renderToStaticMarkup(React.createElement(DetailedElectricalShading, { result }));
    assert.equal(JSON.stringify(result), before, 'render must not mutate persisted results');
    assert.ok(html.includes('Complete means all applicable simulated coverage'));
    assert.ok(html.includes('never subtracted from production again'));
    assert.ok(!html.includes('<svg'), 'attribution is not combined in actual energy charts');
    assert.ok(html.includes('Run total'));
    for (const period of result.attribution_energy_summary.periods) {
      const table = renderToStaticMarkup(React.createElement(AttributionPeriodTable, { period }));
      for (const channel of Object.values(period.channels)) {
        if (['complete', 'partial'].includes(channel.completeness)) assert.ok(table.includes(`data-raw-wh="${channel.observed_signed_energy_wh}"`), 'every daily/monthly/run energy must match persisted summary exactly');
        for (const reason of channel.unavailable_reason_codes) assert.ok(table.includes(reason));
      }
      if (period.period_kind !== 'run_total') assert.ok(html.includes(period.period_key));
    }
    const first = result.attribution_energy_summary.periods[0];
    for (const channel of Object.values(first.channels)) {
      if (['complete', 'partial'].includes(channel.completeness)) {
        assert.ok(html.includes(`data-raw-wh="${channel.observed_signed_energy_wh}"`));
      }
      for (const reason of channel.unavailable_reason_codes) assert.ok(html.includes(reason));
    }
    if (name === 'signed') {
      assert.ok(html.includes('−') && html.includes('recovery'));
      assert.ok(html.includes('+') && html.includes('reduction'));
      assert.ok(html.includes('&lt;0.001 Wh'));
    }
    if (name === 'partial') assert.ok(html.includes('partial coverage'));
    if (name === 'unavailable' || name === 'dark') assert.ok(!html.includes('data-raw-wh'));
    if (name === 'dark') assert.ok(html.includes('not applicable'));
    fs.writeFileSync(`/tmp/rawibumi-inc3-${name}.html`, html);
  }
  assert.equal(coveragePercentage(0.0000001), '<0.01%');
  assert.equal(coveragePercentage(0.9999999), '>99.99%');
  assert.equal(signedEnergy(null), '—');
  assert.equal(signedEnergy(0), '0 Wh');
  assert.equal(signedEnergy(-0.0000001), '−<0.001 Wh · recovery');
  assert.equal(renderToStaticMarkup(React.createElement(DetailedElectricalShading, { result: { attribution_energy_summary: null } })), '');
  const source = fs.readFileSync('src/results/DetailedElectricalShading.tsx', 'utf8');
  assert.ok(!/fetch\(|\.reduce\(|new Date|Date\.|value_w|duration_seconds\s*\/\s*3600/.test(source), 'no fetching curves, regrouping timestamps, or attribution integration');
  console.log('Detailed rendering: signed/small values, coverage, reasons, raw values, period keys, isolation and legacy absence passed.');
} finally {
  await server.close();
}
