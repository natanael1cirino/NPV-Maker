"""Local NPV Maker job launched from CET. Never installs anything into the game.

Build creates a project-specific NPC candidate and review. Packaging is a
separate, explicit in-game action for a private Vortex test ZIP with assets.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

from build_companion_candidate import run as build_candidate
from companion_expansion import project_info
from package_private_companion_test import package
from preview_companion_test import preview

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "work/templates/female/build-config.json"
PROJECT_ID = re.compile(r"npv-\d{8}T\d{6}Z-\d{4}\Z")


def paths(project_id: str, config_file: Path | None = None,
          root: Path | None = None) -> dict[str, Path]:
    config_file = config_file or CONFIG
    root = root or ROOT
    if not PROJECT_ID.fullmatch(project_id):
        raise ValueError("Invalid generated project ID")
    config = json.loads(config_file.read_text(encoding="utf-8-sig"))
    game = Path(config["game"])
    mod = game / "bin/x64/plugins/cyber_engine_tweaks/mods/NPVMaker"
    project = mod / "projects" / f"{project_id}.npv.json"
    if not project.is_file():
        raise FileNotFoundError(f"Saved project missing: {project}")
    data, digest = project_info(project)
    if data["body"] != config["body"]:
        raise ValueError(f"No {data['body']} conversion template configured")
    # The raw project digest identifies the immutable save revision and record.
    candidate = root / "work/candidates" / f"{project_id}-{digest[:16]}"
    return {"mod": mod, "project": project, "candidate": candidate,
            "status": mod / "projects/exports" / f"{project_id}.json",
            "zip": root / "releases" / f"NPV-Maker-Companion-{digest[:16]}-private-test.zip"}


# MEDIDO EM 29/09/2026 (item 35): the CET panel reads these files with io.open, which on
# Windows opens them without FILE_SHARE_DELETE; os.replace during that read fails with
# PermissionError WinError 5 ("Acesso negado"). On 28/09 (0.4.17) it escaped an import and
# killed the converter. The panel holds the file only while it reads, so a short retry gets
# through; if it still fails, the file is left as it was: it is panel telemetry and never
# stops the work it describes. The temporary file is never read by the panel.
REPLACE_ATTEMPTS = 20
REPLACE_DELAY = 0.025
status_failure_hook = None
# Called with the path after a successful write: the game (no CET) reads a mirror in its storage
# (storage_bridge.install_hook), and a long conversion never reaches the converter loop to mirror it.
panel_written_hook = None


def write_panel_file(path: Path, text: str) -> bool:
    """Replace a file the panel reads; False (reported to status_failure_hook), never an exception."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(text, encoding="utf8")
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                if panel_written_hook is not None:
                    try:
                        panel_written_hook(path)
                    except Exception:
                        pass
                return True
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_DELAY)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        if status_failure_hook is not None:
            try:
                status_failure_hook(path, error)
            except Exception:
                pass
    return False


# Activity log the panel shows under the message, like a terminal (author request 05/10/2026): the last steps of
# the current task, each with its time. A task that starts after a finished one starts a new log.
LOG_LINES = 12
LOG_FINISHED = {"installed", "error", "exported", "packaged", "removed", "requirements_ready", "saved"}


def status_log(path: Path, stage: str, message: str) -> list[dict]:
    try:
        previous = json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError):
        previous = {}
    log = previous.get("log") if isinstance(previous, dict) and isinstance(previous.get("log"), list) else []
    if previous.get("stage") in LOG_FINISHED and stage not in LOG_FINISHED:
        log = []
    log = [entry for entry in log if isinstance(entry, dict) and isinstance(entry.get("text"), str)]
    if message and (not log or log[-1]["text"] != message):
        log.append({"time": time.strftime("%H:%M:%S"), "text": message})
    return log[-LOG_LINES:]


def status_write(path: Path, *, stage: str, message: str, detail: str | None = None, **extra: object) -> bool:
    """`detail`: a step inside the current message (which file, which choice); it goes to the log only."""
    payload = {"format": "npv-maker-companion-job", "stage": stage,
               "message": message, "log": status_log(path, stage, detail or message), **extra}
    return write_panel_file(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def run(action: str, project_id: str, *, config_file: Path | None = None,
        root: Path | None = None) -> Path:
    config_file = config_file or CONFIG
    p = paths(project_id, config_file, root)
    status = p["status"]
    project, digest = project_info(p["project"])
    candidate = p["candidate"]
    spec = candidate / "companion-bridge-spec.json"
    review = candidate / "asset-review.json"
    staged = candidate / "package-preview"
    if action == "build":
        if candidate.exists():
            raise FileExistsError(f"Candidate already exists: {candidate}")
        status_write(status, stage="building", message=f"Convertendo {project['name']} para NPC...")
        build_candidate(p["project"], config_file, candidate)
        if not review.is_file():
            raise ValueError("Asset provenance unavailable; candidate cannot be packaged")
        preview(p["project"], spec, review, staged)
        inventory = json.loads(review.read_text(encoding="utf8"))
        status_write(status, stage="ready", message=(
            f"Candidato pronto: {project['name']}. "
            f"{len(inventory['assets'])} assets externos; clique em ZIP PRIVADO para inclui-los."),
            project_sha256=digest, candidate_dir=str(candidate),
            external_assets=len(inventory["assets"]))
        return candidate
    if action == "package":
        if not staged.is_dir() or not review.is_file() or not spec.is_file():
            raise ValueError("Build this saved project before requesting a private ZIP")
        if p["zip"].exists():
            raise FileExistsError(f"Private ZIP already exists: {p['zip']}")
        status_write(status, stage="packaging", message="Criando ZIP privado com assets revisados...")
        result = package(p["project"], spec, review, staged, p["zip"],
                         include_reviewed_assets=True)
        status_write(status, stage="packaged",
                     message=f"ZIP privado pronto: {result.name}",
                     project_sha256=digest, zip=str(result))
        return result
    raise ValueError("Unsupported action")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "package"))
    parser.add_argument("project_id")
    args = parser.parse_args()
    try:
        result = run(args.action, args.project_id)
        print(result)
    except Exception as exc:
        # The GUI needs a persistent error even if the external CLI crashes.
        try:
            status = paths(args.project_id)["status"]
            status_write(status, stage="error", message=str(exc)[:400])
            status.with_suffix(".log").write_text(traceback.format_exc(), encoding="utf8")
        except Exception:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
