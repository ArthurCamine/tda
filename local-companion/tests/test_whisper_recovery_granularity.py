"""Track is the supported durable unit; partial segment replay is not resume."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tda_companion.asr_whisper import WhisperRuntimeError, transcribe_craig_package
from tda_companion.craig import CraigPackage, CraigTrack
from test_asr_whisper import _install_whisper_fixture


@pytest.mark.parametrize("interruption", ["cancel", "crash"])
def test_partial_track_recomputes_but_completed_track_skips_engine(tmp_path, interruption):
    models = tmp_path / "Models"
    _install_whisper_fixture(models)
    root = tmp_path / "source"
    (root / "tracks").mkdir(parents=True)
    tracks = []
    for number in (1, 2):
        payload = f"synthetic track {number}".encode()
        name = f"{number}-speaker.flac"
        (root / "tracks" / name).write_bytes(payload)
        tracks.append(CraigTrack(number=number, speaker=f"Speaker {number}", filename=name,
                                 path=f"tracks/{name}", size_bytes=len(payload),
                                 sha256=hashlib.sha256(payload).hexdigest(), identity=None))
    package = CraigPackage(schema_version="tda_craig_package_v1", source_zip="fixture.zip",
                           source_sha256="a" * 64, recording_id="fixture", guild=None, channel=None,
                           requester=None, start_time=None, tracks=tuple(tracks), info_present=False, raw_dat_present=False)
    attempt = 1
    cancelled = False
    engine_work = []
    class Model:
        def transcribe(self, path, **options):
            number = int(Path(path).name[0])
            assert options["vad_filter"] is True
            assert "clip_timestamps" not in options
            def segments():
                for index in range(3):
                    if attempt == 1 and number == 2 and index == 1 and interruption == "crash":
                        raise RuntimeError("SIMULATED_ENGINE_CRASH")
                    engine_work.append((attempt, number, index))
                    start = index * 10 + 0.1
                    yield SimpleNamespace(id=index, start=start, end=start + 1, text=f"synthetic {number} {index}", words=[])
            return segments(), SimpleNamespace(duration=30.0)
    def report(event):
        nonlocal cancelled
        if attempt == 1 and event.get("code") == "WHISPER_SEGMENT_TRANSCRIBED" and event.get("track") == 2:
            cancelled = interruption == "cancel"
    common = dict(profile_id="whisper-turbo", model_loader=lambda _, plan: (Model(), plan.compute_type, False),
                  cuda_status={"available": True, "supported_compute_types": ["float16"]}, report=report,
                  is_cancelled=lambda: cancelled)
    with pytest.raises((WhisperRuntimeError, RuntimeError), match="ASR_CANCELLED|SIMULATED_ENGINE_CRASH"):
        transcribe_craig_package(package, root, models, **common)
    assert not list(root.rglob("run.json"))
    attempt = 2
    cancelled = False
    result = transcribe_craig_package(package, root, models, **common)
    assert [entry for entry in engine_work if entry[0] == 2] == [(2, 2, 0), (2, 2, 1), (2, 2, 2)]
    assert (1, 2, 0) in engine_work  # Prefix work was repeated, never claimed reused.
    assert [len(track.segments) for track in result.tracks] == [3, 3]
    assert [segment.start for segment in result.tracks[1].segments] == [0.1, 10.1, 20.1]
    prior_work = list(engine_work)
    transcribe_craig_package(package, root, models, **common)
    assert engine_work == prior_work  # All-complete fast path avoids engine work.
