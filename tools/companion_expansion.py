"""Prepare or export a bridge from an NPV Maker project to Companion Expansion.

The bridge references a separately installed NPC archive. It never packages assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from export_project import validate_project


RECORD = re.compile(r"^Character\.[A-Za-z][A-Za-z0-9_]{2,90}$")
RESOURCE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\\.-]*\.(?:ent|app)$")
NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}$")


def project_info(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("Project exceeds 1 MB")
    project = json.loads(raw.decode("utf-8-sig"))
    validate_project(project)
    return project, hashlib.sha256(raw).hexdigest()


def resource_path(value: str, suffix: str) -> str:
    if not isinstance(value, str) or not RESOURCE.fullmatch(value):
        raise ValueError(f"Invalid resource path: {value!r}")
    parts = value.replace("/", "\\").split("\\")
    if any(part in ("", ".", "..") for part in parts) or not value.lower().endswith(suffix):
        raise ValueError(f"Invalid {suffix} resource path: {value!r}")
    return "\\".join(parts)


def prepare(project_path: Path, output: Path) -> Path:
    project, digest = project_info(project_path)
    if output.exists():
        raise FileExistsError(output)
    selected = [o for o in project["options"] if o["active"] and o["editable"]]
    spec = {
        "format": "npv-maker-companion-bridge-spec",
        "schema_version": 1,
        "project_sha256": digest,
        "display_name": project["name"],
        "body": project["body"],
        "appearance_metrics": {
            "active_editable_options": len(selected),
            "head_morphs": sum(o["body_part"] == "Head" and o["kind"] == "morph" for o in selected),
            "switchers": sum(o["kind"] == "switcher" for o in selected),
            "appearance_values": sum(o["kind"] == "appearance" for o in selected),
        },
        "hair_choices": [
            {key: o[key] for key in ("name", "selected_name", "selected_index", "choice_count")}
            for o in selected if o["body_part"] == "Head" and "hair" in o["name"].lower()
        ],
        "record_id": f"Character.NPVMaker_{digest[:16]}",
        "base_record": None,
        "entity_path": None,
        "appearance_name": None,
        "npc_archive_path": None,
        "npc_archive_sha256": None,
        "visual_match_confirmed": False,
        "in_game_spawn_tested": False,
        "asset_origin": None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def run_cli(cli: Path, *args: str) -> str:
    result = subprocess.run([str(cli), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode:
        raise ValueError(f"WolvenKit CLI failed: {result.stderr or result.stdout}")
    return result.stdout


def check_archive(cli: Path, archive: Path, entity_path: str, appearance: str) -> str:
    if not cli.is_file() or not archive.is_file() or archive.suffix.lower() != ".archive":
        raise ValueError("A WolvenKit CLI and an existing NPC .archive are required")
    listed = {line.strip().lower() for line in
              run_cli(cli, "archive", str(archive), "--list").splitlines()
              if line.strip().lower().endswith((".ent", ".app"))}
    if entity_path.lower() not in listed:
        raise ValueError(f"NPC archive does not contain {entity_path}")
    with tempfile.TemporaryDirectory(prefix="npv-companion-") as tmp:
        folder = Path(tmp)
        run_cli(cli, "extract", str(archive), "--outpath", str(folder),
                "--regex", "^" + re.escape(entity_path) + "$")
        entity = folder.joinpath(*entity_path.split("\\"))
        if not entity.is_file():
            raise ValueError("The declared .ent could not be extracted")
        run_cli(cli, "convert", "serialize", str(entity))
        serial = json.loads(Path(str(entity) + ".json").read_text(encoding="utf-8-sig"))
        entries = serial.get("Data", {}).get("RootChunk", {}).get("appearances", [])
        for entry in entries:
            if entry.get("appearanceName", {}).get("$value") != appearance:
                continue
            app = entry.get("appearanceResource", {}).get("DepotPath", {}).get("$value")
            app = resource_path(app, ".app")
            if app.lower() not in listed:
                raise ValueError(f"The selected appearance references missing {app}")
            run_cli(cli, "extract", str(archive), "--outpath", str(folder),
                    "--regex", "^" + re.escape(app) + "$")
            app_file = folder.joinpath(*app.split("\\"))
            if not app_file.is_file():
                raise ValueError("The referenced .app could not be extracted")
            run_cli(cli, "convert", "serialize", str(app_file))
            app_serial = json.loads(Path(str(app_file) + ".json").read_text(encoding="utf-8-sig"))
            definitions = app_serial.get("Data", {}).get("RootChunk", {}).get("appearances", [])
            if not any(d.get("Data", {}).get("name", {}).get("$value") == appearance
                       for d in definitions):
                raise ValueError(f"The .app lacks appearance {appearance}")
            return app
    raise ValueError(f"Appearance {appearance!r} is absent from the declared .ent")


def validate_spec(project: dict, digest: str, spec: dict) -> tuple[str, str, str]:
    if spec.get("format") != "npv-maker-companion-bridge-spec" or spec.get("schema_version") != 1:
        raise ValueError("Unsupported Companion Expansion bridge spec")
    if spec.get("project_sha256") != digest or spec.get("display_name") != project["name"]:
        raise ValueError("Bridge spec belongs to another project revision")
    if spec.get("body") != project["body"]:
        raise ValueError("NPC body differs from the captured project")
    if spec.get("visual_match_confirmed") is not True:
        raise ValueError("NPC appearance has not been visually matched to this project")
    if spec.get("asset_origin") not in ("self_authored", "external_dependency"):
        raise ValueError("Asset origin must be reviewed")
    record = spec.get("record_id")
    base = spec.get("base_record")
    appearance = spec.get("appearance_name")
    if not isinstance(record, str) or not RECORD.fullmatch(record):
        raise ValueError("Invalid Character record ID")
    if not isinstance(base, str) or not RECORD.fullmatch(base) or base == record:
        raise ValueError("A distinct, valid base Character record is required")
    if not isinstance(appearance, str) or not NAME.fullmatch(appearance):
        raise ValueError("Invalid NPC appearance name")
    entity = resource_path(spec.get("entity_path"), ".ent")
    if spec.get("npc_archive_sha256") is None or not re.fullmatch(
            r"[0-9a-f]{64}", str(spec["npc_archive_sha256"])):
        raise ValueError("NPC archive SHA-256 is required")
    if not isinstance(spec.get("npc_archive_path"), str) or not spec["npc_archive_path"]:
        raise ValueError("NPC archive path is required")
    return record, base, entity


def bridge_script(record: str, digest: str) -> str:
    # Companion Expansion constructs this ID from the tagged Character record.
    companion_id = "CompanionFramework." + record
    return (f"public class NPVMakerCompanion_{digest[:16]}_BridgeSystem extends ScriptableSystem {{\n"
            "  private func OnAttach() -> Void {\n"
            "    GameInstance.GetCallbackSystem()\n"
            "      .RegisterCallback(n\"Session/Ready\", this, n\"OnNPVMakerCompanionReady\")\n"
            "      .SetLifetime(CallbackLifetime.Forever);\n"
            "  }\n\n"
            "  private cb func OnNPVMakerCompanionReady(event: ref<GameSessionEvent>) -> Void {\n"
            "    if GameInstance.GetSystemRequestsHandler().IsPreGame() { return; };\n"
            "    let reg: ref<AikoNPVRegistrySystem> =\n"
            "      AikoNPVRegistrySystem.Get(this.GetGameInstance());\n"
            "    if IsDefined(reg) {\n"
            f"      reg.UnlockCompanion(n\"{companion_id}\", \"NPV Maker bridge\");\n"
            "    };\n"
            "  }\n"
            "}\n")


def bridge_yaml(project: dict, record: str, base: str,
                entity: str, appearance: str, name_key: str | None = None, companion: bool = True) -> str:
    """TweakXL record. displayName is a localization key: with `name_key` it
    points to the ArchiveXL name table the runtime installs; without it (old
    private packages) the plain name is written, which only shows when the
    game already has a key with that text. The CompanionFramework tag only
    when the Companion Expansion integration is marked (adapters.py)."""
    body_tag = "WomanAverage" if project["body"] == "female" else "ManAverage"
    shown = json.dumps(name_key or project['name'], ensure_ascii=False)
    # JSON strings are valid YAML scalars. Never inject free text into YAML syntax.
    return (f"{record}:\n"
            f"  $base: {base}\n"
            f"  displayName: {shown}\n"
            f"  fullDisplayName: {shown}\n"
            f"  entityTemplatePath: {json.dumps(entity)}\n"
            f"  appearanceName: {appearance}\n"
            + (f"  tags: [CompanionFramework]\n" if companion else "")
            + f"  visualTags: [{body_tag}]\n")


def export(project_path: Path, spec_path: Path, cli: Path, destination: Path) -> Path:
    project, digest = project_info(project_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    record, base, entity = validate_spec(project, digest, spec)
    archive_path = Path(spec["npc_archive_path"])
    hasher = hashlib.sha256()
    with archive_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    archive_digest = hasher.hexdigest()
    if archive_digest != spec["npc_archive_sha256"]:
        raise ValueError("NPC archive changed since the bridge spec was reviewed")
    app = check_archive(cli, archive_path, entity, spec["appearance_name"])
    yaml = bridge_yaml(project, record, base, entity, spec["appearance_name"])
    manifest = {
        "format": "npv-maker-companion-bridge", "schema_version": 1,
        "project_sha256": digest, "npc_archive_sha256": archive_digest,
        "record_id": record, "entity_path": entity,
        "appearance_name": spec["appearance_name"], "appearance_resource": app,
        "body": project["body"], "asset_origin": spec["asset_origin"],
        "archive_bundled": False, "in_game_spawn_tested": spec.get("in_game_spawn_tested") is True,
    }
    requirements = ("NPV Maker + Companion Expansion bridge\n\n"
                    "Install the matching NPC archive separately. This ZIP contains a TweakXL "
                    "record and a REDscript unlock hook for this NPC only. It does not contain "
                    "a character mesh, texture, .ent or .app.\n"
                    f"NPC archive SHA-256: {archive_digest}\n"
                    f"Entity: {entity}\nAppearance: {spec['appearance_name']}\n"
                    "Requires TweakXL and Companion Expansion.\n"
                    "Verify the character and spawning inside the game before sharing publicly.\n")
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "x", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("r6/tweaks/NPVMaker/companion_" + digest[:16] + ".yaml", yaml)
        bundle.writestr("r6/scripts/NPVMakerCompanion/bridge_" + digest[:16] + ".reds",
                        bridge_script(record, digest))
        bundle.writestr("NPV-Maker-Companion-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        bundle.writestr("NPV-Maker-Companion-README.txt", requirements)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare", help="Create a reviewable bridge spec; no installable package")
    p.add_argument("project", type=Path)
    p.add_argument("--output", type=Path, required=True)
    e = sub.add_parser("export", help="Verify the NPC archive and create a bridge ZIP")
    e.add_argument("project", type=Path)
    e.add_argument("--spec", type=Path, required=True)
    e.add_argument("--cli", type=Path, required=True)
    e.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (prepare(args.project, args.output) if args.action == "prepare" else
                  export(args.project, args.spec, args.cli, args.output))
        print(result)
    except (ValueError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Companion Expansion bridge failed: {exc}\n")


if __name__ == "__main__":
    main()
