'use strict';
const token = location.hash.slice(1);
history.replaceState(null, '', '/');
const el = id => document.getElementById(id);
let initialized = false;
let enabled = false;
let locked = false;
let closed = false;
function buttons() {
  if (closed) {
    for (const id of ['enable','pause','resume','remove','refresh','quit']) el(id).disabled = true;
    return;
  }
  el('enable').disabled = locked || !initialized || !el('accept').checked;
  for (const id of ['pause', 'resume', 'remove']) el(id).disabled = locked || !enabled;
  el('refresh').disabled = locked;
  el('quit').disabled = locked;
}
async function request(action, body) {
  const response = await fetch(action ? '/api/' + action : '/api/status', {
    method: action ? 'POST' : 'GET', headers: {'X-Vision-Token': token, 'Content-Type': 'application/json'},
    ...(action ? {body: JSON.stringify(body || {})} : {})
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Please try again.');
  return value;
}
function render(value) {
  el('status').textContent = value.message;
  if (value.settings) {
    enabled = value.enabled;
    el('code-label').hidden = value.accountSaved;
    if (!initialized) {
      for (const [id, setting] of Object.entries(value.settings)) {
        if (id === 'preventSleep') el(id).checked = setting;
        else el(id).value = setting;
      }
      initialized = true;
    }
  }
  buttons();
}
async function act(name, body) {
  locked = true; buttons(); el('status').textContent = 'Please wait. Any current batch will finish safely.';
  try {
    render(await request(name, body)); el('code').value = '';
    if (name === 'quit') closed = true;
  } catch (error) {el('status').textContent = error.message;}
  finally {locked = false; buttons();}
}
el('settings').addEventListener('submit', event => {
  event.preventDefault();
  const settings = {};
  for (const id of ['dayStart','nightStart','dayPace','nightPace']) settings[id] = el(id).value;
  for (const id of ['retryMinutes','storageLimitGb']) settings[id] = Number(el(id).value);
  settings.preventSleep = el('preventSleep').checked;
  act('enable', {settings, code: el('code').value, accept: el('accept').checked});
});
el('accept').addEventListener('change', buttons);
for (const id of ['pause','resume','remove','quit']) el(id).addEventListener('click', () => act(id));
el('refresh').addEventListener('click', async () => {
  try {render(await request());} catch (error) {el('status').textContent = error.message;}
});
el('refresh').click();
