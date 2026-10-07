"""Body of the NPC from the puppet the character editor rendered (0.4.14 DEV).

The project keeps two records: the editor options (what the user chose) and,
since 0.4.14, `runtime_manifest` (the visual components the game mounted on
the editor puppet, read by NPVMaker.reds). This module turns the second into
the body components of the NPC:

    runtime manifest -> body candidates -> strategy filter -> body components

Measured with the NPV Probe (docs/FASE1-PROBE.md, docs/FASE1-PROBE-02.md): each
component names the .app and the appearance that created it; a component whose
mesh is 0 draws nothing; a file absent from the depot draws nothing; the
preview keeps copies from appearances no option selected (arms of
"pwa_default") and they draw too. Which of those copies the NPC should carry
is not decided: SELECTED_TPP and RUNTIME_TPP are both built for an in-game A/B.
No rule here uses the name of a mod, preset or body.
"""
from __future__ import annotations

import copy
import hashlib
import re

STRATEGIES = ("legacy", "selected_tpp", "runtime_tpp")
SCHEMA = 1
# NONE: no file (mesh 0). MISSING: the depot has no such file. LOADED: the
# engine loaded it. EXISTS_NOT_LOADED: the depot has it and loading failed.
# UNOBSERVED: the depot has it and loading had not finished at capture.
STATES = ("NONE", "MISSING", "LOADED", "EXISTS_NOT_LOADED", "UNOBSERVED")
USABLE = ("LOADED", "UNOBSERVED")
BODY_PARTS = ("Body", "Arms")
# Editor options of the Body and Arms parts that stay on the 0.4.13 path in
# this slice: overlays with their own pipeline and the censorship pieces
# (decided with the author on 27/09/2026: no censorship change here). Matched
# on the editor's option names, the same names vanilla and mods register.
OUTSIDE_SLICE = re.compile(r"tattoo|scar|censor|underpants", re.I)
FIELDS = ("name", "type", "enabled", "owner_appearance", "owner_app", "field", "hash", "path",
          "mesh_appearance", "chunk_mask", "state")
MAX_COMPONENTS = 1024


def state(component: dict) -> str:
    """One place decides the resource state of a runtime component."""
    value = str(component.get("hash") or "0")
    if value in ("0", ""):
        return "NONE"
    captured = component.get("state")
    return captured if captured in STATES else "UNOBSERVED"


def manifest(project: dict) -> tuple[list[dict] | None, str]:
    """Runtime components of a project, or None and the reason when the
    project has no usable runtime record (older projects, preview missing)."""
    section = project.get("runtime_manifest")
    if section is None:
        return None, "projeto sem manifest de runtime (salvo antes da 0.4.14)"
    if not isinstance(section, dict) or section.get("schema") != SCHEMA:
        return None, "manifest de runtime em formato desconhecido"
    if section.get("status") != "captured":
        return None, "captura do editor indisponivel: " + str(section.get("reason") or "sem motivo")
    raw = section.get("components")
    if raw == {}:
        raw = []
    if not isinstance(raw, list) or len(raw) > MAX_COMPONENTS:
        return None, "lista de componentes do manifest invalida"
    components = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, "componente invalido no manifest"
        entry = {key: item.get(key) for key in FIELDS}
        for key in FIELDS:
            if key != "enabled" and entry[key] is not None and (not isinstance(entry[key], str)
                                                                or len(entry[key]) > 512):
                return None, "campo invalido no manifest: " + key
        if not entry["name"] or entry["field"] not in ("mesh", "morphResource"):
            return None, "componente sem nome ou sem recurso no manifest"
        if entry["hash"] is not None and not str(entry["hash"]).isdecimal():
            return None, "hash invalido no manifest"
        entry["index"] = index
        entry["state"] = state(entry)
        components.append(entry)
    return components, ""


def _norm(path) -> str:
    return str(path or "").replace("/", "\\").lower()


def _chooses(option: dict, appearance: str) -> bool:
    # CCXL options name a choice "<option>/<appearance>" (measured with the
    # heterochromia mod); the component carries the appearance alone.
    name = str(option.get("selected_name") or "")
    return name == appearance or name.split("/")[-1] == appearance


