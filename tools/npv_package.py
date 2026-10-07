"""NPV package: a tested NPV exported for others, and old rebuild-recipe packages read back.

Since 03/10/2026 (BUGS items 67b/67c, author decision) EXPORTAR writes the NPV itself: the files the
local install wrote (archive, record, integrations), with the pieces from mods kept as references to
the mods' own files and their preset shapes applied in game by NPV Maker. Meshes the NPV carries
were made only from base game files; an NPV built before that rule, or carrying a copy of a mod
piece, is refused with the instruction to create it again. Mods are listed as requirements; a
missing mod leaves its piece missing. Old recipe packages (docs/EXPORT-MAPA.md, 30/09/2026) are
still read and installed by INSTALAR. Permission to publish is the publisher's responsibility.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import time
import unicodedata
import zipfile
from pathlib import Path

import adapters
import diagnostics
import i18n
import material_chain
import runtime_import
from runtime_resources import archive_hashes, path_hash

PACKAGE_TYPE = "npvmaker_npv"
FORMAT_VERSION = 1
MINIMUM_NPVMAKER = "0.4.22"
CHARACTER_ID = re.compile(r"npv_[a-z0-9_]{1,24}_[0-9a-f]{8}")
VERSION = re.compile(r"\d{1,4}\.\d{1,4}\.\d{1,4}")
PROJECT_NAME = re.compile(r"npv-\d{8}T\d{6}Z-\d{4}\.npv\.json")
PACKAGE_ROOT = "red4ext/plugins/NPVMaker/packages"
MANIFEST_NAME = "npv-package.json"
RECIPE_NAME = "recipe/project.npv.json"
REQUIREMENTS_NAME = "REQUIREMENTS.txt"
PACKAGE_FILES = (MANIFEST_NAME, RECIPE_NAME, REQUIREMENTS_NAME)
# The exported NPV (03/10/2026): its game files plus the description, in a folder NPV Maker does not install from.
NPV_PACKAGE_TYPE = "npvmaker_npv_files"
NPV_INFO_ROOT = "red4ext/plugins/NPVMaker/npvs"
NOTICE = ("Este pacote pode conter ou depender de conteudo criado por terceiros. Verifique as permissoes dos "
          "respectivos autores e forneca os creditos e requisitos necessarios antes de distribuir o NPV.")
NPVMAKER_REQUIREMENT = "NPV Maker"
# A recipe that names a drive or a user folder would publish a private path.
PRIVATE_PATH = re.compile(r"[A-Za-z]:\\\\|\\\\Users\\\\|/Users/", re.IGNORECASE)
KIND_TEXT = {"override": "substitui arquivos do jogo", "own_path": "arquivos do proprio mod",
             "xl_patch": "patch do ArchiveXL herdado",
             "material_override": "substitui material/textura do jogo usado pelo NPV",
             "material_own": "material/textura do proprio mod usado pelo NPV"}
# Vortex staging folders, as measured in vortex.deployment.json on 30/09/2026:
# "VTK body user - Vanilla eyes compatible-16930-1-06-1737836074" and
# "DreamGalaxyEyesCCXL By Protossvoid 34080 1 2026-09-18T23-31Z rxs7xRsWV".
VORTEX_DASHED = re.compile(r"^(?P<name>.*?)-(?P<id>\d+)-(?P<version>[0-9A-Za-z.\-]*?)-?\d{9,11}$")
VORTEX_SPACED = re.compile(r"^(?P<name>.*?) (?P<id>\d+) (?P<version>\S+) \d{4}-\d\d-\d\dT[0-9\-]+Z \S+$")
TEXT_LIMITS = {"display_name": 64, "author": 64, "version": 14, "description": 2000}
PRESET_LIMITS = {"name": 120, "author": 64, "url": 300, "version": 40}
DEPENDENCY_LIMITS = {"name": 120, "author": 64, "url": 300, "reason": 200}


class PackageError(ValueError):
    """A package that cannot be written or read; `code` is its diagnostic."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(text))[:3])


def slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "_", plain).strip("_")
    return (text[:24].strip("_")) or "npv"


def new_character_id(name: str) -> str:
    """Created once, at the first export; never from content, version or date."""
    return "npv_" + slug(name) + "_" + secrets.token_hex(4)


def package_identity(character_id: str) -> str:
    """Identity of the rebuilt NPV: depends only on the character_id, so every version of one
    package lands on the same record, namespace and files (runtime_npc.build `identity`)."""
    if not CHARACTER_ID.fullmatch(character_id or ""):
        raise PackageError("NPVM-PACKAGE-006", "character_id invalido: " + repr(character_id))
    return hashlib.sha256(("npvmaker-package:" + character_id).encode("ascii")).hexdigest()


def meta_path(project: Path) -> Path:
    """Sidecar beside the project (author decision 30/09/2026): the project hash covers the
    whole .npv.json, so the character_id and the export data live outside it."""
    if not PROJECT_NAME.fullmatch(project.name):
        raise PackageError("NPVM-PACKAGE-001", "nome de projeto inesperado: " + project.name)
    return project.with_name(project.name[:-len(".npv.json")] + ".npv.meta.json")


def read_meta(project: Path) -> dict:
    path = meta_path(project)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("format") != "npv-maker-project-meta" or data.get("schema_version") != 1:
        raise PackageError("NPVM-PACKAGE-001", "metadados do projeto em formato desconhecido")
    if data.get("character_id") is not None and not CHARACTER_ID.fullmatch(data["character_id"]):
        raise PackageError("NPVM-PACKAGE-001", "character_id invalido nos metadados do projeto")
    return data


def write_meta(project: Path, meta: dict) -> None:
    path = meta_path(project)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    temporary.replace(path)


def find_project(projects: Path, source_sha256: str) -> Path | None:
    """The saved project whose bytes built the tested NPV."""
    for candidate in sorted(projects.glob("npv-*.npv.json")):
        if PROJECT_NAME.fullmatch(candidate.name) and candidate.stat().st_size <= 1024 * 1024:
            if hashlib.sha256(candidate.read_bytes()).hexdigest() == source_sha256:
                return candidate
    return None


