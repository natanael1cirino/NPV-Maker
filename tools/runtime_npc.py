"""Compose local NPCs from captured installed appearances, not a character template.

No game/mod binaries are shipped by this module. It reads the player's own
resources on demand and produces an archive for that installation only.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from appearance_catalog import selected_components
from bake_morph_glb import bake, unpack_glb
from companion_expansion import project_info, check_archive, resource_path, run_cli
from export_project import duplicate_choice
from extract_project_apps import archive_xl_material_sources, safe_path
from runtime_resources import (Resources, ResourceMissing, UnreadableResource, cli_run, fix_key, path_hash,
                               archive_hashes)
import tempfile
import contextlib
import threading
import diagnostics
import photomode
import runtime_body
import runtime_head
import perf_trace
from eye_lashes import change_material


SKIN_SUBTONE = re.compile(r"(?P<base>.+__\d{2}_[a-z]{2}_[a-z]+)_\d{2}_[a-z]+(?:_[a-z]+)*")


def cname(value: str) -> dict:
    return {"$type": "CName", "$storage": "string", "$value": value}


def ref(value: str) -> dict:
    return {"DepotPath": {"$type": "ResourcePath", "$storage": "uint64" if value.isdecimal() else "string", "$value": value}, "Flags": "Default"}


def handles(doc: dict) -> dict:
    result = {}
    def walk(value):
        if isinstance(value, dict):
            if "HandleId" in value and "Data" in value:
                result[value["HandleId"]] = value["Data"]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(doc)
    return result


def expanded(value, table: dict, seen=frozenset()):
    """Make a selected appearance independent from other variants' handles."""
    if isinstance(value, dict):
        key = value.get("HandleRefId", value.get("HandleId"))
        if key is not None:
            if key in seen or key not in table:
                raise ValueError("Cyclic or unresolved appearance handle: " + str(key))
            return {"HandleId": "pending", "Data": expanded(table[key], table, seen | {key})}
        return {k: expanded(v, table, seen) for k, v in value.items()}
    if isinstance(value, list):
        return [expanded(v, table, seen) for v in value]
    return value


def npc_render_plane(part: dict) -> None:
    """Draw a captured player component in the NPC's normal render plane.

    The player's arms, nails and some CCXL tattoos carry an animation-driven
    render plane (renderPlane, renderPlaneLeftArm) that the player's anim graph
    sets. MEDIDO EM 26/09/2026 on the NPV "Thai": the arms vanished at a
    distance and the back tattoo showed through the chest, and those were the
    only components with a player plane; vanilla NPC components (judy.app) use
    None. That the plane causes both is a hypothesis until checked in game.
    """
    plane = part.get("renderingPlaneAnimationParam")
    if isinstance(plane, dict) and plane.get("$value") not in (None, "None"):
        plane["$value"] = "None"


def npc_hide_distance(selected: dict) -> None:
    """Give V's parts without their own auto-hide distance the NPV's largest one.

    With 0 the game picks the distance itself; the camera never moves away from
    the player, so V's arms, feet and neck seam come with 0. MEDIDO EM 26/09/2026
    (NPV "Thai", "THAILEND"): the arms vanished at a distance while the body and
    head, captured with 200, stayed; judy.app gives its visible parts 80 to 150
    and keeps 0 only for small face decals. That 0 is the cause is a hypothesis
    until checked in game.
    """
    distances = [part["autoHideDistance"] for part in selected.values()
                 if isinstance(part.get("autoHideDistance"), (int, float))]
    farthest = max(distances, default=0)
    if farthest <= 0:
        return
    for part in selected.values():
        if part.get("autoHideDistance") == 0 and ("mesh" in part or "morphResource" in part):
            part["autoHideDistance"] = farthest


def add_component(selected: dict, key: tuple, part: dict) -> None:
    """Add a captured component; the same identity from two options unites chunks.

    V's body is one component shared by two captured options. Measured on
    t0_000_pwa_base__full (female and male: chunk 0 chest, 1 neckline,
    2 belly, 3 waist, 4 thigh, 5 calf, 6 ankle, 7 foot): body_color keeps
    0-4 visible (0x...ff1f) and lifted_feet keeps 5-7 (0x...ffe0). The player
    shows the whole body, so the visible chunks add up. Replacing one mask
    with the other left generated NPCs without chest, belly and thighs.
    """
    npc_render_plane(part)
    previous = selected.get(key)
    if previous is not None and "chunkMask" in previous and "chunkMask" in part:
        united = int(previous["chunkMask"]) | int(part["chunkMask"])
        part["chunkMask"] = str(united) if isinstance(part["chunkMask"], str) else united
    selected[key] = part


def show_lash_chunks(eye_key: tuple, eye_part: dict, lash_parts: list) -> None:
    """The eye component also shows the chunks the eyelash option draws on V.

    MEDIDO EM 29/09/2026 (item 39, Mako): V draws one mesh twice. The eye
    .app (vanilla he_000__basehead.app and the ArchiveXL copy) hides chunk 0
    (0x...fffe); the eyelash .app (vanilla hel_000__basehead.app and the
    ArchiveXL copy) repeats the same component (name, id, morphtarget, rig)
    showing only chunk 0 (0x...fff9). Chunk 0 is the lashes, 1 the iris,
    2 the wetness. The NPC keeps one component and receives the lash material
    in chunk 0 (eye_lashes.change_material); with the eye mask alone that
    chunk stayed hidden. A lash component on other geometry is not this case
    and changes nothing here.
    """
    for key, part in lash_parts:
        if key != eye_key or "chunkMask" not in part or "chunkMask" not in eye_part:
            continue
        united = int(eye_part["chunkMask"]) | int(part["chunkMask"])
        eye_part["chunkMask"] = str(united) if isinstance(eye_part["chunkMask"], str) else united


def renumber(doc: dict) -> None:
    counter = 0
    def walk(value):
        nonlocal counter
        if isinstance(value, dict):
            if "HandleId" in value:
                counter += 1
                value["HandleId"] = str(counter)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(doc)


