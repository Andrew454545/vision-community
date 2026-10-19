import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

async function screen(workType) {
  const elements = new Map(), calls = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, { value: id === 'workType' ? 'scene' : '', checked: false,
      handlers: {}, addEventListener(event, handler) { this.handlers[event] = handler; },
      click() { return this.handlers.click?.(); } });
    return elements.get(id);
  };
  const saved = { workType, dayStart: '06:00', nightStart: '00:00', dayPace: 'medium', nightPace: 'max',
    storageLimitGb: 20, retryMinutes: 30, preventSleep: true };
  const original = JSON.stringify(saved);
  const scope = { document: { getElementById: element }, location: { hash: '#synthetic-local-token' },
    history: { replaceState() {} }, fetch: async (path, options) => {
      calls.push({ path, options });
      return { ok: true, json: async () => ({ settings: saved, enabled: true, accountSaved: true, message: 'Paused' }) };
    } };
  runInNewContext(readFileSync(new URL('../../../community/background_web/app.js', import.meta.url), 'utf8'), scope);
  await element('refresh').click(); calls.length = 0;
  return { element, scope, calls, saved, original };
}

test('saved Object/Both background settings stay unchanged while enable/resume are blocked', async () => {
  for (const workType of ['object', 'both']) {
    const { element, scope, calls, saved, original } = await screen(workType);
    element('accept').checked = true; scope.buttons();
    assert.equal(element('workType').value, workType);
    assert.equal(element('enable').disabled, true);
    assert.equal(element('resume').disabled, true);
    for (const id of ['pause', 'remove', 'quit']) assert.equal(element(id).disabled, false, id);
    await scope.act('enable', { settings: saved }); await scope.act('resume');
    assert.equal(calls.length, 0); assert.equal(JSON.stringify(saved), original);
    assert.match(element('status').textContent, /Choose Scenes.*settings are kept/);
    element('workType').value = 'scene'; element('workType').handlers.change();
    assert.equal(element('enable').disabled, false);
    assert.equal(element('resume').disabled, true, 'unsaved choice cannot resume old Object task');
    assert.equal(JSON.stringify(saved), original);
  }
});

test('Scene background schedules keep enable/resume and safe pause/removal available', async () => {
  const { element, scope, calls, saved } = await screen('scene');
  element('accept').checked = true; scope.buttons();
  assert.equal(element('enable').disabled, false);
  assert.equal(element('resume').disabled, false);
  await scope.act('enable', { settings: saved, accept: true });
  assert.equal(calls.length, 1); assert.equal(calls[0].path, '/api/enable');
  assert.equal(JSON.parse(calls[0].options.body).settings.workType, 'scene');
  assert.equal(element('dayPace').value, 'medium'); assert.equal(element('nightPace').value, 'max');
});