def tested_build(plugin: Path, token: str) -> dict:
    """The installed build behind an imported NPV: receipt, manifest and job folder."""
    if not re.fullmatch(r"[0-9a-f]{16}", token or ""):
        raise PackageError("NPVM-PACKAGE-001", "identificador de NPV invalido")
    receipts = [r for r in sorted((plugin / "data/imports").glob("*.json")) if r.stem.startswith(token)]
    if len(receipts) != 1:
        raise PackageError("NPVM-PACKAGE-001", "NPV importado nao encontrado: " + token)
    receipt = json.loads(receipts[0].read_text(encoding="utf8"))
    if receipt.get("character_id"):
        raise PackageError("NPVM-PACKAGE-001", "este NPV foi instalado de um pacote; exporte o projeto original")
    manifest_path = Path(receipt.get("manifest") or "")
    if not manifest_path.is_file():
        raise PackageError("NPVM-PACKAGE-001", "o build testado deste NPV nao esta mais em data/jobs")
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    job = manifest_path.parent.parent
    recipe = job / "project.npv.json"
    if not recipe.is_file():
        raise PackageError("NPVM-PACKAGE-001", "a receita do build testado nao foi encontrada")
    return {"receipt": receipt, "manifest": manifest, "job": job, "recipe": recipe}


def npvsrc_resources(resources: Path) -> list[dict]:
    """Resources the conversion read, with the archive that served each one (.npvsrc stamps)."""
    found = []
    if not resources.is_dir():
        return found
    for marker in sorted(resources.rglob("*.npvsrc")):
        relative = marker.relative_to(resources).with_suffix("")
        parts = relative.parts
        if parts and parts[0] == "hashes":
            resource = relative.stem
            if not resource.isdecimal():
                continue
        else:
            resource = "\\".join(parts)
        lines = marker.read_text(encoding="utf8", errors="replace").splitlines()
        archive = lines[0].split("|")[0] if lines and lines[0].split("|")[0].lower().endswith(".archive") else None
        found.append({"resource": resource, "archive": archive, "via": "read"})
        for line in lines[1:]:
            fields = line.split("|")
            if fields[0] == "props" and len(fields) > 1 and fields[1]:
                found.append({"resource": fields[1], "archive": None, "via": "read"})
    return found


def build_resources(job: Path, manifest: dict, recipe: dict, materials: list[str] | None = None) -> list[dict]:
    """Every resource the tested NPV used, read or only referenced, once each.

    `materials`: files the materials of the chosen appearances reach (material_chain, BUGS 68)."""
    entries = npvsrc_resources(job / "npc/installed-resources")
    for component in manifest.get("components") or []:
        mesh = component.get("mesh")
        if isinstance(mesh, str) and mesh and not mesh.lower().startswith("npvmaker\\"):
            entries.append({"resource": mesh, "archive": None, "via": "reference"})
    for record in manifest.get("diagnostics") or []:
        dependency = record.get("external_dependency") or {}
        if dependency.get("type") == "archivexl_patch" and dependency.get("patch"):
            entries.append({"resource": dependency["patch"], "archive": None, "via": "xl_patch"})
    for component in (recipe.get("runtime_manifest") or {}).get("components") or []:
        if component.get("state") == "LOADED":
            value = component.get("hash") or component.get("path")
            if isinstance(value, str) and value:
                entries.append({"resource": value, "archive": None, "via": "puppet"})
    entries += [{"resource": path, "archive": None, "via": "material"} for path in materials or []]
    merged = {}
    for entry in entries:
        key = resource_key(entry["resource"])
        if key is None:
            continue
        known = merged.get(key)
        if known is None:
            merged[key] = dict(entry)
            continue
        if entry["archive"] and not known["archive"]:
            known["archive"] = entry["archive"]
        if entry["via"] == "xl_patch":
            known["via"] = "xl_patch"
        if known["resource"].isdecimal() and not entry["resource"].isdecimal():
            known["resource"] = entry["resource"]
    return list(merged.values())


def resource_key(resource) -> int | None:
    text = str(resource or "").strip()
    if not text:
        return None
    if text.isdecimal():
        value = int(text)
        return value if 0 < value < 2 ** 64 else None
    return int(path_hash(text.replace("/", "\\")))


class Locator:
    """Which installed archive ships a resource, by path hash, as the game mounts them:
    archives directly in archive/pc/mod in name order (runtime_resources.Resources), the
    game archives and the ArchiveXL bundle."""

    def __init__(self, game: Path):
        self.game = game
        mods = game / "archive/pc/mod"
        self.mods = [(a, archive_hashes(a)) for a in (sorted(mods.glob("*.archive"), key=lambda p: p.name.lower())
                                                    if mods.is_dir() else [])]
        self.base = set()
        for folder in (game / "archive/pc/content", game / "archive/pc/ep1"):
            for archive in (sorted(folder.rglob("*.archive")) if folder.is_dir() else []):
                self.base |= archive_hashes(archive)
        bundle = game / "red4ext/plugins/ArchiveXL/Bundle"
        self.frameworks = [(a, archive_hashes(a)) for a in (sorted(bundle.glob("*.archive")) if bundle.is_dir() else [])]

    def mod_owners(self, key: int) -> list[str]:
        return [a.name for a, hashes in self.mods if key in hashes]

    def framework_owner(self, key: int) -> str | None:
        return next((a.name for a, hashes in self.frameworks if key in hashes), None)

    def in_base(self, key: int) -> bool:
        return key in self.base

    def relative(self, archive_name: str) -> str:
        for archive, _ in self.mods + self.frameworks:
            if archive.name == archive_name:
                return str(archive.relative_to(self.game)).replace("/", "\\")
        return "archive\\pc\\mod\\" + archive_name


def vortex_sources(game: Path) -> dict:
    """relPath (lower case) -> Vortex staging folder, from the file Vortex writes in the game."""
    path = game / "vortex.deployment.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return {str(f.get("relPath", "")).lower(): str(f.get("source", "")) for f in data.get("files") or []
            if f.get("relPath") and f.get("source")}


def parse_vortex_folder(folder: str) -> tuple[str, int | None]:
    for pattern in (VORTEX_DASHED, VORTEX_SPACED):
        match = pattern.match(folder)
        if match and match.group("name").strip():
            return match.group("name").strip(), int(match.group("id"))
    return folder, None


def nexus_url(mod_id) -> str:
    return "https://www.nexusmods.com/cyberpunk2077/mods/" + str(mod_id) if isinstance(mod_id, int) else ""


