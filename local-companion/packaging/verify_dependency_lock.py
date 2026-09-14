from __future__ import annotations

import argparse
import importlib.metadata
import re
from pathlib import Path

_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)$")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def load_lock(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.fullmatch(line)
        if not match:
            raise SystemExit(f"LOCK_ENTRY_INVALID:{line}")
        key = canonical(match.group(1))
        if key in result:
            raise SystemExit(f"LOCK_DUPLICATE:{key}")
        result[key] = match.group(2)
    if not result:
        raise SystemExit("LOCK_EMPTY")
    return result


def installed() -> dict[str, str]:
    result: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if not name:
            continue
        key = canonical(name)
        if key == "tda-companion":
            continue
        result[key] = dist.version
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    expected = load_lock(args.lock)
    actual = installed()
    unexpected = sorted(set(actual) - set(expected))
    mismatched = sorted(
        name for name in set(actual) & set(expected) if actual[name] != expected[name]
    )
    missing = sorted(set(expected) - set(actual)) if args.require_all else []
    if unexpected or mismatched or missing:
        for name in unexpected:
            print(f"UNLOCKED_INSTALLED:{name}=={actual[name]}")
        for name in mismatched:
            print(f"LOCK_VERSION_MISMATCH:{name}:{actual[name]}!={expected[name]}")
        for name in missing:
            print(f"LOCK_REQUIRED_MISSING:{name}=={expected[name]}")
        raise SystemExit(1)
    print(f"DEPENDENCY_LOCK_OK installed={len(actual)} locked={len(expected)} require_all={args.require_all}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
