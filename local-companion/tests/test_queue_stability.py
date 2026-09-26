from __future__ import annotations

import sqlite3

import pytest

from tda_companion.legacy.artifacts import sha256_json
from tda_companion.store import Conflict, Store


BODY = dict(
    kind='synthetic.fixture',
    campaign_id='synthetic-campaign',
    session_id='synthetic-session',
    source_id='synthetic-source',
    units=3,
)


def test_v2_database_migrates_queue_metadata_without_losing_jobs(tmp_path):
    database = tmp_path / 'jobs.sqlite3'
    db = sqlite3.connect(database)
    try:
        db.executescript(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, signature TEXT NOT NULL,
                body TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, attempt INTEGER NOT NULL DEFAULT 0,
                error TEXT, result TEXT, updated TEXT NOT NULL
            );
            CREATE TABLE events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                code TEXT NOT NULL, at TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info', data TEXT
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=2;
            """
        )
        body = {
            **BODY,
        }
        db.execute(
            "INSERT INTO jobs(id,idem,signature,body,status,stage,completed,attempt,error,result,updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                'legacy-job',
                'legacy-idem',
                'legacy-signature',
                __import__('json').dumps(body),
                'failed',
                'failed',
                1,
                1,
                'WORKER_EXECUTION_FAILED',
                None,
                '2026-09-19T12:00:00Z',
            ),
        )
        db.execute("INSERT INTO settings VALUES ('device','legacy-device')")
        db.execute("INSERT INTO settings VALUES ('paused','false')")
        db.commit()
    finally:
        db.close()

    store = Store(tmp_path)

    assert store.get('legacy-job')['error'] == {
        'code': 'WORKER_EXECUTION_FAILED',
        'recoverable': True,
    }
    with sqlite3.connect(database) as check:
        assert check.execute('PRAGMA user_version').fetchone()[0] == 6
        columns = {row[1] for row in check.execute('PRAGMA table_info(jobs)').fetchall()}
        event_columns = {row[1] for row in check.execute('PRAGMA table_info(events)').fetchall()}
        assert 'error_recoverable' in columns
        assert 'attempt' in event_columns
        alias = check.execute(
            'SELECT job_id,signature FROM idempotency_keys WHERE key=?',
            ('legacy-idem',),
        ).fetchone()
        assert alias == ('legacy-job', 'legacy-signature')
        receipt_table = check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='terminal_job_receipts'"
        ).fetchone()
        assert receipt_table == ('terminal_job_receipts',)


def test_polling_reads_never_open_immediate_write_transactions(tmp_path, monkeypatch):
    store = Store(tmp_path)
    job = store.submit('read-only-polling', BODY)
    claim = store.claim()
    assert claim is not None
    while store.step(*claim):
        pass

    def forbidden_tx():
        raise AssertionError('read path must not reserve a writer transaction')

    monkeypatch.setattr(store, 'tx', forbidden_tx)

    assert store.setting('paused') == 'false'
    assert store.has_running_jobs() is False
    assert store.get(job['id'])['status'] == 'succeeded'
    assert store.body(job['id'])['source_id'] == BODY['source_id']
    assert store.jobs()[0]['id'] == job['id']
    assert store.events(job['id'])
    assert store.result(job['id'])['job_id'] == job['id']


def test_read_connection_is_query_only(tmp_path):
    store = Store(tmp_path)
    store.submit('query-only', BODY)

    with store.read() as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute('DELETE FROM jobs')


def test_pause_persists_after_store_reopen(tmp_path):
    store = Store(tmp_path)
    store.submit('paused-job', BODY)
    store.pause(True)

    reopened = Store(tmp_path)

    assert reopened.setting('paused') == 'true'
    assert reopened.claim() is None

    reopened.pause(False)
    claim = reopened.claim()
    assert claim is not None


def test_non_recoverable_failure_is_exposed_and_cannot_retry(tmp_path):
    store = Store(tmp_path)
    job = store.submit('fatal-job', BODY)
    claim = store.claim()
    assert claim is not None

    store.fail(*claim, 'WORKER_RESULT_RUN_MISMATCH', recoverable=False)

    failed = store.get(job['id'])
    assert failed['error'] == {
        'code': 'WORKER_RESULT_RUN_MISMATCH',
        'recoverable': False,
    }
    with pytest.raises(Conflict, match='JOB_NOT_RETRYABLE'):
        store.action(job['id'], 'retry')


def test_stale_fail_cannot_overwrite_cancelled_job(tmp_path):
    store = Store(tmp_path)
    job = store.submit('cancel-fence', BODY)
    claim = store.claim()
    assert claim is not None

    store.action(job['id'], 'cancel')
    store.fail(*claim)

    state = store.get(job['id'])
    assert state['status'] == 'cancelled'
    assert state['error'] is None


def test_stale_fail_cannot_overwrite_new_retry_attempt(tmp_path):
    store = Store(tmp_path)
    job = store.submit('retry-fence', BODY)
    old_claim = store.claim()
    assert old_claim is not None

    store.recover()
    assert store.get(job['id'])['status'] == 'interrupted'

    store.action(job['id'], 'retry')
    new_claim = store.claim()
    assert new_claim is not None
    assert new_claim[1] == old_claim[1] + 1

    store.fail(*old_claim)

    state = store.get(job['id'])
    assert state['status'] == 'running'
    assert state['error'] is None

    while store.step(*new_claim):
        pass

    assert store.get(job['id'])['status'] == 'succeeded'


def test_worker_detail_event_is_persisted_only_for_active_attempt(tmp_path):
    store = Store(tmp_path)
    job = store.submit('worker-event', BODY)
    claim = store.claim()
    assert claim is not None

    assert store.record_worker_event(
        job['id'],
        claim[1],
        'MODEL_DOWNLOAD_PROGRESS',
        {'stage': 'model_prepare', 'downloaded_bytes': 123456},
    ) is True
    event = store.events(job['id'])[0]
    assert event['code'] == 'MODEL_DOWNLOAD_PROGRESS'
    assert event['data'] == {
        'stage': 'model_prepare',
        'downloaded_bytes': 123456,
    }

    store.action(job['id'], 'cancel')
    assert store.record_worker_event(
        job['id'],
        claim[1],
        'MODEL_DOWNLOAD_PROGRESS',
        {'downloaded_bytes': 999999},
    ) is False


def test_terminal_job_can_be_removed_with_events(tmp_path):
    store = Store(tmp_path)
    job = store.submit('delete-terminal', BODY)
    claim = store.claim()
    assert claim is not None
    store.fail(*claim, 'WORKER_EXECUTION_FAILED')
    assert store.events(job['id'])

    result = store.remove(job['id'])

    assert result == {'deleted': True, 'id': job['id']}
    assert store.jobs() == []
    with pytest.raises(KeyError):
        store.get(job['id'])
    assert store.terminal_receipt(job['id']) == {
        'job_id': job['id'],
        'attempt': claim[1],
        'status': 'failed',
        'result_available': False,
        'updated_at': store.terminal_receipt(job['id'])['updated_at'],
    }
    with sqlite3.connect(store.path) as db:
        assert db.execute(
            'SELECT job_id,signature FROM idempotency_keys WHERE key=?',
            ('delete-terminal',),
        ).fetchone() == (job['id'], sha256_json(BODY))
    with pytest.raises(Conflict, match='IDEMPOTENCY_OPERATION_REMOVED'):
        store.submit('delete-terminal', BODY)

    reopened = Store(tmp_path)
    assert reopened.terminal_receipt(job['id'])['status'] == 'failed'


def test_active_job_cannot_be_removed(tmp_path):
    store = Store(tmp_path)
    queued = store.submit('delete-queued', BODY)

    with pytest.raises(Conflict, match='JOB_ACTIVE'):
        store.remove(queued['id'])

    claim = store.claim()
    assert claim is not None
    with pytest.raises(Conflict, match='JOB_ACTIVE'):
        store.remove(queued['id'])


def test_reused_idempotency_key_remains_bound_after_original_job_finishes(tmp_path):
    store = Store(tmp_path)
    body = {
        'kind': 'transcription.craig',
        'campaign_id': 'campaign',
        'session_id': 'session',
        'source_id': 'craig-' + 'e' * 64,
        'profile_id': 'whisper-turbo',
        'glossary': '',
        'context': '',
        'cpu': False,
        'units': 1,
    }

    first = store.submit('request-a', body)
    reused = store.submit('request-b', body)
    assert reused['id'] == first['id']

    claim = store.claim()
    assert claim is not None
    store.progress(
        first['id'],
        claim[1],
        completed=1,
        total=1,
        stage='transcription',
    )
    assert store.complete(first['id'], claim[1], {'ok': True}) is True

    retried_b = store.submit('request-b', body)

    assert retried_b['id'] == first['id']
    assert retried_b['status'] == 'succeeded'
    assert len(store.jobs()) == 1


def test_identical_active_transcription_is_reused_across_different_idempotency_keys(tmp_path):
    store = Store(tmp_path)
    body = {
        'kind': 'transcription.craig',
        'campaign_id': 'desktop-local',
        'session_id': 'session-1',
        'source_id': 'craig-' + 'a' * 64,
        'profile_id': 'whisper-detailed',
        'glossary': '',
        'context': '',
        'cpu': False,
        'units': 4,
    }

    first = store.submit('desktop-first', body)
    duplicate_queued = store.submit('desktop-second', body)
    assert duplicate_queued['id'] == first['id']
    assert len(store.jobs()) == 1
    assert store.events(first['id'])[0]['code'] == 'DUPLICATE_SUBMISSION_REUSED'

    claim = store.claim()
    assert claim is not None
    duplicate_running = store.submit('web-third', body)
    assert duplicate_running['id'] == first['id']
    assert duplicate_running['status'] == 'running'
    assert len(store.jobs()) == 1


def test_same_active_asr_work_with_different_destination_is_rejected(tmp_path):
    store = Store(tmp_path)
    first_body = {
        'kind': 'transcription.craig',
        'campaign_id': 'desktop-local',
        'session_id': 'desktop-session',
        'source_id': 'craig-' + 'c' * 64,
        'profile_id': 'qwen-quality',
        'glossary': 'Yuhara',
        'context': 'mesa principal',
        'cpu': False,
        'units': 4,
    }
    web_body = {
        **first_body,
        'campaign_id': 'campaign-web',
        'session_id': 'session-web',
    }

    first = store.submit('desktop-work', first_body)
    with pytest.raises(Conflict, match='TRANSCRIPTION_WORK_ALREADY_ACTIVE'):
        store.submit('web-work', web_body)

    assert len(store.jobs()) == 1
    assert store.get(first['id'])['context']['campaign_id'] == 'desktop-local'
    assert all(
        event['code'] != 'DUPLICATE_SUBMISSION_REUSED'
        for event in store.events(first['id'])
    )


def test_retry_cannot_reactivate_work_already_owned_by_another_job(tmp_path):
    store = Store(tmp_path)
    body = {
        'kind': 'transcription.craig',
        'campaign_id': 'desktop-local',
        'session_id': 'retry-old',
        'source_id': 'craig-' + 'd' * 64,
        'profile_id': 'whisper-detailed',
        'glossary': '',
        'context': '',
        'cpu': False,
        'units': 2,
    }
    old = store.submit('old-job', body)
    old_claim = store.claim()
    assert old_claim is not None
    store.fail(*old_claim, 'WORKER_EXECUTION_FAILED')

    replacement = store.submit(
        'replacement-job',
        {**body, 'campaign_id': 'web-campaign', 'session_id': 'replacement'},
    )
    assert replacement['status'] == 'queued'

    with pytest.raises(Conflict, match='TRANSCRIPTION_WORK_ALREADY_ACTIVE'):
        store.action(old['id'], 'retry')

    assert store.get(old['id'])['status'] == 'failed'
    assert store.get(replacement['id'])['status'] == 'queued'


def test_finished_transcription_can_be_submitted_again_with_new_key(tmp_path):
    store = Store(tmp_path)
    body = {
        'kind': 'transcription.craig',
        'campaign_id': 'desktop-local',
        'session_id': 'session-2',
        'source_id': 'craig-' + 'b' * 64,
        'profile_id': 'whisper-detailed',
        'glossary': '',
        'context': '',
        'cpu': False,
        'units': 1,
    }
    first = store.submit('first-run', body)
    claim = store.claim()
    assert claim is not None
    store.progress(
        first['id'],
        claim[1],
        completed=1,
        total=1,
        stage='transcription',
    )
    assert store.complete(first['id'], claim[1], {'ok': True}) is True

    second = store.submit('second-run', body)
    assert second['id'] != first['id']
    assert len(store.jobs()) == 2
