import ctypes
import uuid

import pytest

from tda_companion.execution_device import resolve_execution_device, matching_gpu, pci_bus_id
from tda_companion.execution_lineage import capture_execution_lineage
from tda_companion.store import Store
from test_execution_lineage import _document

UUIDS = ['GPU-11111111-1111-1111-1111-111111111111', 'GPU-22222222-2222-2222-2222-222222222222']
ROWS = [{'index':0,'uuid':UUIDS[0],'pci_bus_id':'00000000:01:00.0','name':'RTX 4070'}, {'index':1,'uuid':UUIDS[1],'pci_bus_id':'00000000:02:00.0','name':'RTX 3090'}]
class Driver:
    def __init__(self, visible): self.visible = visible
    def cuInit(self, flags): return 0
    def cuDeviceGet(self, output, ordinal):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_int))[0] = self.visible[ordinal]
        return 0
    def cuDeviceGetUuid_v2(self, output, selected):
        data = uuid.UUID(UUIDS[selected.value][4:]).bytes
        ctypes.memmove(output, data, 16)
        return 0
    def cuDeviceGetPCIBusId(self, output, length, selected):
        output.value = ROWS[selected.value]['pci_bus_id'].encode('ascii')
        return 0

@pytest.mark.parametrize('visibility,logical,expected', [('1',0,1),('1,0',1,0),('0,1',0,0)])
def test_driver_namespace_is_joined_by_uuid_not_nvml_ordinal(monkeypatch, visibility, logical, expected):
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES',visibility)
    identity = resolve_execution_device(f'cuda:{logical}', driver=Driver([int(i) for i in visibility.split(',')]))
    assert identity['logical_index'] == logical
    assert identity['physical_uuid'] == UUIDS[expected]
    for rows in (ROWS, list(reversed(ROWS))):
        value = capture_execution_lineage(_document(f'cuda:{logical}'), snapshot={'gpus':rows}, environ={}, execution_device=identity)
        assert value['gpu']['model'] == ROWS[expected]['name']
        assert value['gpu']['index'] == expected
        assert value['gpu']['logical_index'] == logical


def test_unknown_driver_identity_never_falls_back_to_nvml_index():
    identity = resolve_execution_device('cuda:0',driver=object())
    assert identity['physical_uuid'] is None
    assert matching_gpu(ROWS,identity) is None
    assert capture_execution_lineage(_document('cuda:0'),snapshot={'gpus':ROWS},execution_device=identity,environ={})['gpu'] is None
    assert resolve_execution_device('cpu',driver=object())['kind'] == 'cpu'


def test_pci_fallback_is_canonical_and_ambiguous_or_mig_mismatch_stays_unknown():
    assert pci_bus_id('0000:01:00.0') == '00000000:01:00.0'
    pci = {'kind':'cuda','logical_index':0,'physical_uuid':None,'pci_bus_id':'00000000:02:00.0'}
    assert matching_gpu(ROWS,pci)['name'] == 'RTX 3090'
    assert matching_gpu([ROWS[1],ROWS[1]],pci) is None
    assert matching_gpu(ROWS,{**pci,'physical_uuid':'MIG-33333333-3333-3333-3333-333333333333'}) is None


def test_attempt_device_survives_reopen_but_never_leaks_across_retry(tmp_path):
    store = Store(tmp_path)
    body = {'kind':'synthetic.fixture','campaign_id':'campaign','session_id':'session','source_id':'source','units':1}
    job = store.submit('key',body); job_id, attempt = store.claim()
    identity = {'kind':'cuda','logical_index':0,'physical_uuid':UUIDS[1],'pci_bus_id':'00000000:02:00.0'}
    assert store.record_worker_event(job_id,attempt,'ASR_EXECUTION_DEVICE',identity)
    assert Store(tmp_path).get(job_id)['execution_device'] == identity
    store.fail(job_id,attempt,'TEST'); store.action(job_id,'retry'); assert store.claim() == (job_id,2)
    assert store.get(job_id)['execution_device'] is None
    assert not store.record_worker_event(job_id,attempt,'ASR_EXECUTION_DEVICE',identity)
    assert store.get(job_id)['execution_device'] is None


def test_checkpoint_only_commit_does_not_invent_gpu_use(monkeypatch):
    import tda_companion.execution_device as module
    monkeypatch.setattr(module, 'resolve_execution_device', lambda _: {'kind':'cuda','logical_index':0,'physical_uuid':UUIDS[1],'pci_bus_id':None})
    module.reset_execution_device()
    assert module.committed_execution_device('cuda:0')['physical_uuid'] is None
    module.device_event('cuda:0')
    assert module.committed_execution_device('cuda:0')['physical_uuid'] == UUIDS[1]
    module.reset_execution_device()
    assert module.committed_execution_device('cuda:0')['physical_uuid'] is None
