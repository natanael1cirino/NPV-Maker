"""Create a local-only Vortex test ZIP from a reviewed Companion preview.

This command requires an explicit asset-bundling flag. It never changes the
asset review's distribution status or claims an in-game visual/spawn test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from asset_review import sha256
from companion_expansion import NAME, RECORD, bridge_script, bridge_yaml, project_info, resource_path


def package(project_file: Path, spec_file: Path, review_file: Path,
            preview_dir: Path, destination: Path, *, include_reviewed_assets: bool) -> Path:
    if not include_reviewed_assets:
        raise ValueError("Explicit local-test asset-bundling flag is required")
    if destination.exists():
        raise FileExistsError(destination)
    project, project_hash = project_info(project_file)
    canonical = hashlib.sha256(json.dumps(project, sort_keys=True,
                                          ensure_ascii=False).encode("utf8")).hexdigest()
    spec = json.loads(spec_file.read_text(encoding="utf-8-sig"))
    review = json.loads(review_file.read_text(encoding="utf-8-sig"))
    plan = json.loads((preview_dir / "package-plan.json").read_text(encoding="utf-8-sig"))
    if (spec.get("format") != "npv-maker-companion-bridge-spec"
            or spec.get("schema_version") != 1
            or spec.get("project_sha256") != project_hash
            or spec.get("display_name") != project["name"]
            or spec.get("body") != project["body"]
            or spec.get("visual_match_confirmed") is not False
            or spec.get("in_game_spawn_tested") is not False):
        raise ValueError("Spec does not describe this untested project")
    if (review.get("format") != "npv-maker-candidate-asset-review"
            or review.get("project_digest") != canonical
            or review.get("contains_external_assets") is not True
            or review.get("approved_for_distribution") is not False
            or review.get("private_validation_only") is not True
            or not isinstance(review.get("assets"), list)
            or not review["assets"]):
        raise ValueError("Private external-asset review does not match this project")
    if (plan.get("format") != "npv-maker-private-companion-package-preview"
            or plan.get("schema_version") != 1
            or plan.get("project_name") != project["name"]
            or plan.get("project_sha256") != project_hash
            or plan.get("archive_sha256") != review.get("archive_sha256")
            or plan.get("archive_sha256") != spec.get("npc_archive_sha256")
            or plan.get("external_assets") != len(review["assets"])
            or plan.get("private_test_only") is not True
            or plan.get("zip_created") is not False
            or plan.get("asset_bundling_approved") is not False
            or plan.get("visual_match_confirmed") is not False
            or plan.get("in_game_spawn_tested") is not False):
        raise ValueError("Preview plan does not match the reviewed archive")
    archive = Path(spec["npc_archive_path"])
    if (str(archive) != plan.get("planned_archive_source")
            or not archive.is_file()
            or sha256(archive) != review["archive_sha256"]):
        raise ValueError("Reviewed NPC archive is missing or changed")
    record, base = spec["record_id"], spec["base_record"]
    entity, appearance = resource_path(spec["entity_path"], ".ent"), spec["appearance_name"]
    if (not isinstance(record, str) or not RECORD.fullmatch(record)
            or not isinstance(base, str) or not RECORD.fullmatch(base) or base == record
            or not isinstance(appearance, str) or not NAME.fullmatch(appearance)):
        raise ValueError("Invalid Companion record or appearance")
    prefix = project_hash[:16]
    archive_member = f"archive/pc/mod/NPVMaker_{prefix}.archive"
    yaml_member = f"r6/tweaks/NPVMaker/companion_{prefix}.yaml"
    script_member = f"r6/scripts/NPVMakerCompanion/bridge_{prefix}.reds"
    if (plan.get("planned_archive_in_zip") != archive_member
            or plan.get("staged_code_files") != [yaml_member, script_member]):
        raise ValueError("Preview names do not match the project")
    expected_code = {yaml_member: bridge_yaml(project, record, base, entity, appearance),
                     script_member: bridge_script(record, project_hash)}
    for member, expected in expected_code.items():
        if (preview_dir / member).read_text(encoding="utf8") != expected:
            raise ValueError(f"Preview code changed: {member}")
    manifest = {
        "format": "npv-maker-private-companion-test", "schema_version": 1,
        "project_name": project["name"], "project_sha256": project_hash,
        "record_id": record, "entity_path": entity, "appearance_name": appearance,
        "archive_member": archive_member, "archive_sha256": review["archive_sha256"],
        "external_assets": len(review["assets"]), "private_test_only": True,
        "asset_bundling_authorized_for_local_test": True,
        "approved_for_distribution": False, "visual_match_confirmed": False,
        "in_game_spawn_tested": False,
    }
    readme = ("NPV Maker + Companion Expansion: teste privado local\n\n"
              "Instale este ZIP pelo Vortex junto com o NPV Maker e o Companion Expansion.\n"
              "Requer TweakXL, RED4ext, redscript, Codeware e os mods de aparencia usados no projeto.\n"
              "Este pacote inclui um archive de NPC com assets externos derivados do jogo/template.\n"
              "A autorizacao foi apenas para teste local; NAO publique ou redistribua este ZIP.\n"
              "A aparencia e o spawn do NPC ainda nao foram confirmados dentro do jogo.\n"
              "Use um save de teste: a ponte desbloqueia o companion quando a sessao carrega.\n"
              f"Personagem: {project['name']}\nRecord: {record}\n"
              f"Archive SHA-256: {review['archive_sha256']}\n")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    try:
        with ZipFile(temporary, "x", compression=ZIP_DEFLATED) as bundle:
            for member, content in expected_code.items():
                bundle.writestr(member, content)
            bundle.write(archive, archive_member)
            bundle.writestr("NPV-Maker-Companion-private-test-manifest.json",
                            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            bundle.writestr("NPV-Maker-Companion-private-test-README.txt", readme)
        with ZipFile(temporary) as bundle:
            if bundle.testzip() is not None or set(bundle.namelist()) != {
                    *expected_code, archive_member,
                    "NPV-Maker-Companion-private-test-manifest.json",
                    "NPV-Maker-Companion-private-test-README.txt"}:
                raise ValueError("Invalid private test ZIP structure")
            with bundle.open(archive_member) as embedded:
                check = hashlib.sha256()
                for chunk in iter(lambda: embedded.read(1024 * 1024), b""):
                    check.update(chunk)
                if check.hexdigest() != review["archive_sha256"]:
                    raise ValueError("Embedded archive differs from reviewed candidate")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--asset-review", type=Path, required=True)
    parser.add_argument("--preview-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-reviewed-assets-for-private-test", action="store_true")
    args = parser.parse_args()
    try:
        print(package(args.project, args.spec, args.asset_review, args.preview_dir,
                      args.output, include_reviewed_assets=
                      args.include_reviewed_assets_for_private_test))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Private Companion test package failed: {exc}\n")


if __name__ == "__main__":
    main()
