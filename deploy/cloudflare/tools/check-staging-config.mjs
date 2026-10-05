// Offline preflight for the existing closed staging deployment. No API/storage
// access or provisioning. An admission change needs its own measured rollout.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { RESOURCE_PROFILES } from './account-restore.mjs';

export function checkStagingConfig(config) {
  const resource = RESOURCE_PROFILES.staging;
  assert.equal(config.account_id, resource.accountId, 'wrong staging account');
  assert.equal(config.name, 'vision-community-staging', 'wrong staging Worker');
  assert.deepEqual(config.d1_databases, [{ binding: 'DB', database_name: 'vision-community-staging',
    database_id: resource.databaseId }], 'wrong staging database');
  assert.deepEqual(config.r2_buckets, [{ binding: 'INDEX', bucket_name: resource.bucket }], 'wrong staging bucket');
  assert.deepEqual(config.vars, { DEPLOYMENT_ENVIRONMENT: 'staging', INDEX_BUCKET_NAME: resource.bucket,
    RATE_LIMITS_REQUIRED: '1',
    DELETION_ARCHIVE_REQUIRED: '1', DELETION_ARCHIVE_ENVIRONMENT: 'staging',
    DELETION_ARCHIVE_DB_ID: resource.databaseId, RESTORE_MAINTENANCE: '0',
    SCENE_POLICY_ID: '', SCENE_AUDIT_MAX_LOCATIONS: '8' }, 'staging admission/privacy settings changed');
  assert.deepEqual(config.services, [{ binding: 'SCENE_VERIFIER', service: 'vision-community-native-host-staging',
    entrypoint: 'NativeSceneVerification' }], 'unexpected service binding');
  assert.deepEqual(config.ratelimits, [{ name: 'API_RATE_LIMITER', namespace_id: '1586479201', simple: { limit: 120, period: 60 } },
    { name: 'API_INGRESS_LIMITER', namespace_id: '1586479203', simple: { limit: 600, period: 60 } },
    { name: 'API_VIEW_LIMITER', namespace_id: '1586479205', simple: { limit: 12, period: 60 } }], 'staging abuse control changed');
  assert.equal(config.main, 'src/worker.js');
  assert.deepEqual(config.assets, { directory: '../../community/web', binding: 'ASSETS',
    html_handling: 'auto-trailing-slash', not_found_handling: '404-page', run_worker_first: true });
  assert.equal(config.preview_urls, false);
  assert.deepEqual(config.observability, { enabled: false });
  assert.equal(config.workers_dev, true);
  assert.deepEqual(config.triggers, { crons: ['0 * * * *'] });
  const allowed = new Set(['name', 'account_id', 'main', 'compatibility_date', 'compatibility_flags',
    'workers_dev', 'preview_urls', 'observability', 'triggers', 'd1_databases', 'r2_buckets',
    'ratelimits', 'services', 'vars', 'assets', '$schema']);
  assert.ok(Object.keys(config).every(key => allowed.has(key)), 'unexpected deployment override or resource');
  return { status: 'CONFIRMED_CLOSED_STAGING_CONFIG_PASSED', environment: 'staging',
    contributionsEnabled: false, searchEngineBound: false, cloudResourcesAccessed: false };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    console.log(JSON.stringify(checkStagingConfig(JSON.parse(readFileSync(new URL('../wrangler.staging.jsonc', import.meta.url), 'utf8')))));
  } catch {
    console.error('Staging configuration changed. Review the confirmed resource pair and closed admission settings before deploying.');
    process.exitCode = 1;
  }
}
