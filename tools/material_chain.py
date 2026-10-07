"""Files the materials an NPV really uses reach in game (BUGS 68, author rule 04/10/2026).

Skin, eyebrow and texture mods often replace a base game .mi or .xbm instead of shipping a new path. Those
files are not in the mesh: component appearance -> mesh appearance (chunkMaterials) -> materialEntries ->
local instance or external .mi -> .mi base (baseMaterial) and values -> textures, .mlsetup layers. Only the
appearance the component uses is followed; files are read as the game serves them (Resources: the mod
archive that wins first), so a mod's own .mi leads to the files that mod points at.

Measured 04/10/2026 on the NPV RED (output/validation/68-overrides/MAPA.md): the chain reaches Preem Skin,
Arkhe Universal Skin Tone HEAD and ANRUI DarkEyebrows, which the export missed, and none of four installed but
unused skin mods.

ArchiveXL dynamic materials (BUGS 76, author scope 05/10/2026; ArchiveXL >= 1.13, redmodding wiki): a chunk
material "X@ctx" takes the material entry "@ctx", a path that starts with * is dynamic and {material} is X. Measured
on the RED hair (Y2K Ponytail): ginger_strawberry@long -> @long -> *.../hair_profiles/{material}.hp ->
hair_profiles/ginger_strawberry.hp. Only {material} is resolved: player tokens ({gender}, {body}, {arms}, {feet},
{sleeves}, {skin_color}, {hair_color}, {camera}) have no value proven for an NPC, so a path with any other token
stays unresolved and never makes a requirement. The ArchiveXL `resource: fix` names of the mesh are applied first,
and an appearance with no chunk materials takes the first appearance that has them as template (ArchiveXL rule).

Readers give mesh(path) -> serialized mesh and references(path) -> depot paths of a material file, embedded
files included. FastReader (BUGS 68 performance round) takes meshes from the conversion job and references
from the archive imports (archive_imports); WolvenKitReader is the slow path, used per file when the fast one
cannot read it.
"""
from __future__ import annotations

FOLLOW = (".mi", ".mlsetup", ".mltemplate")
# Shader templates and engine parameter sets are shared by every material of a kind: a mod reached only
# through them changes all skin, not this NPV. Author decision 04/10/2026: information, never a requirement.
SHARED = (".mt", ".remt", ".sp")
MAX_LEVELS = 8
READ_ERRORS = (ValueError, KeyError, TypeError, OSError)


def depot_paths(node, out: list) -> list:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "DepotPath" and isinstance(value, dict) and value.get("$storage") == "string":
                if value.get("$value"):
                    out.append(value["$value"])
            else:
                depot_paths(value, out)
    elif isinstance(node, list):
        for value in node:
            depot_paths(value, out)
    return out


def dynamic(text: str) -> bool:
    return "@" in text or "*" in text or "{" in text


def resolve_path(path: str, material: str | None) -> str | None:
    """The file an ArchiveXL dynamic path stands for, or None when it needs a value not proven here."""
    if path.startswith("*"):
        path = path[1:]
        if material is not None:
            path = path.replace("{material}", material)
    return None if "{" in path or "}" in path or "*" in path or "@" in path else path


def chunk_names(appearances: list, chosen: dict, appearance: str) -> list[str]:
    names = [n.get("$value") for n in chosen.get("chunkMaterials") or [] if isinstance(n, dict) and n.get("$value")]
    if names:
        return names
    # ArchiveXL: an appearance without chunk materials uses the first one that has them, with its own name.
    template = next((a for a in appearances if a and a.get("chunkMaterials")), None)
    if template is None:
        return []
    old = template.get("name", {}).get("$value") or ""
    result = []
    for name in (n.get("$value") for n in template["chunkMaterials"] if isinstance(n, dict) and n.get("$value")):
        head, at, context = name.partition("@")
        result.append(appearance + at + context if at and head == old else (appearance if name == old else name))
    return result