def first_choices(options: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep the first active copy of an editor option a mod registered twice.

    Returns the options to use and the later active copies that chose
    something else (reported as NPVM-PROJECT-002). Inactive copies stay; they
    are never applied.
    """
    kept, first, conflicts = [], {}, []
    for option in options:
        key = (option["body_part"], option["name"])
        if option.get("active"):
            if key in first:
                if duplicate_choice(first[key]) != duplicate_choice(option):
                    conflicts.append(option)
                continue
            first[key] = option
        kept.append(option)
    return kept, conflicts


# MEDIDO EM 02/10/2026: the editor's first eyelash choice (index 0) is "male__05_brown_liquorice" (AFT); the
# ArchiveXL eyelash .app is a single template that builds any "<prefix>__NN_<color>" (customization_template).
DEFAULT_LASH = "05_brown_liquorice"


def default_lash(options: list[dict], body: str) -> tuple[list[dict], list[dict]]:
    """An eyelash choice outside the editor's list gets the editor's first choice.

    MEDIDO EM 02/10/2026 (Thai, preset de ACU): eyelash_color came with selected_index 43 of 35 choices and no
    name, and the editor puppet mounted no eyelash component, so the V and her NPV had no lashes. An NPC
    without lashes looks broken; the NPV takes the first choice of the list instead (author decision 02/10/2026).
    Returns the options and the ones that were changed.
    """
    result, changed = [], []
    prefix = "female" if body == "female" else "male"
    for option in options:
        index, count = option.get("selected_index"), option.get("choice_count")
        if (option.get("name") == "eyelash_color" and option.get("active") and option.get("kind") == "appearance"
                and option.get("resource_path") and option.get("selected_name") in ("", "None", None)
                and isinstance(index, int) and isinstance(count, int) and not 0 <= index < count):
            option = dict(option, selected_name=prefix + "__" + DEFAULT_LASH)
            changed.append(option)
        result.append(option)
    return result, changed


# The editor's genital options (vanilla names, kept by genital mods): the genitals switcher and its appearances,
# and the penis/vagina shape and pubic hair options.
GENITAL_OPTION = re.compile(r"genitals(_\d+)?|(penis|vagina)_[a-z0-9_]*", re.I)
COVERING_UNDERWEAR = ("bottom", "full")


def covered_genitals(options: list[dict], underwear: str) -> tuple[list[dict], list[dict]]:
    """With a default outfit that covers the groin, the NPV leaves the genitals out.

    MEDIDO EM 03/10/2026 (AFT no modo foto, roupa padrao "bottom"): the penis went through the boxers on the NPV
    and not on V. V hides them with gameuiCharacterCustomizationGenitalsController, a component of the player
    entity only; on the NPV the underwear is part of the appearance and nothing hides them. Author decision
    03/10/2026: outfit "bottom" or "full" -> no genitals; "none" keeps them. Returns the options and the ones
    made inactive.
    """
    if underwear not in COVERING_UNDERWEAR:
        return options, []
    result, hidden = [], []
    for option in options:
        if option.get("active") and GENITAL_OPTION.fullmatch(str(option.get("name") or "")):
            option = dict(option, active=False)
            hidden.append(option)
        result.append(option)
    return result, hidden


def selected_appearances(project: dict) -> list[dict]:
    result = []
    for option in project["options"]:
        name = option["name"].lower()
        if not option["active"] or option["kind"] != "appearance":
            continue
        # The capture includes first-person/censored alternatives in addition
        # to the visible third-person body. Do not combine mutually exclusive meshes.
        if "fpp" in name or "censored" in name or "photomode" in name or "proxy" in name:
            continue
        path = option.get("resource_path")
        if not path or option["selected_name"] in ("", "None"):
            continue
        # A path the reader cannot use (seen: 'ResourceAsyncRef[ ]' on
        # 23/09/2026) is kept here and decided per option in collect_components.
        result.append(option)
    if not any(x["name"] == "body_color" for x in result):
        raise ValueError("Projeto antigo sem captura do corpo: salve novamente no editor.")
    return result


# The editor's censorship piece (option "underpants", t0_000_base__censored_items.app) is a vanilla-body mesh.
# MEDIDO EM 01/10/2026: no installed body mod ships a refit of it, and on the modded bodies of mako and seila it
# showed through the skin. Author decision 01/10/2026: without a chosen outfit the NPV wears the player's underwear
# items instead, the ones the body selection preview shows. Seen by the author in the body selection preview
# afterwards (01/10/2026, print): on the modded body the bra t1_057 does not cover the breasts (no refit) while the
# panties sit. Author decision (option A): the publisher picks the default outfit in EXPORTAR; full, bottom only
# (the default, also for IMPORTAR NO COMPANION) or none.
UNDERWEAR_MODES = ("bottom", "full", "none")
UNDERWEAR_ITEMS = {
    "female": (("t1", "base\\characters\\appearances\\player\\items\\torso\\t1_underwear_01.app", "basic_01_w"),
               ("l1", "base\\characters\\appearances\\player\\items\\legs\\l1_underwear_01.app", "basic_01_w")),
    # basic_01_m of the torso .app has no components.
    "male": (("l1", "base\\characters\\appearances\\player\\items\\legs\\l1_underwear_01.app", "basic_01_m"),),
}


def default_underwear(options: list[dict], body: str, mode: str = "bottom") -> list[dict]:
    """Replace the editor's censorship underwear with the player's underwear items (`mode`: UNDERWEAR_MODES)."""
    if mode not in UNDERWEAR_MODES:
        raise ValueError("Roupa padrao desconhecida: " + str(mode))
    result = []
    for option in options:
        if option["name"] != "underpants":
            result.append(option)
            continue
        for slot, app, appearance in UNDERWEAR_ITEMS[body]:
            if mode == "none" or (mode == "bottom" and slot != "l1"):
                continue
            result.append(dict(option, name="underpants:" + slot, kind="appearance", resource_path=app,
                               selected_name=appearance))
    return result


def appearance_components(definition: dict) -> list:
    """Components of a selected appearance; an empty appearance adds none.

    Measured in i0_000_base__genitals.app: the female-rig vagina appearances
    (i0_000_pwa_base__vagina__NN_*) have no components, parts or compiled
    data at all; that choice adds no mesh to the body. WolvenKit serializes
    the missing list as null.
    """
    return definition.get("components") or []


class AppearanceNotFound(ValueError):
    """The captured choice does not exist in the option's appearance file."""


CCXL_COLOR = re.compile(r"\d{1,3}_([A-Za-z0-9_]+)")
MESH_COMPONENTS = ("entSkinnedMeshComponent", "entGarmentSkinnedMeshComponent",
                   "entMorphTargetSkinnedMeshComponent")


def resource_ref(reader: Resources, ref, suffix: str) -> str:
    value = str(((ref or {}).get("DepotPath") or {}).get("$value") or "")
    # Some mods reference meshes by hash (seen in CCXL Sub Hair Pack).
    if value.isdecimal():
        return reader.register(value, suffix)
    if not safe_path(value, suffix):
        raise ValueError("Recurso nao resolvido: " + value)
    return value


def component_mesh(reader: Resources, part: dict) -> str:
    if part.get("$type") == "entMorphTargetSkinnedMeshComponent":
        morph = resource_ref(reader, part.get("morphResource"), ".morphtarget")
        return resource_ref(reader, reader.read(morph)["Data"]["RootChunk"]["baseMesh"], ".mesh")
    return resource_ref(reader, part.get("mesh"), ".mesh")


def speculating(reader):
    """Reads made only to look ahead: they must not count as reads of the conversion (Resources.speculation)."""
    return reader.speculation() if hasattr(reader, "speculation") else contextlib.nullcontext()


def read_ahead(reader, resources: list) -> None:
    """Batch read of files the next steps read one by one (Resources.prefetch); a reader without it
    (tests) reads as before."""
    prefetch = getattr(reader, "prefetch", None)
    if prefetch is not None and resources:
        prefetch(list(resources))


def mesh_patches(reader, mesh: str) -> list[str]:
    patches = getattr(reader, "patches", {})
    source = getattr(reader, "source", lambda path: path)
    return [p for key in dict.fromkeys((mesh.lower(), source(mesh).lower())) for p in patches.get(key, [])]


def read_ahead_parts(reader, parts: list, with_patches: bool = False) -> None:
    """Read ahead the files component_mesh (and mesh_colors) read for these parts: morphtargets and
    meshes first, then the base meshes the morphtargets name. Errors are left to the reads that follow."""
    if getattr(reader, "prefetch", None) is None:
        return
    first, morphs = [], []
    for part in parts:
        if part.get("$type") not in MESH_COMPONENTS:
            continue
        try:
            if part.get("$type") == "entMorphTargetSkinnedMeshComponent":
                first.append(resource_ref(reader, part.get("morphResource"), ".morphtarget"))
                morphs.append(part)
            else:
                mesh = resource_ref(reader, part.get("mesh"), ".mesh")
                first += [mesh] + (mesh_patches(reader, mesh) if with_patches else [])
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    read_ahead(reader, first)
    second = []
    with speculating(reader):
        for part in morphs:
            try:
                mesh = component_mesh(reader, part)
                second += [mesh] + (mesh_patches(reader, mesh) if with_patches else [])
            except (ValueError, KeyError, TypeError, AttributeError, OSError):
                continue
    read_ahead(reader, second)


def entity_rigs(reader, entity_source: str) -> list[str]:
    """The rigs entity_body_bones reads (body skeletons of the base entity)."""
    rigs = []

    def walk(node):
        if isinstance(node, dict):
            setup = ((node.get("facialSetup") or {}).get("DepotPath") or {}).get("$value")
            if node.get("$type") == "entAnimatedComponent" and setup in (None, "", "0") and node.get("rig"):
                try:
                    rigs.append(resource_ref(reader, node["rig"], ".rig"))
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    try:
        with speculating(reader):
            walk(reader.read(entity_source))
    except (ValueError, KeyError, OSError):
        return []
    return rigs


FIELD_SUFFIX = {"mesh": ".mesh", "morphResource": ".morphtarget", "rig": ".rig"}


def ref_key(reader, value, suffix: str) -> str | None:
    """The cache key the converter uses for a depot reference (path, or registered hash), None if unusable."""
    value = str(value or "")
    if not value or value == "0":
        return None
    try:
        if value.isdecimal():
            return reader.register(value, suffix)
        return value if safe_path(value, suffix) else None
    except ValueError:
        return None


def component_refs(reader, part: dict) -> list[str]:
    keys = []
    for field, suffix in FIELD_SUFFIX.items():
        value = ((part.get(field) or {}).get("DepotPath") or {}).get("$value") if isinstance(part.get(field), dict) else None
        key = ref_key(reader, value, suffix)
        if key:
            keys.append(key)
    return keys


def appearance_refs(reader, doc: dict, names: set) -> list[str]:
    """References of the components of the named appearances of an .app (all of a one-appearance CCXL app)."""
    definitions = [x.get("Data") or {} for x in doc["Data"]["RootChunk"].get("appearances") or []]
    chosen = [d for d in definitions if (d.get("name") or {}).get("$value") in names]
    if not chosen and len(definitions) == 1:
        chosen = definitions
    table, keys = handles(doc), []
    for definition in chosen:
        for item in appearance_components(definition):
            keys += component_refs(reader, expanded(item, table))
    return keys


def read_ahead_closure(reader, project: dict, options: list[dict], wanted: list[str], entity_source: str,
                       runtime: bool) -> None:
    """Extract and serialize, in a few batches, what the conversion reads later one level at a time: the
    .app files, the components of the chosen appearances (meshes, morphtargets, rigs), the files the editor
    puppet loaded (Runtime Manifest, under the key its .app uses), base meshes of morphtargets, ArchiveXL list
    patches, rigs of the base entity and the photo mode templates. Pure cache: every decision stays with the
    reads that follow, which find the same files ready."""
    if getattr(reader, "prefetch", None) is None:
        return
    rows = (runtime_body.manifest(project)[0] or []) if runtime else []
    chosen = {}
    for option in options:
        chosen.setdefault(option.get("resource_path", "").lower(), set()).add(option.get("selected_name"))
    owners = {}
    for row in rows:
        owners.setdefault(str(row.get("owner_app") or "").lower(), []).append(row)
    batch = list(wanted)
    for row in rows:
        suffix = ".morphtarget" if row["field"] == "morphResource" else ".mesh"
        path = row.get("path") or ""
        batch.append(path if path and not path.isdecimal() and ref_key(reader, path, suffix) else
                     ref_key(reader, row.get("hash"), suffix))
    template = photomode.TEMPLATES.get(project.get("body"))
    if template:
        batch += [template, photomode.ATLAS_TEMPLATE]
    patches = getattr(reader, "patches", {})
    known = set()
    for _ in range(5):
        batch = [b for b in dict.fromkeys(batch) if b and b not in known]
        if not batch:
            break
        known.update(batch)
        read_ahead(reader, batch)
        found = []
        for resource in batch:
            try:
                if not reader.serial_ok(reader.path(reader.source(resource))):
                    continue
                with speculating(reader):
                    doc = reader.read(resource)
            except (ValueError, KeyError, TypeError, OSError, AttributeError):
                continue
            kind = reader.hash_types.get(resource) or Path(resource).suffix.lower()
            try:
                found += patches.get(resource.lower(), []) + patches.get(reader.source(resource).lower(), [])
                if kind == ".app":
                    found += appearance_refs(reader, doc, chosen.get(resource.lower(), set()) |
                                             {row.get("owner_appearance") for row in owners.get(resource.lower(), [])})
                    for patch in patches.get(resource.lower(), []):
                        found.append(patch)
                elif kind == ".morphtarget":
                    found.append(ref_key(reader, doc["Data"]["RootChunk"]["baseMesh"]["DepotPath"]["$value"], ".mesh"))
                elif kind == ".ent":
                    if resource == entity_source:
                        found += entity_rigs(reader, entity_source)
                    elif resource == template:
                        found.append(photomode.template_app_path(doc))
            except (ValueError, KeyError, TypeError, AttributeError, IndexError):
                continue
        batch = found


def read_ahead_runtime(reader, project: dict, entity_source: str) -> None:
    """Read ahead, in two batches, the files the conversion reads later in waves: every morphtarget and mesh
    the editor puppet loaded (Runtime Manifest, same path or hash the .app names), the base entity rigs and
    the photo mode templates; then the base meshes of those morphtargets, the ArchiveXL list patches of the
    meshes and the photo mode .app. Pure cache: nothing is decided here."""
    if getattr(reader, "prefetch", None) is None:
        return
    components, _ = runtime_body.manifest(project)
    first = []
    for component in components or []:
        suffix = ".morphtarget" if component["field"] == "morphResource" else ".mesh"
        path = component.get("path") or ""
        try:
            if path and not path.isdecimal() and safe_path(path, suffix):
                first.append(path)
            elif component.get("hash"):
                first.append(reader.register(component["hash"], suffix))
        except ValueError:
            continue
    first += entity_rigs(reader, entity_source)
    template = photomode.TEMPLATES.get(project.get("body"))
    if template:
        first += [template, photomode.ATLAS_TEMPLATE]
    read_ahead(reader, first)
    second = []
    for resource in dict.fromkeys(first):
        try:
            if resource.endswith(".morphtarget") or reader.hash_types.get(resource) == ".morphtarget":
                base = resource_ref(reader, reader.read(resource)["Data"]["RootChunk"]["baseMesh"], ".mesh")
                second += [base] + mesh_patches(reader, base)
            elif resource.endswith(".mesh") or reader.hash_types.get(resource) == ".mesh":
                second += mesh_patches(reader, resource)
        except (ValueError, KeyError, TypeError, OSError, AttributeError):
            continue
    if template:
        try:
            second.append(photomode.template_app_path(reader.read(template)))
        except (ValueError, KeyError, TypeError, OSError, IndexError, AttributeError):
            pass
    read_ahead(reader, second)


def write_all(reader, items: list) -> None:
    """Write generated files with one WolvenKit call; the first failure raises as write_binary did."""
    writer = getattr(reader, "write_binaries", None)
    if writer is None:
        for doc, destination in items:
            reader.write_binary(doc, destination)
        return
    for error in writer(items):
        if error is not None:
            raise error


def mesh_colors(reader: Resources, mesh: str) -> tuple[set, bool]:
    """Appearance names a mesh offers, and whether ArchiveXL resolves any name.

    Meshes with an `@context` material (ArchiveXL dynamic materials; measured
    in Hair Collection 3 and Veegee Alicia) or a `*` appearance build the
    requested color in game, so the color need not be a listed appearance.
    List-form ArchiveXL patches add the patch mesh appearances.
    """
    root = reader.read(mesh)["Data"]["RootChunk"]
    names = {a["Data"]["name"]["$value"] for a in root.get("appearances") or []}
    materials = {(e.get("name") or {}).get("$value") for e in root.get("materialEntries") or []}
    dynamic = "@context" in materials or any(n.startswith("*") for n in names)
    source = getattr(reader, "source", lambda path: path)
    patches = getattr(reader, "patches", {})
    keys = {mesh.lower(), source(mesh).lower()}
    for patch in {p for key in keys for p in patches.get(key, [])}:
        more, more_dynamic = mesh_colors(reader, patch)
        names |= more
        dynamic = dynamic or more_dynamic
    return names, dynamic


def ccxl_color(reader: Resources, template: dict, option: str, name: str):
    """ArchiveXL character customization color on a one-appearance app.

    CCXL apps (hair, eyebrows) keep a single template appearance and the
    editor choice NN_<color> selects the mesh appearance <color>. Recognized
    by that shape, not by the option name: Raven (sb_raven_pma), Phoenicia
    and CCXL eyebrows have no "hair" in the option name. A piece whose mesh
    lacks the color keeps its captured appearance (hair shadow, Sub Hair
    Pack clips "*_prop" with appearance "standard"); the manifest lists it.
    If no piece takes the color the choice is not supported and fails.
    """
    color = CCXL_COLOR.fullmatch(name)
    if not color:
        return None
    match = copy.deepcopy(template)
    recolored, kept, notes = 0, [], []
    read_ahead_parts(reader, [raw.get("Data", raw) for raw in appearance_components(match)
                              if "meshAppearance" in raw.get("Data", raw)], with_patches=True)
    for raw in appearance_components(match):
        part = raw.get("Data", raw)
        if part.get("$type") not in MESH_COMPONENTS or "meshAppearance" not in part:
            continue
        try:
            names, dynamic = mesh_colors(reader, component_mesh(reader, part))
        except (ResourceMissing, UnreadableResource) as error:
            notes.append(error)
            # The mod references a mesh it does not ship (measured: every
            # Hair Collection 3 style lists raenef\<style>\meshes\
            # hair_shadow.mesh, absent from its archive). In game that piece
            # draws nothing on V either; keep it as captured.
            names, dynamic = set(), False
        if dynamic or color[1] in names:
            part["meshAppearance"] = cname(color[1])
            recolored += 1
        else:
            kept.append(part.get("name", {}).get("$value", "") + "=" + part["meshAppearance"]["$value"])
    if not recolored:
        raise AppearanceNotFound("Cor " + color[1] + " ausente em todas as malhas de " + option + "/" + name)
    if kept:
        match["_npv_kept"] = kept
    if notes:
        match["_npv_notes"] = notes
    return match


CUSTOMIZATION_SCOPE = "player_customization.app"


def customization_template(definitions: list[dict], name: str) -> dict | None:
    """The appearance ArchiveXL creates in game for a name the .app lacks.

    Same rules as ArchiveXL CustomizationExtension::FixCustomizationAppearance
    (read in its source, 28/09/2026), for .app files of the player
    customization scope: a name "NN_x" uses appearance [1] (or [0] when it
    is the only one) and mesh appearance "x"; a name "a__b" uses the only
    appearance or the first whose name starts with "a", and mesh appearance
    "b" without "NN_"; any other name uses [1] (or [0]) and mesh appearance
    the whole name. The mesh appearance goes to the skinned and morph
    components whose appearance is not "default". MEDIDO no puppet do mesmo
    projeto: Soft Natural Eyelashes "black_carbon" (one appearance) and Dream
    Galaxy Eyes "protoss_dg13" (template [1] "he_000_pwa__basehead__mod").
    Returns None when the rules give no template (ArchiveXL does nothing).
    """
    if not definitions or len(name) < 3:
        return None
    single = definitions[0] if len(definitions) == 1 else None
    default_source = definitions[1] if len(definitions) > 1 else definitions[0]
    mesh, source, rule = name, None, "whole_name"
    if name[2] == "_" and name[0].isdigit():
        mesh, source, rule = name[3:], default_source, "numbered"
    else:
        cut = name.rfind("__")
        if cut != -1:
            source = single or next((d for d in definitions if d["name"]["$value"][:cut] == name[:cut]), None)
            mesh, rule = name[cut + 2:], "prefixed"
            if len(mesh) < 3:
                return None
            if mesh[2] == "_" and mesh[0].isdigit():
                mesh = mesh[3:]
        source = source or default_source
    overrides = ((source.get("partsOverrides") or [{}])[0] or {}).get("componentsOverrides") or []
    targets = None
    if len(source.get("partsOverrides") or []) == 1 and len(overrides) == 1 \
            and not (overrides[0].get("componentName") or {}).get("$value"):
        # ArchiveXL keeps an appearance it already fixed as it is.
        mesh = (overrides[0].get("meshAppearance") or {}).get("$value") or mesh
        rule = "fixed"
    elif overrides:
        targets = [(o.get("componentName") or {}).get("$value") for o in overrides]
        targets = None if not all(targets) else targets
    created = copy.deepcopy(source)
    created["name"] = dict(created["name"], **{"$value": name})
    created["_npv_template"] = dict(template=source["name"]["$value"], rule=rule, mesh_appearance=mesh,
                                    components=targets)
    return created


def apply_template(reader, components: list[dict], template: dict, observed) -> dict:
    """Give the components of an appearance created from a template the mesh
    appearance ArchiveXL sets (FixCustomizationComponents: skinned and morph
    components whose appearance is not "default"), then compare with what the
    editor puppet showed for that option. Where they differ the observed file
    or mesh appearance is used and the difference is reported, never hidden.
    """
    mesh, targets, changed = template["mesh_appearance"], template["components"], []
    for part in components:
        name = part.get("name", {}).get("$value")
        current = (part.get("meshAppearance") or {}).get("$value")
        if part.get("$type") not in MESH_COMPONENTS or (targets is not None and name not in targets) \
                or current in (None, "", "None", "default"):
            continue
        part["meshAppearance"] = dict(part["meshAppearance"], **{"$value": mesh})
        changed.append(name)
    record = dict(template=template["template"], rule=template["rule"], mesh_appearance=mesh, components=changed,
                  runtime="sem evidencia", divergences=[])
    rows = {row["name"]: row for row in observed or []}
    if not rows:
        return record
    names = set()
    for part in components:
        name = part.get("name", {}).get("$value")
        names.add(name)
        row = rows.get(name)
        if row is None or part.get("$type") not in MESH_COMPONENTS:
            continue
        seen, now = row.get("mesh_appearance"), (part.get("meshAppearance") or {}).get("$value")
        if seen not in (None, "", "None") and now is not None and seen != now:
            record["divergences"].append(name + ": malha prevista " + str(now) + ", editor " + seen)
            part["meshAppearance"] = dict(part["meshAppearance"], **{"$value": seen})
        geometry = runtime_body._geometry(part)
        if row.get("hash") and geometry and runtime_body._hash(geometry, path_hash) != row["hash"]:
            record["divergences"].append(name + ": arquivo previsto " + geometry + ", editor "
                                         + str(row.get("path") or row["hash"]))
            runtime_body._set_resource(part, row, reader.register, safe_path, path_hash)
    outside = sorted(set(rows) - names)
    if outside:
        record["divergences"].append("editor mostrou pecas fora do modelo: " + ", ".join(outside))
    record["runtime"] = "diverge" if record["divergences"] else "confere"
    return record


def read_selection(reader: Resources, option: dict, redirects: dict) -> tuple[dict, dict]:
    resource, name = option["resource_path"], option["selected_name"]
    doc = reader.read(resource)
    own_doc = doc
    definitions = doc["Data"]["RootChunk"]["appearances"]
    match = next((x["Data"] for x in definitions if x["Data"]["name"]["$value"] == name), None)
    if match is None and resource in redirects:
        doc = reader.read(redirects[resource])
        match = next((x["Data"] for x in doc["Data"]["RootChunk"]["appearances"]
                      if x["Data"]["name"]["$value"] == name), None)
    if match is None and len(definitions) == 1:
        match = ccxl_color(reader, definitions[0]["Data"], option["name"], name)
    if match is None:
        # The editor appends the skin subtone to every body part, but some
        # installed apps only define the base tone for a part (measured in
        # i0_000_base__genitals.app: pwa vagina has 03_ca_senna and no
        # 03_ca_senna_01_honey, while pma vagina has the subtones). V still
        # renders there, so fall back to the base tone of the same app; the
        # manifest records the name used.
        tone = SKIN_SUBTONE.fullmatch(name)
        if tone:
            match = next((x["Data"] for x in doc["Data"]["RootChunk"]["appearances"]
                          if x["Data"]["name"]["$value"] == tone["base"]), None)
    in_scope = getattr(reader, "in_scope", None)
    if match is None and in_scope is not None and in_scope(CUSTOMIZATION_SCOPE, resource):
        # Last step, only where the path above found nothing: the appearance
        # ArchiveXL creates in game from the .app template (mechanism 2,
        # docs/MECANISMO2-MAPA.md).
        match = customization_template([x["Data"] for x in definitions], name)
        doc = own_doc if match is not None else doc
    if match is None:
        raise AppearanceNotFound("Aparencia nao encontrada: " + option["name"] + "/" + name)
    return doc, match


def drawable(reader, part: dict) -> bool:
    """False for a mesh component whose file no mounted archive ships: the
    game adds it and draws nothing. A reader that cannot tell keeps it."""
    morph = part.get("$type") == "entMorphTargetSkinnedMeshComponent"
    value = str((((part.get("morphResource") if morph else part.get("mesh")) or {}).get("DepotPath") or {})
                .get("$value") or "")
    if part.get("$type") not in MESH_COMPONENTS:
        return True
    if value in ("", "0"):
        return False
    owners, base_owner = getattr(reader, "owners", None), getattr(reader, "base_owner", None)
    if owners is None or base_owner is None:
        return True
    key = reader.register(value, ".morphtarget" if morph else ".mesh") if value.isdecimal() \
        else getattr(reader, "source", lambda path: path)(value)
    return bool(owners(key)) or base_owner(key) is not None


def app_patch_components(reader, resources: list[str], appearance: str) -> tuple[list, list, list]:
    """Components ArchiveXL puts in `appearance` of an .app through list-form
    `resource: patch`, as its ResourcePatch extension does in game
    (PatchPackageResults, MergeComponents): the patch appearance of the same
    name, else the patch appearance without a name, gives its components; one
    with the name and id of a component already there replaces it, the others
    are added. MEDIDO EM 28/09/2026 (NPV Probe 0.2, "mariko 3.0"): the editor
    puppet drew Nim_Head_Bits_02..05 from the patch of Nim's More Everything
    on h0_000__basehead_d04.app, with meshes of Sedth Cyber Jaw; the NPV,
    built from the .app alone, had holes under the chin and beside the mouth.
    Slots whose mesh no archive ships (Nim_Head_Bits_01, 06..10 there) draw
    nothing in game: they are returned with drawn=False.
    Returns ([(patch, component, drawn)], [(patch, error)]).
    """
    patches = getattr(reader, "patches", {})
    found, errors, seen = [], [], []
    for resource in resources:
        for patch in patches.get(resource.lower(), []):
            if patch.lower() in seen:
                continue
            seen.append(patch.lower())
            try:
                doc = reader.read(patch)
                definitions = [x["Data"] for x in doc["Data"]["RootChunk"].get("appearances") or []]
                match = next((d for d in definitions if d["name"]["$value"] == appearance), None) or \
                    next((d for d in definitions if d["name"]["$value"] in ("", "None")), None)
                if match is None:
                    continue
                table = handles(doc)
                parts = [expanded(item, table) for item in appearance_components(match)]
                found += [(patch, part, drawable(reader, part)) for part in parts]
            except (ValueError, KeyError, TypeError) as error:
                errors.append((patch, error))
    return found, errors


def merge_patch_components(components: list[dict], found: list) -> dict:
    """Apply app_patch_components to an appearance's components in place."""
    added, replaced, removed, empty = [], [], [], []
    for patch, part, drawn in found:
        name = part.get("name", {}).get("$value")
        same = next((i for i, c in enumerate(components)
                     if c.get("name", {}).get("$value") == name and c.get("id") == part.get("id")), None)
        if same is None and drawn:
            components.append(part)
            added.append(name)
        elif same is None:
            empty.append(name)
        elif drawn:
            components[same] = part
            replaced.append(name)
        else:
            del components[same]
            removed.append(name)
    patches = sorted({patch for patch, _, _ in found})
    return {key: value for key, value in (("patches", patches), ("added", added), ("replaced", replaced),
                                          ("removed", removed), ("without_mesh", empty)) if value}


ESSENTIAL_OPTION = re.compile(r"(body_color|skin_type_\d+|tpp_head_face_rig|h_default_arms_colors_tpp|"
                              r"lifted_feet|teeth|eyes_color)")


def option_diagnostic(reader, option: dict, error: Exception, essential: bool, character: str, redact) -> dict:
    """Map a failed option to its stable diagnostic code."""
    tool = tool_version = ""
    source = None
    resource = option.get("resource_path") or ""
    if isinstance(error, UnreadableResource):
        code = "NPVM-WK-APP-002" if essential else "NPVM-WK-APP-001"
        resource, tool = error.resource, "WolvenKit"
        tool_version = reader.tool_version() if hasattr(reader, "tool_version") else ""
        mods = reader.provider(error.resource) if hasattr(reader, "provider") else []
        source = ", ".join(mods) if mods else None
    elif isinstance(error, ResourceMissing):
        code = "NPVM-RESOURCE-002" if essential else "NPVM-RESOURCE-001"
    elif isinstance(error, AppearanceNotFound):
        code = "NPVM-APPEAR-002" if essential else "NPVM-APPEAR-001"
    else:
        code = "NPVM-CONVERT-002" if essential else "NPVM-CONVERT-001"
    return diagnostics.make(code, character=character, option=option["name"],
                            body_part=option.get("body_part", ""), selection=option.get("selected_name", ""),
                            resource=resource, source_mod=source, tool=tool, tool_version=tool_version,
                            technical_error=type(error).__name__ + ": " + str(error),
                            action="stopped" if essential else "skipped",
                            result="failed" if essential else "continued", redact=redact)


def tell(progress, text: str) -> None:
    """A step for the activity log, without changing the message (author request 05/10/2026)."""
    try:
        progress(text, detail=True)
    except TypeError:
        pass  # a progress that takes only the message (tests, older callers)


def collect_components(reader: Resources, options: list[dict], redirects: dict,
                       character: str = "", redact=None, step=None) -> dict:
    """Resolve every captured option into components, all or nothing per option.

    Body and head options are required: without them the NPC is broken, so
    their failure stops the import. Any other option (hair, brows, makeup,
    cyberware, piercings, tattoos, mostly from mods) that cannot be resolved
    is left out and listed in `skipped`, so one broken mod piece (measured:
    Ruth offers nd_hair_ruth_cyberware.app, which no archive contains) does
    not block the character. Decided with the author on 26/09/2026.
    """
    selected, used_options, skipped, notes = {}, [], [], []
    lash_material, eye_part, eye_key, app_doc = None, None, None, None
    lash_parts, lash_option = [], None
    for option in options:
        template = None
        try:
            doc, current = read_selection(reader, option, redirects)
            table = handles(doc)
            parts, lash, eye, lash_found = [], None, None, []
            components = [expanded(item, table) for item in appearance_components(current)]
            loaded = [option["resource_path"]] + ([redirects[option["resource_path"]]]
                                                  if option["resource_path"] in redirects else [])
            found, patch_errors = app_patch_components(reader, loaded, current["name"]["$value"])
            patch_record = merge_patch_components(components, found)
            # An option read from the origin the puppet showed (runtime_head)
            # takes the file and mesh appearance the editor used.
            observed = {row["name"]: row for row in option.get("runtime_components") or []}
            for part in components:
                row = observed.get(part.get("name", {}).get("$value"))
                if row is None:
                    continue
                if part.get("$type") in MESH_COMPONENTS and row.get("hash"):
                    runtime_body._set_resource(part, row, reader.register, safe_path, path_hash)
                if row.get("mesh_appearance") not in (None, "", "None") and "meshAppearance" in part:
                    part["meshAppearance"] = dict(part["meshAppearance"], **{"$value": row["mesh_appearance"]})
            template = current.pop("_npv_template", None)
            if template is not None:
                template_record = apply_template(reader, components, template, option.get("runtime_observed"))
            for part in components:
                name = part.get("name", {}).get("$value")
                if not name:
                    raise ValueError("Appearance component has no name")
                geometry = part.get("morphResource", part.get("mesh", {})).get("DepotPath", {}).get("$value", "")
                # Different pieces can share both their label and component ID.
                # Keep distinct geometry/rig components; only exact identities replace.
                key = (name, part["$type"], part.get("id"), geometry,
                       part.get("rig", {}).get("DepotPath", {}).get("$value", ""))
                if option["name"] == "eyelash_color":
                    lash = part.get("meshAppearance", {}).get("$value")
                    lash_found.append((key, part))
                    continue
                parts.append((key, part))
                if option["name"] == "eyes_color" and geometry:
                    eye = (key, part)
        except (ValueError, KeyError, TypeError) as error:
            essential = bool(ESSENTIAL_OPTION.fullmatch(option["name"]))
            record = option_diagnostic(reader, option, error, essential, character, redact)
            if essential:
                raise diagnostics.DiagnosticError(record) from error
            notes.append(record)
            skipped.append({"name": option["name"], "selected_name": option["selected_name"],
                            "resource": option["resource_path"], "code": record["code"],
                            "reason": record["technical_error"][:300]})
            continue
        if app_doc is None:
            app_doc = copy.deepcopy(doc)
        for key, part in parts:
            add_component(selected, key, part)
        lash_material = lash if lash is not None else lash_material
        lash_parts = lash_found if lash is not None else lash_parts
        lash_option = option if lash is not None else lash_option
        if eye is not None:
            eye_key, eye_part = eye
        used = {"name": option["name"], "selected_name": option["selected_name"],
                "resource": option["resource_path"]}
        context = dict(character=character, option=option["name"], body_part=option.get("body_part", ""),
                       selection=option["selected_name"], resource=option["resource_path"], redact=redact)
        if patch_record:
            used["archivexl_patch"] = patch_record
        if option.get("runtime_origin"):
            used["runtime_origin"] = option["runtime_origin"]
        if template is not None:
            used["archivexl_template"] = template_record
            notes.append(diagnostics.make(
                "NPVM-TEMPLATE-001", action="archivexl_template", result="continued",
                technical_error="modelo " + template_record["template"] + ", aparencia da malha "
                                + template_record["mesh_appearance"] + ", editor: " + template_record["runtime"],
                **context))
            if template_record["divergences"]:
                notes.append(diagnostics.make(
                    "NPVM-TEMPLATE-002", action="runtime_preferred", result="continued",
                    technical_error="; ".join(template_record["divergences"])[:600], **context))
        for patch, error in patch_errors:
            notes.append(diagnostics.make("NPVM-PATCH-001", action="skipped", result="continued",
                                          technical_error=type(error).__name__ + ": " + str(error),
                                          **dict(context, resource=patch)))
        if current["name"]["$value"] != option["selected_name"]:
            used["resolved_name"] = current["name"]["$value"]
            if SKIN_SUBTONE.fullmatch(option["selected_name"]):
                notes.append(diagnostics.make("NPVM-APPEAR-003", action="base_tone", result="continued",
                                              technical_error="usado " + current["name"]["$value"], **context))
        if current.get("_npv_kept"):
            used["kept_appearance"] = current.pop("_npv_kept")
            notes.append(diagnostics.make("NPVM-APPEAR-004", action="kept_captured", result="continued",
                                          technical_error="; ".join(used["kept_appearance"]), **context))
        for error in current.pop("_npv_notes", []):
            unreadable = isinstance(error, UnreadableResource)
            notes.append(diagnostics.make(
                "NPVM-WK-RES-001" if unreadable else "NPVM-RESOURCE-003", action="kept_captured",
                result="continued", tool="WolvenKit" if unreadable else "",
                tool_version=reader.tool_version() if unreadable and hasattr(reader, "tool_version") else "",
                technical_error=type(error).__name__ + ": " + str(error),
                **dict(context, resource=getattr(error, "resource", "") or option["resource_path"])))
        used_options.append(used)
        if step is not None:
            step(option["name"] + ": " + (used.get("resolved_name") or option["selected_name"]))
    eye_mask, eye_lashes, standalone_lashes = None, [], []
    if eye_part is not None:
        eye_mask = eye_part.get("chunkMask")
        eye_lashes = [copy.deepcopy(part) for key, part in lash_parts if key == eye_key]
        show_lash_chunks(eye_key, eye_part, lash_parts)
        # BUGS 79 (05/10/2026): an ArchiveXL template (he_000_pma__basehead__mod) moves the eye to another
        # morphtarget while the lashes stay on the vanilla one; same component, other file. V draws two
        # components (runtime manifest of NPV "teste"), so the lashes become their own component.
        moved = [(key, part) for key, part in lash_parts if key != eye_key and key[:3] == eye_key[:3]]
        if moved and not eye_lashes:
            standalone_lashes = standalone_lash_parts(reader, selected, moved, lash_option, eye_part)
    elif lash_parts:
        standalone_lashes = standalone_lash_parts(reader, selected, lash_parts, lash_option)
        if step is not None:
            for part in (p for _, p in lash_parts):
                step("cilios: componente proprio (" + str((part.get("meshAppearance") or {}).get("$value")) + ")")
    npc_hide_distance(selected)
    return {"selected": selected, "used": used_options, "skipped": skipped, "diagnostics": notes,
            "lash_material": lash_material, "eye_part": eye_part, "app_doc": app_doc,
            "eye_mask": eye_mask, "eye_lashes": eye_lashes, "standalone_lashes": standalone_lashes}


def standalone_lash_parts(reader, selected: dict, lash_parts: list, option: dict | None,
                          eye_part: dict | None = None) -> list[str]:
    """The eyelash components as their own NPC pieces when no eye component came from eyes_color.

    BUGS 78 (05/10/2026): with heterochromia on (Heterochromia Eyes CCXL) eyes_color is off and the eyes are
    other components, so the lashes had no eye to join and the NPV came out without them. V draws them as
    their own component (NPV HETERO, runtime manifest: MorphTargetSkinnedMesh3637 on he_000_pwa__morphs,
    appearance brown_liquorice, chunkMask of the lashes only, from the bundle's hel_000_pwa__basehead.app).
    The component is the one of the eyelash choice; what the editor puppet showed for it (file, mesh
    appearance, chunk mask) is used when the runtime manifest has it. Beside an eye component of the same
    name and id (BUGS 79) the lashes take their own name and id, as lash_component does."""
    rows = {row["name"]: row for row in (option or {}).get("runtime_observed") or []}
    added = []
    for key, part in lash_parts:
        name = part.get("name", {}).get("$value")
        row = rows.get(name)
        if row is not None:
            if part.get("$type") in MESH_COMPONENTS and row.get("hash"):
                runtime_body._set_resource(part, row, reader.register, safe_path, path_hash)
            if row.get("mesh_appearance") not in (None, "", "None") and "meshAppearance" in part:
                part["meshAppearance"] = dict(part["meshAppearance"], **{"$value": row["mesh_appearance"]})
            if row.get("chunk_mask") not in (None, "") and "chunkMask" in part:
                mask = int(row["chunk_mask"])
                part["chunkMask"] = str(mask) if isinstance(part["chunkMask"], str) else mask
        if eye_part is not None:
            part = lash_component(eye_part, part)
            name = part["name"]["$value"]
            key = ("lashes", name, part["$type"], part["id"])
        add_component(selected, key, part)
        added.append(name)
    return added


def inherit_patches(reader, original: str, copy_path: str, targets: dict) -> None:
    """A copied mesh keeps the ArchiveXL patches of the mesh it copies.

    ArchiveXL `resource: patch` adds appearances to a depot path in game.
    Morph baking and the eyelash edit write copies under npvmaker/generated,
    which no mod patches. Measured 26/09/2026 (NPV "asia"): Beanie's CCXL
    Clinic patches hx_000_pwa_c__basehead_makeup_freckles_01.mesh with
    xtra_cyberware.mesh (bby_cyberware_01..); the baked copy had 361
    appearances and no bby_cyberware_01, and the face cyberware rendered
    as a grey patch. The generated .xl repeats the mod's patch on the copy.
    """
    source = getattr(reader, "source", lambda path: path)
    patches = getattr(reader, "patches", {})
    for key in {original.lower(), source(original).lower()}:
        for patch in patches.get(key, []):
            if copy_path not in targets.setdefault(patch, []):
                targets[patch].append(copy_path)


def copied_fixes(reader, copies: dict) -> dict:
    """ArchiveXL `resource: fix` of each copied mesh's original, for the copy.

    ArchiveXL applies a fix (material `names`, `context`) to the mesh loaded
    from that exact path, so a copy under npvmaker/generated loses it. MEDIDO
    EM 28/09/2026 (0.4.17, "olhos de galaxia"): the bundle renames the vanilla
    eye materials (blood_gradient_black -> blood_gradient_black@eyes); on the
    baked copy the Dream Galaxy appearance protoss_dg13 was expanded without
    "@eyes", its material could not be made and the NPC had no eyes. The
    original is the path the game loads for that piece (a `resource: copy`
    target is its own path in game), never the file it was copied from.
    `copies` is {copy path: original path}; returns {copy path: fix}.
    """
    fixes = getattr(reader, "fixes", {})
    result = {}
    for copy_path, original in sorted(copies.items()):
        fix = fixes.get(fix_key(original))
        if fix:
            result[copy_path] = {"names": dict(fix["names"]), "context": dict(fix["context"])}
    return result


def yaml_text(value: str) -> str:
    """A scalar written so ArchiveXL (yaml-cpp) reads it back unchanged."""
    if not value or re.search(r"^[\s!&*\[\]{}|>'\"%@`#,?:-]|: | #|:$|\s$", value):
        return "'" + value.replace("'", "''") + "'"
    return value


# Every game language reads the same name table.
LANGUAGES = ("en-us", "pt-br", "es-es", "es-mx", "fr-fr", "de-de", "it-it", "pl-pl", "ru-ru", "cz-cz",
             "hu-hu", "tr-tr", "ua-ua", "ar-ar", "th-th", "jp-jp", "kr-kr", "zh-cn", "zh-tw")


def archive_xl_text(targets: dict, names: str | None = None, fixes: dict | None = None) -> str:
    lines = []
    if names:
        lines += ["localization:", "  onscreens:"] + ["    " + code + ": " + names for code in LANGUAGES]
    if targets or fixes:
        lines.append("resource:")
    if targets:
        lines.append("  patch:")
        for patch in sorted(targets):
            lines.append("    " + patch + ":")
            lines.extend("      - " + target for target in targets[patch])
    if fixes:
        lines.append("  fix:")
        for path in sorted(fixes):
            lines.append("    " + path + ":")
            for part in ("names", "context"):
                if fixes[path].get(part):
                    lines.append("      " + part + ":")
                    lines.extend("        " + yaml_text(k) + ": " + yaml_text(v) for k, v in fixes[path][part].items())
    return "\n".join(lines) + "\n"


def names_resource(header: dict, key: str, name: str) -> dict:
    """ArchiveXL onscreens table holding the chosen character name.

    Character.displayName is a localization key: TweakXL turns the text it
    is given into a key and Companion Expansion shows the text of that key
    (AikoNPVCatalogo.NomeDoRecord). Plain "red" matched an existing game key
    by chance; "asia" had none and Companion fell back to the record id
    ("NPVMAKER 771926010EBFAAF1", 26/09/2026). Same layout as the onscreens
    file of Beanie's CCXL Clinic.
    """
    entry = {"$type": "localizationPersistenceOnScreenEntry", "femaleVariant": name,
             "maleVariant": "", "primaryKey": "0", "secondaryKey": key}
    return {"Header": copy.deepcopy(header),
            "Data": {"Version": 195, "BuildVersion": 0, "EmbeddedFiles": [],
                     "RootChunk": {"$type": "JsonResource", "cookingPlatform": "PLATFORM_PC",
                                   "root": {"HandleId": "0", "Data": {
                                       "$type": "localizationPersistenceOnScreenEntries", "entries": [entry]}}}}}


# WolvenKit's export reads only archive/pc/content and archive/pc/ep1 of
# --gamepath, and only archives whose name starts like the game's own.
DEPOT_ARCHIVE = "basegame_npvmaker_depot"


def depot_game(cli: Path, work: Path, resource: str, file: Path) -> Path:
    """A game folder where WolvenKit finds `file` at the depot path `resource`."""
    shutil.rmtree(work, ignore_errors=True)
    staged = work / DEPOT_ARCHIVE
    target = staged.joinpath(*resource.split("\\"))
    target.parent.mkdir(parents=True)
    shutil.copy2(file, target)
    game = work / "game"
    (game / "bin/x64").mkdir(parents=True)
    (game / "archive/pc/content").mkdir(parents=True)
    cli_run(cli, "pack", staged, "--outpath", game / "archive/pc/content")
    return game


def exported_glb(folder: Path) -> Path:
    glbs = list(folder.glob("*.morphtarget.glb"))
    if len(glbs) != 1:
        raise ValueError("Morph export did not produce one GLB")
    return glbs[0]


def glb_skinned(raw: bytes) -> bool:
    """The GLB has a skeleton and every primitive has joints and weights."""
    meta, _ = unpack_glb(raw)
    primitives = [p for m in meta.get("meshes", []) for p in m.get("primitives", [])]
    return bool(meta.get("skins")) and bool(primitives) and all(
        "JOINTS_0" in p["attributes"] and "WEIGHTS_0" in p["attributes"] for p in primitives)


# MEDIDO EM 03/10/2026: world NPCs of the base game give their face rig these facial graphs (goro_takemura.app,
# panam.app); the NPV kept the character editor's (pma_paperdoll_sermo), which plays no facial animation.
# Not applied in package 38 (BUGS 82 test, see bind_face_meshes).
NPC_FACE_GRAPHS = {"male": "base\\animations\\facial\\_facial_graphs\\man_average_sermo.animgraph",
                   "female": "base\\animations\\facial\\_facial_graphs\\woman_average_sermo.animgraph"}


def face_rig_part(selected: dict) -> dict | None:
    """The animated component that carries the facial setup (the face rig)."""
    for part in selected.values():
        setup = ((part.get("facialSetup") or {}).get("DepotPath") or {}).get("$value")
        if part.get("$type") == "entAnimatedComponent" and setup not in (None, "", "0"):
            return part
    return None


def _rebind(part: dict, field: str, name: str) -> None:
    binding = part.get(field)
    if isinstance(binding, dict) and isinstance(binding.get("Data"), dict):
        binding = copy.deepcopy(binding)
        binding["Data"]["bindName"] = dict(binding["Data"].get("bindName") or {"$type": "CName", "$storage": "string"},
                                           **{"$value": name})
        part[field] = binding


def entity_body_bones(reader, entity_source: str) -> set:
    """Bones of the base entity's own skeletons (root, deformations): what the body moves without the face rig."""
    bones, rigs = set(), []

    def walk(node):
        if isinstance(node, dict):
            setup = ((node.get("facialSetup") or {}).get("DepotPath") or {}).get("$value")
            if node.get("$type") == "entAnimatedComponent" and setup in (None, "", "0") and node.get("rig"):
                rigs.append(node["rig"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    try:
        walk(reader.read(entity_source))
        for rig in rigs:
            root = reader.read(resource_ref(reader, rig, ".rig"))["Data"]["RootChunk"]
            bones |= {b.get("$value") if isinstance(b, dict) else b for b in root.get("boneNames") or []}
    except (ValueError, KeyError, OSError, ResourceMissing, UnreadableResource):
        return set()
    return bones


def bind_face_meshes(reader, selected: dict, body: str, body_bones: set = frozenset()) -> list[str]:
    """Face meshes skinned to the face rig (package 38: the face rig keeps the editor facial graph).

    MEDIDO EM 03/10/2026 (AFT sem expressao no mundo e no modo foto): goro_photomode_appearance.app,
    goro_takemura.app, panam.app, judy.app and the Sina NPV bind every head mesh to face_rig (skinning, and
    parentTransform on Sina); the NPV kept V's binding to root, which only moves the face on the player entity.
    A mesh goes to the face rig when every bone it uses is a bone of the face rig skeleton and at least one of them
    is not a bone of the body skeletons (`body_bones`). Measured on the AFT: head, eyes, brows, teeth, face cyberware,
    earrings and V's hair (69 face-only bones) yes; the hair shadow (only Head, as the NPC hair of goro_takemura.app
    and panam.app, bound to root) and the body, nails and underwear no. Returns the component names rebound.
    """
    face = face_rig_part(selected)
    if face is None:
        return []
    name = (face.get("name") or {}).get("$value")
    try:
        rig = reader.read(resource_ref(reader, face.get("rig"), ".rig"))["Data"]["RootChunk"]
        rig_bones = {b.get("$value") if isinstance(b, dict) else b for b in rig.get("boneNames") or []}
    except (ValueError, KeyError, OSError, ResourceMissing, UnreadableResource):
        return []
    # BUGS 82 test build (package 38, 06/10/2026): the face rig keeps the graph the editor gave it (pma_paperdoll_sermo,
    # player_woman_paperdoll_sermo). NPC_FACE_GRAPHS (package 19) play mood poses at rest (idle__neutral__male,
    # idle__interested__male...) on the face rig the meshes follow; documentacao/script/mapa-rosto-npc-82.md.
    rebound = []
    for part in selected.values():
        if part.get("$type") not in MESH_COMPONENTS or part is face:
            continue
        try:
            bones = {b.get("$value") for b in reader.read(component_mesh(reader, part))["Data"]["RootChunk"]
                     .get("boneNames") or []}
        except (ValueError, KeyError, OSError, ResourceMissing, UnreadableResource):
            continue
        if bones and bones <= rig_bones and bones - body_bones:
            _rebind(part, "skinning", name)
            _rebind(part, "parentTransform", name)
            rebound.append((part.get("name") or {}).get("$value"))
    return rebound


def mesh_has_bones(reader, mesh: str) -> bool:
    return bool(reader.read(mesh)["Data"]["RootChunk"].get("boneNames"))


def morph_draws(morph_doc: dict) -> bool:
    """Whether the game draws anything from a morphtarget component.

    MEDIDO EM 02/10/2026 (AFT, V masculino): a teeth .app from a mod adds 15
    morphtarget components whose own render blob is one 150-vertex chunk with
    lodMask 0 and an empty vertex layout, on the full teeth mesh as baseMesh.
    No LOD draws such a chunk; the NPV gave each one the whole base mesh
    without shapes, drawing 15 extra unshaped teeth. A morphtarget with no
    chunk in any LOD is left out; one whose blob cannot be read keeps the
    previous path.
    """
    root = morph_doc["Data"]["RootChunk"]
    blob = ((root.get("blob") or {}).get("Data") or {}).get("baseBlob") or {}
    chunks = ((blob.get("Data") or {}).get("header") or {}).get("renderChunkInfos")
    if not chunks:
        return True
    return any(int(chunk.get("lodMask") or 0) for chunk in chunks)


def external_morph(reader, morph: str, morph_doc: dict) -> bool:
    """Whether a morphtarget piece comes from a mod (BUGS 67c, author decision 03/10/2026).

    A piece counts as a mod piece when a mod gives the game its morphtarget, the base mesh of that
    morphtarget, or the file ArchiveXL fills it from. The NPV never carries a copy of such a piece:
    it keeps the morphtarget component on the original path and NPV Maker applies the preset shapes
    in game (NPVMakerMorphs.reds). MEDIDO EM 03/10/2026 (sondas em jogo): the whole AFT face with the
    morphtarget of a head mod and the Hyst Angel body took the shapes at runtime this way.
    """
    if not hasattr(reader, "from_mod"):
        return False
    base = morph_doc["Data"]["RootChunk"]["baseMesh"]["DepotPath"]["$value"]
    donor = reader.props_donor(morph) if hasattr(reader, "props_donor") else None
    return bool(reader.from_mod(morph) or reader.from_mod(base) or (donor and reader.from_mod(donor)))


def declared_shapes(morph_doc: dict) -> set:
    return {t["name"]["$value"] + "_" + t["regionName"]["$value"]
            for t in morph_doc["Data"]["RootChunk"].get("targets", [])}


def lash_component(eye_part: dict, lash_part: dict) -> dict:
    """The eyelash draw of V as its own NPC component, for an eye from a mod.

    MEDIDO EM 03/10/2026 (sonda do olho, AFT): V draws the eye mesh twice, the eye appearance with
    the eye mask and the eyelash appearance with the lash mask (item 39). Two components on the
    original morphtarget showed eye and lashes like V, with the ArchiveXL fix and the mod patches
    applied by the game, so no eyes.mesh copy is needed. The second one needs its own name and id
    to live in the same appearance.
    """
    part = copy.deepcopy(lash_part)
    name = eye_part["name"]["$value"] + "_lashes"
    part["name"] = cname(name)
    part["id"] = str(int(path_hash(name)) & 0x7FFFFFFFFFFFFFFF)
    return part


MORPH_MANAGER_NAME = "NPVMakerMorphTargetManager"


def morph_manager() -> dict:
    """V carries an entMorphTargetManagerComponent; the Codeware call that applies shapes needs it."""
    return {"$type": "entMorphTargetManagerComponent", "externalComponentName": cname("None"),
            "id": str(int(path_hash(MORPH_MANAGER_NAME)) & 0x7FFFFFFFFFFFFFFF), "isReplicable": 0,
            "name": cname(MORPH_MANAGER_NAME)}


def runtime_morphs(project_options: list[dict], shapes: set) -> list[list[str]]:
    """[target, region] pairs NPV Maker applies in game, in editor order, for the shapes the kept
    morphtarget pieces declare (the editor applies each choice with weight 1)."""
    pairs = []
    for option in project_options:
        if option.get("active") and option.get("kind") == "morph" and option.get("selected_name") not in ("", "None", None):
            if option["selected_name"] + "_" + option["name"] in shapes:
                pair = [option["selected_name"], option["name"]]
                if pair not in pairs:
                    pairs.append(pair)
    return pairs


def bake_morph(reader: Resources, cli: Path, game: Path, morph: str, morph_doc: dict, shape_keys: list[str],
               folder: Path, namespace: str, source: Path, patch_targets: dict, prepared: dict | None = None) -> dict:
    """Give one morphtarget's base mesh the selected shapes.

    Returns {"resource", "source_mesh", "applied_shapes", "error"}. A piece whose
    shapes cannot be applied keeps its default shape and reports the error;
    before 0.4.13 any failure here stopped the import. tools/varredura.py runs
    this same function for every morphtarget of the installed editor options.
    """
    mesh = morph_doc["Data"]["RootChunk"]["baseMesh"]["DepotPath"]["$value"]
    declared_shapes = {t["name"]["$value"] + "_" + t["regionName"]["$value"]
                       for t in morph_doc["Data"]["RootChunk"].get("targets", [])}
    relevant = set(shape_keys) & declared_shapes
    matched, resource, failure = [], None, None
    try:
        if relevant:
            # WolvenKit takes the skeleton of the GLB from the morphtarget's
            # base mesh. A morphtarget that ArchiveXL fills from another file
            # (Arkhe eyebrows and makeup) names a mod mesh without bones, so
            # the export uses that other file, whose base mesh has them.
            donor = reader.props_donor(morph) if hasattr(reader, "props_donor") else None
            exported = donor or reader.source(morph)
            reader.fetch([exported])
            if prepared and prepared.get("exported") == exported and list(folder.glob("*.morphtarget.glb")):
                log = prepared["export_log"]  # exported with the other pieces in one call (prepare_bakes)
            else:
                log = cli_run(cli, "export", reader.path(exported), "--outpath", folder, "--gamepath", game)
            glb = exported_glb(folder).read_bytes()
            # MEDIDO EM 28/09/2026 (item 37): WolvenKit does not load the mod
            # archives, so a base mesh shipped only by a mod (icxrus teeth and
            # Soft Natural lashes) was "not found"; the export still succeeded,
            # without skeleton, and the baked NPC piece had no bone weights and
            # floated off the face. The mesh the reader extracted is given to
            # WolvenKit at its depot path, and a piece that must be skinned is
            # never baked from a GLB without skin.
            missing = "could not be found" in log
            if missing or not glb_skinned(glb):
                needs_skin = mesh_has_bones(reader, mesh)
                if (missing or needs_skin) and exported == reader.source(morph) and not mesh.isdecimal():
                    reader.fetch([mesh])
                    depot = depot_game(cli, folder.with_name(folder.name + "-depot"), mesh, reader.path(mesh))
                    exported_glb(folder).unlink()
                    log = cli_run(cli, "export", reader.path(exported), "--outpath", folder, "--gamepath", depot)
                    glb = exported_glb(folder).read_bytes()
                    missing = "could not be found" in log
                if missing or (needs_skin and not glb_skinned(glb)):
                    raise ValueError("esqueleto nao preservado: o WolvenKit exportou " + morph
                                     + " sem os ossos de " + mesh + "; peca mantida sem as formas")
            meta, _ = unpack_glb(glb)
            available = {n for m in meta.get("meshes", []) for n in m.get("extras", {}).get("targetNames", [])}
            if not relevant.issubset(available):
                raise ValueError("GLB export omitted declared morphs: " + ", ".join(sorted(relevant - available)))
            matched = [key for key in shape_keys if key in available]
        if matched:
            mesh_name = reader.path(mesh).name
            original = folder / mesh_name
            baked = folder / (Path(mesh_name).stem + ".glb")
            data = bake(glb, matched)
            if not (prepared and prepared.get("imported") and baked.is_file() and original.is_file()
                    and baked.read_bytes() == data):
                shutil.copy2(reader.path(mesh), original)
                baked.write_bytes(data)
                cli_run(cli, "import", baked, "--outpath", folder, "--keep")
            resource = namespace + "\\meshes\\" + folder.name + ".mesh"
            target = source.joinpath(*resource.split("\\"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            inherit_patches(reader, mesh, resource, patch_targets)
    except (ValueError, OSError, KeyError) as error:
        matched, resource, failure = [], None, error
    if resource is None and hasattr(reader, "patched") and reader.patched(mesh):
        # The mod file lacks what ArchiveXL patches in (geometry, and the
        # bones that geometry needs); the NPV gets the patched copy.
        resource = namespace + "\\meshes\\" + folder.name + ".mesh"
        target = source.joinpath(*resource.split("\\"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reader.path(mesh), target)
        inherit_patches(reader, mesh, resource, patch_targets)
    elif resource is None:
        resource = mesh
    return {"resource": resource, "source_mesh": mesh, "applied_shapes": matched, "error": failure}


def prepare_bakes(reader, cli: Path, game: Path, jobs: list, shape_keys: list[str], staging: Path) -> dict:
    """The WolvenKit work of every bake_morph in two calls: one export of all morphtargets, one import of all
    baked meshes. Checked 06/10/2026 on the TI 38 pieces: same GLB and mesh bytes as one call per piece.

    `jobs` is [(morph, morph_doc, folder)] in bake order. Only the ordinary path is prepared (file found,
    skinned GLB, every declared shape present); bake_morph does any other piece alone, as 0.1.0 did, and
    uses a prepared result only when it is exactly the one it would make. Returns {morph: prepared}."""
    plan = []
    for morph, morph_doc, folder in jobs:
        declared = {t["name"]["$value"] + "_" + t["regionName"]["$value"]
                    for t in morph_doc["Data"]["RootChunk"].get("targets", [])}
        relevant = set(shape_keys) & declared
        if not relevant:
            continue
        donor = reader.props_donor(morph) if hasattr(reader, "props_donor") else None
        exported = donor or reader.source(morph)
        mesh = morph_doc["Data"]["RootChunk"]["baseMesh"]["DepotPath"]["$value"]
        try:
            with speculating(reader):
                reader.fetch([exported])
            plan.append(dict(morph=morph, folder=folder, exported=exported, file=reader.path(exported),
                             relevant=relevant, mesh=mesh))
        except (ValueError, OSError, KeyError):
            continue
    names = [p["file"].name for p in plan]
    plan = [p for p in plan if names.count(p["file"].name) == 1]
    if len(plan) < 2:
        return {}
    shutil.rmtree(staging, ignore_errors=True)
    exports = staging / "export"
    exports.mkdir(parents=True)
    try:
        log = cli_run(cli, "export", *[p["file"] for p in plan], "--outpath", exports, "--gamepath", game)
    except ValueError:
        return {}
    if "could not be found" in log:
        return {}
    prepared, imports = {}, []
    for p in plan:
        glb_file = exports / (p["file"].name + ".glb")
        if not glb_file.is_file():
            continue
        glb = glb_file.read_bytes()
        try:
            meta, _ = unpack_glb(glb)
            if not glb_skinned(glb):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        available = {n for m in meta.get("meshes", []) for n in m.get("extras", {}).get("targetNames", [])}
        matched = [key for key in shape_keys if key in available]
        if not p["relevant"].issubset(available) or not matched:
            continue
        p["folder"].mkdir(parents=True, exist_ok=True)
        shutil.move(str(glb_file), str(p["folder"] / glb_file.name))
        prepared[p["morph"]] = dict(exported=p["exported"], export_log=log, imported=False)
        try:
            with speculating(reader):
                reader.fetch([p["mesh"]])
            mesh_file = reader.path(p["mesh"])
        except (ValueError, OSError, KeyError):
            continue
        imports.append(dict(p, mesh_file=mesh_file, data=bake(glb, matched)))
    mesh_names = [i["mesh_file"].name for i in imports]
    imports = [i for i in imports if mesh_names.count(i["mesh_file"].name) == 1]
    if not imports:
        return prepared
    rebuild = staging / "import"
    rebuild.mkdir()
    for i in imports:
        shutil.copy2(i["mesh_file"], rebuild / i["mesh_file"].name)
        (rebuild / (Path(i["mesh_file"].name).stem + ".glb")).write_bytes(i["data"])
    before = {i["morph"]: (rebuild / i["mesh_file"].name).stat().st_mtime_ns for i in imports}
    try:
        cli_run(cli, "import", *[rebuild / (Path(i["mesh_file"].name).stem + ".glb") for i in imports],
                "--outpath", rebuild, "--keep")
    except ValueError:
        return prepared
    for i in imports:
        rebuilt = rebuild / i["mesh_file"].name
        if rebuilt.stat().st_mtime_ns == before[i["morph"]]:
            continue
        shutil.copy2(rebuilt, i["folder"] / i["mesh_file"].name)
        (i["folder"] / (Path(i["mesh_file"].name).stem + ".glb")).write_bytes(i["data"])
        prepared[i["morph"]]["imported"] = True
    return prepared


def check_packed_archive(cli: Path, archive: Path, entity_path: str, app_path: str, appearance: str) -> str:
    """companion_expansion.check_archive with its WolvenKit work in two calls (extract both files, serialize
    both). Same checks: the .ent is in the archive and parses, its appearance names an .app that is in the
    archive, and that .app parses and has the appearance. Archive membership is read from the archive
    index (path hash), as the game finds files. Anything unexpected runs check_archive itself."""
    try:
        listed = archive_hashes(archive)
    except (OSError, ValueError):
        return check_archive(cli, archive, entity_path, appearance)
    if int(path_hash(entity_path)) not in listed:
        raise ValueError(f"NPC archive does not contain {entity_path}")
    with tempfile.TemporaryDirectory(prefix="npv-companion-") as tmp:
        folder = Path(tmp)
        run_cli(cli, "extract", str(archive), "--outpath", str(folder),
                "--regex", "^(?:" + re.escape(entity_path) + "|" + re.escape(app_path) + ")$")
        entity = folder.joinpath(*entity_path.split("\\"))
        app_file = folder.joinpath(*app_path.split("\\"))
        if not entity.is_file():
            raise ValueError("The declared .ent could not be extracted")
        run_cli(cli, "convert", "serialize", str(entity), *([str(app_file)] if app_file.is_file() else []))
        serial = json.loads(Path(str(entity) + ".json").read_text(encoding="utf-8-sig"))
        entries = serial.get("Data", {}).get("RootChunk", {}).get("appearances", [])
        for entry in entries:
            if entry.get("appearanceName", {}).get("$value") != appearance:
                continue
            app = resource_path(entry.get("appearanceResource", {}).get("DepotPath", {}).get("$value"), ".app")
            if int(path_hash(app)) not in listed:
                raise ValueError(f"The selected appearance references missing {app}")
            if app.lower() != app_path.lower():
                return check_archive(cli, archive, entity_path, appearance)
            if not app_file.is_file():
                raise ValueError("The referenced .app could not be extracted")
            app_serial = json.loads(Path(str(app_file) + ".json").read_text(encoding="utf-8-sig"))
            definitions = app_serial.get("Data", {}).get("RootChunk", {}).get("appearances", [])
            if not any(d.get("Data", {}).get("name", {}).get("$value") == appearance for d in definitions):
                raise ValueError(f"The .app lacks appearance {appearance}")
            return app
    raise ValueError(f"Appearance {appearance!r} is absent from the declared .ent")


# SELECTED_TPP is the editor's default body since 0.5.0; the author asked (01/10/2026) for no tag on its name.
DEV_SUFFIX = {"runtime_tpp": " [RUNTIME_TPP]"}


def appearance_names(reader, app: str, appearance: str) -> list[str]:
    """Component names of one appearance of an .app as collect_components reads it."""
    doc = reader.read(app)
    match = next((x["Data"] for x in doc["Data"]["RootChunk"].get("appearances") or []
                  if x["Data"]["name"]["$value"] == appearance), None)
    if match is None:
        raise AppearanceNotFound("Aparencia nao encontrada: " + app + "/" + appearance)
    table = handles(doc)
    components = [expanded(item, table) for item in appearance_components(match)]
    found, _ = app_patch_components(reader, [app], appearance)
    merge_patch_components(components, found)
    return [c.get("name", {}).get("$value") for c in components]


def attach_observed(project: dict, options: list[dict], redirects: dict) -> list[dict]:
    """Give each option what the editor puppet showed coming from its own .app
    with its choice (LOADED only), to check appearances rebuilt from a
    template (apply_template). Options without that evidence stay as they are."""
    components, _ = runtime_body.manifest(project)
    loaded = [c for c in components or [] if c["state"] == "LOADED" and c.get("owner_app")]
    result = []
    for option in options:
        own = {runtime_body._norm(option["resource_path"]), runtime_body._norm(redirects.get(option["resource_path"]))}
        seen = [dict(name=c["name"], field=c["field"], path=c.get("path"), hash=c.get("hash"),
                     mesh_appearance=c.get("mesh_appearance"), chunk_mask=c.get("chunk_mask")) for c in loaded
                if runtime_body._norm(c["owner_app"]) in own - {""}
                and runtime_body._chooses(option, c.get("owner_appearance") or "")]
        result.append(dict(option, runtime_observed=seen) if seen and not option.get("runtime_origin") else option)
    return result


def head_notes(decisions: list[dict], character: str, redact) -> list[dict]:
    """NPVM-HEAD-001 for each option read from its observed origin; NPVM-HEAD-002
    when the puppet showed another origin that could not be used."""
    notes = []
    for record in decisions:
        if record["decision"] == "runtime_origin":
            notes.append(diagnostics.make(
                "NPVM-HEAD-001", character=character, option=record["option"], selection=record["choice"],
                resource=record["app"], action="runtime_origin", result="continued", redact=redact,
                technical_error="lido de " + record["app"] + " / " + record["appearance"]
                                + " (a opcao aponta para " + record["resource"] + ")"))
        elif record["decision"] in ("ambiguous", "no_definition"):
            detail = record.get("error") or ("apps " + ", ".join(record.get("apps", [])) + "; aparencias "
                                             + ", ".join(record.get("appearances", [])) + "; outras opcoes "
                                             + ", ".join(record.get("rivals", [])))
            notes.append(diagnostics.make(
                "NPVM-HEAD-002", character=character, option=record["option"], selection=record["choice"],
                resource=record["resource"], action="legacy_head", result="continued", redact=redact,
                technical_error=record["decision"] + ": " + detail[:600]))
    return notes


def runtime_missing(project: dict, selected: dict, left_out: list[dict] = ()) -> list[str]:
    """Pieces the editor drew with a loaded file that the NPC lacks, by name.

    The editor puppet is the authority on what V wears (runtime manifest,
    0.4.14); a piece it drew and the NPC lacks is a hole or a missing detail
    in game. MEDIDO EM 28/09/2026: the jaw plates of "mariko 3.0" (patch of an
    .app) and CCXL teeth (component in another .app) were found only on
    screen. Only LOADED counts: UNOBSERVED is no proof the piece was drawn.
    `left_out` are options the NPV leaves out on purpose (covered_genitals); their pieces are not missing.
    """
    components, _ = runtime_body.manifest(project)
    have = {re.sub(r"__npv_rt\d+$", "", p.get("name", {}).get("$value", "")) for p in selected.values()}
    excluded = [(runtime_body._norm(o.get("resource_path")), o) for o in left_out]
    missing = []
    for component in components or []:
        owner = runtime_body._norm(component.get("owner_app"))
        if any(owner and owner == app and runtime_body._chooses(o, component.get("owner_appearance") or "")
               for app, o in excluded):
            continue
        if component["state"] == "LOADED" and component["name"] not in have and component["name"] not in missing:
            missing.append(component["name"])
    return missing


def build_identity(digest: str, strategy: str) -> str:
    """Hash that names a build. A DEV body strategy is its own NPC, so the two
    variants of one project can be imported side by side."""
    if strategy == "legacy":
        return digest
    return hashlib.sha256((digest + ":" + strategy).encode("ascii")).hexdigest()


def runtime_body_route(reader, redirects, project: dict, project_options: list[dict], options: list[dict],
                       strategy: str, redact, output: Path, step=None) -> tuple[dict | None, list[dict]]:
    """Components of the NPC with the body taken from the editor puppet.

    Returns (collected, notes); collected is None when the 0.4.13 path must be
    used (no runtime record, or it lacks an essential body piece).
    """
    character = project["name"]
    notes = []
    components, reason = runtime_body.manifest(project)
    if components is None:
        notes.append(diagnostics.make("NPVM-BODY-003", character=character, technical_error=reason,
                                      action="legacy_body", result="continued", redact=redact))
        return None, notes
    body_options, rest = runtime_body.slice_options(options)
    selection = runtime_body.select(components, project_options, strategy)
    built = runtime_body.body_parts(reader, redirects, selection, project_options, collect_components,
                                    reader.register, safe_path, path_hash, character, redact,
                                    patches=getattr(reader, "patches", {}))
    missing = runtime_body.essential_missing(built["used"], selection, project_options, ESSENTIAL_OPTION)
    legacy = collect_components(reader, body_options, redirects, character=character, redact=redact)
    comparison = runtime_body.compare(list(legacy["selected"].values()), built["parts"], path_hash)
    supports = runtime_body.bound_supports(built["parts"], list(legacy["selected"].values()))
    record = dict(strategy=strategy, components=len(components),
                  states={s: sum(c["state"] == s for c in components) for s in runtime_body.STATES},
                  included=[dict(name=c["name"], state=c["state"], owner_appearance=c["owner_appearance"],
                                 owner_app=c["owner_app"], selected_by_editor=c["selected_by_editor"],
                                 options=c["options"]) for c in selection["included"]],
                  skipped=[dict(name=c["name"], reason=c["reason"], owner_appearance=c["owner_appearance"],
                                state=c["state"]) for c in selection["skipped"]],
                  used=built["used"], failures=[dict(name=f["name"], reason=f["reason"]) for f in built["failures"]],
                  merged=built["merged"], essential_missing=missing, comparison=comparison,
                  bound_supports=[p["name"]["$value"] for p in supports],
                  options=[o["name"] for o in body_options])
    (output / "body-runtime.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
    for failure in built["failures"][:10]:
        notes.append(diagnostics.make("NPVM-BODY-002", character=character, option=", ".join(failure["options"]),
                                      resource=failure.get("path") or failure.get("hash") or "",
                                      technical_error=failure["name"] + ": " + str(failure["reason"]),
                                      action="skipped", result="continued", redact=redact))
    if missing or not built["parts"]:
        notes.append(diagnostics.make(
            "NPVM-BODY-003", character=character, action="legacy_body", result="continued", redact=redact,
            technical_error="sem peca do editor para " + (", ".join(missing) or "o corpo")))
        return None, notes
    skipped = {}
    for row in selection["skipped"]:
        skipped[row["reason"]] = skipped.get(row["reason"], 0) + 1
    summary = ("estrategia " + strategy.upper() + "; corpo do editor: " + str(len(built["used"]))
               + " pecas (" + ", ".join(k + " " + str(v) for k, v in record["states"].items() if v) + " no puppet)"
               + "; fora: " + (", ".join(k + " " + str(v) for k, v in sorted(skipped.items())) or "nenhuma")
               + "; antes " + str(comparison["legacy_count"]) + ", agora " + str(comparison["runtime_count"])
               + "; novas: " + (", ".join(comparison["added"]) or "nenhuma")
               + "; perdidas: " + (", ".join(comparison["lost"]) or "nenhuma")
               + "; outra aparencia: " + (", ".join(comparison["recolored"]) or "nenhuma")
               + "; copias extras: " + (", ".join(comparison["extra_copies"]) or "nenhuma")
               + "; ligadas mantidas: " + (", ".join(record["bound_supports"]) or "nenhuma"))
    notes.append(diagnostics.make("NPVM-BODY-001", character=character, action="runtime_body",
                                  result="continued", technical_error=summary[:1500], redact=redact))
    if step is not None:
        step("corpo: " + str(len(built["used"])) + " pecas do editor")
    collected = collect_components(reader, rest, redirects, character=character, redact=redact,
                                   **({"step": step} if step is not None else {}))
    for part in built["parts"] + supports:
        key = ("runtime", part["name"]["$value"], part["$type"], part.get("id"))
        add_component(collected["selected"], key, part)
    npc_hide_distance(collected["selected"])
    collected["used"].extend(dict(name=o["name"], selected_name=o["selected_name"], resource=o["resource_path"],
                                  body_source="runtime_" + strategy) for o in body_options)
    if collected["app_doc"] is None:
        collected["app_doc"] = copy.deepcopy(reader.read(reader.source(body_options[0]["resource_path"])))
    collected["body_runtime"] = record
    return collected, notes


PHOTO_ERRORS = (ValueError, KeyError, OSError, ResourceMissing, UnreadableResource)


def photomode_paths(namespace: str) -> tuple[str, str, str, str]:
    return (namespace + "\\photomode.ent", namespace + "\\photomode_icon.inkatlas",
            namespace + "\\photomode_icon.xbm", namespace + "\\photomode.app")


def photomode_prepare(reader, project: dict, namespace: str, app_path: str, source: Path,
                      app_doc: dict | None = None) -> tuple[list, dict]:
    """The reads and documents of photomode_files, without writing: ([(doc, destination)], info)."""
    entity_path, atlas_path, texture_path, photo_app_path = photomode_paths(namespace)
    template = photomode.TEMPLATES[project["body"]]
    template_doc = reader.read(template)
    graph, animations, puppet_app = None, None, app_path
    template_app = photomode.template_app_path(template_doc)
    if template_app and app_doc is not None:
        template_app_doc = reader.read(template_app)
        graph = photomode.template_face_graph(template_app_doc)
        animations = photomode.template_face_animations(template_app_doc)
    writes = []
    if graph is not None:
        photo_doc, changed = photomode.face_graph_app(app_doc, graph, animations)
        if changed:
            writes.append((photo_doc, source.joinpath(*photo_app_path.split("\\"))))
            puppet_app = photo_app_path
    writes.append((photomode.entity(template_doc, puppet_app), source.joinpath(*entity_path.split("\\"))))
    writes.append((photomode.atlas(reader.read(photomode.ATLAS_TEMPLATE), texture_path),
                   source.joinpath(*atlas_path.split("\\"))))
    return writes, {"entity": entity_path, "atlas": atlas_path, "template": template,
                    "scope": photomode.SCOPES[project["body"]]}


def photomode_icon(cli: Path, namespace: str, display_name: str, source: Path, output: Path) -> dict:
    """Start the icon import of photomode_finish in the background; photomode_finish waits for it."""
    texture_path = photomode_paths(namespace)[2]
    raw = output / "photomode_raw"
    png = raw.joinpath(*texture_path.split("\\")).with_suffix(".png")
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(photomode.icon_png(display_name))
    state = {"error": None}

    def run():
        try:
            cli_run(cli, "import", raw, "--outpath", source)
        except ValueError as error:
            state["error"] = error
    state["thread"] = threading.Thread(target=run, daemon=True)
    state["thread"].start()
    return state


def photomode_finish(cli: Path, namespace: str, display_name: str, source: Path, output: Path, info: dict | None,
                     error: Exception | None, icon: dict | None = None) -> dict:
    """The icon texture of photomode_files, and its error handling: a failure removes every photo mode file."""
    paths = photomode_paths(namespace)
    texture_path = paths[2]
    try:
        if error is not None:
            raise error
        texture = source.joinpath(*texture_path.split("\\"))
        try:
            if icon is not None:
                icon["thread"].join()
                if icon["error"] is not None:
                    raise icon["error"]
            else:
                raw = output / "photomode_raw"
                png = raw.joinpath(*texture_path.split("\\")).with_suffix(".png")
                png.parent.mkdir(parents=True, exist_ok=True)
                png.write_bytes(photomode.icon_png(display_name))
                cli_run(cli, "import", raw, "--outpath", source)
        except ValueError:
            # MEDIDO EM 02/10/2026: WolvenKit 8.19 imports a folder ("Imported 1/1 file(s)") with a nonzero exit
            # code; the texture it wrote is the proof.
            if not texture.is_file():
                raise
        if not texture.is_file():
            raise ValueError("WolvenKit nao gerou o icone do modo foto")
    except PHOTO_ERRORS as failure:
        if icon is not None:
            icon["thread"].join()
        for path in paths:
            source.joinpath(*path.split("\\")).unlink(missing_ok=True)
        return {"error": type(failure).__name__ + ": " + str(failure)[:300]}
    return info


def photomode_files(reader, cli: Path, project: dict, namespace: str, app_path: str, display_name: str,
                    source: Path, output: Path, app_doc: dict | None = None) -> dict:
    """The photo mode .ent and icon in the NPV archive (photomode.py). Never stops the build: an NPV without
    photo mode is still a working NPV, so a failure is returned as `error` (NPVM-PHOTO-001)."""
    entity_path = namespace + "\\photomode.ent"
    atlas_path = namespace + "\\photomode_icon.inkatlas"
    texture_path = namespace + "\\photomode_icon.xbm"
    photo_app_path = namespace + "\\photomode.app"
    try:
        template = photomode.TEMPLATES[project["body"]]
        template_doc = reader.read(template)
        # The photo mode puppet takes its own copy of the NPV .app with the template's facial graph (photomode.py);
        # without a graph in the template it uses the NPV .app as before.
        graph, animations, puppet_app = None, None, app_path
        template_app = photomode.template_app_path(template_doc)
        if template_app and app_doc is not None:
            template_app_doc = reader.read(template_app)
            graph = photomode.template_face_graph(template_app_doc)
            animations = photomode.template_face_animations(template_app_doc)
        writes = []
        if graph is not None:
            photo_doc, changed = photomode.face_graph_app(app_doc, graph, animations)
            if changed:
                writes.append((photo_doc, source.joinpath(*photo_app_path.split("\\"))))
                puppet_app = photo_app_path
        writes.append((photomode.entity(template_doc, puppet_app), source.joinpath(*entity_path.split("\\"))))
        writes.append((photomode.atlas(reader.read(photomode.ATLAS_TEMPLATE), texture_path),
                       source.joinpath(*atlas_path.split("\\"))))
        write_all(reader, writes)
        raw = output / "photomode_raw"
        png = raw.joinpath(*texture_path.split("\\")).with_suffix(".png")
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(photomode.icon_png(display_name))
        texture = source.joinpath(*texture_path.split("\\"))
        try:
            cli_run(cli, "import", raw, "--outpath", source)
        except ValueError:
            # MEDIDO EM 02/10/2026: WolvenKit 8.19 imports a folder ("Imported 1/1 file(s)") with a nonzero exit
            # code; the texture it wrote is the proof.
            if not texture.is_file():
                raise
        if not texture.is_file():
            raise ValueError("WolvenKit nao gerou o icone do modo foto")
    except (ValueError, KeyError, OSError, ResourceMissing, UnreadableResource) as error:
        for path in (entity_path, atlas_path, texture_path, photo_app_path):
            source.joinpath(*path.split("\\")).unlink(missing_ok=True)
        return {"error": type(error).__name__ + ": " + str(error)[:300]}
    return {"entity": entity_path, "atlas": atlas_path, "template": template, "scope": photomode.SCOPES[project["body"]]}


def build(project_file: Path, game: Path, cli: Path, output: Path, progress=lambda text: None,
          body_strategy: str = "legacy", identity: str | None = None, display_name: str | None = None,
          underwear: str = "bottom") -> dict:
    if body_strategy not in runtime_body.STRATEGIES:
        raise ValueError("Estrategia de corpo desconhecida: " + str(body_strategy))
    project, source_digest = project_info(project_file)
    # The NPC takes its identity from the build: the project hash, or that
    # hash with the DEV body strategy (see build_identity). An installed NPV
    # package passes its own (npv_package.package_identity), stable across its
    # versions, and the name its author gave it.
    if identity is not None and not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ValueError("Identidade de build invalida")
    digest = identity or build_identity(source_digest, body_strategy)
    display_name = display_name or project["name"] + DEV_SUFFIX.get(body_strategy, "")
    output.mkdir(parents=True, exist_ok=False)
    perf_trace.mark("resources_init")
    reader = Resources(game, cli, output / "installed-resources")
    perf_trace.mark("options_prepare")

    def step(text):
        tell(progress, text)
    reader.on_step = step
    redact = diagnostics.redactor(game)
    late_notes = []
    project_options, conflicts = first_choices(project["options"])
    for option in conflicts:
        late_notes.append(diagnostics.make(
            "NPVM-PROJECT-002", character=project["name"], option=option["name"],
            selection=option["selected_name"], action="first_choice", result="continued", redact=redact))
    project_options, lash_defaults = default_lash(project_options, project["body"])
    for option in lash_defaults:
        late_notes.append(diagnostics.make(
            "NPVM-APPEAR-005", character=project["name"], option=option["name"], selection=option["selected_name"],
            technical_error="escolha " + str(option["selected_index"]) + " fora das " + str(option["choice_count"])
            + " opcoes do editor", action="first_choice", result="continued", redact=redact))
    project_options, genitals_hidden = covered_genitals(project_options, underwear)
    if genitals_hidden:
        late_notes.append(diagnostics.make(
            "NPVM-APPEAR-006", character=project["name"], option=", ".join(o["name"] for o in genitals_hidden),
            technical_error="roupa padrao " + underwear + " cobre a genitalia", action="skipped",
            result="continued", redact=redact))
    options = default_underwear(selected_appearances(dict(project, options=project_options)), project["body"],
                                underwear)
    redirects = archive_xl_material_sources(game / "red4ext/plugins/ArchiveXL/Bundle")
    base = "woman" if project["body"] == "female" else "man"
    entity_source = f"base\\characters\\base_entities\\{base}_base\\{base}_base.ent"
    # A captured path the reader cannot use is decided per option in
    # collect_components (skipped or, for body and head, fatal).
    wanted = [entity_source] + [o["resource_path"] for o in options if safe_path(o["resource_path"], ".app")]
    wanted += [redirects[p] for p in list(wanted) if p in redirects]
    progress("Lendo aparencias e corpo dos arquivos instalados...")
    perf_trace.mark("read_apps", wanted=len(wanted))
    read_ahead_closure(reader, project, options, wanted, entity_source, body_strategy != "legacy")
    try:
        reader.serialize(wanted)
    except (ResourceMissing, UnreadableResource):
        # A mod option may point to a file its archive lacks; that option is
        # decided (skipped or fatal) in collect_components.
        reader.serialize([w for w in wanted if reader.path(reader.source(w)).is_file()])
    perf_trace.mark("head_resolve")
    options, head_decisions = runtime_head.resolve(
        project, project_options, options, redirects,
        lambda app, appearance: appearance_names(reader, app, appearance))
    late_notes.extend(head_notes(head_decisions, project["name"], redact))
    options = attach_observed(project, options, redirects)
    if head_decisions:
        (output / "head-runtime.json").write_text(json.dumps(head_decisions, ensure_ascii=False, indent=2),
                                                  encoding="utf8")
    shape_keys = []
    for option in project_options:
        if option["active"] and option["kind"] == "morph" and option["selected_name"] not in ("", "None"):
            key = option["selected_name"] + "_" + option["name"]
            # A duplicated editor option (see validate_project) must not
            # bake the same morph twice.
            if key not in shape_keys:
                shape_keys.append(key)
    collected = None
    if body_strategy != "legacy":
        progress("Lendo aparencias e corpo do personagem do editor...")
        perf_trace.mark("body_route")
        collected, body_notes = runtime_body_route(reader, redirects, project, project_options, options,
                                                   body_strategy, redact, output, step)
        late_notes.extend(body_notes)
    if collected is None:
        perf_trace.mark("collect_components")
        collected = collect_components(reader, options, redirects, character=project["name"],
                                       redact=diagnostics.redactor(game), step=step)
    selected, used_options = collected["selected"], collected["used"]
    lash_material, eye_part, app_doc = collected["lash_material"], collected["eye_part"], collected["app_doc"]
    if not selected or app_doc is None:
        raise ValueError("Projeto sem componentes de aparencia")
    missing_pieces = runtime_missing(project, selected, genitals_hidden)
    if missing_pieces:
        late_notes.append(diagnostics.make(
            "NPVM-RUNTIME-001", character=project["name"], action="reported", result="continued",
            technical_error="faltam: " + ", ".join(missing_pieces)[:600], redact=redact))
    namespace = "npvmaker\\generated\\" + digest[:16]
    source = output / "archive_source"
    source.mkdir()
    meshes, seen_shapes, patch_targets, mesh_copies = {}, set(), {}, {}
    morph_paths = [p["morphResource"]["DepotPath"]["$value"] for p in selected.values()
                   if p.get("$type") == "entMorphTargetSkinnedMeshComponent"]
    perf_trace.mark("read_morphtargets", count=len(set(morph_paths)))
    for path in morph_paths:
        reader.register(path, ".morphtarget")
    ahead = list(morph_paths)
    face = face_rig_part(selected)
    if face is not None:
        try:
            ahead.append(resource_ref(reader, face.get("rig"), ".rig"))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        for part in selected.values():
            if part.get("$type") in MESH_COMPONENTS and part.get("$type") != "entMorphTargetSkinnedMeshComponent" \
                    and part is not face:
                try:
                    ahead.append(resource_ref(reader, part.get("mesh"), ".mesh"))
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
    ahead += entity_rigs(reader, entity_source)
    photo_template = photomode.TEMPLATES.get(project["body"])
    if photo_template:
        ahead += [photo_template, photomode.ATLAS_TEMPLATE]
    read_ahead(reader, ahead)
    reader.serialize(morph_paths)
    morph_docs = {path: reader.read(path) for path in sorted(set(morph_paths))}
    perf_trace.mark("fetch_base_meshes")
    base_meshes = [reader.register(doc["Data"]["RootChunk"]["baseMesh"]["DepotPath"]["$value"], ".mesh")
                   for doc in morph_docs.values()]
    ahead = list(base_meshes)
    if photo_template:
        try:
            with speculating(reader):
                ahead.append(photomode.template_app_path(reader.read(photo_template)))
        except (ValueError, KeyError, TypeError, OSError, IndexError, AttributeError):
            pass
    read_ahead(reader, ahead)
    reader.fetch(base_meshes)
    perf_trace.mark("classify_external")
    # BUGS 67c: a piece from a mod stays a morphtarget component on its original file; the shapes are
    # applied in game. Only pieces from the base game are still baked into meshes the NPV carries.
    kept_morphs = {path for path, doc in morph_docs.items() if external_morph(reader, path, doc)}
    eye_lashes = None
    if (lash_material and eye_part is not None and eye_part.get("$type") == "entMorphTargetSkinnedMeshComponent"
            and eye_part["morphResource"]["DepotPath"]["$value"] in kept_morphs and collected.get("eye_lashes")):
        if collected.get("eye_mask") is not None:
            eye_part["chunkMask"] = collected["eye_mask"]
        for lash in collected["eye_lashes"]:
            part = lash_component(eye_part, lash)
            npc_render_plane(part)
            selected[("lashes", part["name"]["$value"], part["$type"], part["id"])] = part
        npc_hide_distance(selected)
        lash_material, eye_lashes = None, "components"
    perf_trace.mark("entity_body_bones")
    body_bones = entity_body_bones(reader, entity_source)
    perf_trace.mark("face_rig_binding")
    face_bound = bind_face_meshes(reader, selected, project["body"], body_bones)
    perf_trace.mark("bake_morphs")
    undrawn, runtime_shapes = [], set()
    # The activity log shows each piece as it is baked (author request 05/10/2026).
    to_bake = sorted({p["morphResource"]["DepotPath"]["$value"] for p in selected.values()
                      if p.get("$type") == "entMorphTargetSkinnedMeshComponent"
                      and p["morphResource"]["DepotPath"]["$value"] not in kept_morphs
                      and morph_draws(morph_docs[p["morphResource"]["DepotPath"]["$value"]])})
    icon = photomode_icon(cli, namespace, display_name, source, output) if project["body"] in photomode.TEMPLATES else None
    prepared = prepare_bakes(reader, cli, game, [
        (morph, morph_docs[morph], output / "morphs" / hashlib.sha256(morph.encode()).hexdigest()[:16])
        for morph in to_bake], shape_keys, output / "morphs-batch")
    for name, part in selected.items():
        if part.get("$type") != "entMorphTargetSkinnedMeshComponent":
            continue
        morph = part["morphResource"]["DepotPath"]["$value"]
        if not morph_draws(morph_docs[morph]):
            undrawn.append(name)
            if morph not in meshes:
                meshes[morph] = None
                late_notes.append(diagnostics.make(
                    "NPVM-BAKE-003", character=project["name"], resource=morph,
                    technical_error="nenhum pedaco do morphtarget em algum LOD", action="skipped",
                    result="continued", redact=redact))
            continue
        if morph in kept_morphs:
            runtime_shapes |= declared_shapes(morph_docs[morph]) & set(shape_keys)
            continue
        part.pop("morphResource")
        if morph not in meshes:
            folder = output / "morphs" / hashlib.sha256(morph.encode()).hexdigest()[:16]
            folder.mkdir(parents=True, exist_ok=morph in prepared)
            progress("Convertendo formas: peca " + str(to_bake.index(morph) + 1 if morph in to_bake else len(meshes) + 1)
                     + " de " + str(max(len(to_bake), 1)) + " (" + morph.split("\\")[-1].rsplit(".", 1)[0] + ")...")
            perf_trace.mark("bake_morph", morph=morph)
            result = bake_morph(reader, cli, game, morph, morph_docs[morph], shape_keys, folder,
                                namespace, source, patch_targets, prepared.get(morph))
            perf_trace.mark("bake_morphs")
            error = result.pop("error")
            if error is not None:
                late_notes.append(diagnostics.make(
                    "NPVM-BAKE-002", character=project["name"], resource=result["source_mesh"],
                    technical_error=type(error).__name__ + ": " + str(error), action="default_shape",
                    result="continued", redact=redact))
            seen_shapes.update(result["applied_shapes"])
            meshes[morph] = result
        part["$type"] = "entSkinnedMeshComponent"
        # Morph-target components expose their own tag field, which does not
        # exist on the ordinary skinned component after baking.
        part.pop("tags", None)
        part["mesh"] = ref(meshes[morph]["resource"])
    for name in undrawn:
        del selected[name]
    present = {(part.get("name") or {}).get("$value") for part in selected.values()}
    face_bound = sorted({name for name in face_bound if name in present})
    meshes = {morph: result for morph, result in meshes.items() if result is not None}
    if lash_material and collected.get("standalone_lashes"):
        # BUGS 78/79: the lashes are their own component (standalone_lash_parts); no eye mesh to recolor.
        lash_material, eye_lashes = None, "standalone"
    if lash_material and eye_part is None:
        # Eyelash mods (CCXL) can take the lashes off the eye mesh; the NPV
        # keeps the default lashes instead of refusing the import.
        late_notes.append(diagnostics.make(
            "NPVM-CONVERT-001", character=project["name"], option="eyelash_color",
            technical_error="Cor de cilios sem componente de olhos correspondente", action="skipped",
            result="continued", redact=redact))
        lash_material = None
    if lash_material and eye_part.get("$type") == "entMorphTargetSkinnedMeshComponent":
        # An eye from a mod is never copied (BUGS 67c); without the editor's eyelash component to
        # draw beside it, it keeps its own appearance.
        late_notes.append(diagnostics.make(
            "NPVM-CONVERT-001", character=project["name"], option="eyelash_color",
            technical_error="olho de mod sem o componente de cilios do editor", action="skipped",
            result="continued", redact=redact))
        lash_material = None
    perf_trace.mark("eyelash_material")
    if lash_material:
        eye_lashes = "eyes_mesh"
        eye_resource = eye_part["mesh"]["DepotPath"]["$value"]
        if eye_resource.startswith(namespace + "\\"):
            eye_binary = source.joinpath(*eye_resource.split("\\"))
            cli_run(cli, "convert", "serialize", eye_binary)
            eye_doc = json.loads(Path(str(eye_binary) + ".json").read_text(encoding="utf-8-sig"))
            Path(str(eye_binary) + ".json").unlink()
        else:
            eye_doc = reader.read(reader.register(eye_resource, ".mesh"))
        change_material(eye_doc, eye_part["meshAppearance"]["$value"], lash_material)
        eye_target = namespace + "\\meshes\\eyes.mesh"
        eye_origin = next((m["source_mesh"] for m in meshes.values() if m["resource"] == eye_resource), eye_resource)
        inherit_patches(reader, eye_origin, eye_target, patch_targets)
        mesh_copies[eye_target] = eye_origin
        reader.write_binary(eye_doc, source.joinpath(*eye_target.split("\\")))
        eye_part["mesh"] = ref(eye_target)
    mesh_copies.update({m["resource"]: m["source_mesh"] for m in meshes.values() if m["resource"] != m["source_mesh"]})
    perf_trace.mark("archivexl_fixes")
    fix_targets = copied_fixes(reader, mesh_copies)
    seen_shapes.update(runtime_shapes)
    missing = set(shape_keys) - seen_shapes
    if missing:
        # A head or body mod may not carry every shape the editor offers; the
        # NPV keeps the rest instead of refusing the import.
        late_notes.append(diagnostics.make(
            "NPVM-BAKE-002", character=project["name"],
            technical_error="Formas sem malha correspondente: " + ", ".join(sorted(missing)),
            action="default_shape", result="continued", redact=redact))
    components = list(selected.values())
    kept_present = sorted({p["morphResource"]["DepotPath"]["$value"] for p in components
                           if p.get("$type") == "entMorphTargetSkinnedMeshComponent"})
    if kept_present:
        components.append(morph_manager())
    # Compiled appearance data is what the game consumes. Author both forms
    # from the same component list and rebuild its component ID directory.
    definition = {"$type": "appearanceAppearanceDefinition", "name": cname("default"),
                  "components": copy.deepcopy(components), "partsValues": [], "partsOverrides": [],
                  "compiledData": {"BufferId": "0", "Flags": 0,
                      "Type": "WolvenKit.RED4.Archive.Buffer.RedPackage, WolvenKit.RED4, Version=8.19.0.0, Culture=neutral, PublicKeyToken=null",
                      "Data": {"Version": 4, "Sections": 7, "CruidIndex": -1,
                          "CruidDict": {str(i): c["id"] for i, c in enumerate(components)},
                          "Chunks": components}}}
    app_doc["Data"]["RootChunk"] = {"$type": "appearanceAppearanceResource",
        "baseEntityType": cname("WomanAverage" if project["body"] == "female" else "ManAverage"),
        "appearances": [{"HandleId": "pending", "Data": definition}]}
    perf_trace.mark("write_entities")
    renumber(app_doc)
    ent = reader.read(entity_source)
    entity_path, app_path = namespace + "\\character.ent", namespace + "\\character.app"
    root = ent["Data"]["RootChunk"]
    root["appearances"] = [{"$type": "entTemplateAppearance", "name": cname("default"),
                           "appearanceName": cname("default"), "appearanceResource": ref(app_path)}]
    root["defaultAppearance"] = cname("default")
    progress("Gerando arquivos do personagem...")
    name_key = "NPVMaker-" + digest[:16] + "-name"
    names_path = namespace + "\\names.json"
    character_files = [(names_resource(app_doc["Header"], name_key, display_name),
                        source.joinpath(*names_path.split("\\"))),
                       (app_doc, source.joinpath(*app_path.split("\\"))),
                       (ent, source.joinpath(*entity_path.split("\\")))]
    # The character files and the photo mode files go to WolvenKit in one call. A character file that fails
    # stops the build as before; a photo mode failure only drops photo mode (NPVM-PHOTO-001), as before.
    perf_trace.mark("photomode")
    photo_writes, photo_info, photo_error = [], None, None
    try:
        photo_writes, photo_info = photomode_prepare(reader, project, namespace, app_path, source, app_doc)
    except PHOTO_ERRORS as error:
        photo_error = error
    writer = getattr(reader, "write_binaries", None)
    if writer is None:
        write_all(reader, character_files)
        errors = [None] * len(character_files)
        try:
            write_all(reader, photo_writes)
        except PHOTO_ERRORS as error:
            photo_error = photo_error or error
    else:
        errors = writer(character_files + photo_writes)
    for error in errors[:len(character_files)]:
        if error is not None:
            raise error
    photo_error = photo_error or next((e for e in errors[len(character_files):] if e is not None), None)
    photo = photomode_finish(cli, namespace, display_name, source, output, photo_info, photo_error, icon)
    if photo.get("error"):
        late_notes.append(diagnostics.make("NPVM-PHOTO-001", character=project["name"], action="skipped",
                                           result="continued", technical_error=photo["error"], redact=redact))
    packed = output / "packed"
    packed.mkdir()
    step("montando archive: " + str(sum(1 for f in source.rglob("*") if f.is_file())) + " arquivos")
    perf_trace.mark("pack")
    cli_run(cli, "pack", source, "--outpath", packed)
    archives = list(packed.glob("*.archive"))
    if len(archives) != 1:
        raise ValueError("Archive pack did not produce one archive")
    perf_trace.mark("check_archive")
    check_packed_archive(cli, archives[0], entity_path, app_path, "default")
    perf_trace.mark("manifest")
    redact = diagnostics.redactor(game)
    collected["diagnostics"].extend(late_notes)
    for patch, copies in sorted(patch_targets.items()):
        mods = reader.provider(patch) if hasattr(reader, "provider") else []
        collected["diagnostics"].append(diagnostics.make(
            "NPVM-DEPENDENCY-002", character=project["name"], resource=patch,
            source_mod=", ".join(mods) if mods else None, action="archivexl_patch", result="continued",
            technical_error="patch aplicado a " + ", ".join(copies),
            external_dependency={"type": "archivexl_patch", "patch": patch, "targets": copies,
                                 "mods": mods}, redact=redact))
    result = {"format": "npv-maker-runtime-npc", "schema_version": 1,
              "project_sha256": digest, "source_project_sha256": source_digest,
              "body_strategy": body_strategy, "body_runtime": collected.get("body_runtime"),
              "name": display_name, "body": project["body"],
              "archive": str(archives[0]), "entity_path": entity_path, "appearance_name": "default",
              "record_id": "Character.NPVMaker_" + digest[:16],
              "base_record": "Character.bella", "underwear": underwear, "meshes": meshes, "options": used_options,
              "skipped_options": collected["skipped"], "diagnostics": collected["diagnostics"],
              "runtime_missing": missing_pieces, "head_runtime": head_decisions,
              "archive_xl": archive_xl_text(patch_targets, names_path, fix_targets), "name_key": name_key,
              "photomode": None if photo.get("error") else photo,
              "archivexl_fixes": {path: {"source": mesh_copies[path], "names": len(fix["names"]),
                                         "context": sorted(fix["context"])} for path, fix in fix_targets.items()},
              "component_count": len(components), "visual_match_confirmed": False,
              "components": [{"name": p["name"]["$value"], "kind": p["$type"],
                  "mesh": p.get("mesh", {}).get("DepotPath", {}).get("$value"),
                  "morphtarget": p.get("morphResource", {}).get("DepotPath", {}).get("$value"),
                  "material": p.get("meshAppearance", {}).get("$value")} for p in components],
              "eyelash_material": lash_material, "face_rig_bound": face_bound,
              "kept_morphtargets": kept_present, "runtime_morphs": runtime_morphs(project_options, runtime_shapes),
              "eye_lashes": eye_lashes,
              "embedded_copies": [{"resource": path, "source": original,
                                   "from_mod": bool(getattr(reader, "from_mod", lambda p: False)(original))}
                                  for path, original in sorted(mesh_copies.items())],
              "local_use_only": True, "tutorial_assets_used": False}
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    return result
