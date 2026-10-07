"""Transform any saved NPV project into candidate NPC appearance metadata.

This is an offline development step. It writes JSON for WolvenKit conversion and
a resource relocation map, but never packages or redistributes source assets.
The generated NPC still needs morph baking, option coverage and an in-game test.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from export_project import validate_project
from hair_catalog import resolve_hair


def fnv1a64(path: str) -> str:
    value = 14695981039346656037
    for byte in path.lower().encode("utf8"):
        value = ((value ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return str(value)


def active_option(project: dict, name: str) -> dict | None:
    matching = [x for x in project["options"] if x["name"] == name and x["active"] and x["editable"]]
    if len(matching) > 1:
        raise ValueError(f"Duplicate active option: {name}")
    return matching[0] if matching else None


def component_sets(definition: dict) -> list[list[dict]]:
    data = definition["Data"]
    sets = [data["components"]]
    compiled = data.get("compiledData", {}).get("Data", {}).get("Chunks")
    if compiled is not None:
        sets.append(compiled)
    return sets


def set_component(definition: dict, name: str, *, mesh: str | None = None,
                  appearance: str | None = None) -> int:
    hits = 0
    for group in component_sets(definition):
        for component in group:
            data = component.get("Data", component)
            if data.get("name", {}).get("$value") != name:
                continue
            if mesh is not None:
                data["mesh"]["DepotPath"] = {"$type": "ResourcePath", "$storage": "string", "$value": mesh}
            if appearance is not None:
                data["meshAppearance"]["$value"] = appearance
            hits += 1
    return hits


def set_overlay_component(definition: dict, template_name: str, name: str,
                          mesh: str, appearance: str, chunk_mask: str,
                          namespace: str) -> None:
    """Reuse an NPC skinned component for one baked, selected player part."""
    for group in component_sets(definition):
        originals = [part for part in group
                     if part.get("Data", part).get("name", {}).get("$value") == template_name]
        if len(originals) != 1:
            raise ValueError(f"Template needs one {template_name} component")
        item = originals[0] if name == template_name else copy.deepcopy(originals[0])
        data = item.get("Data", item)
        data["name"]["$value"] = name
        data["mesh"]["DepotPath"] = {"$type": "ResourcePath", "$storage": "string", "$value": mesh}
        data["meshAppearance"]["$value"] = appearance
        data["chunkMask"] = chunk_mask
        data["isEnabled"] = 1
        if name != template_name:
            data["id"] = fnv1a64(namespace + "\\" + name)
            group.append(item)


def set_component_enabled(definition: dict, name: str, enabled: bool) -> int:
    hits = 0
    for group in component_sets(definition):
        for item in group:
            data = item.get("Data", item)
            if data.get("name", {}).get("$value") == name:
                data["isEnabled"] = 1 if enabled else 0
                hits += 1
    return hits


def selected_overlay_assets(choices: dict, source_files: list[str],
                            prefix: str, morph_prefix: str, mesh_prefix: str) -> list[dict]:
    selected = [(name, choice) for name, choice in choices.items() if name.startswith(prefix)]
    if len(selected) > 1:
        raise ValueError(f"Multiple active {prefix} choices")
    if not selected:
        return []
    option_name, choice = selected[0]
    available = {name.replace("/", "\\").lower() for name in source_files}
    parts = []
    for component in choice["components"]:
        morph = component.get("morph_resource") or ""
        marker = ("base\\characters\\head\\player_base_heads\\player_female_average\\"
                  + morph_prefix)
        if not morph.lower().startswith(marker.lower()) or not morph.lower().endswith(".morphtarget"):
            return []
        suffix = morph[len(marker):-len(".morphtarget")]
        if not re.fullmatch(r"\d{2}", suffix):
            return []
        relative = "head\\" + mesh_prefix + suffix + ".mesh"
        if relative.lower() not in available:
            return []
        material = component.get("mesh_appearance")
        mask = component.get("chunk_mask")
        if not isinstance(material, str) or not material or not isinstance(mask, str):
            return []
        parts.append({"mesh": relative, "material": material, "chunk_mask": mask})
    return parts


def relocate_resources(doc: dict, source_root: str, target_root: str,
                       source_files: list[str], overrides: dict[str, str] | None = None) -> dict[str, str]:
    source_root = source_root.rstrip("\\/").replace("/", "\\")
    target_root = target_root.rstrip("\\/").replace("/", "\\")
    replacement = {}
    overrides = {key.replace("/", "\\").lower(): value for key, value in (overrides or {}).items()}
    for relative in source_files:
        relative = relative.replace("/", "\\")
        if relative.startswith("\\") or ".." in relative.split("\\"):
            raise ValueError(f"Unsafe source asset path: {relative}")
        old = source_root + "\\" + relative
        new = overrides.get(relative.lower(), target_root + "\\" + relative)
        replacement[old.lower()] = new
        replacement[fnv1a64(old)] = fnv1a64(new)
    rewritten = {}

    def walk(value):
        if isinstance(value, dict):
            if value.get("$type") == "ResourcePath":
                old = str(value.get("$value", ""))
                new = replacement.get(old.lower()) or replacement.get(old)
                if new is not None:
                    value["$value"] = new
                    rewritten[old] = new
                elif old.lower().startswith(source_root.lower() + "\\"):
                    raise ValueError(f"Missing source asset for {old}")
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(doc)
    return rewritten


def hair_from_choices(project: dict, appearances: dict | None) -> dict | None:
    if not appearances:
        return None
    selected = [x for x in project["options"] if x["active"] and x["editable"]
                and x["kind"] == "appearance" and "hair" in x["name"].lower()
                and x["name"] in appearances.get("choices", {})]
    if len(selected) > 1:
        raise ValueError("Multiple captured hair appearances are active")
    if not selected:
        return None
    color = selected[0]
    choice = appearances.get("choices", {}).get(color["name"])
    if not choice:
        return None
    hair, shadow = [], []
    for component in choice["components"]:
        mesh = component.get("mesh")
        name = component.get("name") or ""
        if not isinstance(mesh, str) or not mesh.lower().endswith(".mesh"):
            continue
        item = {"name": name, "mesh": mesh,
                "mesh_appearance": component.get("mesh_appearance") or "default",
                "chunk_mask": component.get("chunk_mask") or "9223372036854775807"}
        if "shadow" in name.lower() or "shadow" in mesh.lower():
            shadow.append(item)
        else:
            hair.append(item)
    if not hair:
        raise ValueError(f"Captured hair appearance {color['name']} has no mesh")
    styles = [x for x in project["options"] if x["active"] and x["editable"]
              and x["name"] in ("hairstyle", "hairstyle_cyberware")]
    return {"slot_index": styles[0]["selected_index"] if len(styles) == 1 else None,
            "color_name": color["selected_name"], "source_app": choice["source_app"],
            "hair_components": hair, "shadow_components": shadow}


def plan(project: dict, catalog: dict, appearances: dict | None = None) -> dict:
    validate_project(project)
    digest = hashlib.sha256(json.dumps(project, sort_keys=True, ensure_ascii=False).encode("utf8")).hexdigest()
    hair = hair_from_choices(project, appearances) or resolve_hair(project, catalog)
    morphs = [dict(option=x["name"], selected_name=x["selected_name"],
                   shape_key=f"{x['selected_name']}_{x['name']}") for x in project["options"]
              if x["active"] and x["editable"] and x["kind"] == "morph"
              and x["selected_name"] not in ("", "None")]
    if len({x["shape_key"] for x in morphs}) != len(morphs):
        raise ValueError("Duplicate selected morph name")
    return {"name": project["name"], "body": project["body"], "digest": digest,
            "resource_root": "npvmaker\\npv\\" + digest[:16],
            "hair": hair, "morphs": morphs}


def transform(project: dict, catalog: dict, app: dict, ent: dict,
              source_root: str, source_files: list[str],
              appearances: dict | None = None,
              assets: dict | None = None) -> tuple[dict, dict, dict]:
    task = plan(project, catalog, appearances)
    if not 1 <= len(task["hair"]["hair_components"]) <= 8:
        raise ValueError("This hairstyle needs 1-8 hair mesh components")
    if len(task["hair"]["shadow_components"]) > 1:
        raise ValueError("This hairstyle has multiple shadow meshes; candidate conversion needs a compatible template")
    app, ent = copy.deepcopy(app), copy.deepcopy(ent)
    if assets is not None and (assets.get("format") != "npv-maker-template-asset-map"
                               or assets.get("schema_version") != 1
                               or assets.get("body") != project["body"]):
        raise ValueError("Template asset map does not match this NPC")
    vanilla = dict(assets.get("vanilla_references", {})) if assets else {}
    if task["morphs"]:
        vanilla = {key: value for key, value in vanilla.items()
                   if not key.lower().startswith("head\\") or not key.lower().endswith(".mesh")}
    if appearances and "eyelash_color" in appearances.get("choices", {}):
        vanilla = {key: value for key, value in vanilla.items()
                   if key.lower() != r"head\he_000_pwa_c__basehead.mesh"}
    old_app = ent["Data"]["RootChunk"]["appearances"][0]["appearanceResource"]["DepotPath"]["$value"]
    if not old_app.lower().startswith(source_root.lower().rstrip("\\") + "\\"):
        raise ValueError("Template entity references another appearance root")
    old_references = set()
    def collect(value):
        if isinstance(value, dict):
            if value.get("$type") == "ResourcePath":
                old_references.add(str(value.get("$value", "")))
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(app)
    collect(ent)
    app_changes = relocate_resources(app, source_root, task["resource_root"], source_files, vanilla)
    ent_changes = relocate_resources(ent, source_root, task["resource_root"], source_files, vanilla)
    if not app_changes or not ent_changes:
        raise ValueError("Template resources were not relocated")

    skin = active_option(project, "skin_color")
    eyes = active_option(project, "eyes_color")
    eyebrow_style = active_option(project, "eyebrows")
    eyebrow_color = [x for x in project["options"] if x["active"] and x["editable"]
                     and re.fullmatch(r"eyebrows_color\d+", x["name"])]
    if not skin or not eyes or not eyebrow_style or len(eyebrow_color) != 1:
        raise ValueError("Template conversion needs skin, eyes and eyebrows choices")
    skin_name = skin["selected_name"].split("__")[-1]
    eye_name = re.sub(r"^\d+_", "", eyes["selected_name"].split("__")[-1])
    brow_color = re.sub(r"^\d+_", "", eyebrow_color[0]["selected_name"].split("__")[-1])
    brow_name = f"{brow_color}__{eyebrow_style['selected_index'] + 1:02d}"
    if not all((skin_name, eye_name, brow_color)):
        raise ValueError("An appearance value is empty")
    if appearances is not None and (appearances.get("format") != "npv-maker-appearance-catalog"
                                    or appearances.get("schema_version") != 1):
        raise ValueError("Unsupported appearance catalog")
    choices = appearances.get("choices", {}) if appearances else {}
    pimples = selected_overlay_assets(
        choices, source_files, "makeupPimples_", "hx_000_pwa__morphs_pimples_",
        "hx_000_pwa_c__basehead_pimples_")
    piercings = selected_overlay_assets(
        choices, source_files, "piercings_", "i1_000_pwa__morphs_earring_",
        "i1_000_pwa_c__basehead_earring_")
    def material(option: str, fallback: str) -> str:
        components = choices.get(option, {}).get("components", [])
        materials = [x["mesh_appearance"] for x in components if x.get("mesh_appearance")]
        return materials[0] if len(materials) == 1 else fallback
    eye_name = material("eyes_color", eye_name)
    brow_name = material(eyebrow_color[0]["name"], brow_name)
    hair_mesh = task["hair"]["hair_components"][0]
    shadows = task["hair"]["shadow_components"]
    definitions = app["Data"]["RootChunk"]["appearances"]
    if not definitions:
        raise ValueError("Template has no appearances")
    applied_catalog = {}
    cyberware = active_option(project, "cyberware")
    for definition in definitions:
        for name in ("h0_head", "t0_body", "an0__arm_right", "an0__arm_left",
                     "s0_flat_feet", "s0_heeled_feet", "h0_tattoo"):
            set_component(definition, name, appearance=skin_name)
        required = [
            set_component(definition, "he_eyes", appearance=eye_name),
            set_component(definition, "heb_eyebrows", appearance=brow_name),
            set_component(definition, "hh_hair", mesh=hair_mesh["mesh"], appearance=hair_mesh["mesh_appearance"]),
        ]
        if not all(required):
            raise ValueError("Template is missing essential appearance components")
        for index, part in enumerate(task["hair"]["hair_components"][1:], 2):
            set_overlay_component(definition, "hh_hair", f"hh_hair_extra_{index:02d}",
                                  part["mesh"], part["mesh_appearance"],
                                  part["chunk_mask"], task["resource_root"])
        if shadows:
            shadow = shadows[0]
            if not set_component(definition, "hh_hair_shadow", mesh=shadow["mesh"],
                                 appearance=shadow["mesh_appearance"]):
                raise ValueError("Template is missing a hair shadow component")
            set_component_enabled(definition, "hh_hair_shadow", True)
        elif not set_component_enabled(definition, "hh_hair_shadow", False):
            raise ValueError("Template is missing a hair shadow component")
        mapped = {
            "teeth": ["ht_teeth"],
            "nails_color_tpp": ["an0_nails_left", "an0_nails_right"],
        }
        for option_name in choices:
            if option_name.startswith("makeupCheeks_"):
                mapped[option_name] = ["hx_makeup_freckles"]
        for option_name, component_names in mapped.items():
            entry = choices.get(option_name)
            if not entry or not entry["components"]:
                continue
            materials = [x["mesh_appearance"] for x in entry["components"]]
            if len(materials) == 1 and len(component_names) > 1:
                materials *= len(component_names)
            if len(materials) != len(component_names):
                continue
            if all(set_component(definition, name, appearance=value)
                   for name, value in zip(component_names, materials)):
                applied_catalog[option_name] = materials
        for index, part in enumerate(pimples, 1):
            set_overlay_component(
                definition, "hx_makeup_freckles", f"hx_makeup_pimples_{index:02d}",
                task["resource_root"] + "\\" + part["mesh"], part["material"],
                part["chunk_mask"], task["resource_root"])
        if pimples:
            name = next(name for name in choices if name.startswith("makeupPimples_"))
            applied_catalog[name] = [part["material"] for part in pimples]
        if piercings:
            for index, part in enumerate(piercings, 1):
                name = "i1_earring" if index == 1 else f"i1_earring_{index:02d}"
                set_overlay_component(
                    definition, "i1_earring", name,
                    task["resource_root"] + "\\" + part["mesh"], part["material"],
                    part["chunk_mask"], task["resource_root"])
            name = next(name for name in choices if name.startswith("piercings_"))
            applied_catalog[name] = [part["material"] for part in piercings]
        else:
            set_component_enabled(definition, "i1_earring", False)
        # The tutorial template contains visible makeup and a face tattoo.
        # Do not let these defaults appear on characters who did not select them.
        if not any(name.startswith("makeupCheeks_") for name in applied_catalog):
            set_component_enabled(definition, "hx_makeup_freckles", False)
        for name in ("hx_makeup_eyes", "hx_makeup_lips_01", "h0_tattoo"):
            set_component_enabled(definition, name, False)
        if not cyberware or cyberware["selected_index"] != 1:
            set_component_enabled(definition, "h0_cyberware_face", False)
    task["relocated_resource_count"] = len(app_changes) + len(ent_changes)
    task["available_vanilla_references"] = len(vanilla)
    task["required_custom_assets"] = sorted(set(relative.replace("/", "\\") for relative in source_files
        if relative.replace("/", "\\").lower() not in {key.lower() for key in vanilla}
        and (fnv1a64(source_root.rstrip("\\") + "\\" + relative.replace("/", "\\")) in old_references
             or (source_root.rstrip("\\") + "\\" + relative.replace("/", "\\")) in old_references)
        and Path(relative).suffix.lower() in (".mesh", ".xbm"))
        | {part["mesh"] for part in pimples + piercings})
    task["forced_custom_assets"] = sorted({part["mesh"] for part in pimples + piercings})
    task["appearance_path"] = old_app.replace(source_root.rstrip("\\"), task["resource_root"], 1)
    task["mapped_appearances"] = {"skin": skin_name, "eyes": eye_name,
                                   "eyebrows": brow_name, "hair_color": task["hair"]["color_name"]}
    task["catalog_applied"] = applied_catalog
    task["template_defaults_disabled"] = ["hx_makeup_eyes", "hx_makeup_lips_01", "h0_tattoo"]
    if not any(name.startswith("makeupCheeks_") for name in applied_catalog):
        task["template_defaults_disabled"].append("hx_makeup_freckles")
    if not cyberware or cyberware["selected_index"] != 1:
        task["template_defaults_disabled"].append("h0_cyberware_face")
    if not piercings:
        task["template_defaults_disabled"].append("i1_earring")
    task["unsupported_switchers"] = (["cyberware"] if cyberware and
                                      cyberware["selected_index"] not in (0, 1) else [])
    task["catalog_pending"] = sorted(set(choices) - set(applied_catalog)
                                     - {"eyes_color", eyebrow_color[0]["name"]}
                                     - {x["name"] for x in project["options"]
                                        if x["active"] and x["editable"] and "hair" in x["name"].lower()})
    task["status"] = "candidate_metadata_only"
    task["still_required"] = ["bake every selected morph into compatible meshes",
                               "map remaining editor options to NPC components",
                               "validate mesh appearance names and compiled resources",
                               "build and spawn-test NPC before Companion bridge export"]
    return app, ent, task


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--appearance-catalog", type=Path)
    parser.add_argument("--template-asset-map", type=Path)
    parser.add_argument("--template-app", type=Path, required=True)
    parser.add_argument("--template-ent", type=Path, required=True)
    parser.add_argument("--template-root", type=Path, required=True)
    parser.add_argument("--resource-root", required=True, help="In-game resource root of the template")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output_dir.exists():
            raise FileExistsError(args.output_dir)
        project = json.loads(args.project.read_text(encoding="utf-8-sig"))
        catalog = json.loads(args.catalog.read_text(encoding="utf-8-sig"))
        app = json.loads(args.template_app.read_text(encoding="utf-8-sig"))
        ent = json.loads(args.template_ent.read_text(encoding="utf-8-sig"))
        appearances = (json.loads(args.appearance_catalog.read_text(encoding="utf-8-sig"))
                       if args.appearance_catalog else None)
        assets = (json.loads(args.template_asset_map.read_text(encoding="utf-8-sig"))
                  if args.template_asset_map else None)
        files = [str(p.relative_to(args.template_root)) for p in args.template_root.rglob("*") if p.is_file()]
        modified_app, modified_ent, report = transform(project, catalog, app, ent,
                                                       args.resource_root, files, appearances, assets)
        ent_name = args.template_ent.name.removesuffix(".json")
        app_name = Path(report["appearance_path"]).name
        report["entity_path"] = report["resource_root"] + "\\" + ent_name
        args.output_dir.mkdir(parents=True)
        for name, value in ((app_name + ".json", modified_app), (ent_name + ".json", modified_ent),
                            ("conversion-report.json", report)):
            (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        print(args.output_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"NPC transform failed: {exc}\n")


if __name__ == "__main__":
    main()
