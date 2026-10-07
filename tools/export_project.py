"""Package a captured project for exchange, never label it as a finished NPC."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def duplicate_choice(option: dict) -> tuple:
    return (option.get("kind"), option.get("selected_name"), option.get("resource_path"))


def validate_project(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("Project must be an object")
    if data.get("format") != "npv-maker-project" or data.get("schema_version") != 1:
        raise ValueError("Unsupported NPV maker project format/version")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ValueError("A character name is required")
    if data.get("body") not in ("male", "female") or data.get("voice") not in ("male", "female"):
        raise ValueError("Invalid body or voice")
    options = data.get("options")
    if not isinstance(options, list) or not options:
        raise ValueError("No captured appearance options")
    seen = {}
    for option in options:
        if not isinstance(option, dict):
            raise ValueError("Invalid option")
        if not isinstance(option.get("name"), str) or not option["name"]:
            raise ValueError("Option needs an internal name")
        if not isinstance(option.get("body_part"), str) or not option["body_part"]:
            raise ValueError("Option needs a body part")
        key = (option["body_part"], option["name"])
        # Appearance mods can register the same editor option twice (seen with
        # bby_cyberware_06 from bby_xtra_face_cyberware: two identical,
        # inactive copies). The converter uses the first active copy and warns
        # when a later one differs (runtime_npc.first_choices); a mod that
        # registers an option twice must not make the whole project invalid.
        seen.setdefault(key, option)
        index = option.get("selected_index")
        count = option.get("choice_count")
        if type(index) is not int or index < 0 or type(count) is not int or count < 0:
            raise ValueError(f"Invalid selection: {key}")
        if option.get("kind") not in ("appearance", "morph", "switcher", "unknown"):
            raise ValueError(f"Unknown option kind: {key}")
        if not isinstance(option.get("selected_name"), str):
            raise ValueError(f"Invalid internal value: {key}")
        if "resource_path" in option and (not isinstance(option["resource_path"], str)
                                          or len(option["resource_path"]) > 512):
            raise ValueError(f"Invalid resource path: {key}")
        for flag in ("active", "editable", "censored"):
            if type(option.get(flag)) is not bool:
                raise ValueError(f"Invalid {flag}: {key}")
        # The game uses UINT32_MAX and other out-of-range indices for hidden
        # or read-only options, and mods leave active ones out of range too.
        # MEDIDO EM 27/09/2026: CCXL eyelashes left the active "eyelashes_options"
        # switcher at index 2 of 2 and the import of "mariko" stopped here. Such
        # a snapshot has no value name: the converter leaves that option out and
        # reopening the project skips it; neither needs the whole project refused.
    # CET's JSON encoder may encode an empty Lua table as {} rather than [].
    dependencies = data.get("dependencies")
    if dependencies != {} and not isinstance(dependencies, list):
        raise ValueError("Invalid dependency list")
    if data.get("dependency_status") not in ("unresolved", "author_reviewed"):
        raise ValueError("Invalid dependency status")
    for dependency in dependencies:
        if not isinstance(dependency, dict) or not dependency.get("name"):
            raise ValueError("Dependency needs a name")
        if not isinstance(dependency.get("url"), str) or not dependency["url"].startswith("https://"):
            raise ValueError("Dependency needs an HTTPS source link")
    if data.get("npc_status") != "not_generated":
        raise ValueError("This exporter only supports captured projects, not NPC packages")


def export_project(source: Path, destination: Path) -> Path:
    raw = source.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    validate_project(data)
    digest = hashlib.sha256(raw).hexdigest()
    # Names can contain Unicode, slashes or Windows reserved words. Never use
    # the display name as an archive path or a local destination.
    project_id = f"npv-{digest[:16]}"
    dependencies = data["dependencies"]
    lines = ["# Requirements", "", f"Dependency review: {data['dependency_status']}", ""]
    if dependencies:
        lines += [f"- {d['name']}: {d['url']}" for d in dependencies]
    else:
        lines.append("Dependencies have NOT been resolved. An empty list does not mean vanilla-only.")
    lines += ["", "This package contains a captured project, not a spawnable NPC.",
              "AMM, NCA and Companion Expansion adapters are not included.",
              "Third-party meshes, textures, archives and scripts are not bundled."]
    manifest = {
        "format": "npv-maker-project-bundle", "schema_version": 1,
        "project": f"projects/{project_id}.npv.json", "sha256": digest,
        "npc_generated": False, "dependencies_resolved": data["dependency_status"] == "author_reviewed",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents an accidental overwrite of an earlier export.
    with ZipFile(destination, "x", compression=ZIP_DEFLATED) as archive:
        archive.writestr(manifest["project"], raw)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("REQUIREMENTS.md", "\n".join(lines) + "\n")
        archive.writestr("README.txt", "NPV maker - captured project exchange\n\n"
                          "Keep this bundle as a project backup. NPV maker 0.2.2 can reopen\n"
                          "a project through ABRIR ULTIMO PROJETO when its JSON is placed in\n"
                          "the CET NPVMaker/projects directory. NPC generation is not yet\n"
                          "implemented. This is not a Vortex-installable NPC release and\n"
                          "cannot be installed into AMM/NCA/Companion Expansion yet.\n")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(export_project(args.project, args.output))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Export failed: {exc}\n")


if __name__ == "__main__":
    main()
