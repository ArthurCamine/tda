from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from pathlib import Path

import tda_companion.asr_worker as worker
from tda_companion.craig import ingest_craig_zip
from tda_companion.transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptWord,
    stats_for_tracks,
)
from tda_companion.transcription_runs import list_runs
from tda_companion.worker_protocol import WorkerRunCommand


def _document(source_sha: str, text: str) -> TranscriptDocument:
    segment = TranscriptSegment(
        id="1-0",
        start=0.0,
        end=1.0,
        text=text,
        words=(TranscriptWord(text=text, start=0.0, end=1.0, confidence=0.9),),
    )
    track = TranscriptTrack(
        number=1,
        speaker="Alice",
        source_filename="1-Alice.flac",
        source_sha256="a" * 64,
        duration_seconds=30.0,
        segments=(segment,),
    )
    return TranscriptDocument(
        recording_id=None,
        source_sha256=source_sha,
        language="pt",
        engine=TranscriptEngine(
            engine="faster-whisper",
            model="large-v3-turbo",
            profile="whisper-turbo",
            device="cuda",
            compute_type="float16",
            alignment="native",
            model_revision="test-revision",
        ),
        tracks=(track,),
        stats=stats_for_tracks((track,), processing_seconds=2.0),
    )


def _stage(data_root: Path) -> tuple[str, str, Path]:
    source = data_root.parent / "session.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-worker-run")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    source_id = f"craig-{source_sha}"
    package_root = data_root / "staging" / source_id
    ingest_craig_zip(source, package_root)
    return source_id, source_sha, package_root


def _command(job_id: str, source_id: str) -> WorkerRunCommand:
    return WorkerRunCommand(
        job_id=job_id,
        attempt=1,
        kind="transcription.craig",
        payload={
            "source_id": source_id,
            "profile_id": "whisper-turbo",
            "glossary": "Valyndra",
            "context": "Neverwinter",
            "cpu": False,
        },
    )


def _run(command: WorkerRunCommand) -> tuple[int, list[dict]]:
    stream = io.StringIO()
    emitter = worker._Emitter(stream, command)
    code = worker._run_craig(command, emitter, threading.Event())
    messages = [json.loads(line) for line in stream.getvalue().splitlines() if line]
    return code, messages


def test_worker_keeps_previous_run_and_uses_root_only_as_latest_compatibility_mirror(
    tmp_path: Path,
    monkeypatch,
):
    data_root = tmp_path / "Data"
    models_root = tmp_path / "Models"
    data_root.mkdir()
    models_root.mkdir()
    source_id, source_sha, package_root = _stage(data_root)
    monkeypatch.setenv("TDA_WORKER_DATA_ROOT", str(data_root))
    monkeypatch.setenv("TDA_WORKER_MODELS_ROOT", str(models_root))

    current = {"text": "primeira versao"}

    def transcribe(*_args, **_kwargs):
        return _document(source_sha, current["text"])

    monkeypatch.setattr(worker, "transcribe_craig_package", transcribe)

    first_code, first_messages = _run(_command("job-one", source_id))
    assert first_code == 0
    first_result = next(message for message in first_messages if message["type"] == "result")
    first_run_id = first_result["payload"]["run_id"]
    first_path = package_root / "runs" / first_run_id / "transcript.json"
    first_bytes = first_path.read_bytes()
    assert (package_root / "transcript.json").read_bytes() == first_bytes

    current["text"] = "segunda versao"
    second_code, second_messages = _run(_command("job-two", source_id))
    assert second_code == 0
    second_result = next(message for message in second_messages if message["type"] == "result")
    second_run_id = second_result["payload"]["run_id"]

    assert second_run_id != first_run_id
    assert first_path.read_bytes() == first_bytes
    assert (package_root / "transcript.json").read_bytes() != first_bytes
    runs = list_runs(package_root, verify_content=True)
    assert {value["run_id"] for value in runs} == {first_run_id, second_run_id}
    # The root compatibility mirror of run 1 must not be duplicated as a fake legacy run.
    assert all(value["origin"] == "asr" for value in runs)