def classify(entries: list[dict], locator) -> dict:
    """Technical origin only: VANILLA, MOD DE TERCEIRO, GERADO PELO NPV MAKER, ORIGEM DESCONHECIDA."""
    counts = {"VANILLA": 0, "MOD DE TERCEIRO": 0, "GERADO PELO NPV MAKER": 0, "ORIGEM DESCONHECIDA": 0}
    by_archive, unknown, shared = {}, [], {}
    for entry in entries:
        resource = entry["resource"]
        if not resource.isdecimal() and resource.lower().startswith("npvmaker\\"):
            counts["GERADO PELO NPV MAKER"] += 1
            continue
        key = resource_key(resource)
        owners = locator.mod_owners(key)
        framework = None if owners else locator.framework_owner(key)
        if owners:
            archive = entry["archive"] if entry["archive"] in owners else owners[0]
        elif framework:
            archive = framework
        elif locator.in_base(key):
            counts["VANILLA"] += 1
            continue
        else:
            counts["ORIGEM DESCONHECIDA"] += 1
            unknown.append(resource)
            continue
        counts["MOD DE TERCEIRO"] += 1
        item = {"hash": resource} if resource.isdecimal() else {"path": resource}
        if entry["via"] == "material" and material_chain.shared(resource):
            # Author decision 04/10/2026 (BUGS 68): a shared shader only goes to the report.
            shared.setdefault(archive, []).append(item)
            continue
        if entry["via"] == "xl_patch":
            kind = "xl_patch"
        elif entry["via"] == "material":
            kind = "material_override" if locator.in_base(key) else "material_own"
        else:
            kind = "override" if locator.in_base(key) else "own_path"
        item["kind"] = kind
        by_archive.setdefault(archive, []).append(item)
    return {"counts": counts, "by_archive": by_archive, "unknown": sorted(unknown)[:200], "shared": shared}


def detect_dependencies(game: Path, entries: list[dict], locator=None, sources: dict | None = None,
                        downloads=None) -> dict:
    """Mods that served the NPV, grouped by the Vortex mod when Vortex deployed them.

    Assistive, never authoritative: the author reviews, edits and adds before exporting."""
    locator = locator or Locator(game)
    sources = vortex_sources(game) if sources is None else sources
    found = classify(entries, locator)
    # `downloads`: archive names -> Nexus download names, for archives Vortex did not deploy (BUGS 68).
    unknown = {a.lower() for a in list(found["by_archive"]) + list((found.get("shared") or {}))
               if not sources.get(locator.relative(a).lower())}
    downloaded = downloads(unknown) if downloads is not None and unknown else {}

    def origin(archive):
        folder = sources.get(locator.relative(archive).lower())
        if folder:
            name, mod_id = parse_vortex_folder(folder)
            return "vortex:" + folder, "vortex.deployment.json", folder, name, mod_id
        stem = downloaded.get(archive.lower())
        if stem:
            name, mod_id = parse_vortex_folder(stem)
            return "download:" + stem, "nexus download", stem + ".zip", name, mod_id
        return "archive:" + archive, "archive", "", Path(archive).stem, None
    groups = {}
    for archive, resources in sorted(found["by_archive"].items()):
        key, detected_from, folder, name, mod_id = origin(archive)
        group = groups.setdefault(key, {"name": name, "author": "", "nexus_mod_id": mod_id,
                                        "url": nexus_url(mod_id), "file": folder, "archives": [],
                                        "resources": [], "detected_from": detected_from})
        group["archives"].append(archive)
        group["resources"].extend(resources)
    dependencies = []
    for group in groups.values():
        kinds = sorted({r["kind"] for r in group["resources"]})
        group["required_for_rebuild"] = kinds != ["xl_patch"]
        group["reason"] = ", ".join(KIND_TEXT[k] for k in kinds)
        if not group["required_for_rebuild"]:
            group["reason"] += "; a aparencia escolhida pode nao usar"
        group["include"] = True
        dependencies.append(group)
    dependencies.sort(key=lambda d: (not d["required_for_rebuild"], d["name"].lower()))
    credited = {group["name"] for group in dependencies}
    shared = {}
    for archive, resources in sorted((found.get("shared") or {}).items()):
        _, _, _, name, mod_id = origin(archive)
        if name not in credited:
            entry = shared.setdefault(name, {"name": name, "nexus_mod_id": mod_id, "archives": [], "resources": []})
            entry["archives"].append(archive)
            entry["resources"].extend(resources)
    return {"dependencies": dependencies, "counts": found["counts"], "unknown": found["unknown"],
            "shared_overrides": list(shared.values())}


