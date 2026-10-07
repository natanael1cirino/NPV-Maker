"""Read-only installed resource reader; private cache, no tutorial inputs."""
from __future__ import annotations
import json
import os
import sys
import re
import struct
from array import array
from bisect import bisect_left
import subprocess
import shutil
import itertools
import contextlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import perf_trace
from extract_project_apps import safe_path, declared_mesh_paths, resolve_declared_meshes


def command_chunks(items: list, room: int = 24000) -> list[list]:
    """Items in groups whose joined length stays far below the 32767 characters of a Windows command line."""
    chunks, chunk, size = [], [], 0
    for item in items:
        length = len(str(item)) + 3
        if chunk and size + length > room:
            chunks.append(chunk)
            chunk, size = [], 0
        chunk.append(item)
        size += length
    if chunk:
        chunks.append(chunk)
    return chunks


def cli_run(cli: Path, *args: str) -> str:
    # The .NET is the one the WolvenKit setup validated (runtime_entry puts it in the environment);
    # no "dotnet" folder next to WolvenKit may replace it (0.4.20, WolvenKit no longer shipped).
    env = os.environ.copy()
    result = subprocess.run([str(cli), *map(str, args)], capture_output=True,
                            encoding="utf8", errors="replace", timeout=600,
                            env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output = result.stdout + result.stderr
    # WolvenKit's hash-list extraction reports a nonzero status for archives
    # that don't contain the hash; verify the requested files after all roots.
    failed = result.returncode and not ("--hash" in args and 0 < result.returncode < 128)
    if failed or re.search(r"\[\s*\d+: Error", output):
        errors = re.search(r"\[\s*\d+: Error[^\n]*\n[\s\S]*", output)
        diagnostic = errors.group(0) if errors else output
        raise ValueError("WolvenKit: " + diagnostic[:1800] + ("\n...\n" + output[-1000:] if len(diagnostic) > 1800 else ""))
    return output


EXTRACT_WORKERS = 3
_call_numbers = itertools.count(1)


class ResourceMissing(ValueError):
    """A referenced resource exists in no installed archive."""


class UnreadableResource(ValueError):
    """The file exists in an installed archive but WolvenKit cannot read it."""

    def __init__(self, resource: str, error: str):
        super().__init__("WolvenKit nao conseguiu ler " + resource + ": " + error)
        self.resource, self.error = resource, error


def path_hash(path: str) -> str:
    """FNV-1a 64 of a lowercased depot path, as the game hashes resources."""
    value = 14695981039346656037
    for byte in path.lower().encode("utf8"):
        value = ((value ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return str(value)


def archive_hashes(archive: Path) -> set[int]:
    """Path hashes listed in an .archive index.

    RDAR header: magic, version, index offset. The index starts with 28 bytes
    (table offset/size, crc, entry count, segment and dependency counts) and then
    56-byte file entries whose first field is the FNV-1a 64 path hash. Checked on
    vtk_VanillaHD_Head_xBaebsae.archive: its 6 entries include the path hashes of
    the head mesh and morphtarget that WolvenKit lists in it.
    """
    return set(archive_hash_array(archive))


def archive_hash_array(archive: Path) -> array:
    """The same hashes, sorted in a compact array: the game archives list about
    940 thousand (measured 27/09/2026: 33 in content, 35 in ep1, read in 1.2 s)."""
    with archive.open("rb") as file:
        magic, _, index, _ = struct.unpack("<4sIQI", file.read(20))
        if magic != b"RDAR":
            raise ValueError("Arquivo .archive invalido: " + archive.name)
        file.seek(index)
        _, _, _, count = struct.unpack("<IIQI", file.read(20))
        file.seek(index + 28)
        raw = file.read(count * 56)
    if len(raw) != count * 56:
        raise ValueError("Indice truncado em " + archive.name)
    entries = array("Q")
    entries.frombytes(raw)
    if sys.byteorder != "little":
        entries.byteswap()
    return array("Q", sorted(entries[::7]))


def xl_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        return [item.strip("'\" ") for item in value[1:-1].split(",") if item.strip("'\" ")]
    return [value.strip("'\" ")] if value else []


def expand_scope(name: str, scopes: dict, seen: frozenset = frozenset()) -> list[str]:
    """Paths an ArchiveXL scope stands for; a name that is no scope is itself.

    ArchiveXL (ResourceMetaExtension::Configure/ExpandList) joins the scope
    lists of every .xl, its own bundle included, and replaces a scope listed
    inside a scope by its paths.
    """
    key = name.lower()
    if key not in scopes:
        return [name]
    if key in seen:
        return []
    result = []
    for item in scopes[key]:
        for path in expand_scope(item, scopes, seen | {key}):
            if path.lower() not in (known.lower() for known in result):
                result.append(path)
    return result


def archive_xl_resources(folders: list[Path], props: dict | None = None,
                         scope_folders: list[Path] = (), scopes_out: dict | None = None) -> tuple[dict, dict]:
    """Read `resource: copy`, `resource: patch` and `resource: scope` from installed .xl.

    Appearance mods reference files ArchiveXL creates only in game: CCXL
    Clinic/More Cyberware offer bby_extra_cyberware_app_2.app and
    hx_000__cyberware_2.app, copies that exist in no archive. A list-form mesh
    patch adds the patch mesh appearances to each target mesh.
    Returns ({copy target: source}, {patched resource: [patch resources]}),
    keys lowercased: ArchiveXL paths are case-insensitive.

    Property patches (`props:` + `targets:`) go to `props` when given, as
    {path hash of target: (source, [properties])}. MEDIDO EM 26/09/2026: Arkhe
    Beautiful Eyebrows 02 and Beautiful Makeup give their morphtargets `blob`,
    `boundingBox` and `targets` from a copy of the vanilla file, and their meshes
    `renderResourceBlob`; on disk those files lack the face shapes, so the NPV
    "THAILEND" got eyebrows and eye makeup without them, hidden in the head.

    Patch targets can be scopes, names that stand for a list of files
    (`player_head.app`); each target is replaced by its files. MEDIDO EM
    28/09/2026: Nim's More Everything patches `player_head.app` with the jaw
    slots Sedth Cyber Jaw fills; read as a file name, the slots never reached
    the head of the NPV "mariko 3.0", which showed holes under the chin and
    beside the mouth. `scope_folders` (the ArchiveXL bundle) give scopes and
    copies, never patches. MEDIDO EM 28/09/2026: the ArchiveXL eye template
    appearance (`he_000_pwa__basehead__mod`) points to
    `he_000_pwa__morphs_normal_fix.morphtarget`, which no archive ships: the
    bundle's PlayerCustomizationEyesPatch.xl copies it from the vanilla eye
    morphtarget in game. The scopes read go to `scopes_out` when given
    ({scope: [names]}, keys lowercased).
    """
    copies, patches, scopes, merged_all = {}, {}, {}, []
    entry = re.compile(r"(\S[^:\[]*?)\s*:\s*(.*)")
    for folder in list(folders) + list(scope_folders):
        modes = ("scope:", "copy:") if folder in scope_folders and folder not in folders else ("copy:", "patch:", "scope:")
        for xl in sorted(folder.rglob("*.xl")):
            in_resource, mode, mode_indent = False, None, 0
            key, key_indent, complex_key = None, None, False
            anchors, merged, receiving = {}, [], None
            for raw in xl.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = raw.rstrip()
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    in_resource, mode = text.split(":", 1)[0] == "resource", None
                    continue
                if not in_resource:
                    continue
                if mode is None or indent <= mode_indent:
                    mode = None
                    if text in modes:
                        mode, mode_indent = text[:-1], indent
                        key, key_indent, complex_key = None, None, False
                    continue
                if text.startswith("- "):
                    if key and not complex_key:
                        add_xl_pair(mode, key, text[2:].strip(), copies, patches, scopes)
                    elif receiving is not None:
                        receiving.append(text[2:].strip().strip("'\" "))
                    continue
                pair = entry.fullmatch(text)
                if not pair:
                    continue
                if key_indent is None or indent <= key_indent:
                    key, key_indent, complex_key = pair.group(1).strip(), indent, False
                    receiving = None
                    value = pair.group(2).strip()
                    if value.startswith("[") and value.endswith("]"):
                        for item in value[1:-1].split(","):
                            add_xl_pair(mode, key, item.strip(), copies, patches, scopes)
                    elif value and not value.startswith(("&", "*", "|", ">")):
                        add_xl_pair(mode, key, value, copies, patches, scopes)
                else:
                    # props:/targets: under a patch entry merge properties.
                    if not complex_key and mode == "patch":
                        merged.append({"source": key.strip("'\" "), "props": [], "targets": []})
                    complex_key = True
                    name, value = pair.group(1).strip(), pair.group(2).strip()
                    receiving = None
                    if mode != "patch" or not merged or name not in ("props", "targets"):
                        continue
                    if name == "props":
                        merged[-1]["props"] = xl_list(value)
                    elif value.startswith("*"):
                        merged[-1]["targets"].extend(anchors.get(value[1:].strip(), []))
                    else:
                        receiving = merged[-1]["targets"]
                        if value.startswith("&"):
                            anchors[value[1:].strip()] = receiving
                        else:
                            receiving.extend(xl_list(value))
            merged_all += merged
    expanded = {}
    for target, sources in patches.items():
        for path in expand_scope(target, scopes):
            bucket = expanded.setdefault(path.lower(), [])
            bucket.extend(s for s in sources if s not in bucket and s.lower() != path.lower())
    patches = {target: sources for target, sources in expanded.items() if sources}
    if props is not None:
        for patch in merged_all:
            for target in patch["targets"] if patch["props"] else []:
                for path in expand_scope(target, scopes):
                    props[int(path_hash(path))] = (patch["source"], patch["props"])
    if scopes_out is not None:
        scopes_out.update(scopes)
    return copies, patches


def fix_key(path: str) -> str:
    return path.strip().replace("/", "\\").lower()


def yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    return value


def yaml_value(value: str) -> str:
    """A value with its trailing comment removed, quotes kept."""
    value = value.strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        while value[0] == "'" and end != -1 and value[end + 1:end + 2] == "'":
            end = value.find("'", end + 2)
        return value[:end + 1] if end != -1 else value
    return re.split(r"\s#", value, maxsplit=1)[0].strip()


def xl_fix_block(text: str) -> dict:
    """The `resource: fix` mapping of one .xl, as nested dicts.

    A YAML subset: block mappings, `&anchor` on a nested mapping and `*alias`
    to it (the ArchiveXL bundle writes `names: &MaterialFix` once and
    `names: *MaterialFix` for the male mesh), flow maps `{a: b}`, quotes and
    comments. Anchors are read inside the fix block only."""
    root, anchors, stack, empty = {}, {}, [], {}
    in_resource, child_indent, fix_indent = False, None, None
    pair = re.compile(r"('(?:[^']|'')*'|\"(?:[^\"\\]|\\.)*\"|[^'\"\s][^:]*?)\s*:(?:\s+(.*))?")
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_resource = stripped.split(":", 1)[0].strip() == "resource"
            child_indent = fix_indent = None
            continue
        if not in_resource:
            continue
        if child_indent is None:
            child_indent = indent
        if indent <= child_indent:
            fix_indent = indent if indent == child_indent and yaml_value(stripped) == "fix:" else None
            stack = [(indent, root)] if fix_indent is not None else []
            continue
        if fix_indent is None or stripped.startswith("- "):
            continue
        match = pair.fullmatch(stripped)
        if not match:
            continue
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        empty.pop(id(parent), None)
        key, value = yaml_scalar(match.group(1)), yaml_value(match.group(2) or "")
        if value.startswith("*"):
            parent[key] = anchors.get(value[1:].strip())
        elif value.startswith("{") and value.endswith("}"):
            parent[key] = {yaml_scalar(k): yaml_scalar(v) for k, _, v in
                           (item.partition(":") for item in value[1:-1].split(",") if ":" in item)}
        elif not value or value.startswith("&"):
            child = {}
            parent[key] = child
            if value.startswith("&"):
                anchors[value[1:].strip()] = child
            else:
                empty[id(child)] = (parent, key)
            stack.append((indent, child))
        else:
            parent[key] = yaml_scalar(value)
    # `key:` with nothing under it is null in YAML, not an empty map.
    for parent, key in empty.values():
        parent[key] = None
    return root


def archive_xl_fixes(folders: list[Path]) -> dict:
    """Read `resource: fix` from installed .xl, joined as ArchiveXL joins them.

    ArchiveXL (ResourceMetaConfig::LoadFixes, ResourceMetaExtension::Configure,
    source read 28/09/2026) keys a fix by the exact resource path and merges the
    fixes of one path from every .xl, the bundle first and then the mod folders
    (ExtensionLoader::Configure). A fix has `names`, `paths` and `context`; an
    entry where one of them is not a map is skipped. When a mesh loads,
    `names` renames its chunk and material entry names and `context` feeds its
    dynamic materials (ResourcePatchExtension::OnMeshResourceLoad); `paths`
    is read only for the character creator file
    (CustomizationExtension), so it is not kept here.
    MEDIDO EM 28/09/2026: the bundle's eye fix renames blood_gradient_black to
    blood_gradient_black@eyes on the vanilla eye mesh; the NPC copy of that
    mesh has another path and lost it, and the Dream Galaxy eye had no
    material ("@material" template missing in the ArchiveXL log).
    Returns {path lowercased: {"names": {old: new}, "context": {attr: value}}}.
    """
    fixes = {}
    for folder in folders:
        for xl in sorted(folder.rglob("*.xl")):
            block = xl_fix_block(xl.read_text(encoding="utf-8-sig", errors="replace"))
            for target, definition in block.items():
                if not isinstance(definition, dict):
                    continue
                parts = {part: definition.get(part) for part in ("names", "paths", "context")}
                if any(part in definition and not isinstance(value, dict) for part, value in parts.items()):
                    continue
                entry = fixes.setdefault(fix_key(target), {"names": {}, "context": {}})
                for part in ("names", "context"):
                    entry[part].update({k: v for k, v in (parts[part] or {}).items() if isinstance(v, str)})
    return {path: fix for path, fix in fixes.items() if fix["names"] or fix["context"]}


BONE_PROPS = ("boneNames", "boneRigMatrices", "boneVertexEpsilons", "lodBoneMask")


def handle_table(value, table: dict | None = None) -> dict:
    table = {} if table is None else table
    if isinstance(value, dict):
        if "HandleId" in value and "Data" in value:
            table[value["HandleId"]] = value["Data"]
        for child in value.values():
            handle_table(child, table)
    elif isinstance(value, list):
        for child in value:
            handle_table(child, table)
    return table


def graft(value, table: dict, ids: list[int], seen=frozenset()):
    """Copy a property from another file: each handle becomes its own copy
    with an id above every id of the receiving file."""
    if isinstance(value, dict):
        key = value.get("HandleRefId", value.get("HandleId"))
        if key is not None:
            if key in seen or key not in table:
                raise ValueError("Handle ciclico ou ausente no patch ArchiveXL: " + str(key))
            ids[0] += 1
            number = ids[0]
            return {"HandleId": str(number), "Data": graft(table[key], table, ids, seen | {key})}
        return {k: graft(v, table, ids, seen) for k, v in value.items()}
    if isinstance(value, list):
        return [graft(v, table, ids, seen) for v in value]
    return value


def add_xl_pair(mode: str, source: str, target: str, copies: dict, patches: dict, scopes: dict | None = None) -> None:
    source, target = source.strip("'\" "), target.strip("'\" ")
    if not source or not target:
        return
    if mode == "copy":
        copies[target.lower()] = source
    elif mode == "scope":
        if scopes is not None and source.lower() != target.lower():
            scopes.setdefault(source.lower(), []).append(target)
    else:
        patches.setdefault(target.lower(), []).append(source)


class Resources:
    def __init__(self, game: Path, cli: Path, cache: Path):
        self.game, self.cli, self.cache = game, cli, cache
        self.hash_types = {}
        self.roots = [p for p in (game / "archive/pc/content", game / "archive/pc/ep1",
                     game / "red4ext/plugins/ArchiveXL/Bundle") if p.is_dir()]
        # The game loads archive/pc/mod alphabetically and the FIRST archive that
        # ships a path wins. Unbundling the whole folder let the LAST one win.
        # MEDIDO EM 26/09/2026: the NPV "Thai" got the head mesh and morphtarget
        # of vtk_VanillaHD_Head_xBaebsae while the editor showed the ones of
        # 003_EKT_CC_AsianVersion_VTK_Unique_eyes_V4; each mod file now comes
        # from the archive the game uses. Not measured: the game's tie-break for
        # names that differ only in letter case or in "_" against a letter, and
        # a Vortex modlist.txt load order.
        self.mod_folder = game / "archive/pc/mod"
        # Only archives directly in archive/pc/mod are mounted. MEDIDO EM
        # 27/09/2026 (NPV Probe 0.2, ResourceDepot.ArchiveExists): 85/85 in the
        # folder itself, 0/110 in subfolders, 0/2 fake names; the 10 files that
        # exist only in subfolders never loaded on the editor puppet (4 captures).
        self.mod_archives = (sorted(self.mod_folder.glob("*.archive"), key=lambda p: p.name.lower())
                             if self.mod_folder.is_dir() else [])
        self.mod_index = None
        # Every file is taken from the archive that ships it. Before 27/09/2026
        # a file missing from the mods ran unbundle on content, ep1, the bundle
        # and the mod folder, again at every read: the editor sweep spent 9
        # hours on CCXL apps pointing to meshes no archive ships.
        self.base_archives = [a for root in self.roots
                              for a in sorted(root.rglob("*.archive"), key=lambda p: p.name.lower())]
        self.base_index = None
        self.unindexed, self.absent, self.fresh = [], set(), set()
        self.declared = declared_mesh_paths([p for p in (game / "red4ext/plugins/ArchiveXL/Bundle",
                                                        game / "archive/pc/mod") if p.is_dir()])
        self.prop_patches, self.props_failed = {}, {}
        # The ArchiveXL bundle defines the player scopes (player_wa.ent,
        # player_wa_eyes.mesh) that mod patches name; its own patches stay out.
        self.scopes = {}
        self.copies, self.patches = archive_xl_resources(
            [p for p in (game / "archive/pc/mod",) if p.is_dir()], self.prop_patches,
            scope_folders=[p for p in (game / "red4ext/plugins/ArchiveXL/Bundle",) if p.is_dir()],
            scopes_out=self.scopes)
        # Bundle fixes (material names of the player eye, lashes, hair and
        # beard meshes) apply by path; runtime_npc.copied_fixes gives them to copies.
        self.fixes = archive_xl_fixes([p for p in (game / "red4ext/plugins/ArchiveXL/Bundle", game / "archive/pc/mod")
                                       if p.is_dir()])
        self.unreadable, self.version = {}, None
        # Read ahead (prefetch) is speculative: its stamps stay provisional until 0.1.0's own reads ask for the file.
        self.speculative, self.provisional = 0, set()
        # Activity log of the conversion (runtime_npc.build sets it): which archive each read comes from.
        self.on_step = None
        cache.mkdir(parents=True, exist_ok=True)

    def in_scope(self, scope: str, resource: str) -> bool:
        """True when `resource` is one of the files an ArchiveXL scope stands for."""
        return resource.lower() in (path.lower() for path in expand_scope(scope, self.scopes))

    def source(self, resource: str) -> str:
        """Follow ArchiveXL `resource: copy` to the archived file it duplicates.
        A copy named only by its hash (as .app files reference it) is followed too."""
        if isinstance(resource, str) and resource.isdecimal():
            if getattr(self, "copy_hashes", None) is None:
                self.copy_hashes = {path_hash(target): target for target in self.copies}
            resource = self.copy_hashes.get(resource, resource)
        seen = set()
        while isinstance(resource, str) and resource.lower() in self.copies:
            if resource.lower() in seen:
                raise ValueError("Copia ArchiveXL circular: " + resource)
            seen.add(resource.lower())
            resource = self.copies[resource.lower()]
        return resource

    def path(self, resource: str) -> Path:
        if resource in self.hash_types:
            return self.cache / "hashes" / (resource + self.hash_types[resource])
        if not safe_path(resource, Path(resource).suffix):
            raise ValueError("Invalid installed resource path: " + str(resource))
        return self.cache.joinpath(*resource.replace("/", "\\").split("\\"))

    def register(self, resource: str, suffix: str) -> str:
        if isinstance(resource, str) and resource.isdecimal() and 0 < int(resource) < 2**64:
            if resource in self.hash_types and self.hash_types[resource] != suffix:
                raise ValueError("Conflicting resource types for hash " + resource)
            self.hash_types[resource] = suffix
        elif not safe_path(resource, suffix):
            raise ValueError("Invalid " + suffix + " resource: " + str(resource))
        return resource

    def owners(self, resource: str) -> list[Path]:
        """Mod archives that ship `resource`, in the order the game loads them."""
        if self.mod_index is None:
            started = time.perf_counter()
            self.mod_index = {}
            for archive in self.mod_archives:
                try:
                    found = archive_hashes(archive)
                except (OSError, ValueError, struct.error):
                    self.unindexed.append(archive)
                    continue
                for key in found:
                    self.mod_index.setdefault(key, []).append(archive)
            perf_trace.event("index_built", kind="mod", archives=len(self.mod_archives),
                             seconds=round(time.perf_counter() - started, 3))
        return self.mod_index.get(self.key(resource), [])

    def base_owner(self, resource: str) -> Path | None:
        """Game archive that ships `resource`. With the same file in content and
        ep1 the last one is used, as when each folder was unbundled in turn into
        the cache (the game's own order between them was not measured)."""
        if self.base_index is None:
            started = time.perf_counter()
            self.base_index = []
            self.base_hashes = {}
            for archive in self.base_archives:
                try:
                    self.base_index.append((archive, archive_hash_array(archive)))
                    self.base_hashes[archive] = self.base_index[-1][1]
                except (OSError, ValueError, struct.error):
                    self.unindexed.append(archive)
            perf_trace.event("index_built", kind="base", archives=len(self.base_archives),
                             seconds=round(time.perf_counter() - started, 3))
        key, owner = self.key(resource), None
        for archive, hashes in self.base_index:
            at = bisect_left(hashes, key)
            if at < len(hashes) and hashes[at] == key:
                owner = archive
        return owner

    def key(self, resource: str) -> int:
        return int(resource) if resource in self.hash_types else int(path_hash(resource.replace("/", "\\")))

    def patched(self, resource: str) -> bool:
        """True when ArchiveXL patches properties into `resource` in game."""
        return self.key(resource) in self.prop_patches

    def from_mod(self, resource: str) -> bool:
        """True when the file the game uses for `resource` comes from a mod: a mounted mod archive
        ships it (or the file an ArchiveXL copy duplicates), or a mod patches properties into it.

        Author decision 03/10/2026 (BUGS 67c): a piece from the base game may still be baked and
        embedded in the NPV; a piece from a mod is only referenced. The ArchiveXL bundle is read
        with the game archives (self.roots), so its own copies of game files count as game files.
        """
        if not isinstance(resource, str) or not resource:
            return False
        return bool(self.owners(resource) or self.owners(self.source(resource)) or self.patched(resource))

    def props_donor(self, resource: str) -> str | None:
        """The file whose morph data ArchiveXL gives `resource` in game, if any."""
        patch = self.prop_patches.get(self.key(resource))
        return self.source(patch[0]) if patch and "blob" in patch[1] else None

    def apply_props(self, resource: str, source: str, props: list[str], write: bool = True):
        """Give the cached file the properties ArchiveXL patches into it in game.

        A mesh that receives `renderResourceBlob` also receives the donor's
        bones: the skin indices of that geometry point into the donor's bone
        list. MEDIDO EM 26/09/2026: the Arkhe eyebrow and eye makeup meshes have
        no bones on disk (the EKT eyebrow they take the geometry from has 74),
        so the NPV "THAILEND" got them without skin and they were drawn on the
        chest instead of the face.
        """
        donor = self.read(self.source(source))
        path = self.path(resource)
        if not self.serial_ok(path):
            cli_run(self.cli, "convert", "serialize", path)
        doc = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8-sig"))
        ids = [max((int(k) for k in handle_table(doc) if str(k).isdigit()), default=0)]
        table, given = handle_table(donor), donor["Data"]["RootChunk"]
        if "renderResourceBlob" in props:
            props = list(props) + [p for p in BONE_PROPS if p not in props]
        for prop in props:
            if prop in given:
                doc["Data"]["RootChunk"][prop] = graft(given[prop], table, ids)
        if not write:
            return doc, path
        self.write_binary(doc, path)

    def stamp(self, resource: str, depth: int = 0) -> str:
        """Where the cached copy of `resource` has to come from now: the archive
        the game uses (name, size, time) and the ArchiveXL patch it receives."""
        owners = self.owners(resource)
        owner = owners[0] if owners else self.base_owner(resource)
        lines = [f"{a.name}|{a.stat().st_size}|{a.stat().st_mtime_ns}"
                 for a in ([owner] if owner is not None else self.unindexed)]
        patch = self.prop_patches.get(self.key(resource))
        if patch:
            lines.append("props|" + patch[0] + "|" + ",".join(patch[1]))
            donor = self.source(patch[0])
            if depth < 2 and donor != resource:
                lines.append("donor|" + self.stamp(donor, depth + 1))
        return "\n".join(lines)

    def cached(self, resource: str) -> bool:
        # Measured in the sweep of 27/09/2026: an Arkhe eyebrow morphtarget stayed
        # in the cache with 0 face shapes (105 once patched) and every later run
        # reused it. A copy is reused only with the stamp it was made under.
        if resource in self.fresh:
            return True
        path = self.path(resource)
        marker = Path(str(path) + ".npvsrc")
        if path.is_file() and marker.is_file() and marker.read_text(encoding="utf8") == self.stamp(resource):
            self.fresh.add(resource)
            return True
        return False

    def fetch(self, resources: list[str]) -> None:
        if not self.speculative:
            for resource in resources:
                self.promote(resource)
        missing = sorted({r for r in resources if not self.cached(r)})
        perf_trace.event("fetch", asked=len(resources), missing=missing, speculative=bool(self.speculative))
        if not missing:
            return
        asked = set(missing)
        # A file ArchiveXL fills from a donor (props patch) needs the donor right away (apply_props reads
        # it). Fetching the donor here gives it the same extraction, stamp and checks it would get from
        # that nested read, in the same WolvenKit call as the file. A donor that is patched itself keeps
        # the nested read of 0.1.0.
        companions = set()
        for resource in missing:
            donor = self.donor_of(resource)
            if donor is not None and donor not in asked and not self.patched(donor):
                try:
                    if not self.cached(donor):
                        companions.add(donor)
                except ValueError:
                    pass
        missing = sorted(asked | companions)
        for resource in missing:
            path = self.path(resource)
            for stale in (path, Path(str(path) + ".json"), Path(str(path) + ".npvsrc"), Path(str(path) + ".npvpre")):
                stale.unlink(missing_ok=True)
        winners = {}
        for resource in missing:
            if resource in self.absent:
                continue
            owners = self.owners(resource)
            owner = owners[0] if owners else self.base_owner(resource)
            if owner is not None:
                winners.setdefault(owner, []).append(resource)
        for archive, group in winners.items():
            if self.on_step is not None:
                self.on_step("extraindo " + str(len(group)) + " arquivo(s) de " + archive.name)
        self.extract_winners(winners)
        # Only an archive whose index could not be read is searched blind.
        leftover = [r for r in missing if r not in self.absent and not self.path(r).is_file()]
        if leftover and self.unindexed:
            self.extract(self.unindexed, leftover)
        absent = [r for r in missing if not self.path(r).is_file()]
        self.absent.update(absent)
        # The files that were found get their patches before a missing one is
        # reported; the missing one only concerns its own piece. Files without a
        # patch are stamped first, so a donor fetched above is ready for apply_props.
        found = [r for r in missing if r not in absent]
        patched = [r for r in found if self.prop_patches.get(self.key(r))]
        for resource in found:
            if resource not in patched:
                self.write_stamp(resource)
                self.fresh.add(resource)
        if patched:
            self.apply_patches(patched)
        absent = [r for r in absent if r in asked]
        if absent:
            raise ResourceMissing("Recurso nao encontrado nos mods instalados: " + ", ".join(absent))

    @contextlib.contextmanager
    def speculation(self):
        self.speculative += 1
        try:
            yield
        finally:
            self.speculative -= 1

    def write_stamp(self, resource: str) -> None:
        if self.speculative:
            Path(str(self.path(resource)) + ".npvpre").write_text(self.stamp(resource), encoding="utf8")
            self.provisional.add(resource)
        else:
            Path(str(self.path(resource)) + ".npvsrc").write_text(self.stamp(resource), encoding="utf8")

    def promote(self, resource: str, depth: int = 0) -> None:
        """A file fetched ahead is now asked by the conversion itself: its stamp becomes final, with the donor
        0.1.0 would have read to patch it."""
        if resource in self.provisional:
            self.provisional.discard(resource)
            path = self.path(resource)
            marker = Path(str(path) + ".npvpre")
            if marker.is_file():
                os.replace(marker, Path(str(path) + ".npvsrc"))
        # 0.1.0 read the donor at the start of apply_props, even when the patch then failed.
        if depth < 4 and resource in self.fresh:
            donor = self.donor_of(resource)
            if donor is not None and donor in self.provisional:
                self.promote(donor, depth + 1)

    def donor_of(self, resource: str) -> str | None:
        patch = self.prop_patches.get(self.key(resource))
        if not patch:
            return None
        donor = self.source(patch[0])
        return donor if isinstance(donor, str) and donor and donor != resource else None

    def apply_patches(self, patched: list[str]) -> None:
        """apply_props for every patched file of one fetch, with the WolvenKit work in two calls: one
        serialize for the files and their donors, one deserialize for the results. A file whose patch
        fails is left as on disk, without a stamp, exactly as before (props_failed). When a donor is
        patched itself, order matters: the 0.1.0 loop runs unchanged."""
        if any(self.patched(d) for d in (self.donor_of(r) for r in patched) if d is not None):
            for resource in patched:
                try:
                    self.apply_props(resource, *self.prop_patches[self.key(resource)])
                except (ValueError, KeyError, TypeError, OSError) as error:
                    self.props_failed[resource] = type(error).__name__ + ": " + str(error)
                    self.fresh.add(resource)
                    continue
                self.write_stamp(resource)
                self.fresh.add(resource)
            return
        pending = []
        for resource in patched:
            path = self.path(resource)
            if not self.serial_ok(path):
                pending.append(path)
            donor = self.donor_of(resource)
            try:
                if donor is not None and donor in self.fresh and donor not in self.unreadable \
                        and not self.serial_ok(self.path(donor)):
                    pending.append(self.path(donor))
            except ValueError:
                pass
        pending = list(dict.fromkeys(pending))
        if len(pending) > 1:
            try:
                cli_run(self.cli, "convert", "serialize", *pending)
            except ValueError:
                pass  # apply_props and read() serialize each one again, one by one, as before
        results = []
        for resource in patched:
            try:
                results.append((resource, self.apply_props(resource, *self.prop_patches[self.key(resource)],
                                                           write=False)))
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.props_failed[resource] = type(error).__name__ + ": " + str(error)
                self.fresh.add(resource)
        errors = self.write_binaries([written for _, written in results])
        for (resource, _), error in zip(results, errors):
            if error is not None:
                self.props_failed[resource] = type(error).__name__ + ": " + str(error)
                self.fresh.add(resource)
                continue
            self.write_stamp(resource)
            self.fresh.add(resource)

    def contains(self, archive: Path, resource: str) -> bool:
        """True when the index of `archive` lists `resource` (mod or game archive)."""
        key = self.key(resource)
        if archive in self.mod_archives:
            if self.mod_index is None:
                self.owners(resource)
            return archive in self.mod_index.get(key, [])
        if self.base_index is None:
            self.base_owner(resource)
        hashes = self.base_hashes.get(archive)
        if hashes is None:
            return True  # unknown: never batched with another archive
        at = bisect_left(hashes, key)
        return at < len(hashes) and hashes[at] == key

    def extract_winners(self, winners: dict) -> None:
        """Extract each file from the archive the game uses, several archives per WolvenKit call.

        One `unbundle` call takes many archives and one path list, and writes every match of every
        archive (checked 06/10/2026: same bytes as one call per archive). Archives go in the same call only
        when no file asked from one of them is also in another archive of that call, so no file can come
        from an archive other than its winner; the rest get their own call, as in 0.1.0."""
        candidates = list(winners)
        holders = {r: {a for a in candidates if self.contains(a, r)} for group in winners.values() for r in group}
        calls = []
        for hashed in (False, True):
            sets = []
            for archive, group in winners.items():
                for resource in group:
                    if (resource in self.hash_types) != hashed:
                        continue
                    for archives, resources in sets:
                        trial = set(archives) | {archive}
                        if all(len(holders[r] & trial) == 1 for r in resources + [resource]):
                            if archive not in archives:
                                archives.append(archive)
                            resources.append(resource)
                            break
                    else:
                        sets.append(([archive], [resource]))
            calls.extend(sets)
        # The calls never share a file, so they run side by side (at most EXTRACT_WORKERS WolvenKit processes);
        # the first error is raised as the serial loop of 0.1.0 would have raised it.
        if len(calls) < 2:
            for archives, resources in calls:
                self.extract(archives, resources, together=True)
            return
        with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as pool:
            futures = [pool.submit(self.extract, archives, resources, True) for archives, resources in calls]
        for future in futures:
            future.result()

    def extract(self, roots: list[Path], resources: list[str], together: bool = False) -> None:
        """`together`: the roots never share a requested file (extract_winners), so one call reads them all."""
        if not roots or not resources:
            return
        groups = [roots] if together else [[root] for root in roots]
        hashes = [r for r in resources if r in self.hash_types]
        if hashes:
            number = next(_call_numbers)
            extracted = self.cache / "hash-source" / str(number)
            extracted.mkdir(parents=True, exist_ok=True)
            listing = self.cache / ("requested-hashes-" + str(number) + ".txt")
            listing.write_text("\n".join(hashes), encoding="ascii")
            for group in groups:
                cli_run(self.cli, "unbundle", *group, "--outpath", extracted, "--hash", listing)
            # WolvenKit writes <hash>.bin only for unknown names; a resource it
            # can name (mod archives carry their path list) lands at the named
            # path. Match those by the path hash (measured: CCXL eyebrow
            # morphtarget 2625047240192513416 was extracted by name).
            named = {path_hash(str(f.relative_to(extracted)).replace("/", "\\")): f
                     for f in extracted.rglob("*") if f.is_file() and f.suffix != ".bin"}
            for key in hashes:
                file = extracted / (key + ".bin")
                if not file.is_file():
                    file = named.get(key, file)
                if file.is_file():
                    target = self.path(key)
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(file, target)
        named = [r for r in resources if r not in self.hash_types]
        # Windows limits a command line to 32767 characters: paths go in chunks well below it.
        room = 24000 - sum(len(str(root)) + 3 for root in roots)
        batches, batch, size = [], [], 0
        for resource in named:
            item = len(re.escape(resource)) + 1
            if batch and (size + item > room or (not together and len(batch) == 40)):
                batches.append(batch)
                batch, size = [], 0
            batch.append(resource)
            size += item
        if batch:
            batches.append(batch)
        for batch in batches:
            regex = "^(?:" + "|".join(re.escape(r) for r in batch) + ")$"
            for group in groups:
                cli_run(self.cli, "unbundle", *group, "--outpath", self.cache, "--regex", regex)

    def serial_ok(self, path: Path) -> bool:
        # WolvenKit leaves a 0-byte JSON when it cannot read a file.
        serial = Path(str(path) + ".json")
        return serial.is_file() and serial.stat().st_size > 0

    def read(self, resource: str) -> dict:
        resource = self.source(resource)
        perf_trace.event("read", resource=resource,
                         ready=resource in self.fresh and self.serial_ok(self.path(resource)))
        self.fetch([resource])
        path = self.path(resource)
        if resource in self.unreadable:
            raise UnreadableResource(resource, self.unreadable[resource])
        if not self.serial_ok(path):
            try:
                cli_run(self.cli, "convert", "serialize", path)
            except ValueError as error:
                self.unreadable[resource] = str(error)
            if not self.serial_ok(path):
                self.unreadable.setdefault(resource, "WolvenKit produced no JSON")
                raise UnreadableResource(resource, self.unreadable[resource])
        started = time.perf_counter()
        doc = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8-sig"))
        resolve_declared_meshes(doc, self.declared)
        perf_trace.event("json_load", resource=resource, seconds=round(time.perf_counter() - started, 3))
        return doc

    def serialize(self, resources: list[str]) -> None:
        resources = [self.source(r) for r in resources]
        self.fetch(resources)
        pending = [(r, str(self.path(r))) for r in sorted(set(resources)) if not self.serial_ok(self.path(r))]
        sizes = command_chunks([path for _, path in pending])
        starts = [sum(len(c) for c in sizes[:i]) for i in range(len(sizes))]
        for index, size in zip(starts, map(len, sizes)):
            batch = pending[index:index + size]
            if self.on_step is not None:
                self.on_step("convertendo " + str(len(batch)) + " arquivo(s) para leitura")
            try:
                cli_run(self.cli, "convert", "serialize", *[path for _, path in batch])
            except ValueError:
                # One file WolvenKit cannot read fails the whole batch (seen:
                # an old-format mod .app with castShadows as Bool). Retry one
                # by one; the unreadable one is decided by its option.
                for resource, path in batch:
                    if self.serial_ok(Path(path)):
                        continue
                    try:
                        cli_run(self.cli, "convert", "serialize", path)
                    except ValueError as error:
                        self.unreadable[resource] = str(error)

    def provider(self, resource: str) -> list[str]:
        """Installed mod archives that ship `resource` (for diagnostics), the one
        the game uses first."""
        return [archive.stem for archive in self.owners(resource)]

    def tool_version(self) -> str:
        if self.version is None:
            try:
                text = cli_run(self.cli, "--version").strip().splitlines()
                self.version = text[-1].strip() if text else "desconhecida"
            except (ValueError, OSError):
                self.version = "desconhecida"
        return self.version

    def write_binaries(self, items: list) -> list:
        """write_binary for many (doc, destination) pairs with one deserialize call.

        Checked 06/10/2026: `convert deserialize a.json b.json` writes each binary beside its JSON, byte for
        byte as the single call with --outpath. A file that is not confirmed afterwards (missing, or not
        rewritten) goes through write_binary alone, so its error is the one 0.1.0 gave. Returns one error
        (or None) per item."""
        errors = [None] * len(items)
        if len(items) > 1:
            serials, before = [], []
            for doc, destination in items:
                destination.parent.mkdir(parents=True, exist_ok=True)
                serial = destination.with_name(destination.name + ".json")
                serial.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf8")
                serials.append(serial)
                before.append(destination.stat().st_mtime_ns if destination.is_file() else None)
            try:
                cli_run(self.cli, "convert", "deserialize", *serials)
            except ValueError:
                pass
            pending = []
            for index, ((doc, destination), serial) in enumerate(zip(items, serials)):
                if destination.is_file() and destination.stat().st_mtime_ns != before[index]:
                    serial.unlink(missing_ok=True)
                else:
                    pending.append(index)
        else:
            pending = list(range(len(items)))
        for index in pending:
            try:
                self.write_binary(*items[index])
            except (ValueError, OSError) as error:
                errors[index] = error
        return errors

    def prefetch(self, resources: list) -> None:
        """Extract and serialize ahead, in batch, files the conversion reads next. Nothing is decided
        here: read() of each file still raises what it raised in 0.1.0 (missing, unreadable)."""
        wanted = []
        for resource in resources:
            if not isinstance(resource, str) or not resource or resource in wanted:
                continue
            try:
                self.path(self.source(resource))
            except ValueError:
                continue
            wanted.append(resource)
        if not wanted:
            return
        with self.speculation():
            try:
                self.serialize(wanted)
            except (ValueError, OSError):
                try:
                    self.serialize([w for w in wanted if w not in self.absent and self.path(self.source(w)).is_file()])
                except (ValueError, OSError):
                    pass

    def write_binary(self, doc: dict, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        serial = destination.with_name(destination.name + ".json")
        serial.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf8")
        cli_run(self.cli, "convert", "deserialize", serial, "--outpath", destination.parent)
        serial.unlink()
        if not destination.is_file():
            raise ValueError("Conversor nao produziu " + destination.name)
