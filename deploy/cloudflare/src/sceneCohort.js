import { encodeUtf8, sha256Hex } from './model.js';

// A finite staging invitation is an additional restriction, never an approval.
// Store hashes of opaque account IDs; never accept invitations from a request.
export async function sceneCohortAllows(env, account, now = Date.now()) {
  if (env.SCENE_COHORT_ACCOUNTS === undefined && env.SCENE_COHORT_UNTIL === undefined) return true;
  if (env.DEPLOYMENT_ENVIRONMENT !== 'staging'
      || env.INDEX_BUCKET_NAME !== 'vision-community-staging'
      || env.DELETION_ARCHIVE_DB_ID !== '17043cb7-5dab-4a6f-84ca-19ae1c14cc05'
      || typeof env.SCENE_POLICY_ID !== 'string' || !env.SCENE_POLICY_ID.startsWith('staging.')
      || typeof env.SCENE_COHORT_ACCOUNTS !== 'string' || env.SCENE_COHORT_ACCOUNTS.length > 1200
      || typeof env.SCENE_COHORT_UNTIL !== 'string' || !/^[1-9][0-9]{12}$/.test(env.SCENE_COHORT_UNTIL)) return false;
  const deadline = Number(env.SCENE_COHORT_UNTIL);
  if (!Number.isFinite(now) || now >= deadline || deadline - now > 8 * 86400000) return false;
  let hashes;
  try { hashes = JSON.parse(env.SCENE_COHORT_ACCOUNTS); } catch { return false; }
  if (!Array.isArray(hashes) || !hashes.length || hashes.length > 16
      || hashes.some(value => typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value))
      || new Set(hashes).size !== hashes.length || typeof account !== 'string' || !account) return false;
  return hashes.includes(await sha256Hex(encodeUtf8(account)));
}