def mesh_layer(mesh_doc: dict, fix: dict | None = None) -> dict:
    """Appearances and material entries of one mesh, with the names its ArchiveXL fix gives them."""
    root = mesh_doc["Data"]["RootChunk"]
    renames = (fix or {}).get("names") or {}
    entries = {}
    for entry in root.get("materialEntries") or root.get("materials") or []:
        name = entry.get("name", {}).get("$value")
        if name:
            entries.setdefault(renames.get(name, name), entry)
    return {"appearances": [a.get("Data", a) if isinstance(a, dict) else None for a in root.get("appearances") or []],
            "entries": entries, "renames": renames,
            "local": (root.get("localMaterialBuffer") or {}).get("materials") or root.get("preloadLocalMaterialInstances")
            or root.get("localMaterialInstances") or [],
            "external": root.get("externalMaterials") or root.get("preloadExternalMaterials") or []}


def find_appearance(layer: dict, appearance: str) -> dict | None:
    return next((a for a in layer["appearances"] if a and a.get("name", {}).get("$value") == appearance), None)


def entry_paths(layer: dict, name: str) -> tuple[list[str], list[str]] | None:
    """Files of the material entry a chunk material name takes in this mesh; None when it has none."""
    head, at, context = name.partition("@")
    # An entry with the exact name wins (the ArchiveXL bundle fix renames the eye entries to X@eyes too);
    # only without one does "X@ctx" take the "@ctx" template.
    entry = layer["entries"].get(name) or (layer["entries"].get(at + context) if at else None)
    if entry is None:
        return None
    index = entry.get("index", 0)
    pool = layer["local"] if entry.get("isLocalInstance") else layer["external"]
    if not (isinstance(index, int) and 0 <= index < len(pool)):
        return None
    found, left = [], []
    for path in depot_paths(pool[index], []):
        resolved = resolve_path(path, head if at else None)
        if resolved is None:
            left.append(path)
        else:
            found.append(resolved)
    return found, left


def material_roots(mesh_doc: dict, appearance: str, fix: dict | None = None,
                   patch_layers=None) -> tuple[list[str], list[str]] | None:
    """Files named by the materials of `appearance` only, and the dynamic paths left unresolved.

    BUGS 77 (05/10/2026): an appearance the mesh lacks may come from an ArchiveXL `resource: patch` mesh
    (measured: Beanie's CCXL Clinic adds bby_cyberware_01..06 to the vanilla freckles mesh). `patch_layers()`
    gives the mesh_layer of each patch of this mesh; exactly one must have the appearance, and its materials are
    looked up in the patch first and then in the mesh. Order, includes and excludes of patches are not read
    (item 29): two patches with the appearance, or the same material resolving to other files in the patch and
    in the mesh, leave it unresolved. None when the appearance or its materials cannot be told."""
    target = mesh_layer(mesh_doc, fix)
    chosen, owner, layers = find_appearance(target, appearance), target, [target]
    if chosen is None:
        if patch_layers is None:
            return None
        providers = [layer for layer in patch_layers() if find_appearance(layer, appearance)]
        if len(providers) != 1:
            return None
        owner = providers[0]
        chosen, layers = find_appearance(owner, appearance), [owner, target]
    names = [owner["renames"].get(n, n) for n in chunk_names(owner["appearances"], chosen, appearance)]
    if not names:
        return None
    found, left = [], []
    for name in dict.fromkeys(names):
        results = [result for result in (entry_paths(layer, name) for layer in layers) if result is not None]
        if not results:
            return None
        if any(sorted(result[0]) != sorted(results[0][0]) or sorted(result[1]) != sorted(results[0][1])
               for result in results[1:]):
            return None
        found += results[0][0]
        left += results[0][1]
    return found, left


