"""Append-only registry authority; no runtime or model inference in these tests."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from community import object_audit_registry as registry
from community.search_snapshot import digest, encoded
from community.object_audit_recovery import recovery_revocations
from community.process_owner import run_owned
from community.search_snapshot import resource_for_environment


class ObjectAuditRegistryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.old = self.root / 'old.json'
        self.added = self.root / 'added.json'
        self.target = self.root / 'extended.json'
        self.document = {'version': 1, 'scope': 'private-object-audit-registry', 'policyId': 'staging.synthetic',
            'resource': {'synthetic': True}, 'assignments': [self.entry(1)]}
        self.old.write_bytes(encoded(self.document))
        self.additions = {**self.document, 'assignments': [self.entry(2)]}
        self.added.write_bytes(encoded(self.additions))

    def entry(self, number):
        return {'leaseId': f'{number:032x}', 'profileId': '1'*64,
            'assignment': {'path': str(self.root/f'assignment-{number}.json'), 'bytes': 1, 'sha256': '2'*64},
            'source': {'path': str(self.root/'locations.tsv'), 'bytes': 1, 'sha256': '3'*64}}

    def extend(self):
        return registry.extend_registry(self.old, digest(self.old.read_bytes()), self.added,
            digest(self.added.read_bytes()), self.target)

    def read(self, document):
        self.target.write_bytes(encoded(document))
        return registry.read_registry(self.target, digest(self.target.read_bytes()))

    def test_builder_is_create_only_keeps_exact_prefix_and_returns_no_authorization(self):
        old, added = self.old.read_bytes(), self.added.read_bytes()
        report = self.extend()
        document = registry.read_registry(self.target, report['registrySha256'])
        self.assertEqual(registry.previous_registry(document), self.document)
        self.assertEqual(document['assignments'], self.document['assignments']+self.additions['assignments'])
        self.assertEqual(self.old.read_bytes(), old)
        self.assertEqual(self.added.read_bytes(), added)
        self.assertFalse(report['nativeAssignmentsValidated'])
        self.assertFalse(report['productionQualified'])
        self.assertNotIn(str(self.root), encoded(report).decode())
        original = self.target.read_bytes()
        with self.assertRaises(FileExistsError):
            self.extend()
        self.assertEqual(self.target.read_bytes(), original)

    def test_changed_history_policy_resource_order_or_removal_are_refused(self):
        self.extend()
        original = registry.read_registry(self.target, digest(self.target.read_bytes()))
        for field in ('profileId', 'leaseId', 'assignment', 'source'):
            changed = copy.deepcopy(original)
            value = changed['assignments'][0][field]
            changed['assignments'][0][field] = ({**value, 'sha256': 'f'*64}
                if isinstance(value, dict) else 'f'*len(value))
            with self.assertRaises(ValueError):
                registry.previous_registry(changed)
        for change in ({'policyId': 'different'}, {'resource': {}},
                       {'assignments': original['assignments'][::-1]},
                       {'assignments': original['assignments'][:1]}):
            with self.assertRaises(ValueError):
                registry.previous_registry({**original, **change})

    def test_old_registry_pin_byte_count_and_file_are_mandatory(self):
        self.extend()
        document = registry.read_registry(self.target, digest(self.target.read_bytes()))
        for change in ({'sha256': 'f'*64}, {'bytes': 1}, {'path': str(self.root/'missing.json')}):
            with self.assertRaises((ValueError, OSError)):
                registry.previous_registry({**document, 'previousRegistry': {**document['previousRegistry'], **change}})
        self.old.write_bytes(self.old.read_bytes()+b' ')
        with self.assertRaises(ValueError):
            registry.previous_registry(document)

    def test_schema_identity_pin_and_budgets_are_bounded(self):
        for change in ({'version': True}, {'version': 3}, {'extra': 1}, {'assignments': []},
                       {'assignments': [self.entry(1)]*2}, {'assignments': [self.entry(i) for i in range(65)]}):
            with self.assertRaises(ValueError):
                self.read({**self.document, **change})
        for change in ({'path': 'relative.tsv'}, {'bytes': True}, {'bytes': 1024**2+1},
                       {'sha256': 'invalid'}, {'extra': 1}):
            document = copy.deepcopy(self.document)
            document['assignments'][0]['source'].update(change)
            with self.assertRaises(ValueError):
                self.read(document)
        with patch.object(registry, 'MAX_REGISTRY_BYTES', 1):
            with self.assertRaises(ValueError):
                registry.read_registry(self.old, digest(self.old.read_bytes()))

    def test_builder_refuses_duplicate_lease_changed_identity_and_capacity_before_output(self):
        for change in ({'assignments': self.document['assignments']}, {'policyId': 'other'}, {'resource': {}}):
            self.added.write_bytes(encoded({**self.additions, **change}))
            with self.assertRaises(ValueError):
                self.extend()
            self.assertFalse(self.target.exists())
        self.added.write_bytes(encoded(self.additions))
        with patch.object(registry, 'MAX_ASSIGNMENTS', 1):
            with self.assertRaises(ValueError):
                self.extend()
        self.assertFalse(self.target.exists())

    def test_second_extension_preserves_the_complete_first_extension(self):
        self.extend()
        first = self.target
        original = first.read_bytes()
        second_additions = self.root/'third.json'
        second_additions.write_bytes(encoded({**self.document, 'assignments': [self.entry(3)]}))
        second = self.root/'second-extension.json'
        report = registry.extend_registry(first, digest(original), second_additions,
            digest(second_additions.read_bytes()), second)
        document = registry.read_registry(second, report['registrySha256'])
        self.assertEqual(len(registry.previous_registry(document)['assignments']), 2)
        self.assertEqual(len(document['assignments']), 3)
        self.assertEqual(first.read_bytes(), original)

    def test_actual_node_export_and_python_recovery_cover_70_historical_and_new_leases(self):
        node = os.environ.get('VISION_TEST_NODE')
        if not node:
            self.skipTest('explicit private Node runtime unavailable')
        entries = [self.entry(i) for i in range(1, 71)]
        resource = resource_for_environment('staging')
        old = {**self.document, 'resource': resource}
        self.old.write_bytes(encoded(old))
        document = {**self.document, 'resource': resource, 'version': 2, 'assignments': entries,
            'previousRegistry': {'path': str(self.old), 'bytes': self.old.stat().st_size,
                                 'sha256': digest(self.old.read_bytes())}}
        self.target.write_bytes(encoded(document))
        self.assertEqual(registry.previous_registry(document), old)
        tools = Path(__file__).resolve().parents[2]/'deploy/cloudflare/tools'
        database, output = self.root/'current.sqlite', self.root/'authority-export'
        script = '''
          import {readFileSync,writeFileSync} from 'node:fs';
          import {createHash} from 'node:crypto';
          import {DatabaseSync} from 'node:sqlite';
          const {exportDeletionLedger}=await import(RESTORE);
          const {prepareObjectErasureRecovery}=await import(ERASURE);
          const [database,registry,out]=process.argv.slice(1);
          const raw=readFileSync(registry),doc=JSON.parse(raw);
          const sha=value=>createHash('sha256').update(value).digest('hex');
          const sql=new DatabaseSync(database);
          sql.exec(`CREATE TABLE accounts(id TEXT,deleted_at INTEGER,units INTEGER,recovery_hash TEXT);
            CREATE TABLE account_deletion_receipts(account_id TEXT,request_key TEXT,deleted_at INTEGER,units_forfeited INTEGER);
            CREATE TABLE leases(id TEXT,account_id TEXT,lane TEXT);
            CREATE TABLE account_cleanup(artifact_key TEXT,account_id TEXT,state TEXT);`);
          const owner='a'.repeat(32);
          sql.prepare('INSERT INTO accounts VALUES (?,950,0,NULL)').run(owner);
          sql.prepare('INSERT INTO account_deletion_receipts VALUES (?,?,950,3)').run(owner,'b'.repeat(64));
          for(const entry of doc.assignments)sql.prepare("INSERT INTO leases VALUES (?,?,'object')").run(entry.leaseId,owner);
          const ledger=Buffer.from(JSON.stringify(exportDeletionLedger(sql,1000,'staging')));
          sql.close();
          writeFileSync(out+'.ledger.json',ledger,{flag:'wx'});
          prepareObjectErasureRecovery({current:database,currentSha256:sha(readFileSync(database)),
            registry,registrySha256:sha(raw),policySha256:'f'.repeat(64),deletions:out+'.ledger.json',
            deletionsSha256:sha(ledger),notBefore:1000,now:1000,environment:'staging',out});
        '''.replace('RESTORE', json.dumps((tools/'account-restore.mjs').as_uri())).replace(
            'ERASURE', json.dumps((tools/'object-erasure-recovery.mjs').as_uri()))
        with (self.root/'node.stdout').open('xb') as stdout, (self.root/'node.stderr').open('xb') as stderr:
            result = run_owned([node, '--input-type=module', '-e', script, str(database), str(self.target), str(output)],
                env=dict(os.environ), cwd=self.root, stdout=stdout, stderr=stderr, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(result.returncode, 0, (self.root/'node.stderr').read_text())
        path = output/'object-erasure-authority.private.json'
        raw = path.read_bytes()
        native = recovery_revocations(path, digest(raw), registry_sha256=digest(self.target.read_bytes()),
            verifier=SimpleNamespace(document={'resource': resource}, policy_sha256='f'*64),
            entries={entry['leaseId']: entry for entry in entries}, now=1000)
        self.assertEqual({row['leaseId'] for row in native['revocations']}, {entry['leaseId'] for entry in entries})
        self.assertEqual(len(native['revocations']), 70)
        self.assertEqual(json.loads((output/'export-report.json').read_bytes())['authoritySha256'], digest(raw))


if __name__ == '__main__':
    unittest.main()
