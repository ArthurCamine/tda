from __future__ import annotations

from typing import Any

LABELS = {
    "core": "Núcleo local",
    "network": "Rede e canal online",
    "maintenance": "Atualização e manutenção",
    "whisper": "Transcrição Whisper",
    "qwen": "Transcrição Qwen",
}

CHECK_LABELS = {
    "agent": "Agent local",
    "state": "pasta State",
    "data": "pasta Data",
    "sqlite": "banco SQLite local",
    "disk": "espaço em disco",
    "network_dns": "DNS local",
    "network_https": "HTTPS do TDA",
    "network_manifest": "manifest stable",
    "network_asset": "asset stable",
    "maintenance_metadata": "metadados MSI",
    "maintenance_helper": "helper de manutenção",
    "maintenance_update_channel": "canal stable de update",
    "whisper_runtime": "runtime/CUDA Whisper",
    "whisper_model_turbo": "modelo Whisper Turbo",
    "whisper_model_detailed": "modelo Whisper Detalhado",
    "qwen_runtime": "runtime/CUDA Qwen",
    "qwen_aligner": "alinhador Qwen",
    "qwen_model_fast": "modelo Qwen Rápido",
    "qwen_gate_fast": "gate físico Qwen Rápido",
    "qwen_model_quality": "modelo Qwen Qualidade",
    "qwen_gate_quality": "gate físico Qwen Qualidade",
}


def _status(checks: dict[str, dict[str, Any]], code: str) -> str:
    value = checks.get(code)
    return str(value.get("status") or "unavailable") if value else "unavailable"


def _not_pass(checks: dict[str, dict[str, Any]], codes: tuple[str, ...]) -> list[str]:
    return [code for code in codes if _status(checks, code) != "pass"]


def _human_codes(codes: list[str]) -> str:
    return ", ".join(CHECK_LABELS.get(code, code) for code in codes[:4])


def _summary(
    capability_id: str,
    blockers: list[str],
    degraded: list[str] | None = None,
) -> dict[str, Any]:
    blockers = list(dict.fromkeys(blockers))
    degraded = [
        code for code in dict.fromkeys(degraded or []) if code not in blockers
    ]
    if blockers:
        status = "blocked"
        severity = "blocker"
        message = "Bloqueado: " + _human_codes(blockers)
    elif degraded:
        status = "degraded"
        severity = "degraded"
        message = "Disponível com limitação: " + _human_codes(degraded)
    else:
        status = "ready"
        severity = "info"
        message = "Pronto para uso"
    return {
        "id": capability_id,
        "label": LABELS[capability_id],
        "status": status,
        "severity": severity,
        "message": message,
        "blockers": blockers,
        "degraded": degraded,
    }


def build_capabilities(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = {
        str(check.get("code")): check
        for check in checks
        if isinstance(check, dict) and isinstance(check.get("code"), str)
    }

    core_blockers = _not_pass(values, ("agent", "state", "data"))
    if _status(values, "sqlite") == "fail":
        core_blockers.append("sqlite")
    core_degraded = ["disk"] if _status(values, "disk") == "warning" else []
    core = _summary("core", core_blockers, core_degraded)

    network_blockers = _not_pass(
        values,
        ("network_https", "network_manifest", "network_asset"),
    )
    network_degraded = []
    if not network_blockers and _status(values, "network_dns") != "pass":
        network_degraded.append("network_dns")
    network = _summary("network", network_blockers, network_degraded)

    maintenance_codes = (
        "maintenance_metadata",
        "maintenance_helper",
        "maintenance_update_channel",
    )
    maintenance = _summary("maintenance", _not_pass(values, maintenance_codes))

    whisper_models = ("whisper_model_turbo", "whisper_model_detailed")
    whisper_blockers: list[str] = []
    if _status(values, "whisper_runtime") != "pass":
        whisper_blockers.append("whisper_runtime")
    ready_whisper = [code for code in whisper_models if _status(values, code) == "pass"]
    whisper_degraded: list[str] = []
    if not ready_whisper:
        whisper_blockers.extend(_not_pass(values, whisper_models))
    elif len(ready_whisper) < len(whisper_models):
        whisper_degraded.extend(_not_pass(values, whisper_models))
    whisper = _summary("whisper", whisper_blockers, whisper_degraded)

    qwen_blockers: list[str] = []
    if _status(values, "qwen_runtime") != "pass":
        qwen_blockers.append("qwen_runtime")
    if _status(values, "qwen_aligner") != "pass":
        qwen_blockers.append("qwen_aligner")
    qwen_profiles = (
        ("qwen_model_fast", "qwen_gate_fast"),
        ("qwen_model_quality", "qwen_gate_quality"),
    )
    ready_qwen = [
        pair
        for pair in qwen_profiles
        if all(_status(values, code) == "pass" for code in pair)
    ]
    qwen_degraded: list[str] = []
    if not ready_qwen:
        for pair in qwen_profiles:
            qwen_blockers.extend(_not_pass(values, pair))
    elif len(ready_qwen) < len(qwen_profiles):
        for pair in qwen_profiles:
            if pair not in ready_qwen:
                qwen_degraded.extend(_not_pass(values, pair))
    qwen = _summary("qwen", qwen_blockers, qwen_degraded)

    return [core, network, maintenance, whisper, qwen]


def overall_status(capabilities: list[dict[str, Any]]) -> str:
    values = {
        str(capability.get("id")): str(capability.get("status"))
        for capability in capabilities
    }
    if values.get("core") == "blocked":
        return "fail"
    if values.get("whisper") == "blocked" and values.get("qwen") == "blocked":
        return "fail"
    if any(status != "ready" for status in values.values()):
        return "warning"
    return "pass"


def capability_rows(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_map = {"ready": "pass", "degraded": "warning", "blocked": "fail"}
    rows: list[dict[str, Any]] = []
    for capability in capabilities:
        capability_id = str(capability.get("id") or "unknown")
        status = str(capability.get("status") or "blocked")
        label = str(capability.get("label") or LABELS.get(capability_id) or "Capability")
        rows.append(
            {
                "code": label,
                "capability_id": capability_id,
                "status": status_map.get(status, "fail"),
                "message": str(capability.get("message") or "Estado indisponível"),
                "detail": f"capability.{capability_id} · {status}",
            }
        )
    return rows
