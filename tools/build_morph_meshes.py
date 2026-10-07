"""Bake selected editor morphs into local candidate NPC meshes.

This builds only in a private work directory. It does not package or install
game/third-party files. Each mesh is processed independently with WolvenKit.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from bake_morph_glb import bake, unpack_glb


MESH_NAME = re.compile(r"^(h0|he|heb|ht|hx|i1)_000_pwa_c__basehead(?:_(.+))?\.mesh$", re.I)


def morph_source(mesh_name: str) -> str:
    match = MESH_NAME.fullmatch(mesh_name)
    if not match:
        raise ValueError(f"No morph target naming rule for {mesh_name}")
    return match.group(1) + "_000_pwa__morphs" + ("_" + match.group(2) if match.group(2) else "") + ".morphtarget"


def cli_run(cli: Path, *args: str) -> str:
    result = subprocess.run([str(cli), *args], capture_output=True, text=True,
                            encoding="utf8", errors="replace", timeout=180)
    output = result.stdout + result.stderr
    if result.returncode or "[ 0: Error" in output:
        raise ValueError(f"WolvenKit CLI failed: {output[-2000:]}")
    return output


def build(report: dict, template_root: Path, cli: Path, game: Path, output: Path) -> dict:
    if report.get("status") != "candidate_metadata_only":
        raise ValueError("Expected an NPC candidate conversion report")
    if output.exists():
        raise FileExistsError(output)
    if not cli.is_file():
        raise ValueError("WolvenKit CLI is missing")
    wanted = [m["shape_key"] for m in report["morphs"]]
    entries = []
    output.mkdir(parents=True)
    for relative in report["required_custom_assets"]:
        if not relative.lower().startswith("head\\") or not relative.lower().endswith(".mesh"):
            continue
        mesh_file = template_root.joinpath(*relative.split("\\"))
        target_file = template_root / "head" / "morphtargets" / morph_source(mesh_file.name)
        if not mesh_file.is_file() or not target_file.is_file():
            raise ValueError(f"Missing local mesh or morph target for {relative}")
        folder = output / mesh_file.stem
        folder.mkdir()
        source_copy = folder / mesh_file.name
        shutil.copy2(mesh_file, source_copy)
        cli_run(cli, "export", str(target_file), "--outpath", str(folder), "--gamepath", str(game))
        glbs = list(folder.glob("*.morphtarget.glb"))
        if len(glbs) != 1:
            raise ValueError(f"Expected one exported GLB for {target_file}")
        doc, _ = unpack_glb(glbs[0].read_bytes())
        available = {name for mesh in doc.get("meshes", [])
                     for name in mesh.get("extras", {}).get("targetNames", [])}
        matched = [shape for shape in wanted if shape in available]
        if matched:
            baked = folder / (mesh_file.stem + ".glb")
            baked.write_bytes(bake(glbs[0].read_bytes(), matched))
            cli_run(cli, "import", str(baked), "--outpath", str(folder), "--keep")
        entries.append({"mesh": relative, "morph_target": str(target_file.relative_to(template_root)),
                        "applied_shapes": matched, "missing_shapes": sorted(set(wanted) - set(matched)),
                        "output_mesh": str(source_copy)})
    result = {"format": "npv-maker-morph-bake", "schema_version": 1,
              "project_digest": report["digest"], "meshes": entries,
              "in_game_visual_tested": False}
    (output / "morph-bake-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--template-root", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8-sig"))
        result = build(report, args.template_root, args.cli, args.game, args.output_dir)
        print(f"{args.output_dir} ({len(result['meshes'])} head meshes)")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Morph mesh build failed: {exc}\n")


if __name__ == "__main__":
    main()
