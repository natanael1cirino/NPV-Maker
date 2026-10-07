"""The game side without CET (docs/SEM-CET-MAPA.md, author decision 30/09/2026: all in game, RedFileSystem).

REDscript can only read and write plain files directly in `r6/storages/NPVMaker` (RedFileSystem: no sub
folders, measured by the NPV FS Probe 0.3) and has no JSON reader and no real clock. The converter keeps
its own folder (`red4ext/plugins/NPVMaker/data/projects`, same layout as the old CET folder) and this
bridge is the only thing that touches the storage:

- inbound: requests the game wrote are moved into the converter folder; a saved project ("save-<x>.draft.json")
  gets its dated id here and, when asked, its import request;
- outbound: every status file the converter writes is mirrored as "<name>.txt" in lines of
  "key<TAB>value" ending with "end<TAB>1" (the game ignores a file read before that line);
- latest.txt: the newest project, ready for ABRIR ULTIMO PROJETO.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

import diagnostics
import i18n
from companion_expansion import project_info
from ingame_companion_worker import write_panel_file

STORAGE = "r6/storages/NPVMaker"
CET_PROJECTS = "bin/x64/plugins/cyber_engine_tweaks/mods/NPVMaker/projects"
PROJECT = re.compile(r"npv-\d{8}T\d{6}Z-\d{4}\.npv\.json")
META = re.compile(r"npv-\d{8}T\d{6}Z-\d{4}\.npv\.meta\.json")
DRAFT = re.compile(r"save-([a-z0-9]{1,24})\.draft\.json")
REQUEST = re.compile(r"(npv-\d{8}T\d{6}Z-\d{4}|[0-9a-f]{16}|npv_[a-z0-9_]{1,24}_[0-9a-f]{8})"
                     r"\.(build|remove|requirements|export|install)\.request\.json")
SETUP_REQUEST = re.compile(r"setup\.(download|existing|zip)\.request\.json")
STRATEGIES = ("selected_tpp", "runtime_tpp", "legacy")
# The game writes without rename: a file younger than this may still be half written.
SETTLE_SECONDS = 1.0
GIVE_UP_SECONDS = 30.0
MAX_INBOUND = 2 * 1024 * 1024


def storage_root(game: Path) -> Path:
    return game / STORAGE


def converter_folder(plugin: Path) -> Path:
    return plugin / "data/projects"


def clean(value) -> str:
    text = "" if value is None else str(value)
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def lines_text(rows: list[tuple]) -> str:
    return "".join("\t".join(clean(v) for v in row) + "\n" for row in rows) + "end\t1\n"


def migrate_cet(game: Path, folder: Path) -> list[str]:
    """Copy the projects and export metadata of the CET versions once; the old folder is left as it is."""
    source = game / CET_PROJECTS
    copied = []
    if not source.is_dir():
        return copied
    folder.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir()):
        if item.is_file() and (PROJECT.fullmatch(item.name) or META.fullmatch(item.name)):
            target = folder / item.name
            if not target.exists():
                shutil.copy2(item, target)
                copied.append(item.name)
    return copied


def settled(path: Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime >= SETTLE_SECONDS
    except OSError:
        return False


def stamp(now: float) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))


def save_project(draft: Path, folder: Path, storage: Path, now: float) -> dict:
    """A project saved in the editor: validated, given its id, written to the converter folder."""
    token = DRAFT.fullmatch(draft.name).group(1)
    result = storage / ("save-" + token + ".result.txt")
    raw = draft.read_bytes()
    if len(raw) > MAX_INBOUND:
        raise ValueError("projeto grande demais")
    request = json.loads(raw.decode("utf-8-sig"))
    if request.get("format") != "npv-maker-save-request" or request.get("schema_version") != 1:
        raise ValueError("pedido de salvamento em formato desconhecido")
    project = request.get("project")
    after = request.get("after_save", "none")
    strategy = request.get("body_strategy", "selected_tpp")
    if after not in ("none", "build") or strategy not in STRATEGIES or not isinstance(project, dict):
        raise ValueError("pedido de salvamento invalido")
    # What storage.lua did in the CET versions: trimmed name and the save time (the game has no real clock).
    if isinstance(project.get("name"), str):
        project["name"] = project["name"].strip()
    if not project.get("created_at"):
        project["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    body = (json.dumps(project, ensure_ascii=False, indent=2) + "\n").encode("utf8")
    folder.mkdir(parents=True, exist_ok=True)
    for counter in range(1, 10000):
        project_id = "npv-" + stamp(now) + "-%04d" % counter
        target = folder / (project_id + ".npv.json")
        if not target.exists():
            break
    else:
        raise ValueError("limite de revisoes por segundo")
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(body)
    project_info(temporary)
    temporary.replace(target)
    if after == "build":
        # CRIAR NPV (author request 01/10/2026): the mods chosen in the manager and the default outfit go
        # with the import; runtime_entry checks them.
        extra = {key: request[key] for key in ("integrations", "underwear") if key in request}
        (folder / (project_id + ".build.request.json")).write_text(json.dumps(dict(
            {"format": "npv-maker-worker-request", "schema_version": 1, "action": "build",
             "project_id": project_id, "body_strategy": strategy}, **extra)), encoding="utf8")
    write_panel_file(result, lines_text([("stage", "saved"), ("id", project_id), ("after", after)]))
    return {"id": project_id, "after": after}


def reject(path: Path, storage: Path, reason: str) -> None:
    match = DRAFT.fullmatch(path.name)
    if match:
        message = i18n.text("Nao foi possivel salvar: " + reason, i18n.read_language(storage))
        write_panel_file(storage / ("save-" + match.group(1) + ".result.txt"),
                         lines_text([("stage", "error"), ("message", message)]))
    try:
        path.unlink()
    except OSError:
        pass


def inbound(storage: Path, folder: Path, now: float | None = None) -> list[str]:
    """Move what the game wrote into the converter folder. Returns what was taken, for the log."""
    now = time.time() if now is None else now
    taken = []
    if not storage.is_dir():
        return taken
    for path in sorted(storage.iterdir()):
        if not path.is_file():
            continue
        draft = DRAFT.fullmatch(path.name)
        request = REQUEST.fullmatch(path.name) or SETUP_REQUEST.fullmatch(path.name)
        if not (draft or request) or not settled(path, now):
            continue
        try:
            if draft:
                saved = save_project(path, folder, storage, now)
                path.unlink()
                taken.append("salvo " + saved["id"])
                continue
            if path.stat().st_size > 65536:
                raise ValueError("pedido grande demais")
            json.loads(path.read_text(encoding="utf-8-sig"))
            target = folder / path.name
            if target.exists() or target.with_suffix(".working").exists():
                path.unlink()
                taken.append("repetido " + path.name)
                continue
            folder.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
            taken.append("pedido " + path.name)
        except (ValueError, UnicodeDecodeError) as error:
            # A file the game is still writing parses wrong for a moment; give it time before refusing it.
            if now - path.stat().st_mtime < GIVE_UP_SECONDS:
                continue
            reject(path, storage, str(error)[:200])
            taken.append("recusado " + path.name)
        except OSError:
            continue
    return taken


def job_texts(data: dict, lang: str) -> tuple:
    """Message and lines of a job status in `lang` (i18n). A message the converter built from its diagnostics
    (diagnostics.headline/line) is built again in `lang` from the same records; any other goes through i18n.text."""
    message, lines = data.get("message"), list(data.get("lines") or [])
    if lang == i18n.SOURCE:
        return message, lines
    records = [d for d in data.get("diagnostics") or [] if isinstance(d, dict) and "code" in d and "severity" in d]
    built_message = built_lines = False
    try:
        for character in dict.fromkeys(str(d.get("character") or "") for d in records):
            if diagnostics.headline(character, records, data.get("stage")) == message:
                message, built_message = diagnostics.headline(character, records, data.get("stage"), lang), True
                break
        if records and lines == [diagnostics.line(d) for d in records if d["severity"] != "INFO"]:
            lines, built_lines = [diagnostics.line(d, lang) for d in records if d["severity"] != "INFO"], True
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    if not built_message:
        message = i18n.text(message, lang)
    if not built_lines:
        lines = [i18n.text(line, lang) for line in lines]
    return message, lines


def render(data: dict, lang: str = i18n.SOURCE) -> list[tuple] | None:
    kind = data.get("format")
    if kind == "npv-maker-companion-job":
        message, lines = job_texts(data, lang)
        values = dict(data, message=message)
        rows = [(key, values[key]) for key in ("stage", "message", "character_id", "folder", "zip_sha256",
                                                 "npv_version", "record_id") if values.get(key) not in (None, "")]
        if data.get("restart_required"):
            rows.append(("restart", "1"))
        rows += [("line", line) for line in lines]
        rows += [("log", entry.get("time", ""), job_texts(dict(data, message=entry.get("text")), lang)[0])
                 for entry in data.get("log") or [] if isinstance(entry, dict) and entry.get("text")]
        rows += [("requirement", i18n.text(line, lang)) for line in data.get("requirements") or []]
        if data.get("summary"):
            rows.append(("summary", data["summary"]))
        return rows
    if kind == "npv-maker-imported":
        # Cell 6: the integrations as four 0/1 flags (companion, nca, amm, nca_merc); cell 7: the default outfit;
        # cell 8: photo mode (added after, so older game sides read the same cells).
        return [("npv", c.get("token"), c.get("name"), c.get("package") or "", c.get("package_version") or "",
                 "1" if c.get("removal_pending") else "0",
                 "".join("1" if (c.get("integrations") or {}).get(k) else "0"
                         for k in ("companion", "nca", "amm", "nca_merc")),
                 c.get("underwear") or "",
                 "1" if (c.get("integrations") or {}).get("photomode") else "0")
                for c in data.get("characters") or []]
    if kind == "npv-maker-packages":
        return [("package", p.get("character_id"), p.get("display_name"), p.get("version"), p.get("author"),
                 p.get("state"), i18n.text(p.get("problem") or "", lang), p.get("installed_version") or "")
                for p in data.get("packages") or []]
    if kind == "npv-maker-setup":
        values = dict(data)
        code = data.get("code") or ""
        if code in diagnostics.CODES and data.get("message") == diagnostics.CODES[code][2]:
            values["message"] = i18n.code_text(code, lang, data["message"])
        else:
            values["message"] = i18n.text(data.get("message"), lang)
        if code in diagnostics.HINTS and data.get("hint") == diagnostics.HINTS[code]:
            values["hint"] = i18n.hint_text(code, lang, data["hint"])
        else:
            values["hint"] = i18n.text(data.get("hint"), lang)
        values["step"] = i18n.text(data.get("step"), lang)
        rows = [(key, values[key]) for key in ("state", "message", "hint", "step", "done", "total", "mode",
                                                 "wolvenkit_version", "dotnet_version", "code", "found_version")
                if values.get(key) not in (None, "")]
        if data.get("failed"):
            rows.append(("failed", "1"))
        rows += [("missing", item) for item in data.get("missing") or []]
        sizes = data.get("sizes") or {}
        rows += [("size_" + key, value) for key, value in sizes.items()]
        return rows
    if kind == "npv-maker-export-draft":
        fields = data.get("fields") or {}
        preset = fields.get("source_preset") or {}
        rows = [("token", data.get("token")), ("character_id", data.get("character_id") or ""),
                ("display_name", fields.get("display_name")), ("author", fields.get("author")),
                ("version", fields.get("version")), ("description", fields.get("description")),
                ("preset_name", preset.get("name")), ("preset_author", preset.get("author")),
                ("preset_url", preset.get("url")), ("preset_nexus", preset.get("nexus_mod_id") or ""),
                ("preset_version", preset.get("version")), ("notice", i18n.text(data.get("notice"), lang))]
        for index, dep in enumerate(data.get("dependencies") or []):
            rows.append(("dep", index, dep.get("name"), dep.get("author"), dep.get("url"),
                         dep.get("nexus_mod_id") or "", "1" if dep.get("required_for_rebuild") else "0",
                         i18n.reason_text(dep.get("reason") or "", lang)))
        rows += [("exported", version) for version in data.get("exported_versions") or []]
        return rows
    return None


def mirror_sources(folder: Path) -> list[Path]:
    exports = folder / "exports"
    found = sorted(exports.glob("*.json")) if exports.is_dir() else []
    found += sorted(exports.glob("*.report.txt")) if exports.is_dir() else []
    if (folder / "runtime.json").is_file():
        found.append(folder / "runtime.json")
    return found


def outbound(folder: Path, storage: Path, seen: dict, lang: str | None = None) -> int:
    """Mirror changed status files into the storage. `seen` keeps (mtime, size, language) between calls, so a
    change of the game's language writes every file again."""
    written = 0
    storage.mkdir(parents=True, exist_ok=True)
    lang = i18n.read_language(storage) if lang is None else lang
    for source in mirror_sources(folder):
        try:
            info = source.stat()
        except OSError:
            continue
        mark = (info.st_mtime_ns, info.st_size, lang)
        if seen.get(source.name) == mark:
            continue
        try:
            if source.name.endswith(".report.txt"):
                text = source.read_text(encoding="utf8")
                target = storage / source.name
            else:
                rows = render(json.loads(source.read_text(encoding="utf8")), lang)
                if rows is None:
                    seen[source.name] = mark
                    continue
                text = lines_text(rows)
                target = storage / (source.name[:-len(".json")] + ".txt")
        except (OSError, ValueError):
            continue
        if write_panel_file(target, text):
            seen[source.name] = mark
            written += 1
    return written


