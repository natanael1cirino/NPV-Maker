"""Link a private NPC candidate to a reviewable Companion Expansion spec.

The visual-match flag remains false. This never exports an installable bridge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from companion_expansion import RECORD, check_archive, prepare, project_info


def link(project_path: Path, candidate_manifest: Path, cli: Path,
         base_record: str, output: Path) -> Path:
    if output.exists():
        raise FileExistsError(output)
    if not RECORD.fullmatch(base_record):
        raise ValueError("Invalid base Character record")
    project, _ = project_info(project_path)
    candidate = json.loads(candidate_manifest.read_text(encoding="utf-8-sig"))
    if candidate.get("format") != "npv-maker-local-npc-candidate" or candidate.get("body") != project["body"]:
        raise ValueError("Candidate body/format does not match the project")
    # The conversion namespace is derived from the canonical project content.
    canonical = hashlib.sha256(json.dumps(project, sort_keys=True, ensure_ascii=False).encode("utf8")).hexdigest()
    if candidate.get("project_digest") != canonical:
        raise ValueError("Candidate belongs to another project revision")
    archive = Path(candidate["archive"])
    app = check_archive(cli, archive, candidate["entity_path"], candidate["appearance_name"])
    if app.lower() != candidate["appearance_path"].lower():
        raise ValueError("Candidate appearance resource differs from its manifest")
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    prepare(project_path, output)
    spec = json.loads(output.read_text(encoding="utf8"))
    spec.update(base_record=base_record,
                entity_path=candidate["entity_path"],
                appearance_name=candidate["appearance_name"],
                npc_archive_path=str(archive.resolve()),
                npc_archive_sha256=archive_digest,
                asset_origin="external_dependency",
                visual_match_confirmed=False,
                in_game_spawn_tested=False)
    output.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--base-record", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(link(args.project, args.candidate_manifest, args.cli, args.base_record, args.output))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Companion candidate link failed: {exc}\n")


if __name__ == "__main__":
    main()
