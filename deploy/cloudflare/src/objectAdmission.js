// Object inference/qualification is not approved yet. Disabling buttons is
// insufficient: hosted assignment, publication and new paid object searches
// must remain closed too. The only exception is our offline workerd fixture.
export function localObjectPrototype(request, env) {
  return env.OBJECT_PROTOTYPE_TEST_ONLY === '1'
    && new URL(request.url).origin === 'https://community.test';
}
