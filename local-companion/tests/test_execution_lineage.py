from tda_companion.execution_lineage import capture_execution_lineage
from tda_companion.transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptWord,
    stats_for_tracks,
)


def _document(device: str = "cuda") -> TranscriptDocument:
    segment = TranscriptSegment(
        id="1-0",
        start=0.0,
        end=1.0,
        text="Teste",
        words=(TranscriptWord(text="Teste", start=0.0, end=0.4, confidence=0.9),),
    )
    track = TranscriptTrack(
        number=1,
        speaker="Alice",
        source_filename="1-Alice.flac",
        source_sha256="a" * 64,
        duration_seconds=5.0,
        segments=(segment,),
    )
    return TranscriptDocument(
        recording_id="recording",
        source_sha256="b" * 64,
        language="pt",
        engine=TranscriptEngine(
            engine="qwen3",
            model="model-for-test",
            profile="qwen-quality",
            device=device,
            compute_type="bfloat16",
            alignment="aligner",
            model_revision="revision",
        ),
        tracks=(track,),
        stats=stats_for_tracks((track,), processing_seconds=2.0),
    )


def test_execution_lineage_captures_sanitized_runtime_and_selected_gpu():
    value = capture_execution_lineage(
        _document("cuda:1"),
        snapshot={
            "host": {"os": "private-host-os", "cpu": "private-cpu"},
            "gpus": [
                {
                    "index": 0,
                    "name": "NVIDIA GPU 0",
                    "memory_total_bytes": 8 * 1024**3,
                },
                {
                    "index": 1,
                    "uuid": "GPU-11111111-1111-1111-1111-111111111111",
                    "name": "NVIDIA GPU 1",
                    "memory_total_bytes": 24 * 1024**3,
                    "compute_capability": "8.6",
                    "driver_version": "999.1",
                    "memory_used_bytes": 123,
                    "utilization_percent": 91,
                },
            ],
        },
        execution_device={"kind": "cuda", "logical_index": 1, "physical_uuid": "GPU-11111111-1111-1111-1111-111111111111", "pci_bus_id": None},
        environ={
            "TDA_ASR_RUNTIME_FAMILY": "qwen",
            "TDA_ASR_RUNTIME_VERSION": "1.0.10",
            "USERNAME": "private-user",
        },
    )

    assert value["schema_version"] == "tda_execution_lineage_v1"
    assert value["runtime_family"] == "qwen"
    assert value["runtime_version"] == "1.0.10"
    assert value["device"] == "cuda:1"
    assert value["compute_type"] == "bfloat16"
    assert value["gpu"] == {
        "vendor": "NVIDIA",
        "index": 1,
        "logical_index": 1,
        "uuid": "GPU-11111111-1111-1111-1111-111111111111",
        "pci_bus_id": None,
        "model": "NVIDIA GPU 1",
        "vram_total_bytes": 24 * 1024**3,
        "compute_capability": "8.6",
        "driver_version": "999.1",
    }
    serialized = repr(value)
    assert "private-user" not in serialized
    assert "private-host-os" not in serialized
    assert "memory_used_bytes" not in serialized
    assert "utilization_percent" not in serialized


def test_execution_lineage_keeps_cpu_runs_gpu_free():
    value = capture_execution_lineage(
        _document("cpu"),
        snapshot={
            "gpus": [
                {
                    "index": 0,
                    "name": "NVIDIA GPU",
                    "memory_total_bytes": 8 * 1024**3,
                }
            ]
        },
        environ={
            "TDA_ASR_RUNTIME_FAMILY": "whisper",
            "TDA_ASR_RUNTIME_VERSION": "1.1.5",
        },
    )

    assert value["device"] == "cpu"
    assert value["gpu"] is None