def classify(component: dict, options: list[dict]) -> dict:
    """Where a runtime component comes from, from its .app and appearance."""
    active = [o for o in options if o.get("active") and o.get("kind") == "appearance"
              and o.get("selected_name") not in ("", "None", None)]
    app = _norm(component.get("owner_app"))
    owner = component.get("owner_appearance") or ""
    same_app = [o for o in active if app and _norm(o.get("resource_path")) == app]
    chosen = [o for o in same_app if _chooses(o, owner)]
    related = chosen or same_app
    parts = {o.get("body_part") for o in related}
    fpp = [o for o in related if str(o["name"]).endswith("_fpp")]
    perspective = ("UNKNOWN" if not related else "FPP" if len(fpp) == len(related)
                   else "TPP" if not fpp else "UNKNOWN")
    outside = any(OUTSIDE_SLICE.search(str(o["name"])) for o in related)
    return dict(selected_by_editor=bool(chosen), options=[o["name"] for o in related],
                body_part=parts.pop() if len(parts) == 1 else ("MIXED" if parts else None),
                perspective=perspective, outside_slice=outside)


def select(components: list[dict], options: list[dict], strategy: str) -> dict:
    """Body components to convert under one strategy, and why the others stay out.

    SELECTED_TPP: body components of third-person options whose .app and
    appearance the editor has selected now. RUNTIME_TPP: every third-person
    body component the puppet carries, selected or not (preview copies such
    as the "pwa_default" arms included). Both skip NONE and MISSING files.
    """
    if strategy not in ("selected_tpp", "runtime_tpp"):
        raise ValueError("Estrategia de corpo desconhecida: " + str(strategy))
    included, skipped = [], []
    for component in components:
        info = classify(component, options)
        row = dict(component, **info)
        if info["body_part"] not in BODY_PARTS:
            continue
        reason = None
        if info["outside_slice"]:
            reason = "fora_da_fatia"
        elif info["perspective"] != "TPP":
            reason = "perspectiva_" + info["perspective"].lower()
        elif strategy == "selected_tpp" and not info["selected_by_editor"]:
            reason = "nao_escolhido_no_editor"
        elif row["state"] not in USABLE:
            reason = "recurso_" + row["state"].lower()
        (skipped if reason else included).append(dict(row, reason=reason) if reason else row)
    return dict(strategy=strategy, included=included, skipped=skipped)


def slice_options(options: list[dict]) -> tuple[list[dict], list[dict]]:
    """Editor options whose components the runtime body replaces, and the rest."""
    body, rest = [], []
    for option in options:
        inside = option.get("body_part") in BODY_PARTS and not OUTSIDE_SLICE.search(str(option["name"]))
        (body if inside else rest).append(option)
    return body, rest


def _geometry(part: dict) -> str:
    key = "morphResource" if "morphResource" in part else "mesh"
    return str(((part.get(key) or {}).get("DepotPath") or {}).get("$value") or "")


def _hash(path: str, path_hash) -> str:
    return path if path.isdecimal() else path_hash(path)


def _set_resource(part: dict, component: dict, register, safe_path, path_hash) -> None:
    key = "morphResource" if component["field"] == "morphResource" else "mesh"
    current = _geometry(part)
    if current and _hash(current, path_hash) == component["hash"]:
        return
    suffix = ".morphtarget" if key == "morphResource" else ".mesh"
    path = component.get("path") or ""
    if not (path and not path.isdecimal() and safe_path(path, suffix)):
        path = register(component["hash"], suffix)
    reference = copy.deepcopy(part.get(key) or {"DepotPath": {"$type": "ResourcePath", "$storage": "string"},
                                                 "Flags": "Default"})
    reference.setdefault("DepotPath", {})["$value"] = path
    part[key] = reference


def _set_chunk_mask(part: dict, mask: str) -> None:
    if not mask or not str(mask).isdecimal():
        return
    part["chunkMask"] = str(mask) if isinstance(part.get("chunkMask"), str) else int(mask)


