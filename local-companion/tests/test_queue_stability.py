from __future__ import annotations

from tda_companion.store import Store


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
