// Object inference/qualification is not approved yet. Disabling buttons is
// insufficient: hosted assignment, publication and new paid object searches
// must remain closed too. The only exception is our offline workerd fixture.
import { OBJECT_INDEX_MODEL } from './objectIndex.js';

export function objectCapabilities() {
  // Publish the missing gate explicitly. Scene readiness, prototype flags or
  // a saved local diagnostic may never advertise a qualified Object service.
  return { objectContributions: { ready: false, reason: 'object_verification_unavailable',
    model: OBJECT_INDEX_MODEL, deviceQualificationRequired: true, officialGen4Required: true } };
}

export function localObjectPrototype(request, env) {
  return env.OBJECT_PROTOTYPE_TEST_ONLY === '1'
    && new URL(request.url).origin === 'https://community.test';
}
