"""Copy only the installed dependency closure needed by the portable runtime."""

from __future__ import annotations

import argparse
import json
import shutil
from importlib.metadata import Distribution, distributions
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


KNOWN_BUILD_PTH = {"distutils-precedence.pth", "_virtualenv.pth"}


def _installed_distributions(source: Path) -> dict[str, Distribution]:
    result: dict[str, Distribution] = {}
    for dist in distributions(path=[str(source)]):
        name = dist.metadata.get("Name")
        if name:
            result[canonicalize_name(name)] = dist
    return result


def dependency_closure(
    installed: dict[str, Distribution], roots: list[str]
) -> dict[str, Distribution]:
    pending = [canonicalize_name(name) for name in roots]
    selected: dict[str, Distribution] = {}
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        dist = installed.get(name)
        if dist is None:
            raise RuntimeError(f"Required runtime distribution is missing: {name}")
        selected[name] = dist
        for raw_requirement in dist.requires or ():
            requirement = Requirement(raw_requirement)
            if requirement.marker is not None and not requirement.marker.evaluate(
                {"extra": ""}
            ):
                continue
            pending.append(canonicalize_name(requirement.name))
    return selected


def validate_top_level_pth(source: Path) -> None:
    unexpected = sorted(
        path.name
        for path in source.glob("*.pth")
        if path.name not in KNOWN_BUILD_PTH
    )
    if unexpected:
        raise RuntimeError(
            "Unexpected executable .pth files in build environment: "
            + ", ".join(unexpected)
        )


def copy_distributions(
    source: Path, destination: Path, selected: dict[str, Distribution]
) -> int:
    source = source.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    copied: set[Path] = set()
    for dist in selected.values():
        if dist.files is None:
            raise RuntimeError(f"Distribution has no RECORD file list: {dist.metadata['Name']}")
        for item in dist.files:
            candidate = (source / Path(str(item))).resolve()
            try:
                relative = candidate.relative_to(source)
            except ValueError:
                # Console entry points under Scripts are not needed by the embedded runtime.
                continue
            if any(part.lower() in {"test", "tests", "__pycache__"} for part in relative.parts):
                continue
            if relative.suffix.lower() in {".pth", ".pyc", ".pyo"}:
                continue
            if candidate in copied:
                continue
            if not candidate.is_file():
                raise RuntimeError(
                    f"Recorded runtime file is missing: {dist.metadata['Name']}: {relative}"
                )
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)
            copied.add(candidate)
    return len(copied)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--roots", nargs="+", required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_dir():
        raise RuntimeError(f"site-packages directory does not exist: {source}")
    if not args.dry_run and args.destination is None:
        parser.error("--destination is required unless --dry-run is used")

    validate_top_level_pth(source)
    selected = dependency_closure(_installed_distributions(source), args.roots)
    copied = 0
    if not args.dry_run:
        copied = copy_distributions(source, args.destination, selected)
    summary = {
        "copied_files": copied,
        "distributions": {
            dist.metadata["Name"]: dist.version
            for _, dist in sorted(selected.items())
        },
    }
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
