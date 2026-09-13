from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, ContextManager, Protocol
from urllib.parse import urlsplit

from .network import NetworkError

_COPY_CHUNK = 1024 * 1024
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SAFE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")


class _ReadableResponse(Protocol):
    def read(self, size: int = -1) -> bytes: ...


FallbackOpen = Callable[[], ContextManager[_ReadableResponse]]


class LargeDownloadError(NetworkError):
    def __init__(self, code: str):
        super().__init__(code)


def github_release_asset_url(tag: str, asset_name: str) -> str:
    if not _SAFE_TAG.fullmatch(tag) or ".." in tag:
        raise ValueError("INVALID_RELEASE_TAG")
    if not _SAFE_ASSET.fullmatch(asset_name) or ".." in asset_name:
        raise ValueError("INVALID_RELEASE_ASSET")
    return f"https://github.com/Faysk/tda/releases/download/{tag}/{asset_name}"


def validate_github_release_asset_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("INVALID_RELEASE_ASSET_URL")
    parts = parsed.path.split("/")
    if len(parts) != 7 or parts[:5] != ["", "Faysk", "tda", "releases", "download"]:
        raise ValueError("INVALID_RELEASE_ASSET_URL")
    tag, asset_name = parts[5], parts[6]
    expected = github_release_asset_url(tag, asset_name)
    if expected != url:
        raise ValueError("INVALID_RELEASE_ASSET_URL")
    return url


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_file(path: Path, *, expected_size: int, expected_sha256: str) -> bool:
    try:
        return (
            path.is_file()
            and path.stat().st_size == expected_size
            and _sha256_file(path) == expected_sha256
        )
    except OSError:
        return False


def _powershell_executable() -> Path | None:
    if os.name != "nt":
        return None
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not system_root:
        return None
    executable = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    return executable if executable.is_file() else None


def _bits_display_name(source_url: str, destination: Path) -> str:
    material = f"{source_url}\n{destination.resolve()}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()[:24]
    return f"TDA Companion {digest}"


