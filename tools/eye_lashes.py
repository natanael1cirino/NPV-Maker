"""Apply a captured eyelash material to the NPC eye mesh for one appearance.

The character creator selects eyelash colour separately from eye colour. NPCs
store the eyelash material in the first chunk of the selected eye mesh
appearance. The resulting mesh remains a private validation asset.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from build_morph_meshes import cli_run


EYE_MESH = r"head\he_000_pwa_c__basehead.mesh"


def change_material(mesh: dict, eye_appearance: str, material: str) -> str:
    root = mesh["Data"]["RootChunk"]
    available = {item.get("name", {}).get("$value") for item in root["materialEntries"]}
    if material not in available:
        raise ValueError(f"Eyelash material {material!r} is absent from eye mesh")
    matches = [item["Data"] for item in root["appearances"]
               if item["Data"]["name"]["$value"] == eye_appearance]
    if len(matches) != 1:
        raise ValueError(f"Eye mesh needs exactly one {eye_appearance!r} appearance")
    chunks = matches[0]["chunkMaterials"]
    # MEDIDO EM 02/10/2026 (AFT, V masculino): he_000_pwa_c gives every eye
    # appearance an eyelash material in chunk 0; he_000_pma_c gives eye
    # appearances "eyeMat3" there and keeps the lashes in eyelashes__*
    # appearances, also in chunk 0. Either shape proves chunk 0 is the lashes.
    lash_slot = any(item["Data"]["chunkMaterials"]
                    and item["Data"]["chunkMaterials"][0]["$value"] == material
                    for item in root["appearances"])
    if not chunks or not (chunks[0]["$value"].startswith("eyelashes") or lash_slot):
        raise ValueError("Selected eye appearance lacks an eyelash material chunk")
    previous = chunks[0]["$value"]
    chunks[0]["$value"] = material
    return previous


def apply(report: dict, catalog: dict, morph_root: Path, cli: Path) -> dict | None:
    choice = catalog.get("choices", {}).get("eyelash_color")
    if choice is None:
        return None
    components = choice["components"]
    materials = [part.get("mesh_appearance") for part in components]
    if len(materials) != 1 or not materials[0]:
        raise ValueError("Eyelash choice does not have one material")
    material = materials[0]
    eyes = report["mapped_appearances"]["eyes"]
    morph_file = morph_root / "morph-bake-report.json"
    morph = json.loads(morph_file.read_text(encoding="utf8"))
    if morph["project_digest"] != report["digest"]:
        raise ValueError("Eye mesh belongs to another project")
    entries = [entry for entry in morph["meshes"] if entry["mesh"].lower() == EYE_MESH.lower()]
    if len(entries) != 1:
        raise ValueError("Candidate needs exactly one eye mesh for eyelash colour")
    entry = entries[0]
    source = Path(entry["output_mesh"])
    if not source.is_file():
        raise ValueError(f"Missing eye mesh: {source}")
    cli_run(cli, "convert", "serialize", str(source))
    serial = Path(str(source) + ".json")
    mesh = json.loads(serial.read_text(encoding="utf8"))
    previous = change_material(mesh, eyes, material)
    serial.write_text(json.dumps(mesh, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    rebuilt = source.parent / "eyelash_material"
    rebuilt.mkdir()
    cli_run(cli, "convert", "deserialize", str(serial), "--outpath", str(rebuilt))
    finished = rebuilt / source.name
    if not finished.is_file():
        raise ValueError("WolvenKit did not rebuild the eye mesh")
    shutil.copy2(finished, source)
    edit = {"option": "eyelash_color", "mesh": EYE_MESH,
            "eye_appearance": eyes, "from": previous, "to": material}
    entry.setdefault("material_edits", []).append(edit)
    morph_file.write_text(json.dumps(morph, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return edit
