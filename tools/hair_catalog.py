"""Index installed hairstyle .app metadata for project-to-NPC conversion.

The catalog contains resource paths and appearance names, not game or mod assets.
Pass extracted, WolvenKit-serialized hairstyle .app.json files as input. Additional
modded hairstyle apps can be added to the same input tree after provenance review.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


HAIR_APP = re.compile(r"hh_(\d{3})_p([wm])a__hairs_\d{3}\.app\.json$", re.I)


def read_component(component: dict) -> tuple[str, str, str]:
    data = component.get("Data", component)
    name = data.get("name", {}).get("$value", "")
    mesh = data.get("mesh", {}).get("DepotPath", {}).get("$value", "")
    appearance = data.get("meshAppearance", {}).get("$value", "")
    return name, mesh, appearance


def entry_from_app(path: Path) -> dict:
    match = HAIR_APP.fullmatch(path.name)
    if not match:
        raise ValueError(f"Not a supported hairstyle app: {path.name}")
    body = "female" if match.group(2).lower() == "w" else "male"
    slot = int(match.group(1))
    resource = str(path).replace("/", "\\")
    marker = "base\\characters\\head\\player_base_heads\\appearances\\hairs\\"
    offset = resource.lower().rfind(marker)
    if offset < 0:
        raise ValueError(f"Cannot determine resource path for {path}")
    resource = resource[offset:].removesuffix(".json")
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    variants = {}
    for item in doc["Data"]["RootChunk"]["appearances"]:
        definition = item["Data"]
        color = definition["name"]["$value"]
        meshes = [read_component(comp) for comp in definition["components"]]
        hair = [value for value in meshes if value[1].lower().endswith(".mesh")
                and "\\common\\hair\\" in value[1].lower()
                and "\\shadow_meshes\\" not in value[1].lower()]
        shadow = [value for value in meshes if "\\shadow_meshes\\" in value[1].lower()]
        if not hair:
            raise ValueError(f"Unexpected hair components: {path}, {color}")
        if color in variants:
            raise ValueError(f"Duplicate color {color}: {path}")
        variants[color] = {
            "hair_components": [dict(name=n, mesh=m, mesh_appearance=a) for n, m, a in hair],
            "shadow_components": [dict(name=n, mesh=m, mesh_appearance=a) for n, m, a in shadow],
        }
    if not variants:
        raise ValueError(f"No hairstyle appearances: {path}")
    return {"body": body, "slot_index": slot, "app_path": resource,
            "colors": variants}


def build_catalog(paths: list[Path]) -> dict:
    entries = {}
    for path in sorted(paths):
        entry = entry_from_app(path)
        key = f"{entry['body']}:{entry['slot_index']}"
        if key in entries:
            raise ValueError(f"More than one hairstyle app uses {key}")
        entries[key] = entry
    return {"format": "npv-maker-hair-catalog", "schema_version": 1,
            "entries": entries}


def resolve_hair(project: dict, catalog: dict) -> dict:
    if catalog.get("format") != "npv-maker-hair-catalog" or catalog.get("schema_version") != 1:
        raise ValueError("Unsupported hair catalog")
    selected = [o for o in project["options"] if o["active"] and o["editable"]]
    styles = [o for o in selected if o["name"] in ("hairstyle", "hairstyle_cyberware")]
    colors = [o for o in selected if re.fullmatch(r"hair_color(?:\d+|_cyberware_\d+)", o["name"])]
    if len(styles) != 1 or len(colors) != 1:
        raise ValueError("Expected exactly one active hairstyle and one hair color")
    style, color = styles[0], colors[0]
    key = f"{project['body']}:{style['selected_index']}"
    entry = catalog["entries"].get(key)
    if entry is None:
        raise ValueError(f"Hairstyle {key} is missing from the catalog")
    variant = entry["colors"].get(color["selected_name"])
    if variant is None:
        raise ValueError(f"Hair color {color['selected_name']!r} is absent from {entry['app_path']}")
    return {"slot_index": style["selected_index"], "color_name": color["selected_name"],
            "source_app": entry["app_path"], **variant}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Directory containing serialized hair .app.json files")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError(args.output)
        paths = list(args.source.rglob("hh_*_p*a__hairs_*.app.json"))
        if not paths:
            raise ValueError("No serialized hairstyle apps found")
        catalog = build_catalog(paths)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        print(f"{args.output} ({len(catalog['entries'])} hairstyles)")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Hair catalog failed: {exc}\n")


if __name__ == "__main__":
    main()
