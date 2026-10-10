"""Private, restartable Object audit jobs. No qualification, publication or credit.

Only the independently pinned operator registry chooses assignments. HTTP callers
submit candidate bytes, never paths, programs, models, thresholds or authority.
The existing native auditor owns/kills its children and retains every attempt.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import time

from .native_object_verifier import NativeObjectVerifier, MAX_MANIFEST, MAX_FILES
from .native_scene_search import strict_json
from .object_canary import regular
from .object_index import decode_object_submission
from .search_snapshot import digest, encoded, pinned_read, bounded_read

# Four audited locations need only small lanes. Do not inherit the prototype's
# thousand-location request budget at this private, two-connection endpoint.
MAX_REQUEST = 4 * 1024 * 1024
MAX_JOBS = 64
MAX_QUEUED = 8
MAX_ATTEMPTS = 3
MAX_INPUT_BYTES = 512 * 1024 * 1024
MIN_FREE_BYTES = 1024 * 1024 * 1024
ID = re.compile(r'[0-9a-f]{32}\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')


class JobError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.status = status


def require(value, code='invalid_object_job', status=400):
    if not value:
        raise JobError(code, status)


def write_new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


class ObjectAuditJobs:
    def __init__(self, verifier, registry, registry_sha256, work, *, clock=time.time):
        self.verifier, self.clock = verifier, clock
        self.registry_path = regular(registry)
        self.registry_sha256 = registry_sha256
        document = strict_json(pinned_read(self.registry_path, registry_sha256, MAX_MANIFEST))
        require(isinstance(document, dict) and set(document) == {'version', 'scope', 'policyId', 'resource', 'assignments'}
                and document['version'] == 1 and document['scope'] == 'private-object-audit-registry'
                and document['policyId'] == verifier.document['policyId']
                and document['resource'] == verifier.document['resource'], 'invalid_object_job_registry')
        entries = document['assignments']
        require(isinstance(entries, list) and 1 <= len(entries) <= MAX_JOBS, 'invalid_object_job_registry')
        self.entries = {}
        for entry in entries:
            require(isinstance(entry, dict) and set(entry) == {'leaseId', 'profileId', 'assignment', 'source'}
                    and isinstance(entry['leaseId'], str) and ID.fullmatch(entry['leaseId'])
                    and entry['leaseId'] not in self.entries, 'invalid_object_job_registry')
            for key in ('assignment', 'source'):
                pin = entry[key]
                require(isinstance(pin, dict) and set(pin) == {'path', 'sha256', 'bytes'}
                        and isinstance(pin['path'], str) and Path(pin['path']).is_absolute()
                        and type(pin['bytes']) is int and 0 < pin['bytes'] <= MAX_MANIFEST,
                        'invalid_object_job_registry')
                raw = pinned_read(regular(pin['path']), pin['sha256'], MAX_MANIFEST)
                require(len(raw) == pin['bytes'], 'object_job_registry_changed', 503)
            trusted = verifier.assignment(entry['assignment']['path'], entry['assignment']['sha256'],
                                          self.source(entry))
            require(trusted['leaseId'] == entry['leaseId'] and trusted['profileId'] == entry['profileId'],
                    'invalid_object_job_registry')
            self.entries[entry['leaseId']] = entry
        self.work = Path(work).absolute()
        regular(self.work.parent, directory=True)
        self.work.mkdir(mode=0o700, exist_ok=True)
        regular(self.work, directory=True)
        # Registry/runtime/operator inputs must not be inside the mutable spool.
        roots = [self.registry_path, verifier.policy_path, verifier.binary, verifier.models,
                 verifier.authority_path, verifier.snapshot_path]
        roots += [Path(entry['path']) for entry in verifier.authority_doc['protectedDatabase'].values()]
        roots += [Path(entry[key]['path']) for entry in entries for key in ('assignment', 'source')]
        require(all(path != self.work and self.work not in path.parents and path not in self.work.parents
                    for path in roots), 'object_job_spool_overlaps_authority')
        self.guard = (self.work / 'service.lock').open('a+b')
        try:
            regular(self.work / 'service.lock')
            if os.name == 'nt':
                import msvcrt
                self.guard.seek(0)
                if not self.guard.read(1):
                    self.guard.write(b'1'); self.guard.flush()
                self.guard.seek(0)
                msvcrt.locking(self.guard.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.guard.close()
            raise JobError('object_job_service_already_running', 503) from None
        self.lock, self.wake, self.stop = threading.RLock(), threading.Event(), threading.Event()
        self.active_job = None
        self.worker = None
        self.db = self.work / 'jobs.sqlite'
        try:
            if self.db.exists() or self.db.is_symlink():
                regular(self.db)
            with self.connect() as db:
                db.executescript('''CREATE TABLE IF NOT EXISTS identity (registry TEXT, policy TEXT);
                  CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, lease TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                    submission TEXT NOT NULL, candidate TEXT NOT NULL, input_bytes INTEGER NOT NULL,
                    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, retry_at INTEGER NOT NULL DEFAULT 0,
                    receipt TEXT, created INTEGER NOT NULL);
                  CREATE TABLE IF NOT EXISTS attempts (
                    job TEXT NOT NULL REFERENCES jobs(id), number INTEGER NOT NULL, state TEXT NOT NULL,
                    started INTEGER NOT NULL, finished INTEGER, receipt TEXT, PRIMARY KEY(job,number));''')
                identity = db.execute('SELECT * FROM identity').fetchall()
                wanted = (registry_sha256, verifier.policy_sha256)
                require(not identity or (len(identity) == 1 and tuple(identity[0]) == wanted),
                        'object_job_service_identity_changed', 503)
                if not identity:
                    db.execute('INSERT INTO identity VALUES (?,?)', wanted)
            self.recover()
        except BaseException:
            self.guard.close()
            raise

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def source(self, entry):
        pin = entry['source']
        raw = pinned_read(regular(pin['path']), pin['sha256'], MAX_MANIFEST)
        require(len(raw) == pin['bytes'], 'object_job_registry_changed', 503)
        return raw

    def entry(self, row):
        pinned_read(self.registry_path, self.registry_sha256, MAX_MANIFEST)
        entry = self.entries[row['lease']]
        self.verifier.assignment(entry['assignment']['path'], entry['assignment']['sha256'], self.source(entry))
        return entry

    def response(self, row):
        entry = self.entries[row['lease']]
        return {'version': 1, 'jobId': row['id'], 'leaseId': row['lease'], 'profileId': entry['profileId'],
                'policyId': self.verifier.document['policyId'], 'assignmentSha256': entry['assignment']['sha256'],
                'submissionSha256': row['submission'], 'candidateManifestSha256': row['candidate'],
                'state': row['state'], 'decision': row['state'] if row['state'] in ('approved', 'rejected') else 'pending',
                'attempts': row['attempts'], 'retryAt': row['retry_at'], 'receiptSha256': row['receipt'],
                'serverAuthorization': False, 'productionQualified': False,
                'acceptedContributions': 0, 'searchCreditsCreated': 0}

    def get(self, job):
        require(isinstance(job, str) and ID.fullmatch(job), 'unknown_object_job', 404)
        with self.lock, self.connect() as db:
            require(not self.stop.is_set(), 'object_verifier_unavailable', 503)
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
            require(row is not None, 'unknown_object_job', 404)
            return self.response(row)

    def submit(self, raw):
        require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_REQUEST)
        body = strict_json(raw)
        require(isinstance(body, dict) and set(body) == {'version', 'leaseId', 'profileId', 'policyId',
                'assignmentSha256', 'submissionSha256', 'objectIndex'} and body['version'] == 1)
        lease = body['leaseId']
        require(isinstance(lease, str) and lease in self.entries, 'unknown_object_assignment', 403)
        entry = self.entries[lease]
        require(body['profileId'] == entry['profileId'] and body['policyId'] == self.verifier.document['policyId']
                and body['assignmentSha256'] == entry['assignment']['sha256'], 'object_job_identity_mismatch', 409)
        require(isinstance(body['submissionSha256'], str) and HEX.fullmatch(body['submissionSha256']))
        # Canonical object identity tolerates harmless JSON whitespace, never changed bytes.
        fingerprint = digest(encoded(body))
        with self.lock, self.connect() as db:
            require(not self.stop.is_set(), 'object_verifier_unavailable', 503)
            previous = db.execute('SELECT * FROM jobs WHERE lease=?', (lease,)).fetchone()
            if previous:
                require(previous['fingerprint'] == fingerprint, 'object_job_conflict', 409)
                return self.response(previous)
            index = body['objectIndex']
            require(isinstance(index, dict) and set(index) == {'manifest', 'files', 'sourceTsv'}
                    and isinstance(index['files'], dict) and len(index['files']) <= 87)
            require(all(isinstance(name, str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.bin', name)
                        for name in index['files']), 'invalid_object_job_file')
            manifest, files, source = decode_object_submission(index)
            require(source == self.source(entry), 'object_job_source_mismatch', 409)
            manifest_raw = encoded(manifest)
            require(len(manifest_raw) <= MAX_MANIFEST and sum(map(len, files.values())) <= MAX_FILES)
            size = len(manifest_raw) + len(source) + sum(map(len, files.values()))
            usage = db.execute("SELECT COUNT(*),COALESCE(SUM(input_bytes),0),"
                               "COALESCE(SUM(state IN ('staging','queued','running')),0) FROM jobs").fetchone()
            require(usage[0] < MAX_JOBS and usage[1] + size <= MAX_INPUT_BYTES and usage[2] < MAX_QUEUED,
                    'object_job_capacity_reached', 503)
            require(shutil.disk_usage(self.work).free >= MIN_FREE_BYTES + size, 'object_job_disk_budget', 503)
            job, now = secrets.token_hex(16), int(self.clock())
            folder = self.work / job
            folder.mkdir(mode=0o700)
            (self.work / ('attempts-' + job)).mkdir(mode=0o700)
            # The staging receipt is durable before any candidate file writes.
            db.execute('INSERT INTO jobs (id,lease,fingerprint,submission,candidate,input_bytes,state,created) '
                       "VALUES (?,?,?,?,?,?,'staging',?)",
                       (job, lease, fingerprint, body['submissionSha256'], digest(manifest_raw), size, now))
            db.commit()
            try:
                candidate = folder / 'candidate'
                candidate.mkdir(mode=0o700)
                write_new(candidate / 'manifest.json', manifest_raw)
                write_new(folder / 'locations.tsv', source)
                for name, data in files.items():
                    write_new(candidate / name, data)
                trusted = self.verifier.assignment(entry['assignment']['path'], entry['assignment']['sha256'], source)
                self.verifier.validate_index(candidate, digest(manifest_raw), source, trusted)
                db.execute("UPDATE jobs SET state='queued' WHERE id=?", (job,))
            except BaseException:
                db.execute("UPDATE jobs SET state='failed',retry_at=? WHERE id=?", (now + 60, job))
                db.commit()
                raise
            db.commit()
            self.wake.set()
            return self.response(db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone())

    def control(self, job, action):
        require(action in ('cancel', 'retry'))
        with self.lock, self.connect() as db:
            self.get(job)
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
            if action == 'cancel':
                # Revocation wins over a late native approval. Original evidence stays private.
                db.execute("UPDATE jobs SET state='cancelled' WHERE id=?", (job,))
            elif row['state'] == 'failed':
                require(row['attempts'] < MAX_ATTEMPTS and self.clock() >= row['retry_at'], 'object_job_retry_limited', 429)
                active = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','staging')").fetchone()[0]
                require(active < MAX_QUEUED, 'object_job_capacity_reached', 503)
                # A partial stage is never repaired/reinterpreted as a complete candidate.
                entry = self.entry(row)
                source = self.source(entry)
                require(pinned_read(regular(self.work / job / 'locations.tsv'), entry['source']['sha256'], MAX_MANIFEST)
                        == source, 'object_job_candidate_incomplete', 409)
                trusted = self.verifier.assignment(entry['assignment']['path'], entry['assignment']['sha256'], source)
                self.verifier.validate_index(self.work / job / 'candidate', row['candidate'], source, trusted)
                db.execute("UPDATE jobs SET state='queued' WHERE id=?", (job,))
            db.commit()
            self.wake.set()
            return self.response(db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone())

    def receipt(self, row):
        entry = self.entry(row)
        source = self.source(entry)
        require(pinned_read(regular(self.work / row['id'] / 'locations.tsv'), entry['source']['sha256'], MAX_MANIFEST)
                == source, 'object_job_source_changed', 503)
        trusted = self.verifier.assignment(entry['assignment']['path'], entry['assignment']['sha256'], source)
        self.verifier.validate_index(self.work / row['id'] / 'candidate', row['candidate'], source, trusted)
        path = self.work / ('attempts-' + row['id']) / f"attempt-{row['attempts']}" / 'audit-report.json'
        raw = bounded_read(regular(path), MAX_MANIFEST)
        report = strict_json(raw)
        expected = {'status': 'COMPLETE', 'policyId': self.verifier.document['policyId'],
            'policySha256': self.verifier.policy_sha256, 'assignmentSha256': entry['assignment']['sha256'],
            'candidateManifestSha256': row['candidate'], 'sourceSha256': entry['source']['sha256'],
            'runtimeProfileSha256': self.verifier.profile['sha256'],
            'protectedSnapshotSha256': self.verifier.authority_doc['protectedSnapshot']['sha256'],
            'locations': len(trusted['records']), 'nativeReferenceRecomputed': True, 'protectedAssignmentsChecked': True,
            'serverAuthorization': False, 'productionQualified': False, 'acceptedContributions': 0, 'searchCreditsCreated': 0}
        require(isinstance(report, dict) and all(type(report.get(k)) is type(v) and report[k] == v for k, v in expected.items())
                and report.get('decision') in ('approved', 'rejected'), 'object_job_receipt_unavailable', 503)
        self.verifier.verify_inputs()
        return report['decision'], digest(raw)

    def finish(self, db, row, state, receipt=None):
        now = int(self.clock())
        db.execute("UPDATE attempts SET state=?,finished=?,receipt=? WHERE job=? AND number=? AND state='running'",
                   (state, now, receipt, row['id'], row['attempts']))
        db.execute("UPDATE jobs SET state=?,receipt=?,retry_at=? WHERE id=? AND state='running' AND attempts=?",
                   (state, receipt, now + 60 * 2 ** (row['attempts'] - 1) if state == 'failed' else 0,
                    row['id'], row['attempts']))

    def recover(self):
        with self.lock, self.connect() as db:
            require(self.active_job is None, 'object_job_worker_busy', 409)
            # Never edit the old auditor's report or claim its outcome from a PID check.
            db.execute("UPDATE jobs SET state='failed',retry_at=? WHERE state='staging'", (int(self.clock()) + 60,))
            for row in db.execute("SELECT j.* FROM jobs j JOIN attempts a ON a.job=j.id AND a.number=j.attempts "
                                  "WHERE a.state='running'").fetchall():
                try:
                    state, receipt = self.receipt(row)
                    self.finish(db, row, state, receipt)
                except (OSError, ValueError, KeyError, TypeError):
                    self.finish(db, row, 'failed')
                    db.execute("UPDATE attempts SET state='unconfirmed' WHERE job=? AND number=?",
                               (row['id'], row['attempts']))

    def run_next(self):
        with self.lock, self.connect() as db:
            if self.stop.is_set() or self.active_job is not None:
                return False
            # A transient settlement failure may leave a completed native receipt
            # without a committed decision. Recover it without another model run.
            if db.execute("SELECT 1 FROM attempts WHERE state='running'").fetchone():
                self.recover()
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if not row:
                return False
            require(shutil.disk_usage(self.work).free >= MIN_FREE_BYTES, 'object_job_disk_budget', 503)
            number = row['attempts'] + 1
            require(number <= MAX_ATTEMPTS, 'object_job_retry_limited', 429)
            db.execute("UPDATE jobs SET state='running',attempts=? WHERE id=? AND state='queued'", (number, row['id']))
            db.execute("INSERT INTO attempts VALUES (?,?,'running',?,NULL,NULL)", (row['id'], number, int(self.clock())))
            db.commit()
            row = db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone()
            self.active_job = row['id']
        try:
            try:
                entry = self.entry(row)
                self.verifier.audit(assignment=entry['assignment']['path'], assignment_sha256=entry['assignment']['sha256'],
                    source=self.work / row['id'] / 'locations.tsv', candidate=self.work / row['id'] / 'candidate',
                    candidate_sha256=row['candidate'], out=self.work / ('attempts-' + row['id']) / f'attempt-{number}')
                state, receipt = self.receipt(row)
            except Exception:
                state, receipt = 'failed', None
            with self.lock, self.connect() as db:
                self.finish(db, row, state, receipt)
        finally:
            with self.lock:
                self.active_job = None
        return True

    def start(self):
        require(self.worker is None, 'object_job_worker_already_started', 409)
        def loop():
            while not self.stop.is_set():
                self.wake.clear()
                try:
                    if self.run_next():
                        continue
                except (OSError, ValueError, sqlite3.Error):
                    # No hot retry after disk/authority/database failure.
                    pass
                self.wake.wait(60)
        self.worker = threading.Thread(target=loop, name='private-object-auditor', daemon=True)
        self.worker.start()

    def close(self):
        with self.lock:
            require(self.worker is not None or self.active_job is None, 'object_job_worker_busy', 409)
            self.stop.set()
            self.wake.set()
        if self.worker:
            self.worker.join()  # Native work is bounded by the pinned <=900s policy.
        with self.lock:
            self.guard.close()


def make_server(jobs, secret, *, port=0):
    require(isinstance(secret, str) and re.fullmatch(r'[\x21-\x7e]{32,256}', secret), 'private_verifier_secret_required')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def setup(self):
            super().setup()
            self.connection.settimeout(15)
        def reply(self, status, value):
            raw = encoded(value)
            self.close_connection = True
            self.send_response(status)
            for key, value in {'Content-Type': 'application/json', 'Cache-Control': 'no-store',
                               'Content-Length': str(len(raw)), 'Connection': 'close'}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)
        def dispatch(self):
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + secret).encode()):
                return self.reply(401, {'error': 'unauthorized'})
            route = re.fullmatch(r'/object-audits/([0-9a-f]{32})(?:/(cancel|retry))?', self.path)
            try:
                if self.command == 'GET' and route and route[2] is None:
                    return self.reply(200, jobs.get(route[1]))
                require(self.command == 'POST' and (self.path == '/object-audits' or (route and route[2])), 'not_found', 404)
                lengths = self.headers.get_all('Content-Length', [])
                require(len(lengths) == 1 and re.fullmatch('[0-9]+', lengths[0])
                        and 0 < int(lengths[0]) <= MAX_REQUEST and not self.headers.get('Transfer-Encoding')
                        and self.headers.get('Content-Type', '').split(';')[0].strip() == 'application/json')
                raw = self.rfile.read(int(lengths[0]))
                require(len(raw) == int(lengths[0]))
                if route:
                    require(strict_json(raw) == {})
                    value = jobs.control(route[1], route[2])
                else:
                    value = jobs.submit(raw)
                self.reply(200, value)
            except JobError as error:
                self.reply(error.status, {'error': str(error)})
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                self.reply(503, {'error': 'object_verifier_unavailable'})
        do_GET = dispatch
        do_POST = dispatch
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 2
        def __init__(self, *args):
            self.slots = threading.BoundedSemaphore(2)
            super().__init__(*args)
        def process_request(self, request, address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, address)
            except BaseException:
                self.slots.release()
                raise
        def process_request_thread(self, request, address):
            try:
                super().process_request_thread(request, address)
            finally:
                self.slots.release()
    return Server(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'models', 'policy', 'registry', 'work'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('policy-sha256', 'registry-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    jobs = server = None
    try:
        verifier = NativeObjectVerifier(args.binary, args.models, args.policy, args.policy_sha256)
        jobs = ObjectAuditJobs(verifier, args.registry, args.registry_sha256, args.work)
        server = make_server(jobs, os.environ.get('VISION_OBJECT_VERIFIER_SECRET', ''), port=args.port)
        jobs.start()
        print(encoded({'ready': True, 'bind': '127.0.0.1', 'port': server.server_port,
                       'scope': 'private-object-audit-jobs', 'productionQualified': False}).decode(), flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception:
        print(encoded({'ready': False, 'error': 'private_object_verifier_start_failed'}).decode(), flush=True)
        return 1
    finally:
        if server:
            server.server_close()
        if jobs:
            jobs.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