def latest_rows(folder: Path, lang: str = i18n.SOURCE) -> list[tuple]:
    """The newest project in the form the editor applies (first active copy of a doubled option)."""
    projects = sorted(p for p in folder.glob("npv-*.npv.json") if PROJECT.fullmatch(p.name)) if folder.is_dir() else []
    if not projects:
        return [("error", i18n.text("Nenhum projeto salvo nesta instalacao.", lang))]
    newest = projects[-1]
    try:
        project, _ = project_info(newest)
    except (OSError, ValueError) as error:
        return [("error", i18n.text("Projeto invalido: " + str(error)[:200], lang))]
    rows = [("id", newest.name[:-len(".npv.json")]), ("name", project["name"]), ("body", project["body"]),
            ("voice", project["voice"])]
    first = set()
    for option in project["options"]:
        key = (option.get("body_part"), option.get("name"))
        if option.get("active") and key in first:
            continue
        if option.get("active"):
            first.add(key)
        rows.append(("option", option.get("name"), option.get("body_part"), option.get("kind", ""),
                     option.get("selected_name", ""), option.get("selected_index", 0), option.get("choice_count", 0),
                     "1" if option.get("active") else "0", "1" if option.get("editable") else "0"))
    return rows


def publish_latest(folder: Path, storage: Path, seen: dict) -> bool:
    projects = sorted(p.name for p in folder.glob("npv-*.npv.json")) if folder.is_dir() else []
    lang = i18n.read_language(storage)
    mark = (projects[-1] if projects else "", lang)
    if seen.get("latest") == mark and (storage / "latest.txt").is_file():
        return False
    if write_panel_file(storage / "latest.txt", lines_text(latest_rows(folder, lang))):
        seen["latest"] = mark
        return True
    return False


def install_hook(folder: Path, storage: Path, seen: dict) -> None:
    """Mirror each status the moment the converter writes it (progress during a long conversion)."""
    import ingame_companion_worker
    exports = (folder / "exports").resolve()
    runtime = (folder / "runtime.json").resolve()

    def mirrored(path: Path) -> None:
        resolved = Path(path).resolve()
        if resolved.parent == exports or resolved == runtime:
            outbound(folder, storage, seen)
    ingame_companion_worker.panel_written_hook = mirrored


def sync(storage: Path, folder: Path, seen: dict, now: float | None = None) -> list[str]:
    """One pass of the bridge: take what the game wrote, publish what the converter wrote."""
    taken = inbound(storage, folder, now)
    outbound(folder, storage, seen)
    publish_latest(folder, storage, seen)
    return taken