def _rename(part: dict, number: int) -> None:
    """A second copy of one component (different appearance) gets its own name
    and id, as the preview holds both under one name."""
    name = part["name"]["$value"] + "__npv_rt" + str(number)
    part["name"] = dict(part["name"], **{"$value": name})
    new_id = str(int(hashlib.sha256(name.encode("utf8")).hexdigest()[:15], 16))
    if isinstance(part.get("id"), dict):
        part["id"] = dict(part["id"], **{"id": new_id} if "id" in part["id"] else {"$value": new_id})
    elif part.get("id") is not None:
        part["id"] = new_id if isinstance(part["id"], str) else int(new_id)


def body_parts(reader, redirects, selection: dict, options: list[dict], collect, register,
               safe_path, path_hash, character: str = "", redact=None, patches=None) -> dict:
    """Component definitions for the selected runtime body.

    Each component is read from the appearance that created it (its .app and
    appearance name) through the converter's own collect_components, then
    takes the file, mesh appearance and chunk mask the game used. A component
    the .app lacks is looked up in the same appearance of the .app files that
    ArchiveXL patches into it (`resource: patch` list form, `patches` from the
    reader): ArchiveXL adds their components to the appearance of the same
    name, and the puppet names the patched .app as the origin. Measured
    27/09/2026: t0_000_base__full.app got three body pieces this way. Copies that
    are equal in name, file and appearance become one component with the
    union of their chunks (same drawing: measured, the two body halves of the
    editor split the chunks); copies that differ stay separate.
    """
    groups = {}
    # The copy the editor selected keeps the component name; a preview copy
    # of another appearance is the one renamed.
    ordered = sorted(selection["included"], key=lambda c: (not c["selected_by_editor"], c["index"]))
    for component in ordered:
        key = (_norm(component["owner_app"]), component["owner_appearance"])
        groups.setdefault(key, []).append(component)
    by_name = {o["name"]: o for o in options}
    parts, used, failures, merged = {}, [], [], []
    names_seen = {}
    for (app, appearance), members in groups.items():
        option = next((by_name[n] for n in members[0]["options"] if n in by_name
                       and _chooses(by_name[n], appearance)), None)
        synthetic = dict(option) if option else dict(
            name=members[0]["options"][0] + ":runtime" if members[0]["options"] else "runtime",
            body_part=members[0]["body_part"], kind="appearance", active=True, editable=True)
        synthetic["resource_path"] = members[0]["owner_app"]
        synthetic["selected_name"] = appearance
        result = collect(reader, [synthetic], redirects, character=character, redact=redact)
        if result["skipped"]:
            for member in members:
                failures.append(dict(member, reason=result["skipped"][0]["reason"]))
            continue
        definitions = list(result["selected"].values())
        present = {p.get("name", {}).get("$value") for p in definitions}
        if any(m["name"] not in present for m in members):
            for patch in (patches or {}).get(app, []):
                extra = dict(synthetic, name=synthetic["name"] + ":patch", resource_path=patch)
                patched = collect(reader, [extra], redirects, character=character, redact=redact)
                if not patched["skipped"]:
                    definitions += list(patched["selected"].values())
        for member in members:
            candidates = [p for p in definitions if p.get("name", {}).get("$value") == member["name"]]
            exact = [p for p in candidates if _hash(_geometry(p), path_hash) == member["hash"]]
            if not (exact or candidates):
                failures.append(dict(member, reason="componente ausente da aparencia " + appearance))
                continue
            part = copy.deepcopy((exact or candidates)[0])
            _set_resource(part, member, register, safe_path, path_hash)
            if member.get("mesh_appearance") not in (None, "", "None"):
                part["meshAppearance"] = dict(part.get("meshAppearance") or {"$type": "CName", "$storage": "string"},
                                              **{"$value": member["mesh_appearance"]})
            _set_chunk_mask(part, member.get("chunk_mask"))
            identity = (member["name"], member["hash"], member.get("mesh_appearance"))
            if identity in parts:
                previous = parts[identity]
                if "chunkMask" in previous and "chunkMask" in part:
                    united = int(previous["chunkMask"]) | int(part["chunkMask"])
                    previous["chunkMask"] = str(united) if isinstance(previous["chunkMask"], str) else united
                merged.append(member["name"])
                used.append(dict(component=previous["name"]["$value"], source=member["name"], hash=member["hash"],
                                 owner_app=member["owner_app"], owner_appearance=appearance,
                                 selected_by_editor=member["selected_by_editor"], state=member["state"],
                                 mesh_appearance=member.get("mesh_appearance"), merged=True))
                continue
            count = names_seen.get(member["name"], 0)
            names_seen[member["name"]] = count + 1
            if count:
                _rename(part, count)
            parts[identity] = part
            used.append(dict(component=part["name"]["$value"], source=member["name"], hash=member["hash"],
                             owner_app=member["owner_app"], owner_appearance=appearance,
                             selected_by_editor=member["selected_by_editor"], state=member["state"],
                             mesh_appearance=member.get("mesh_appearance")))
        for note in result["diagnostics"]:
            note.setdefault("slot", "")
    return dict(parts=list(parts.values()), used=used, failures=failures, merged=merged)


