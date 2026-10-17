import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { checkStagingConfig } from '../tools/check-staging-config.mjs';

const current = () => JSON.parse(readFileSync(new URL('../wrangler.staging.jsonc', import.meta.url), 'utf8'));
test('the checked-in closed staging config agrees with the confirmed restore resource identity', () => {
  assert.equal(checkStagingConfig(current()).status, 'CONFIRMED_CLOSED_STAGING_CONFIG_PASSED');
});
test('the retired release-staging and production/mixed resource mappings cannot pass staging preflight', () => {
  for (const change of [config => { config.d1_databases[0].database_id = '1abba87d-d04f-41bb-8a11-7b6a1a662e39'; },
    config => { config.r2_buckets[0].bucket_name = 'vision-community-release-staging'; },
    config => { config.r2_buckets[0].bucket_name = 'vision-community'; },
    config => { config.vars.DELETION_ARCHIVE_DB_ID = 'ed4705fa-1190-41fa-86a0-02d755db1b2a'; }]) {
    const config = current(); change(config); assert.throws(() => checkStagingConfig(config));
  }
});
test('an environment override or added search service cannot silently reopen the closed staging deployment', () => {
  for (const change of [config => { config.env = { production: {} }; },
    config => { config.services.push({ binding: 'SEARCH_ENGINE', service: 'unexpected' }); },
    config => { config.vars.SCENE_POLICY_ID = 'unmeasured'; }]) {
    const config = current(); change(config); assert.throws(() => checkStagingConfig(config));
  }
});
