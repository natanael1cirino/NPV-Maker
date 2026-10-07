"""Build one private Companion Expansion NPC candidate from any saved NPV project.

The config supplies a reviewed, body-compatible template and local catalogues.
Output stays in work/ for technical validation; no game install or Vortex ZIP.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from appearance_catalog import build_catalog as build_appearances, require_captured_choices
from asset_review import review as review_assets
from build_morph_meshes import build as bake_meshes
from export_project import validate_project
from extract_project_apps import extract as extract_mod_apps, archive_xl_material_sources
from eye_lashes import apply as apply_eyelashes
from finalize_npc_candidate import finalize
from link_companion_candidate import link
from npc_transform import transform


REQUIRED = ("body", "template_root", "template_app", "template_ent",
            "resource_root", "creator", "app_root", "hair_catalog",
            "asset_map", "cli", "game", "base_record")


def run(project_file: Path, config_file: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    project = json.loads(project_file.read_text(encoding="utf-8-sig"))
    validate_project(project)
    config = json.loads(config_file.read_text(encoding="utf-8-sig"))
    missing = [key for key in REQUIRED if key not in config]
    if missing:
        raise ValueError("Missing config fields: " + ", ".join(missing))
    if config["body"] != project["body"]:
        raise ValueError(f"No {project['body']} template configured")
    paths = {key: Path(config[key]) for key in REQUIRED if key not in ("body", "resource_root", "base_record")}
    if config.get("provenance"):
        paths["provenance"] = Path(config["provenance"])
    for key, path in paths.items():
        if not path.exists():
            raise ValueError(f"Configured {key} is missing: {path}")
    hair = json.loads(paths["hair_catalog"].read_text(encoding="utf-8-sig"))
    assets = json.loads(paths["asset_map"].read_text(encoding="utf-8-sig"))
    creator = json.loads(paths["creator"].read_text(encoding="utf-8-sig"))
    app = json.loads(paths["template_app"].read_text(encoding="utf-8-sig"))
    ent = json.loads(paths["template_ent"].read_text(encoding="utf-8-sig"))
    output.mkdir(parents=True)
    mod_archives = paths["game"] / "archive" / "pc" / "mod"
    support = [paths["game"] / "red4ext/plugins/ArchiveXL/Bundle"]
    mod_found = (extract_mod_apps(project, paths["cli"], mod_archives, output / "mod_apps", support)
                 if mod_archives.is_dir() else [])
    (output / "mod-app-sources.json").write_text(
        json.dumps({"captured_mod_appearance_paths": mod_found}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf8")
    appearance_catalog = build_appearances(project, creator, paths["app_root"],
                                            [output / "mod_apps"] if mod_found else [],
                                            archive_xl_material_sources(support[0]))
    require_captured_choices(project, appearance_catalog)
    files = [str(p.relative_to(paths["template_root"])) for p in
             paths["template_root"].rglob("*") if p.is_file()]
    transformed_app, transformed_ent, report = transform(
        project, hair, app, ent, config["resource_root"], files,
        appearance_catalog, assets)
    transform_dir = output / "transform"
    transform_dir.mkdir()
    report["entity_path"] = report["resource_root"] + "\\" + paths["template_ent"].name.removesuffix(".json")
    for name, value in ((report["appearance_path"].split("\\")[-1] + ".json", transformed_app),
                        (report["entity_path"].split("\\")[-1] + ".json", transformed_ent),
                        ("conversion-report.json", report)):
        (transform_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    (output / "appearance-catalog.json").write_text(
        json.dumps(appearance_catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    bake_meshes(report, paths["template_root"], paths["cli"], paths["game"], output / "morphs")
    eyelash_edit = apply_eyelashes(report, appearance_catalog, output / "morphs", paths["cli"])
    if eyelash_edit:
        if "eyelash_color" in report["catalog_pending"]:
            report["catalog_pending"].remove("eyelash_color")
        report["catalog_applied"]["eyelash_color"] = [eyelash_edit["to"]]
        (transform_dir / "conversion-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    result = finalize(transform_dir, output / "morphs", paths["template_root"],
                      assets, paths["cli"], output / "candidate")
    link(project_file, output / "candidate" / "candidate-manifest.json", paths["cli"],
         config["base_record"], output / "companion-bridge-spec.json")
    if "provenance" in paths:
        inventory = review_assets(output / "candidate", paths["template_root"], paths["provenance"])
        (output / "asset-review.json").write_text(
            json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.project, args.config, args.output_dir)
        print(result["archive"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Companion candidate failed: {exc}\n")


if __name__ == "__main__":
    main()
