"""Stage a reviewable Vortex test-package layout without bundling any NPC asset."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from asset_review import sha256
from companion_expansion import NAME, RECORD, bridge_script, bridge_yaml, project_info, resource_path


def preview(project_file: Path, spec_file: Path, review_file: Path, output: Path) -> Path:
    if output.exists():
        raise FileExistsError(output)
    project, digest = project_info(project_file)
    canonical = hashlib.sha256(json.dumps(project, sort_keys=True, ensure_ascii=False).encode("utf8")).hexdigest()
    spec = json.loads(spec_file.read_text(encoding="utf8"))
    review = json.loads(review_file.read_text(encoding="utf8"))
    if (spec.get("project_sha256") != digest or spec.get("display_name") != project["name"]
            or spec.get("body") != project["body"]):
        raise ValueError("Bridge specification belongs to another project")
    if spec.get("visual_match_confirmed") is not False or spec.get("in_game_spawn_tested") is not False:
        raise ValueError("This preview is only for an untested local candidate")
    if review.get("format") != "npv-maker-candidate-asset-review" or not review.get("contains_external_assets"):
        raise ValueError("External asset inventory is required")
    if review.get("approved_for_distribution") is not False:
        raise ValueError("Asset inventory is no longer an unapproved test input")
    if review.get("archive_sha256") != spec.get("npc_archive_sha256"):
        raise ValueError("Asset inventory and Companion archive differ")
    if review.get("project_digest") != canonical:
        raise ValueError("Asset inventory belongs to another project")
    record, base = spec["record_id"], spec["base_record"]
    if not RECORD.fullmatch(record) or not RECORD.fullmatch(base):
        raise ValueError("Invalid Character record")
    entity = resource_path(spec["entity_path"], ".ent")
    appearance = spec["appearance_name"]
    if not isinstance(appearance, str) or not NAME.fullmatch(appearance):
        raise ValueError("Invalid appearance name")
    archive = Path(spec["npc_archive_path"])
    if not archive.is_file() or sha256(archive) != review["archive_sha256"]:
        raise ValueError("Candidate archive is missing or changed")
    output.mkdir(parents=True)
    prefix = digest[:16]
    yaml_name = f"r6/tweaks/NPVMaker/companion_{prefix}.yaml"
    script_name = f"r6/scripts/NPVMakerCompanion/bridge_{prefix}.reds"
    yaml = output / yaml_name
    script = output / script_name
    yaml.parent.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    yaml.write_text(bridge_yaml(project, record, base, entity, appearance), encoding="utf8")
    script.write_text(bridge_script(record, digest), encoding="utf8")
    plan = {"format": "npv-maker-private-companion-package-preview", "schema_version": 1,
            "project_name": project["name"], "project_sha256": digest,
            "archive_sha256": review["archive_sha256"],
            "planned_archive_source": str(archive),
            "planned_archive_in_zip": f"archive/pc/mod/NPVMaker_{prefix}.archive",
            "staged_code_files": [yaml_name, script_name],
            "external_assets": len(review["assets"]),
            "asset_review": str(review_file),
            "asset_bundling_approved": False,
            "visual_match_confirmed": False, "in_game_spawn_tested": False,
            "zip_created": False, "private_test_only": True}
    (output / "package-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--asset-review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(preview(args.project, args.spec, args.asset_review, args.output_dir))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Companion package preview failed: {exc}\n")


if __name__ == "__main__":
    main()