_BITS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
function Emit([string]$Status, [string]$Code) {
  [ordered]@{ status = $Status; code = $Code } | ConvertTo-Json -Compress
  exit 0
}
function RemoveInvalidJobs($Jobs) {
  foreach ($candidate in @($Jobs)) {
    try { Remove-BitsTransfer -BitsJob $candidate -Confirm:$false -ErrorAction SilentlyContinue } catch {}
  }
}
try {
  Import-Module BitsTransfer -ErrorAction Stop
} catch {
  Emit 'unavailable' 'BITS_UNAVAILABLE'
}
$source = [Environment]::GetEnvironmentVariable('TDA_BITS_SOURCE', 'Process')
$destination = [Environment]::GetEnvironmentVariable('TDA_BITS_DESTINATION', 'Process')
$displayName = [Environment]::GetEnvironmentVariable('TDA_BITS_DISPLAY_NAME', 'Process')
$windowRaw = [Environment]::GetEnvironmentVariable('TDA_BITS_WINDOW_SECONDS', 'Process')
$windowSeconds = 60
if (-not [int]::TryParse($windowRaw, [ref]$windowSeconds)) { $windowSeconds = 60 }
$windowSeconds = [Math]::Max(1, [Math]::Min($windowSeconds, 3600))
try {
  $jobs = @(Get-BitsTransfer -Name $displayName -ErrorAction SilentlyContinue)
} catch {
  Emit 'unavailable' 'BITS_UNAVAILABLE'
}
if ($jobs.Count -gt 1) {
  RemoveInvalidJobs $jobs
  Emit 'error' 'BITS_JOB_AMBIGUOUS'
}
$job = $null
if ($jobs.Count -eq 1) {
  $job = $jobs[0]
  $files = @($job.FileList)
  if ($files.Count -ne 1) {
    RemoveInvalidJobs @($job)
    Emit 'error' 'BITS_JOB_MISMATCH'
  }
  $remote = [string]$files[0].RemoteName
  $local = [IO.Path]::GetFullPath([string]$files[0].LocalName)
  $expectedLocal = [IO.Path]::GetFullPath($destination)
  if ($remote -ne $source -or $local -ne $expectedLocal) {
    RemoveInvalidJobs @($job)
    Emit 'error' 'BITS_JOB_MISMATCH'
  }
} else {
  try {
    if (Test-Path -LiteralPath $destination) {
      Remove-Item -LiteralPath $destination -Force -ErrorAction Stop
    }
    $job = Start-BitsTransfer `
      -Source $source `
      -Destination $destination `
      -DisplayName $displayName `
      -Description 'TDA verified public release asset' `
      -Priority High `
      -Asynchronous `
      -ErrorAction Stop
  } catch {
    Emit 'unavailable' 'BITS_UNAVAILABLE'
  }
}
$deadline = (Get-Date).AddSeconds($windowSeconds)
while ((Get-Date) -lt $deadline) {
  try {
    $job = Get-BitsTransfer -JobId $job.JobId -ErrorAction Stop
  } catch {
    if (Test-Path -LiteralPath $destination) { Emit 'complete' 'BITS_COMPLETE' }
    Emit 'error' 'BITS_JOB_LOST'
  }
  $state = [string]$job.JobState
  switch ($state) {
    'Transferred' {
      try {
        Complete-BitsTransfer -BitsJob $job -ErrorAction Stop
      } catch {
        RemoveInvalidJobs @($job)
        Emit 'error' 'BITS_COMPLETE_FAILED'
      }
      Emit 'complete' 'BITS_COMPLETE'
    }
    'Suspended' {
      try {
        Resume-BitsTransfer -BitsJob $job -Asynchronous -ErrorAction Stop
      } catch {
        RemoveInvalidJobs @($job)
        Emit 'error' 'BITS_RESUME_FAILED'
      }
    }
    'Error' {
      RemoveInvalidJobs @($job)
      Emit 'error' 'BITS_TRANSFER_FAILED'
    }
    'Cancelled' {
      RemoveInvalidJobs @($job)
      Emit 'error' 'BITS_TRANSFER_CANCELLED'
    }
    'Acknowledged' {
      if (Test-Path -LiteralPath $destination) { Emit 'complete' 'BITS_COMPLETE' }
      Emit 'error' 'BITS_JOB_LOST'
    }
    default { }
  }
  Start-Sleep -Milliseconds 500
}
Emit 'pending' 'DOWNLOAD_CONTINUES_IN_BACKGROUND'
"""


def _run_bits_transfer(
    source_url: str,
    destination: Path,
    *,
    timeout: float,
) -> str:
    executable = _powershell_executable()
    if executable is None:
        return "unavailable"
    window_seconds = max(1, min(int(timeout), 3600))
    encoded = base64.b64encode(_BITS_SCRIPT.encode("utf-16le")).decode("ascii")
    environment = os.environ.copy()
    environment.update(
        {
            "TDA_BITS_SOURCE": source_url,
            "TDA_BITS_DESTINATION": str(destination.resolve()),
            "TDA_BITS_DISPLAY_NAME": _bits_display_name(source_url, destination),
            "TDA_BITS_WINDOW_SECONDS": str(window_seconds),
        }
    )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.run(
            [
                str(executable),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=max(float(window_seconds) + 15.0, 20.0),
            check=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        # BITS owns the transfer, so killing this observation process must not
        # cancel the job. A later call reconnects by deterministic display name.
        return "pending"
    except OSError:
        return "unavailable"
    if len(process.stdout.encode("utf-8", errors="replace")) > 64 * 1024:
        raise LargeDownloadError("BITS_RESPONSE_INVALID")
    lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    if not lines:
        return "unavailable" if process.returncode != 0 else "error"
    try:
        value = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise LargeDownloadError("BITS_RESPONSE_INVALID") from exc
    if not isinstance(value, dict):
        raise LargeDownloadError("BITS_RESPONSE_INVALID")
    status = value.get("status")
    code = value.get("code")
    if status == "complete" and code == "BITS_COMPLETE":
        return "complete"
    if status == "pending" and code == "DOWNLOAD_CONTINUES_IN_BACKGROUND":
        return "pending"
    if status == "unavailable" and code == "BITS_UNAVAILABLE":
        return "unavailable"
    if status == "error" and isinstance(code, str) and code.startswith("BITS_"):
        raise LargeDownloadError(code)
    raise LargeDownloadError("BITS_RESPONSE_INVALID")


def _stream_fallback(
    temporary: Path,
    *,
    expected_size: int,
    fallback_open: FallbackOpen,
    size_exceeded_code: str,
) -> None:
    total = 0
    temporary.unlink(missing_ok=True)
    try:
        with fallback_open() as response:
            with temporary.open("xb") as handle:
                while True:
                    chunk = response.read(_COPY_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > expected_size:
                        raise LargeDownloadError(size_exceeded_code)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
    except BaseException:
        # The synchronous fallback never owns resumable state. Any interrupted,
        # rejected or oversized stream must leave no materialized partial bytes.
        temporary.unlink(missing_ok=True)
        raise


def download_verified_release_asset(
    *,
    target: Path,
    github_url: str,
    expected_size: int,
    expected_sha256: str,
    timeout: float,
    fallback_open: FallbackOpen,
    prefer_bits: bool,
    size_exceeded_code: str,
    size_mismatch_code: str,
) -> Path:
    validate_github_release_asset_url(github_url)
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size <= 0
        or not _SHA256.fullmatch(expected_sha256)
    ):
        raise ValueError("INVALID_RELEASE_ASSET_INTEGRITY")

    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")

    if _valid_file(target, expected_size=expected_size, expected_sha256=expected_sha256):
        return target
    if target.exists():
        target.unlink(missing_ok=True)
    if _valid_file(temporary, expected_size=expected_size, expected_sha256=expected_sha256):
        if not (prefer_bits and os.name == "nt"):
            os.replace(temporary, target)
            return target
        # A complete-looking BITS destination may still belong to a Transferred
        # job waiting for Complete-BitsTransfer. Reconnect before promoting it.

    used_bits = False
    if prefer_bits and os.name == "nt":
        try:
            status = _run_bits_transfer(github_url, temporary, timeout=timeout)
        except BaseException:
            # Every non-pending BITS failure represents terminal state. The
            # PowerShell side removes the corresponding job before surfacing it.
            temporary.unlink(missing_ok=True)
            raise
        if status == "complete":
            used_bits = True
        elif status == "pending":
            # Deliberately preserve the BITS-owned destination. The next call
            # reconnects to the same job using the deterministic display name.
            raise NetworkError("DOWNLOAD_CONTINUES_IN_BACKGROUND")
        elif status == "unavailable":
            temporary.unlink(missing_ok=True)
        else:
            temporary.unlink(missing_ok=True)
            raise LargeDownloadError("BITS_RESPONSE_INVALID")

    if not used_bits:
        _stream_fallback(
            temporary,
            expected_size=expected_size,
            fallback_open=fallback_open,
            size_exceeded_code=size_exceeded_code,
        )

    try:
        actual_size = temporary.stat().st_size
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise LargeDownloadError("DOWNLOAD_OUTPUT_MISSING") from exc
    if actual_size != expected_size:
        temporary.unlink(missing_ok=True)
        raise LargeDownloadError(size_mismatch_code)
    if _sha256_file(temporary) != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise NetworkError("HASH_MISMATCH")
    os.replace(temporary, target)
    return target