def text_field(value, limit: int, name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise PackageError("NPVM-PACKAGE-001", "campo invalido: " + name)
    return value.strip()


def mod_id_field(value, name: str):
    if value in (None, "", 0):
        return None
    if isinstance(value, str) and value.strip().isdecimal():
        value = int(value.strip())
    if not isinstance(value, int) or isinstance(value, bool) or not 0 < value < 10 ** 7:
        raise PackageError("NPVM-PACKAGE-001", "Nexus ID invalido: " + name)
    return value


def url_field(value, name: str) -> str:
    text = text_field(value, 300, name)
    if text and not re.fullmatch(r"https://[^\s\"'<>]+", text):
        raise PackageError("NPVM-PACKAGE-001", "URL precisa comecar com https:// (" + name + ")")
    return text


def clean_fields(fields: dict) -> dict:
    if not isinstance(fields, dict):
        raise PackageError("NPVM-PACKAGE-001", "formulario ausente")
    clean = {key: text_field(fields.get(key), limit, key) for key, limit in TEXT_LIMITS.items()}
    if not clean["display_name"]:
        raise PackageError("NPVM-PACKAGE-001", "informe o nome do NPV")
    clean["version"] = clean["version"] or "1.0.0"
    if not VERSION.fullmatch(clean["version"]):
        raise PackageError("NPVM-PACKAGE-001", "versao no formato 1.0.0")
    preset = fields.get("source_preset") or {}
    if not isinstance(preset, dict):
        raise PackageError("NPVM-PACKAGE-001", "preset original invalido")
    clean["source_preset"] = {key: text_field(preset.get(key), limit, "preset " + key)
                              for key, limit in PRESET_LIMITS.items()}
    clean["source_preset"]["url"] = url_field(preset.get("url"), "preset url")
    clean["source_preset"]["nexus_mod_id"] = mod_id_field(preset.get("nexus_mod_id"), "preset")
    clean["source_preset"]["required_for_rebuild"] = False
    return clean


def merge_dependencies(edited, detected: list[dict]) -> list[dict]:
    """The author's list: detected entries keep their measured resources; manual ones have none.

    A detected requirement is always credited (BUGS 67, 04/10/2026): the author edits it and picks required or
    optional, but cannot drop or exclude it; only requirements added by hand can go."""
    if edited == {}:
        edited = []  # CET's json.encode writes an empty Lua table as an object
    if not isinstance(edited, list) or len(edited) > 100:
        raise PackageError("NPVM-PACKAGE-001", "lista de requisitos invalida")
    result, credited = [], set()
    for item in edited:
        if not isinstance(item, dict):
            raise PackageError("NPVM-PACKAGE-001", "requisito invalido")
        index = item.get("detected")
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(detected):
            if index in credited:
                raise PackageError("NPVM-PACKAGE-001", "requisito detectado repetido: " + detected[index]["name"])
            if item.get("include") is False:
                raise PackageError("NPVM-PACKAGE-001", "requisito detectado nao pode ser removido: "
                                   + detected[index]["name"])
            credited.add(index)
        elif item.get("include") is False:
            continue
        name = text_field(item.get("name"), DEPENDENCY_LIMITS["name"], "requisito")
        if not name:
            raise PackageError("NPVM-PACKAGE-001", "requisito sem nome")
        entry = {"name": name, "author": text_field(item.get("author"), 64, "autor do requisito"),
                 "nexus_mod_id": mod_id_field(item.get("nexus_mod_id"), name),
                 "url": url_field(item.get("url"), name),
                 "required_for_rebuild": bool(item.get("required_for_rebuild", True)),
                 "reason": text_field(item.get("reason"), DEPENDENCY_LIMITS["reason"], "motivo")}
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(detected):
            source = detected[index]
            entry.update({"file": source.get("file", ""), "detected_from": source["detected_from"],
                          "archives": list(source["archives"]), "resources": list(source["resources"])})
        elif index is None:
            entry.update({"file": "", "detected_from": "author", "archives": [], "resources": []})
        else:
            raise PackageError("NPVM-PACKAGE-001", "requisito detectado desconhecido")
        if not entry["url"] and entry["nexus_mod_id"]:
            entry["url"] = nexus_url(entry["nexus_mod_id"])
        result.append(entry)
    missing = [detected[i]["name"] for i in range(len(detected)) if i not in credited]
    if missing:
        raise PackageError("NPVM-PACKAGE-001", "requisito detectado nao pode ser removido: " + ", ".join(missing[:5]))
    return result


def package_manifest(character_id: str, fields: dict, dependencies: list[dict], recipe: dict,
                     recipe_bytes: bytes, body_strategy: str, counts: dict,
                     integrations: dict | None = None, underwear: str = "bottom") -> dict:
    return {"format_version": FORMAT_VERSION, "package_type": PACKAGE_TYPE, "requires_npvmaker": True,
            "minimum_npvmaker_version": MINIMUM_NPVMAKER,
            "created_with": {"npvmaker": diagnostics.NPV_VERSION, "wolvenkit": "8.19.0"},
            "character_id": character_id, "display_name": fields["display_name"], "author": fields["author"],
            "version": fields["version"], "description": fields["description"],
            "body": recipe.get("body"), "voice": recipe.get("voice"),
            "recipe": {"project": RECIPE_NAME, "project_sha256": hashlib.sha256(recipe_bytes).hexdigest(),
                       "body_strategy": body_strategy},
            "source_preset": fields["source_preset"], "dependencies": dependencies,
            "resource_origin": counts, "embedded": [], "notice": NOTICE,
            "integrations": adapters.clean(integrations), "underwear": underwear_field(underwear)}


# Default outfit the NPV is rebuilt with (runtime_npc.UNDERWEAR_MODES); a package without it gets "bottom".
UNDERWEAR_MODES = ("bottom", "full", "none")


def underwear_field(value) -> str:
    if value in (None, ""):
        return "bottom"
    if value not in UNDERWEAR_MODES:
        raise PackageError("NPVM-PACKAGE-001", "roupa padrao invalida")
    return value


def requirement_lines(manifest: dict) -> list[str]:
    lines = [NPVMAKER_REQUIREMENT + (" (obrigatorio; aplica no jogo as formas do rosto e do corpo)"
                                     if manifest.get("package_type") == NPV_PACKAGE_TYPE
                                     else " (obrigatorio; reconstroi este NPV no seu PC)")]
    preset = manifest.get("source_preset") or {}
    if preset.get("name"):
        lines.append("Preset original: " + preset["name"] + (" por " + preset["author"] if preset.get("author") else "")
                     + (" - " + preset["url"] if preset.get("url") else ""))
    for dependency in manifest["dependencies"]:
        line = dependency["name"] + (" por " + dependency["author"] if dependency.get("author") else "")
        line += " (" + ("obrigatorio" if dependency["required_for_rebuild"] else "opcional") + ")"
        if dependency.get("url"):
            line += " - " + dependency["url"]
        lines.append(line)
    return lines


# Whoever downloads the package may read any language, so the file carries the three (i18n.LANGUAGES). Since 0.5.0
# there is no CET window: INSTALAR is in the PACOTES tab of the NPV maker editor.
INSTALL_TEXT = {
    "pt": ("Requisitos:", "Instalacao: instale os requisitos e este pacote, abra o jogo, menu principal > NPV maker >",
           "escolha o corpo > PROXIMO: GERENCIAR > PACOTES > INSTALAR. O NPV Maker reconstroi o personagem no seu PC."),
    "en": ("Requirements:", "Install: install the requirements and this package, start the game, main menu > NPV maker >",
           "choose the body > NEXT: MANAGE > PACKAGES > INSTALL. NPV Maker rebuilds the character on your PC."),
    "es": ("Requisitos:", "Instalación: instala los requisitos y este paquete, abre el juego, menú principal > NPV maker >",
           "elige el cuerpo > SIGUIENTE: GESTIONAR > PAQUETES > INSTALAR. NPV Maker reconstruye el personaje en tu PC."),
}
NPV_INSTALL_TEXT = {
    "pt": ("Requisitos:", "Instalacao: instale o NPV Maker, os requisitos e este arquivo pelo Vortex e reinicie o jogo.",
           "Sem um requisito, a peca que vem dele fica faltando no NPV."),
    "en": ("Requirements:", "Install: install NPV Maker, the requirements and this file with Vortex, then restart the game.",
           "Without a requirement, the piece that comes from it is missing on the NPV."),
    "es": ("Requisitos:", "Instalación: instala NPV Maker, los requisitos y este archivo con Vortex y reinicia el juego.",
           "Sin un requisito, la pieza que viene de él falta en el NPV."),
}
LANGUAGE_NAMES = {"pt": "Portugues", "en": "English", "es": "Espanol"}
INTEGRATIONS_TITLE = {"pt": "Funciona com (opcional, so para usar o NPV nesse mod):",
                      "en": "Works with (optional, only to use the NPV in that mod):",
                      "es": "Funciona con (opcional, solo para usar el NPV en ese mod):"}


def requirements_text(manifest: dict) -> str:
    text = [manifest["display_name"] + " " + manifest["version"] + " (" + manifest["character_id"] + ")"]
    install = NPV_INSTALL_TEXT if manifest.get("package_type") == NPV_PACKAGE_TYPE else INSTALL_TEXT
    for lang in ("en", "pt", "es"):
        title, first, second = install[lang]
        text += ["", "== " + LANGUAGE_NAMES[lang] + " ==", title]
        text += ["- " + i18n.text(line, lang) for line in requirement_lines(manifest)]
        integrations = adapters.requirement_lines(adapters.from_package(manifest))
        if integrations:
            text += ["", INTEGRATIONS_TITLE[lang]] + ["- " + line for line in integrations]
            text += adapters.usage_lines(adapters.from_package(manifest), manifest.get("record_id", ""), lang)
        text += ["", first, second, "", i18n.text(NOTICE, lang)]
    return "\n".join(text + [""])


def nexus_text(manifest: dict) -> str:
    """BBCode for the author's Nexus page; edit before posting."""
    preset = manifest.get("source_preset") or {}
    out = ["[b]" + manifest["display_name"] + "[/b] " + manifest["version"], ""]
    if manifest.get("description"):
        out += [manifest["description"], ""]
    out += ["Created with [b]NPV Maker[/b].", ""]
    if preset.get("name"):
        link = "[url=" + preset["url"] + "]" + preset["name"] + "[/url]" if preset.get("url") else preset["name"]
        out += ["[b]Original preset[/b]", link + (" by " + preset["author"] if preset.get("author") else ""), ""]
    files_package = manifest.get("package_type") == NPV_PACKAGE_TYPE
    out += ["[b]Requirements[/b]", "[list]",
            "[*]NPV Maker (required: it applies the face and body shapes in game)" if files_package
            else "[*]NPV Maker (required: it rebuilds this NPV on your PC)"]
    for dependency in manifest["dependencies"]:
        name = ("[url=" + dependency["url"] + "]" + dependency["name"] + "[/url]") if dependency.get("url") \
            else dependency["name"]
        author = " by " + dependency["author"] if dependency.get("author") else ""
        out.append("[*]" + name + author + ("" if dependency["required_for_rebuild"] else " (optional)"))
    out.append("[/list]")
    integrations = adapters.requirement_lines(adapters.from_package(manifest))
    if integrations:
        out += ["", "[b]Works with[/b] (optional, only to use the NPV in that mod)", "[list]"]
        out += ["[*]" + line for line in integrations] + ["[/list]"]
        out += adapters.usage_lines(adapters.from_package(manifest), manifest.get("record_id", ""), "en")
    out += ["", "[b]Installation[/b]",
            "Install NPV Maker, the requirements and this file with Vortex, then restart the game. Without a "
            "requirement, the piece that comes from it is missing on the NPV." if files_package else
            "Install the requirements and this file, start the game, main menu > NPV maker > choose the body > "
            "NEXT: MANAGE > PACKAGES > INSTALL. NPV Maker rebuilds the character from your installed mods.",
            "", "[b]Credits[/b]", "[list]"]
    if preset.get("name"):
        out.append("[*]" + preset["name"] + (" - " + preset["author"] if preset.get("author") else ""))
    for dependency in manifest["dependencies"]:
        out.append("[*]" + dependency["name"] + (" - " + dependency["author"] if dependency.get("author") else ""))
    # The page is in English (BUGS 68: the notice used to stay in Portuguese).
    out += ["[/list]", "", "[i]" + i18n.text(NOTICE, "en") + "[/i]", ""]
    return "\n".join(out)


def check_recipe(recipe_bytes: bytes) -> dict:
    text = recipe_bytes.decode("utf-8-sig")
    if PRIVATE_PATH.search(text):
        raise PackageError("NPVM-PACKAGE-001", "a receita contem um caminho pessoal e nao pode ser publicada")
    recipe = json.loads(text)
    if recipe.get("format") != "npv-maker-project":
        raise PackageError("NPVM-PACKAGE-001", "receita nao e um projeto do NPV Maker")
    return recipe


def safe_file_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
                  .decode("ascii")).strip("_")[:48] or "NPV"


