import assert from 'node:assert/strict';
import test from 'node:test';
import { localObjectPrototype } from './objectAdmission.js';

test('unqualified hosted object work cannot be enabled by a button, flag alone or request header', () => {
  for (const url of ['https://vision-community-staging.visioncommunity.workers.dev/api/leases',
    'https://vision-community.visioncommunity.workers.dev/api/leases','http://community.test/api/leases',
    'https://community.test.other.example/api/leases']) {
    assert.equal(localObjectPrototype(new Request(url, {headers:{Host:'community.test'}}),
      {OBJECT_PROTOTYPE_TEST_ONLY:'1'}),false);
  }
  assert.equal(localObjectPrototype(new Request('https://community.test/api/leases'),{}),false);
  assert.equal(localObjectPrototype(new Request('https://community.test/api/leases'),
    {OBJECT_PROTOTYPE_TEST_ONLY:'true'}),false);
  assert.equal(localObjectPrototype(new Request('https://community.test/api/leases'),
    {OBJECT_PROTOTYPE_TEST_ONLY:'1'}),true);
});