def closure(reader, roots: list[str]) -> tuple[list[str], list[str]]:
    """Every file the roots reach, following .mi/.mlsetup/.mltemplate level by level."""
    seen, order, unread = set(), [], []
    level = list(roots)
    for _ in range(MAX_LEVELS):
        fresh = []
        for path in level:
            if path and path.lower() not in seen and not dynamic(path):
                seen.add(path.lower())
                order.append(path)
                fresh.append(path)
        follow = [p for p in fresh if p.lower().endswith(FOLLOW)]
        if not follow:
            break
        if hasattr(reader, "prefetch"):
            try:
                reader.prefetch(follow)
            except READ_ERRORS:
                pass  # read one by one below; the unreadable ones are reported
        level = []
        for path in follow:
            try:
                level += reader.references(path)
            except READ_ERRORS:
                unread.append(path)
    return order, unread


def npv_material_files(reader, manifest: dict, fixes: dict | None = None, patches: dict | None = None) -> dict:
    """Material files of the tested NPV: {files, unresolved components, unread files, unresolved dynamic paths}.

    `fixes`: ArchiveXL `resource: fix` by lower-case path (runtime_resources.archive_xl_fixes); a generated copy
    takes the fix of its original, as runtime_npc.copied_fixes gives it in game. `patches`: ArchiveXL list
    `resource: patch`, lower-case target path -> patch meshes (runtime_resources.Resources.patches); a copy takes
    the patches of its original, as the NPV repeats them on the copy."""
    copies = {c["resource"].lower(): c["source"] for c in manifest.get("embedded_copies") or []
              if c.get("resource") and c.get("source")}
    fixes, patches = fixes or {}, patches or {}
    roots, unresolved, tokens = [], [], []
    for component in manifest.get("components") or []:
        appearance = component.get("material")
        mesh = component.get("mesh") or ""
        morph = component.get("morphtarget") or ""
        if not appearance or not (mesh or morph):
            continue
        try:
            source = copies.get(mesh.lower(), mesh)
            if not source:
                base = depot_paths(reader.mesh(morph)["Data"]["RootChunk"].get("baseMesh"), [])
                source = base[0] if base else ""
            key = source.strip().replace("/", "\\").lower()
            fix = fixes.get(key) if source else None

            def patch_layers(key=key, mesh=mesh):
                paths = patches.get(key) or patches.get(mesh.strip().replace("/", "\\").lower()) or []
                return [mesh_layer(reader.mesh(path), fixes.get(path.lower())) for path in paths]
            found = material_roots(reader.mesh(source), appearance, fix, patch_layers) if source else None
        except READ_ERRORS:
            found = None
        if found is None:
            unresolved.append(str(component.get("name") or mesh or morph))
            continue
        roots += found[0]
        tokens += [p for p in found[1] if p not in tokens]
    files, unread = closure(reader, roots)
    return {"files": files, "unresolved": unresolved, "unread": unread, "unresolved_paths": tokens}


def shared(resource: str) -> bool:
    return resource.lower().endswith(SHARED)


class WolvenKitReader:
    """Slow path: files extracted and serialized by WolvenKit (runtime_resources.Resources)."""

    def __init__(self, resources):
        self.resources = resources

    def prefetch(self, paths: list[str]) -> None:
        self.resources.serialize(paths)

    def mesh(self, path: str) -> dict:
        return self.resources.read(path)

    def references(self, path: str) -> list[str]:
        # The whole document: an .mlsetup embedded in an .mi lists its layers under EmbeddedFiles.
        return depot_paths(self.resources.read(path).get("Data"), [])


class FastReader:
    """Meshes and morphtargets as the conversion serialized them (npc/installed-resources), references from
    the archive imports; each file the fast path cannot give falls back to WolvenKit."""

    def __init__(self, installed, references, slow):
        self.installed, self.fast, self.slow = installed, references, slow
        self.fallbacks = []

    def mesh(self, path: str) -> dict:
        serial = self.installed(path)
        if serial is not None:
            return serial
        self.fallbacks.append(path)
        return self.slow.mesh(path)

    def references(self, path: str) -> list[str]:
        if self.fast is not None:
            try:
                return self.fast.references(path)
            except READ_ERRORS:
                pass
        self.fallbacks.append(path)
        return self.slow.references(path)