BINDINGS = ("skinning", "parentTransform", "controlBinding")


def _bound_names(part: dict) -> set:
    names = set()
    for field in BINDINGS:
        data = (part.get(field) or {}).get("Data") or {}
        name = (data.get("bindName") or {}).get("$value")
        if name and name != "None":
            names.add(name)
    return names


def bound_supports(parts: list[dict], legacy: list[dict]) -> list[dict]:
    """Components without geometry that the runtime body pieces bind to.

    MEDIDO EM 02/10/2026 (AFT, V masculino, SELECTED_TPP): the runtime manifest
    lists only mesh and morph components, so the body built from it dropped
    penis_dangles (entAnimatedComponent with the dangle rig) while the penis
    mesh kept skinning and parentTransform bound to it; in game the mesh hung
    off the body. A part without geometry that a kept part names in skinning,
    parentTransform or controlBinding comes from the editor options' own
    components, and so on for what it binds to in turn.
    """
    present = {p.get("name", {}).get("$value") for p in parts}
    supports = {}
    for part in legacy:
        name = part.get("name", {}).get("$value")
        if name and not _geometry(part) and name not in present:
            supports.setdefault(name, part)
    wanted = set().union(*(_bound_names(p) for p in parts)) if parts else set()
    carried = []
    while wanted:
        name = wanted.pop()
        part = supports.pop(name, None)
        if part is None:
            continue
        carried.append(copy.deepcopy(part))
        wanted |= _bound_names(part)
    return carried


def essential_missing(parts_used: list[dict], selection: dict, options: list[dict], essential) -> list[str]:
    """Essential body options (body, feet, arms) with no runtime component."""
    covered = {name for row in selection["included"] if any(r["source"] == row["name"] and
               r["owner_app"] == row["owner_app"] for r in parts_used) for name in row["options"]}
    wanted = [o["name"] for o in options if o.get("active") and o.get("kind") == "appearance"
              and o.get("body_part") in BODY_PARTS and essential.fullmatch(str(o["name"]))
              and o.get("selected_name") not in ("", "None")]
    return [name for name in wanted if name not in covered]


def compare(legacy: list[dict], runtime: list[dict], path_hash) -> dict:
    """OLD converter body vs RUNTIME body, by component name and file."""
    def key(part):
        return (part["name"]["$value"].split("__npv_rt")[0], _hash(_geometry(part), path_hash))

    def label(part):
        return (part["name"]["$value"] + " (" + (_geometry(part) or "0") + " / "
                + str((part.get("meshAppearance") or {}).get("$value")) + ")")
    old = {key(p): p for p in legacy}
    new = {}
    for part in runtime:
        new.setdefault(key(part), []).append(part)
    added = [label(p) for k, ps in new.items() if k not in old for p in ps]
    lost = [label(p) for k, p in old.items() if k not in new]
    recolored = [label(ps[0]) + " antes " + str((old[k].get("meshAppearance") or {}).get("$value"))
                 for k, ps in new.items() if k in old and all(
                     (p.get("meshAppearance") or {}).get("$value") != (old[k].get("meshAppearance") or {}).get("$value")
                     for p in ps)]
    extra_copies = [label(p) for k, ps in new.items() if len(ps) > 1 for p in ps[1:]]
    return dict(added=added, lost=lost, recolored=recolored, extra_copies=extra_copies,
                legacy_count=len(legacy), runtime_count=len(runtime))