def write_package(destination: Path, manifest: dict, recipe_bytes: bytes) -> dict:
    """ZIP with the package folder for Vortex, plus the texts for the author's page."""
    folder = PACKAGE_ROOT + "/" + manifest["character_id"] + "/"
    name = safe_file_name(manifest["display_name"])
    if destination.exists():
        raise PackageError("NPVM-PACKAGE-007", "esta versao ja foi exportada; aumente a versao")
    destination.mkdir(parents=True)
    content = {MANIFEST_NAME: (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf8"),
               RECIPE_NAME: recipe_bytes, REQUIREMENTS_NAME: requirements_text(manifest).encode("utf8")}
    archive = destination / (manifest["character_id"] + "-" + manifest["version"] + ".zip")
    temporary = archive.with_suffix(".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
            for relative in PACKAGE_FILES:
                info = zipfile.ZipInfo(folder + relative, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, content[relative])
        with zipfile.ZipFile(temporary) as bundle:
            if bundle.testzip() is not None or bundle.namelist() != [folder + r for r in PACKAGE_FILES]:
                raise PackageError("NPVM-PACKAGE-001", "ZIP do pacote saiu diferente do esperado")
        temporary.replace(archive)
        (destination / (name + "-REQUIREMENTS.txt")).write_bytes(content[REQUIREMENTS_NAME])
        (destination / (name + "-NEXUS.txt")).write_text(nexus_text(manifest), encoding="utf8")
    except BaseException:
        # A half-written version folder would block the next attempt at the same version.
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {"zip": archive, "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "files": sorted(p.name for p in destination.iterdir())}


def check_mod_copies(manifest: dict) -> None:
    """Refuse an NPV whose archive carries a copy made from a mod file (BUGS 67c).

    The conversion lists every mesh it copied with the origin of the file it copied
    (runtime_npc `embedded_copies`); an NPV built before that list existed cannot prove it."""
    copies = manifest.get("embedded_copies")
    if copies is None:
        raise PackageError("NPVM-PACKAGE-001", "NPV criado antes desta versao: crie o NPV de novo para exportar")
    from_mod = [c.get("source") or c.get("resource") for c in copies if c.get("from_mod")]
    if from_mod:
        raise PackageError("NPVM-PACKAGE-001", "o NPV leva copia de peca de mod: " + ", ".join(from_mod)[:300])


def write_npv(destination: Path, manifest: dict, files: dict) -> dict:
    """ZIP with the NPV's game files and its description, plus the texts for the author's page."""
    if destination.exists():
        raise PackageError("NPVM-PACKAGE-007", "esta versao ja foi exportada; aumente a versao")
    info = NPV_INFO_ROOT + "/" + manifest["character_id"] + "/"
    content = dict(sorted(files.items()))
    content[info + MANIFEST_NAME] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf8")
    content[info + REQUIREMENTS_NAME] = requirements_text(manifest).encode("utf8")
    for relative in content:
        if relative.startswith("/") or ".." in relative.split("/") or "\\" in relative:
            raise PackageError("NPVM-PACKAGE-001", "caminho invalido no NPV: " + relative)
    destination.mkdir(parents=True)
    name = safe_file_name(manifest["display_name"])
    archive = destination / (manifest["character_id"] + "-" + manifest["version"] + ".zip")
    temporary = archive.with_suffix(".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
            for relative, data in content.items():
                info_entry = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
                info_entry.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info_entry, data)
        with zipfile.ZipFile(temporary) as bundle:
            if bundle.testzip() is not None or bundle.namelist() != list(content) or any(
                    hashlib.sha256(bundle.read(r)).digest() != hashlib.sha256(d).digest() for r, d in content.items()):
                raise PackageError("NPVM-PACKAGE-001", "ZIP do NPV saiu diferente do esperado")
        temporary.replace(archive)
        (destination / (name + "-REQUIREMENTS.txt")).write_bytes(content[info + REQUIREMENTS_NAME])
        (destination / (name + "-NEXUS.txt")).write_text(nexus_text(manifest), encoding="utf8")
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {"zip": archive, "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "files": sorted(p.name for p in destination.iterdir())}


def exports_root() -> Path:
    """Documents\\NPVMaker\\exports: outside the game and outside Vortex."""
    override = os.environ.get("NPV_EXPORTS_ROOT")
    if override:
        return Path(override)
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]
    documents = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
    pointer = ctypes.c_wchar_p()
    shell = ctypes.windll.shell32
    if shell.SHGetKnownFolderPath(ctypes.byref(documents), 0, None, ctypes.byref(pointer)) != 0:
        raise PackageError("NPVM-PACKAGE-001", "pasta Documentos indisponivel")
    try:
        return Path(pointer.value) / "NPVMaker" / "exports"
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pointer)


def installed_serial(job: Path):
    """The serialized file the conversion of this NPV read, or None."""
    root = job / "npc/installed-resources"

    def find(path: str):
        if not isinstance(path, str) or not path or path.isdecimal() or ".." in path:
            return None
        serial = Path(str(root.joinpath(*path.replace("/", "\\").split("\\"))) + ".json")
        if serial.is_file() and serial.stat().st_size > 0:
            try:
                return json.loads(serial.read_text(encoding="utf-8-sig"))
            except ValueError:
                return None
        return None
    return find


def material_files(game: Path, build: dict, cli: Path | None, reader=None, plugin: Path | None = None) -> dict:
    """Material chain of the tested NPV (BUGS 68).

    Fast path (performance round 04/10/2026): meshes from the conversion job, references from the archive
    imports, cached for every NPV in data/material-cache. WolvenKit only for a file the fast path cannot read;
    with neither, the draft says the check was skipped."""
    fast, fixes, patches = None, None, None
    if reader is None:
        import archive_imports
        import runtime_resources
        cache = (plugin / "data/material-cache") if plugin is not None else (build["job"] / "npc/material-resources")
        resources = runtime_resources.Resources(game, cli, cache / "files")
        try:
            fast = archive_imports.References(game, resources, cache / "references.json")
        except (OSError, AttributeError, ValueError):
            fast = None
        if fast is None and cli is None:
            return {"files": [], "unresolved": [], "unread": [], "skipped": "WolvenKit nao configurado"}
        reader = material_chain.FastReader(installed_serial(build["job"]), fast,
                                           material_chain.WolvenKitReader(resources))
        fixes, patches = resources.fixes, resources.patches
    try:
        found = material_chain.npv_material_files(reader, build["manifest"], fixes, patches)
    finally:
        if fast is not None:
            try:
                fast.save()
            except OSError:
                pass
    found["slow_reads"] = len(getattr(reader, "fallbacks", []))
    return found


def exported_versions(exports: Path | None, character_id: str | None) -> list[str]:
    """Versions of this NPV whose package folder is still in the exports folder (BUGS 75): EXPORTAR refuses
    them (NPVM-PACKAGE-007), so the window warns before the click."""
    if exports is None or not character_id or not exports.is_dir():
        return []
    prefix = character_id + "-"
    return sorted(folder.name[len(prefix):] for folder in exports.iterdir()
                  if folder.is_dir() and folder.name.startswith(prefix) and VERSION.fullmatch(folder.name[len(prefix):]))


def known_folder(data1: int, data2: int, data3: int, data4: tuple) -> Path | None:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]
    folder = GUID(data1, data2, data3, (ctypes.c_ubyte * 8)(*data4))
    pointer = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(pointer)) != 0:
        return None
    try:
        return Path(pointer.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pointer)


