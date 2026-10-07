"""Build a private NPC archive for technical validation, never a release ZIP.

The local candidate can contain files derived from a game/template installation.
It must not be published or copied to releases without asset-origin review and
an in-game appearance/spawn test.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from npc_transform import fnv1a64


def replace_resource_hashes(value, mapping: dict[str, str]) -> int:
    count = 0
    if isinstance(value, dict):
        if value.get("$type") == "ResourcePath":
            old = str(value.get("$value", ""))
            if old in mapping:
                value["$value"] = mapping[old]
                count += 1
        for child in value.values():
            count += replace_resource_hashes(child, mapping)
    elif isinstance(value, list):
        for child in value:
            count += replace_resource_hashes(child, mapping)
    return count


def cli_run(cli: Path, *args: str) -> str:
    result = subprocess.run([str(cli), *args], capture_output=True, text=True,
                            encoding="utf8", errors="replace", timeout=180)
    output = result.stdout + result.stderr
    if result.returncode or "[ 0: Error" in output:
        raise ValueError(f"WolvenKit CLI failed: {output[-2000:]}")
    return output


def partition_assets(report: dict, morph: dict, assets: dict) -> tuple[dict[str, str], list[str]]:
    vanilla = {key.lower(): value for key, value in assets["vanilla_references"].items()}
    morph_by_mesh = {x["mesh"].lower(): x for x in morph["meshes"]}
    fallbacks, custom = {}, []
    for relative in report["required_custom_assets"]:
        entry = morph_by_mesh.get(relative.lower())
        if (entry and not entry["applied_shapes"] and not entry.get("material_edits")
                and relative.lower() in vanilla):
            old = report["resource_root"] + "\\" + relative
            fallbacks[fnv1a64(old)] = fnv1a64(vanilla[relative.lower()])
            # Overlay components are added after the original relocation pass
            # and use literal paths rather than hashed ResourcePaths.
            fallbacks[old] = vanilla[relative.lower()]
        else:
            custom.append(relative)
    return fallbacks, custom


def finalize(candidate: Path, morph_root: Path, template_root: Path, assets: dict,
             cli: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError(destination)
    report = json.loads((candidate / "conversion-report.json").read_text(encoding="utf8"))
    morph = json.loads((morph_root / "morph-bake-report.json").read_text(encoding="utf8"))
    if report["digest"] != morph["project_digest"] or assets["body"] != report["body"]:
        raise ValueError("Candidate inputs belong to different projects")
    if report.get("status") != "candidate_metadata_only":
        raise ValueError("Not a candidate transform")
    app_path = report["appearance_path"]
    entity_path = report["entity_path"]
    app = json.loads((candidate / (app_path.split("\\")[-1] + ".json")).read_text(encoding="utf8"))
    ent = json.loads((candidate / (entity_path.split("\\")[-1] + ".json")).read_text(encoding="utf8"))
    appearance_name = ent["Data"]["RootChunk"]["appearances"][0]["appearanceName"]["$value"]
    morph_by_mesh = {x["mesh"].lower(): x for x in morph["meshes"]}
    fallbacks, custom = partition_assets(report, morph, assets)
    replacements = replace_resource_hashes(app, fallbacks)
    destination.mkdir(parents=True)
    source = destination / "archive_source"
    source.mkdir()
    temp_binary = destination / "binary"
    temp_binary.mkdir()
    for resource_path, data in ((app_path, app), (entity_path, ent)):
        name = resource_path.split("\\")[-1]
        json_file = destination / (name + ".json")
        json_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        cli_run(cli, "convert", "deserialize", str(json_file), "--outpath", str(temp_binary))
        binary = temp_binary / name
        if not binary.is_file():
            raise ValueError(f"WolvenKit did not produce {name}")
        target = source.joinpath(*resource_path.split("\\"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, target)
    for relative in custom:
        entry = morph_by_mesh.get(relative.lower())
        original = (Path(entry["output_mesh"]) if entry and (entry["applied_shapes"] or entry.get("material_edits"))
                    else template_root.joinpath(*relative.split("\\")))
        if not original.is_file():
            raise ValueError(f"Missing custom candidate asset: {relative}")
        target = source.joinpath(*report["resource_root"].split("\\"), *relative.split("\\"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    packed = destination / "packed"
    packed.mkdir()
    cli_run(cli, "pack", str(source), "--outpath", str(packed))
    archives = list(packed.glob("*.archive"))
    if len(archives) != 1:
        raise ValueError("Expected exactly one local candidate archive")
    result = {"format": "npv-maker-local-npc-candidate", "schema_version": 1,
              "project_digest": report["digest"], "body": report["body"],
              "entity_path": entity_path, "appearance_path": app_path,
              "appearance_name": appearance_name, "archive": str(archives[0]),
              "custom_assets": custom, "vanilla_fallback_references": replacements,
              "unresolved_appearance_options": report.get("catalog_pending", []),
              "unsupported_switchers": report.get("unsupported_switchers", []),
              "template_defaults_disabled": report.get("template_defaults_disabled", []),
              "private_validation_only": True, "visual_match_confirmed": False,
              "in_game_spawn_tested": False}
    (destination / "candidate-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--morph-root", type=Path, required=True)
    parser.add_argument("--template-root", type=Path, required=True)
    parser.add_argument("--asset-map", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        assets = json.loads(args.asset_map.read_text(encoding="utf8"))
        result = finalize(args.candidate, args.morph_root, args.template_root,
                          assets, args.cli, args.output_dir)
        print(result["archive"])
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Local candidate build failed: {exc}\n")


if __name__ == "__main__":
    main()
