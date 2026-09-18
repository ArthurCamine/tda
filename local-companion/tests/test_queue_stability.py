from __future__ import annotations

import pytest

from tda_companion.store import Conflict, Store


BODY = dict(
    kind='synthetic.fixture',
    campaign_id='synthetic-campaign',
    session_id='synthetic-session',
    source_id='synthetic-source',
    units=3,
)


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
    event = store.events(first['id'])[0]
    assert event['code'] == 'DUPLICATE_WORK_REJECTED'


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