def download_roots() -> list[Path]:
    """Where Nexus downloads land: Vortex's download folder and the user's Downloads folder."""
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Vortex/downloads/cyberpunk2077")
    try:
        downloads = known_folder(0x374DE290, 0x123F, 0x4565, (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
    except (OSError, AttributeError):
        downloads = None
    if downloads is not None:
        roots.append(downloads)
    return [root for root in roots if root.is_dir()]


def download_sources(roots: list[Path], wanted: set[str]) -> dict:
    """archive name (lower case) -> Nexus file name of the downloaded .zip that ships it (BUGS 68).

    A mod extracted by hand has no Vortex record, but the .zip downloaded from Nexus keeps Nexus's name
    "<file name>-<mod id>-<version>-<time>" (measured 04/10/2026: 10 - HEAD - NATURAL-15426-3-0-1720411510.zip
    ships ##_Arkhe_UniversalSkinTone_HEAD_VANILLA_Natural.archive). Only names that parse with a mod id count,
    and an archive found in downloads of different mods gets none. .7z/.rar are not read."""
    found = {}
    if not wanted:
        return {}
    for root in roots:
        for package in sorted(root.glob("*.zip")):
            name, mod_id = parse_vortex_folder(package.stem)
            if mod_id is None:
                continue
            try:
                with zipfile.ZipFile(package) as bundle:
                    names = {Path(entry).name.lower() for entry in bundle.namelist()}
            except (OSError, zipfile.BadZipFile, ValueError):
                continue
            for archive in wanted & names:
                found.setdefault(archive, []).append(package.stem)
    result = {}
    for archive, stems in found.items():
        if len({parse_vortex_folder(stem)[1] for stem in stems}) == 1:
            result[archive] = sorted(stems)[-1]
    return result


def draft(plugin: Path, projects: Path, game: Path, token: str, locator=None, sources: dict | None = None,
          cli: Path | None = None, reader=None, exports: Path | None = None, downloads=None) -> dict:
    """What the export window shows: saved fields and the detected requirements."""
    build = tested_build(plugin, token)
    recipe_bytes = build["recipe"].read_bytes()
    recipe = check_recipe(recipe_bytes)
    project = find_project(projects, hashlib.sha256(recipe_bytes).hexdigest())
    if project is None:
        raise PackageError("NPVM-PACKAGE-001", "o projeto salvo deste NPV nao esta mais na pasta projects")
    meta = read_meta(project)
    materials = material_files(game, build, cli, reader, plugin)
    detected = detect_dependencies(game, build_resources(build["job"], build["manifest"], recipe, materials["files"]),
                                   locator, sources, downloads)
    saved = meta.get("export") or {}
    fields = {"display_name": saved.get("display_name") or recipe.get("name", ""),
              "author": saved.get("author", ""), "version": saved.get("version", "1.0.0"),
              "description": saved.get("description", ""),
              "source_preset": saved.get("source_preset") or {"name": "", "author": "", "url": "",
                                                              "nexus_mod_id": None, "version": ""}}
    return {"format": "npv-maker-export-draft", "schema_version": 1, "token": token, "project_id": project.name[:-9],
            "character_id": meta.get("character_id"), "fields": fields,
            "dependencies": detected["dependencies"], "resource_origin": detected["counts"],
            "unknown_resources": len(detected["unknown"]), "body_strategy": build["manifest"].get("body_strategy"),
            "shared_overrides": detected["shared_overrides"],
            "exported_versions": exported_versions(exports, meta.get("character_id")),
            "material_check": {"files": len(materials["files"]), "unresolved": materials["unresolved"][:50],
                               "unread": materials["unread"][:50], "skipped": materials.get("skipped", ""),
                               "slow_reads": materials.get("slow_reads", 0),
                               "unresolved_paths": (materials.get("unresolved_paths") or [])[:50]},
            "notice": NOTICE, "npv_version": diagnostics.NPV_VERSION}


def export(plugin: Path, projects: Path, token: str, request: dict, saved_draft: dict, root: Path) -> dict:
    """Write the package for one tested NPV. The draft is the one the window showed."""
    if saved_draft.get("token") != token:
        raise PackageError("NPVM-PACKAGE-001", "a deteccao de requisitos e de outro NPV; abra EXPORTAR de novo")
    build = tested_build(plugin, token)
    recipe_bytes = build["recipe"].read_bytes()
    recipe = check_recipe(recipe_bytes)
    project = find_project(projects, hashlib.sha256(recipe_bytes).hexdigest())
    if project is None:
        raise PackageError("NPVM-PACKAGE-001", "o projeto salvo deste NPV nao esta mais na pasta projects")
    fields = clean_fields(request.get("fields"))
    dependencies = merge_dependencies(request.get("dependencies"), saved_draft.get("dependencies") or [])
    meta = read_meta(project)
    character_id = meta.get("character_id") or new_character_id(fields["display_name"])
    strategy = build["manifest"].get("body_strategy") or "legacy"
    try:
        integrations = adapters.clean(request.get("integrations"))
    except adapters.AdapterError as error:
        raise PackageError("NPVM-PACKAGE-001", str(error))
    check_mod_copies(build["manifest"])
    # The NPV ships as built and tested: its default outfit is the one of that build.
    manifest = package_manifest(character_id, fields, dependencies, recipe, recipe_bytes, strategy,
                                saved_draft.get("resource_origin") or {}, integrations,
                                underwear_field(build["manifest"].get("underwear")))
    manifest["package_type"] = NPV_PACKAGE_TYPE
    manifest["recipe"] = {"project_sha256": manifest["recipe"]["project_sha256"], "body_strategy": strategy}
    manifest["record_id"] = build["manifest"]["record_id"]
    manifest["kept_morphtargets"] = build["manifest"].get("kept_morphtargets") or []
    manifest["runtime_morphs"] = build["manifest"].get("runtime_morphs") or []
    manifest["shared_overrides"] = [{"name": s["name"], "nexus_mod_id": s.get("nexus_mod_id")}
                                    for s in saved_draft.get("shared_overrides") or []]
    try:
        files = runtime_import.npv_files(build["manifest"], integrations,
                                         {"character_id": character_id, "display_name": fields["display_name"],
                                          "author": fields["author"]})
    except (ValueError, OSError) as error:
        raise PackageError("NPVM-PACKAGE-001", "arquivos do NPV testado indisponiveis: " + str(error)[:200])
    manifest["files"] = {relative: hashlib.sha256(data).hexdigest() for relative, data in sorted(files.items())}
    written = write_npv(root / (character_id + "-" + fields["version"]), manifest, files)
    meta = {"format": "npv-maker-project-meta", "schema_version": 1, "character_id": character_id,
            "created_at": meta.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "export": {k: fields[k] for k in ("display_name", "author", "version", "description", "source_preset")},
            "exports": (meta.get("exports") or []) + [{"version": fields["version"], "zip_sha256": written["zip_sha256"],
                                                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}]}
    write_meta(project, meta)
    return {"character_id": character_id, "manifest": manifest, "folder": written["zip"].parent,
            "zip": written["zip"], "zip_sha256": written["zip_sha256"], "files": written["files"]}


def read_package(folder: Path) -> tuple[dict, bytes]:
    """An installed package folder: its manifest, checked, and the recipe bytes."""
    manifest_file = folder / MANIFEST_NAME
    if not manifest_file.is_file() or manifest_file.stat().st_size > 1024 * 1024:
        raise PackageError("NPVM-PACKAGE-006", "npv-package.json ausente ou grande demais")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        raise PackageError("NPVM-PACKAGE-006", "npv-package.json ilegivel: " + str(error))
    if (manifest.get("package_type") != PACKAGE_TYPE or manifest.get("format_version") != FORMAT_VERSION
            or manifest.get("requires_npvmaker") is not True):
        raise PackageError("NPVM-PACKAGE-006", "nao e um pacote NPV do NPV Maker (formato 1)")
    if manifest.get("character_id") != folder.name or not CHARACTER_ID.fullmatch(folder.name):
        raise PackageError("NPVM-PACKAGE-006", "character_id nao confere com a pasta do pacote")
    if version_tuple(manifest.get("minimum_npvmaker_version", "0")) > version_tuple(diagnostics.NPV_VERSION):
        raise PackageError("NPVM-PACKAGE-006", "pede NPV Maker " + str(manifest.get("minimum_npvmaker_version")))
    if not isinstance(manifest.get("display_name"), str) or not manifest["display_name"].strip():
        raise PackageError("NPVM-PACKAGE-006", "pacote sem nome")
    recipe_info = manifest.get("recipe") or {}
    if recipe_info.get("project") != RECIPE_NAME:
        raise PackageError("NPVM-PACKAGE-006", "receita fora do lugar esperado")
    recipe_file = folder / RECIPE_NAME
    if not recipe_file.is_file() or recipe_file.stat().st_size > 1024 * 1024:
        raise PackageError("NPVM-PACKAGE-006", "receita ausente ou grande demais")
    recipe_bytes = recipe_file.read_bytes()
    if hashlib.sha256(recipe_bytes).hexdigest() != recipe_info.get("project_sha256"):
        raise PackageError("NPVM-PACKAGE-006", "receita diferente da registrada no pacote")
    if not isinstance(manifest.get("dependencies"), list):
        raise PackageError("NPVM-PACKAGE-006", "lista de requisitos ausente")
    return manifest, recipe_bytes


def scan_packages(plugin: Path) -> list[dict]:
    """What the packages window lists; nothing is converted until the player clicks."""
    root = plugin / "packages"
    installed = {}
    for receipt in sorted((plugin / "data/imports").glob("*.json")) if (plugin / "data/imports").is_dir() else []:
        try:
            data = json.loads(receipt.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        if data.get("character_id"):
            installed[data["character_id"]] = data
    listing = []
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if not folder.is_dir():
            continue
        entry = {"character_id": folder.name, "display_name": folder.name, "version": "", "author": "",
                 "state": "invalid", "problem": ""}
        try:
            manifest, _ = read_package(folder)
            entry.update(display_name=manifest["display_name"], version=str(manifest.get("version", "")),
                         author=str(manifest.get("author", "")),
                         dependencies=len(manifest["dependencies"]))
            receipt = installed.get(folder.name)
            if receipt is None:
                entry["state"] = "available"
            elif receipt.get("package_version") == entry["version"]:
                entry["state"] = "installed"
            else:
                entry["state"] = "other_version"
                entry["installed_version"] = receipt.get("package_version", "")
        except (PackageError, OSError) as error:
            entry["problem"] = str(error)[:200]
        listing.append(entry)
    return listing


def check_requirements(manifest: dict, locator) -> list[dict]:
    """Per requirement: ok, missing, other_archive (served by another file) or unchecked (no
    measured resources, e.g. added by the author). A path the game also ships must still be
    served by a mod: the vanilla copy would rebuild another look."""
    results = []
    for dependency in manifest["dependencies"]:
        resources = dependency.get("resources") or []
        state, detail = "ok", []
        if not resources:
            state = "unchecked"
        for item in resources:
            key = resource_key(item.get("path") or item.get("hash"))
            if key is None:
                continue
            owners = locator.mod_owners(key)
            framework = locator.framework_owner(key)
            present = bool(owners or framework) if item.get("kind") == "override" else \
                bool(owners or framework or locator.in_base(key))
            if not present:
                state = "missing"
                detail.append(item.get("path") or item.get("hash"))
            elif state == "ok" and dependency.get("archives") and owners and \
                    not set(owners) & set(dependency["archives"]):
                state = "other_archive"
                detail.append(owners[0])
        results.append({"name": dependency["name"], "required": bool(dependency.get("required_for_rebuild", True)),
                        "state": state, "url": dependency.get("url", ""), "detail": detail[:5]})
    return results


def requirement_report(results: list[dict]) -> list[str]:
    mark = {"ok": "v", "missing": "x", "other_archive": "v", "unchecked": "?"}
    lines = []
    for result in results:
        line = mark[result["state"]] + "  " + result["name"]
        if not result["required"]:
            line += " (opcional)"
        if result["state"] == "missing" and result["url"]:
            line += "  " + result["url"]
        elif result["state"] == "other_archive":
            line += "  (servido por " + result["detail"][0] + ")"
        elif result["state"] == "unchecked":
            line += "  (nao conferido)"
        lines.append(line)
    return lines
