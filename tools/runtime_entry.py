"""Packaged entry point launched by NPVMakerRuntime.dll, with no dev defaults."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import msvcrt
import os
import re
import sys
import time
import traceback
import uuid
from pathlib import Path
from companion_expansion import project_info
import ingame_companion_worker
from ingame_companion_worker import status_write
from runtime_import import (install, companion_available, remove_imported, retry_pending_removals,
                            publish_index)
from runtime_npc import build, build_identity
import runtime_body
import adapters
import diagnostics
import npv_package
import storage_bridge
from npv_package import PackageError
import wolvenkit_setup
from wolvenkit_setup import SetupError
import perf_trace

REQUEST = re.compile(r"^(npv-\d{8}T\d{6}Z-\d{4}|[0-9a-f]{16}|npv_[a-z0-9_]{1,24}_[0-9a-f]{8})"
                     r"\.(build|package|remove|requirements|export|install)\.request\.(json|working)$")
# Which identifier each action takes: saved project, imported NPV token or package character_id.
ACTION_TARGET = {"build": "project", "package": "project", "remove": "token", "requirements": "token",
                 "export": "token", "install": "package"}
TARGET_PATTERN = {"project": re.compile(r"npv-\d{8}T\d{6}Z-\d{4}"), "token": re.compile(r"[0-9a-f]{16}"),
                  "package": npv_package.CHARACTER_ID}
# WolvenKit setup asked from the panel (docs/WOLVENKIT-SETUP-DESENHO.md); served before imports.
SETUP_REQUEST = re.compile(r"^setup\.(download|existing|zip)\.request\.(json|working)$")
SETUP_TEXT = {"READY": "WolvenKit 8.19.0 pronto.",
              "MISSING": "WolvenKit necessario para importar NPVs.",
              "BROKEN": "A instalacao do WolvenKit mudou ou esta incompleta; instale de novo."}


def parent_alive(pid: int) -> bool:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0x102
    finally:
        kernel.CloseHandle(handle)


STAGES = (("Lendo aparencias", "appearance_conversion"), ("Convertendo formas", "morph_bake"),
          ("Gerando arquivos", "pack"))


def classify(error: Exception, stage: str, character: str, redact) -> dict:
    """Turn a pipeline failure into its stable fatal diagnostic."""
    if isinstance(error, diagnostics.DiagnosticError):
        return error.diagnostic
    if isinstance(error, PackageError):
        return diagnostics.make(error.code, character=character, technical_error=str(error), action="stopped",
                                result="failed", redact=redact)
    text = type(error).__name__ + ": " + str(error)
    if stage in ("export", "requirements"):
        return diagnostics.make("NPVM-PACKAGE-001", character=character, technical_error=text, action="stopped",
                                result="failed", redact=redact)
    if stage == "removal":
        code = "NPVM-REMOVE-004" if isinstance(error, LookupError) else "NPVM-INTERNAL-001"
        return diagnostics.make(code, character=character, technical_error=text, action="stopped",
                                result="failed", redact=redact)
    if stage == "dependency":
        code = "NPVM-DEPENDENCY-001"
    elif stage == "project_validation":
        code = "NPVM-PROJECT-001"
    elif stage == "import":
        code = "NPVM-IMPORT-001" if "ocupa o destino" in str(error) else "NPVM-IMPORT-002"
    elif stage == "morph_bake":
        code = "NPVM-BAKE-001"
    elif stage == "pack":
        code = "NPVM-PACK-001"
    elif str(error).startswith("WolvenKit:"):
        code = "NPVM-WK-CLI-001"
    else:
        code = "NPVM-INTERNAL-001"
    tool = "WolvenKit" if str(error).startswith("WolvenKit:") else ""
    return diagnostics.make(code, character=character, tool=tool, technical_error=text,
                            action="stopped", result="failed", redact=redact)


def removal_records(outcome: dict, redact) -> list[dict]:
    name = outcome["name"] or outcome["token"]
    records = []
    if outcome["removed"]:
        records.append(diagnostics.make("NPVM-REMOVE-001", character=name, action="removed", result="continued",
                                        technical_error="; ".join(outcome["removed"]), redact=redact))
    for relative in outcome["pending"]:
        records.append(diagnostics.make("NPVM-REMOVE-002", character=name, resource=relative,
                                        action="removal_pending", result="continued", redact=redact))
    for relative in outcome["kept"]:
        records.append(diagnostics.make("NPVM-REMOVE-003", character=name, resource=relative,
                                        action="kept_modified", result="continued", redact=redact))
    return records


def append_log(plugin: Path, records: list[dict]) -> None:
    """Technical log; like the panel files, a failure here never stops the work."""
    try:
        log = plugin / "data/diagnostics.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf8") as stream:
            for entry in diagnostics.log_lines(records):
                stream.write(entry + "\n")
    except OSError:
        pass


def watch_panel_files(plugin: Path, redact) -> None:
    """Record, in the technical log, a panel file that could not be updated (item 35)."""
    def report(path, error):
        append_log(plugin, [diagnostics.make(
            "NPVM-STATUS-001", resource=str(path), action="reported", result="continued",
            technical_error=type(error).__name__ + ": " + str(error), redact=redact)])
    ingame_companion_worker.status_failure_hook = report


def publish(status: Path, plugin: Path, project_id: str, character: str, stage: str,
            records: list[dict], **extra) -> None:
    """Write the one diagnostic set to the panel status, report file and log."""
    for record in records:
        record["project"] = project_id
        record["character"] = record.get("character") or character
    headline = diagnostics.headline(character, records, stage)
    summary = diagnostics.summary(character, records, stage)
    report = diagnostics.report(character, records, stage)
    lines = [diagnostics.line(d) for d in records if d["severity"] != "INFO"]
    if records:
        ingame_companion_worker.write_panel_file(status.parent / (project_id + ".report.txt"), report + "\n")
        append_log(plugin, records)
    status_write(status, stage=stage, message=headline, npv_version=diagnostics.NPV_VERSION,
                 diagnostics=records, lines=lines, summary=summary, report=report, **extra)


def convert_and_install(project: Path, source_digest: str, digest: str, character: str, strategy: str,
                        status: Path, game: Path, plugin: Path, redact, set_stage,
                        build_extra: dict | None = None, install_extra: dict | None = None,
                        require_companion: bool = True, preparing: str = "",
                        integrations: dict | None = None) -> tuple[dict, dict, str]:
    """Convert (or reuse the finished build of) one identity and install it.

    Shared by IMPORTAR NO COMPANION and by an installed NPV package: the same conversion, the
    same files. Returns (manifest, install result, manifest path)."""
    receipt = plugin / "data/imports" / (digest + ".json")
    ready = plugin / "data/ready" / (digest + ".json")
    # A build made by another converter version is not reused: the same
    # project imported again after the 0.4.15 fix of the "mariko 3.0" jaw
    # would have installed the old NPC, holes included. Its files are in
    # the game and are never overwritten, so the player removes it first.
    if ready.is_file() and json.loads(ready.read_text(encoding="utf8")).get("npv_version") != diagnostics.NPV_VERSION:
        if receipt.is_file():
            raise diagnostics.DiagnosticError(diagnostics.make(
                "NPVM-IMPORT-003", character=character, action="stopped", result="failed",
                technical_error="convertido por outra versao do NPV Maker", redact=redact))
        ready.unlink()
    if ready.is_file():
        previous = json.loads(ready.read_text(encoding="utf8"))
        # Reconcile missing files (e.g. deployment) from our completed build.
        manifest = json.loads(Path(previous["manifest"]).read_text(encoding="utf8"))
        manifest_path = previous["manifest"]
    else:
        # Never start a conversion without a valid WolvenKit (it used to break mid-reading).
        set_stage("setup")
        perf_trace.mark("job_setup_check")
        cli = require_wolvenkit(redact, status.parent.parent)
        set_stage("appearance_conversion")
        job = plugin / "data/jobs" / (digest[:16] + "-" + uuid.uuid4().hex[:8])
        job.mkdir(parents=True)
        perf_trace.mark("job_prepare", job=job.name)
        snapshot = job / "project.npv.json"
        snapshot.write_bytes(project.read_bytes())
        if project_info(snapshot)[1] != source_digest:
            raise ValueError("Projeto mudou durante a importacao; tente novamente.")

        shown = {"message": ""}

        def progress(message, detail=False):
            # detail: a step inside the current message, for the activity log only (author request 05/10/2026).
            if detail:
                status_write(status, stage="building", message=shown["message"], project_sha256=digest, detail=message)
                return
            shown["message"] = message
            perf_trace.event("progress", text=message)
            set_stage(next((name for prefix, name in STAGES if message.startswith(prefix)), None))
            status_write(status, stage="building", message=message, project_sha256=digest)
        progress(preparing or ("Preparando " + character + " para Companion..."))
        extra = {} if strategy == "legacy" else {"body_strategy": strategy}
        extra.update(build_extra or {})
        manifest = build(snapshot, game, cli, job / "npc", progress, **extra)
        manifest_path = str(job / "npc/manifest.json")
        ready.parent.mkdir(parents=True, exist_ok=True)
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(json.dumps({"manifest": manifest_path, "npv_version": diagnostics.NPV_VERSION}),
                             encoding="utf8")
        temporary.replace(ready)
    set_stage("import")
    perf_trace.mark("install")
    status_write(status, stage="installing", message="Importando " + character + "...")
    result = install(game, manifest, require_companion=require_companion, extra=install_extra,
                     integrations=integrations)
    result["manifest"] = manifest_path
    records = manifest.get("diagnostics")
    if records is None:
        # Conversions made by 0.4.3 recorded only the skipped pieces.
        records = [diagnostics.make(s.get("code", "NPVM-CONVERT-001"), character=character,
                                    option=s["name"], selection=s.get("selected_name", ""),
                                    resource=s.get("resource", ""), technical_error=s.get("reason", ""),
                                    action="skipped", result="continued", redact=redact)
                   for s in manifest.get("skipped_options") or []]
        manifest["diagnostics"] = records
    result["diagnostics"] = [{k: d[k] for k in ("code", "severity", "slot", "selection", "resource",
                                                "source_mod", "action")} for d in records]
    result["external_dependencies"] = [d["external_dependency"] for d in records if d.get("external_dependency")]
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temp = receipt.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    temp.replace(receipt)
    perf_trace.mark("job_done")
    return manifest, result, manifest_path


def request_limit(action: str) -> int:
    # The export form carries the requirement list the author edited.
    return 65536 if action == "export" else 16384


def process(request_file: Path, game: Path, plugin: Path) -> None:
    match = REQUEST.fullmatch(request_file.name)
    if not match:
        return
    project_id, action, _ = match.groups()
    if not TARGET_PATTERN[ACTION_TARGET[action]].fullmatch(project_id):
        return
    exporting = action in ("requirements", "export")
    status = request_file.parent / "exports" / (project_id + (".export.json" if exporting else ".json"))
    claimed = request_file.with_suffix(".working")
    redact = diagnostics.redactor(game)
    watch_panel_files(plugin, redact)
    stage = {"requirements": "requirements", "export": "export", "install": "package_install"}.get(
        action, "project_validation")
    character = project_id
    if request_file != claimed:
        try:
            request_file.rename(claimed)
        except OSError:
            return

    def set_stage(value):
        nonlocal stage
        if value:
            stage = value
    try:
        if claimed.stat().st_size > request_limit(action):
            raise ValueError("Oversized runtime request")
        request = json.loads(claimed.read_text(encoding="utf-8-sig"))
        if (request.get("format") != "npv-maker-worker-request" or request.get("schema_version") != 1
                or request.get("project_id") != project_id or request.get("action") != action):
            raise ValueError("Request does not match generated filename")
        if action == "remove":
            stage = "removal"
            outcome = remove_imported(game, plugin, project_id)
            character = outcome["name"] or project_id
            publish(status, plugin, project_id, character, "removed", removal_records(outcome, redact),
                    record_id=outcome["record_id"], removal_pending=outcome["pending"])
            publish_index(plugin, request_file.parent)
            publish_packages(plugin, request_file.parent)
            return
        if action == "package":
            raise ValueError("Exportacao para distribuicao ainda nao disponivel. Use CRIAR NPV.")
        if action == "requirements":
            status_write(status, stage="detecting", message="Procurando os mods usados por este NPV...")
            # BUGS 68: the material chain needs WolvenKit; without it the draft says it was skipped.
            try:
                cli = require_wolvenkit(redact)
            except diagnostics.DiagnosticError:
                cli = None
            roots = npv_package.download_roots()
            found = npv_package.draft(plugin, request_file.parent, game, project_id, cli=cli,
                                      exports=npv_package.exports_root(),
                                      downloads=lambda names: npv_package.download_sources(roots, names))
            character = found["fields"]["display_name"]
            ingame_companion_worker.write_panel_file(
                request_file.parent / "exports" / (project_id + ".export-draft.json"),
                json.dumps(found, ensure_ascii=False, indent=2) + "\n")
            status_write(status, stage="requirements_ready", message=str(len(found["dependencies"]))
                         + " requisito(s) detectado(s). Revise e clique CRIAR PACOTE.", token=project_id)
            return
        if action == "export":
            draft_file = request_file.parent / "exports" / (project_id + ".export-draft.json")
            if not draft_file.is_file():
                raise PackageError("NPVM-PACKAGE-001", "abra EXPORTAR de novo para detectar os requisitos")
            saved = json.loads(draft_file.read_text(encoding="utf8"))
            status_write(status, stage="exporting", message="Criando o pacote...")
            done = npv_package.export(plugin, request_file.parent, project_id, request, saved,
                                      npv_package.exports_root())
            character = done["manifest"]["display_name"]
            shown = "Documentos\\NPVMaker\\exports\\" + done["folder"].name
            record = diagnostics.make("NPVM-PACKAGE-002", character=character, action="exported", result="continued",
                                      technical_error=done["character_id"] + " " + done["manifest"]["version"]
                                      + "; zip sha256 " + done["zip_sha256"], redact=redact)
            append_log(plugin, [record])
            status_write(status, stage="exported", npv_version=diagnostics.NPV_VERSION,
                         message="Pacote criado em " + shown + ". Revise o NEXUS.txt antes de publicar.",
                         character_id=done["character_id"], folder=shown, files=done["files"],
                         zip_sha256=done["zip_sha256"], diagnostics=[record])
            return
        if action == "install":
            folder = plugin / "packages" / project_id
            package, recipe_bytes = npv_package.read_package(folder)
            character = package["display_name"]
            digest = npv_package.package_identity(project_id)
            receipt = plugin / "data/imports" / (digest + ".json")
            if receipt.is_file():
                installed = json.loads(receipt.read_text(encoding="utf8"))
                if installed.get("package_version") != package["version"]:
                    raise PackageError("NPVM-PACKAGE-005", "instalada " + str(installed.get("package_version"))
                                       + ", pacote " + str(package["version"]))
            try:
                integrations = adapters.from_package(package)
            except adapters.AdapterError as error:
                raise PackageError("NPVM-PACKAGE-006", str(error))
            try:
                underwear = npv_package.underwear_field(package.get("underwear"))
            except PackageError as error:
                raise PackageError("NPVM-PACKAGE-006", str(error))
            strategy = (package.get("recipe") or {}).get("body_strategy") or "legacy"
            if strategy not in runtime_body.STRATEGIES:
                raise PackageError("NPVM-PACKAGE-006", "estrategia de corpo desconhecida: " + str(strategy))
            status_write(status, stage="checking", message="Conferindo os requisitos de " + character + "...")
            checks = npv_package.check_requirements(package, npv_package.Locator(game))
            lines = npv_package.requirement_report(checks)
            missing = [c for c in checks if c["state"] == "missing" and c["required"]]
            if missing:
                error = diagnostics.DiagnosticError(diagnostics.make(
                    "NPVM-PACKAGE-003", character=character, action="stopped", result="failed", redact=redact,
                    technical_error="faltam: " + ", ".join(c["name"] for c in missing)))
                error.requirements = lines
                raise error
            notes = [diagnostics.make("NPVM-PACKAGE-004", character=character, resource=c["name"],
                                      action="requirements_checked", result="continued", redact=redact,
                                      technical_error=c["state"] + (": " + ", ".join(c["detail"]) if c["detail"] else ""))
                     for c in checks if c["state"] in ("unchecked", "other_archive")
                     or (c["state"] == "missing" and not c["required"])]
            recipe = folder / npv_package.RECIPE_NAME
            manifest, result, _ = convert_and_install(
                recipe, hashlib.sha256(recipe_bytes).hexdigest(), digest, character, strategy, status, game,
                plugin, redact, set_stage, build_extra={"identity": digest, "display_name": character,
                                                        "underwear": underwear},
                install_extra={"character_id": project_id, "package_version": package["version"],
                               "package_recipe_sha256": package["recipe"]["project_sha256"],
                               "display_name": character, "author": package.get("author") or ""},
                require_companion=False, preparing="Reconstruindo " + character + " a partir do pacote...",
                integrations=integrations)
            publish(status, plugin, project_id, character, "installed", notes + manifest["diagnostics"],
                    project_sha256=digest, restart_required=True, record_id=result["record_id"],
                    requirements=lines, skipped_options=manifest.get("skipped_options") or [])
            publish_index(plugin, request_file.parent)
            publish_packages(plugin, request_file.parent)
            return
        # CRIAR NPV: the mods marked in the manager (a request without them is the old IMPORTAR NO COMPANION).
        integrations = adapters.clean(request.get("integrations"))
        underwear = npv_package.underwear_field(request.get("underwear"))
        stage = "dependency"
        if integrations["companion"] and not companion_available(game):
            raise ValueError("Ative o Companion Expansion e reinicie o jogo antes de importar.")
        stage = "project_validation"
        project = request_file.parent / (project_id + ".npv.json")
        data, source_digest = project_info(project)
        # 0.4.14 DEV: the request may ask for a body strategy; each one is its
        # own NPC (runtime_npc.build_identity). Requests without it keep 0.4.13.
        strategy = request.get("body_strategy", "legacy")
        if strategy not in runtime_body.STRATEGIES:
            raise ValueError("Estrategia de corpo desconhecida no pedido: " + str(strategy))
        digest = build_identity(source_digest, strategy)
        character, stage = data["name"], "appearance_conversion"
        # A local NPV has no character_id yet (EXPORTAR creates it); AMM gets one from the build identity.
        manifest, result, _ = convert_and_install(
            project, source_digest, digest, data["name"], strategy, status, game, plugin, redact, set_stage,
            # build() defaults to "bottom"; only another outfit is passed, so the default call is the old one.
            build_extra={"underwear": underwear} if underwear != "bottom" else None,
            install_extra={"underwear": underwear, "local_id": "npv_local_" + digest[:8]},
            require_companion=integrations["companion"], integrations=integrations)
        shown = manifest.get("name") if isinstance(manifest.get("name"), str) else data["name"]
        publish(status, plugin, project_id, shown, "installed", manifest["diagnostics"],
                project_sha256=digest,
                restart_required=True, record_id=result["record_id"],
                skipped_options=manifest.get("skipped_options") or [])
        publish_index(plugin, request_file.parent)
    except Exception as error:
        record = classify(error, stage, character, redact)
        publish(status, plugin, project_id, character, "error", [record],
                **({"requirements": error.requirements} if hasattr(error, "requirements") else {}))
        ingame_companion_worker.write_panel_file(status.with_suffix(".log"), redact(traceback.format_exc()))
    finally:
        claimed.unlink(missing_ok=True)


# The packages window list: rewritten only when it changes.
packages_published = None


def publish_packages(plugin: Path, folder: Path) -> None:
    """exports/packages.json: packages Vortex placed in red4ext/plugins/NPVMaker/packages."""
    global packages_published
    try:
        listing = npv_package.scan_packages(plugin)
    except OSError:
        return
    text = json.dumps({"format": "npv-maker-packages", "schema_version": 1, "packages": listing},
                      ensure_ascii=False, indent=2) + "\n"
    if text != packages_published and ingame_companion_worker.write_panel_file(folder / "exports/packages.json", text):
        packages_published = text


# A setup status the panel could not receive is sent again by the converter loop.
setup_unpublished = False


def publish_setup(folder: Path, state: dict, **extra) -> bool:
    """exports/setup.json: what the panel shows in the NPV Maker - WolvenKit window."""
    payload = {"format": "npv-maker-setup", "schema_version": 1, "state": state.get("state", "MISSING"),
               "missing": state.get("missing", []), "mode": state.get("mode"),
               "wolvenkit_version": state.get("wolvenkit_version"), "dotnet_source": state.get("dotnet_source"),
               "dotnet_version": state.get("dotnet_version"),
               "sizes": {"wolvenkit": wolvenkit_setup.WOLVENKIT_SIZE, "dotnet": wolvenkit_setup.DOTNET_SIZE},
               "message": SETUP_TEXT.get(state.get("state"), "")}
    payload.update(extra)
    global setup_unpublished
    written = ingame_companion_worker.write_panel_file(folder / "exports/setup.json",
                                                       json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    setup_unpublished = not written
    return written


def tools_state() -> tuple[Path | None, dict]:
    try:
        tools = wolvenkit_setup.tools_root()
        return tools, wolvenkit_setup.check(tools)
    except (SetupError, OSError) as error:
        detail = error.detail if isinstance(error, SetupError) else type(error).__name__ + ": " + str(error)
        return None, {"state": "FAILED", "missing": ["wolvenkit"], "detail": detail}


def require_wolvenkit(redact, folder: Path | None = None) -> Path:
    """The WolvenKit to convert with, or NPVM-SETUP-001 before any conversion starts."""
    _, state = tools_state()
    if state["state"] != "READY":
        if folder is not None:
            publish_setup(folder, state)  # the panel shows the setup window from this fresh state
        raise diagnostics.DiagnosticError(diagnostics.make(
            "NPVM-SETUP-001", action="stopped", result="failed", redact=redact,
            technical_error="estado " + state["state"] + "; falta: " + ", ".join(state.get("missing") or []) +
                            ("; " + state["detail"] if state.get("detail") else "")))
    os.environ.update(wolvenkit_setup.dotnet_env(Path(state["dotnet_root"])))
    return Path(state["wolvenkit"])


def process_setup(request_file: Path, game: Path, plugin: Path) -> None:
    match = SETUP_REQUEST.fullmatch(request_file.name)
    if not match:
        return
    action = match.group(1)
    folder = request_file.parent
    claimed = request_file.with_suffix(".working")
    redact = diagnostics.redactor(game)
    watch_panel_files(plugin, redact)
    if request_file != claimed:
        try:
            request_file.rename(claimed)
        except OSError:
            return
    last = {"time": 0.0, "step": None}

    def progress(step, done, total):
        now = time.monotonic()
        if step == last["step"] and now - last["time"] < 0.5 and done < total:
            return
        last.update(time=now, step=step)
        publish_setup(folder, {"state": "INSTALLING", "missing": []}, step=step, done=done, total=total,
                      message="Instalando o WolvenKit...")
    try:
        try:
            if claimed.stat().st_size > 4096:
                raise ValueError("pedido grande demais")
            request = json.loads(claimed.read_text(encoding="utf-8-sig"))
            if (request.get("format") != "npv-maker-setup-request" or request.get("schema_version") != 1
                    or request.get("action") != action):
                raise ValueError("pedido nao confere com o nome do arquivo")
            chosen = request.get("path") if action in ("existing", "zip") else None
            if action in ("existing", "zip") and (not isinstance(chosen, str) or not chosen.strip()
                                                  or len(chosen) > 1024):
                raise ValueError("caminho ausente ou invalido")
        except (OSError, ValueError) as error:
            raise SetupError({"existing": "NPVM-SETUP-006", "zip": "NPVM-SETUP-004"}.get(action, "NPVM-SETUP-002"),
                             type(error).__name__ + ": " + str(error))
        tools = wolvenkit_setup.tools_root()
        progress("iniciando", 0, 0)
        if action == "download":
            state = wolvenkit_setup.download_all(tools, progress)
        elif action == "existing":
            state = wolvenkit_setup.use_existing(Path(chosen.strip().strip('"')), tools, progress)
        else:
            state = wolvenkit_setup.install_manual(Path(chosen.strip().strip('"')), tools, progress)
        record = diagnostics.make("NPVM-SETUP-010", action="reported", result="continued", redact=redact,
                                  technical_error="modo " + str(state.get("mode")) + "; .NET " +
                                  str(state.get("dotnet_version")) + " (" + str(state.get("dotnet_source")) + ")")
        append_log(plugin, [record])
        if state["state"] == "READY":
            os.environ.update(wolvenkit_setup.dotnet_env(Path(state["dotnet_root"])))
        publish_setup(folder, state, diagnostics=[record])
    except SetupError as error:
        record = diagnostics.make(error.code, action="stopped", result="failed", technical_error=error.detail,
                                  redact=redact)
        append_log(plugin, [record])
        _, state = tools_state()
        publish_setup(folder, state, failed=True, code=error.code,
                      message=record["message"], hint=record["hint"], found_version=error.found_version,
                      diagnostics=[record])
    except Exception:
        record = diagnostics.make("NPVM-INTERNAL-001", action="stopped", result="failed",
                                  technical_error=traceback.format_exc()[-1500:], redact=redact)
        append_log(plugin, [record])
        _, state = tools_state()
        publish_setup(folder, state, failed=True, code=record["code"], message=record["message"],
                      hint=record["hint"], diagnostics=[record])
    finally:
        claimed.unlink(missing_ok=True)


def run_request(request_file: Path, game: Path, plugin: Path) -> None:
    """One request never stops the converter: anything that escapes process() is logged."""
    perf_trace.mark("request", file=request_file.name)
    try:
        if SETUP_REQUEST.fullmatch(request_file.name):
            process_setup(request_file, game, plugin)
        else:
            process(request_file, game, plugin)
    except Exception:
        append_log(plugin, [diagnostics.make(
            "NPVM-INTERNAL-001", project=request_file.name, action="stopped", result="failed",
            technical_error=traceback.format_exc()[-1500:], redact=diagnostics.redactor(game))])


def startup_setup(folder: Path, plugin: Path, redact) -> dict:
    """Converter start: clean cut setups, drop interrupted setup requests, publish the state."""
    tools, setup = tools_state()
    if tools is not None:
        wolvenkit_setup.cleanup(tools)
    failure = {}
    # A setup cut by closing the game is not resumed: setup only runs on a click in this session.
    interrupted = [p for p in folder.glob("setup.*.request.working") if SETUP_REQUEST.fullmatch(p.name)]
    for request in interrupted:
        try:
            request.unlink()
        except OSError:
            pass
    if interrupted:
        record = diagnostics.make("NPVM-SETUP-002", action="stopped", result="failed", redact=redact,
                                  technical_error="instalacao interrompida quando o jogo fechou")
        failure = {"failed": True, "code": record["code"], "message": record["message"], "hint": record["hint"],
                   "diagnostics": [record]}
        append_log(plugin, [record])
    if setup["state"] == "READY":
        os.environ.update(wolvenkit_setup.dotnet_env(Path(setup["dotnet_root"])))
    elif setup["state"] == "BROKEN":
        append_log(plugin, [diagnostics.make("NPVM-SETUP-009", action="reported", result="continued",
                                             technical_error=str(setup.get("wolvenkit")), redact=redact)])
    elif setup["state"] == "FAILED":
        record = diagnostics.make("NPVM-SETUP-008", action="reported", result="failed", redact=redact,
                                  technical_error=setup.get("detail", ""))
        failure = {"failed": True, "code": record["code"], "message": record["message"], "hint": record["hint"],
                   "diagnostics": [record]}
        append_log(plugin, [record])
    publish_setup(folder, setup, **failure)
    return setup

def ordered_requests(folder: Path, pattern: str) -> list[Path]:
    """Setup requests first: an import waiting behind them needs the tools."""
    found = sorted(folder.glob(pattern))
    return ([p for p in found if SETUP_REQUEST.fullmatch(p.name)]
            + [p for p in found if not SETUP_REQUEST.fullmatch(p.name)])


def bridge(storage: Path, folder: Path, mirrored: dict, plugin: Path, redact) -> None:
    """One pass of storage_bridge; like the panel files, it never stops the converter."""
    try:
        for event in storage_bridge.sync(storage, folder, mirrored):
            if event.startswith("recusado"):
                append_log(plugin, [diagnostics.make("NPVM-BRIDGE-001", action="reported", result="continued",
                                                     technical_error=event, redact=redact)])
    except Exception:
        append_log(plugin, [diagnostics.make("NPVM-INTERNAL-001", action="reported", result="continued",
                                             technical_error=traceback.format_exc()[-1500:], redact=redact)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--once", action="store_true", help="Process current queue for isolated validation")
    args = parser.parse_args()
    game, plugin = args.game_root.resolve(), args.plugin_root.resolve()
    if (plugin / "data/perf").is_dir():
        perf_trace.install()
        perf_trace.start(plugin / "data/perf" / ("trace-" + time.strftime("%Y%m%dT%H%M%S") + "-" + str(os.getpid())
                                                 + ".jsonl"))
        perf_trace.mark("converter_start")
    if plugin != (game / "red4ext/plugins/NPVMaker").resolve():
        raise ValueError("Plugin must belong to the supplied game installation")
    if not (game / "bin/x64/Cyberpunk2077.exe").is_file():
        raise ValueError("Cyberpunk game executable missing")
    # 0.5.0 (no CET): the converter keeps its folder in the plugin data; the game reads and writes only
    # r6/storages/NPVMaker through storage_bridge. Projects of the CET versions are copied once.
    folder = storage_bridge.converter_folder(plugin)
    folder.mkdir(parents=True, exist_ok=True)
    storage = storage_bridge.storage_root(game)
    storage.mkdir(parents=True, exist_ok=True)
    data = plugin / "data"
    data.mkdir(exist_ok=True)
    with (data / "runtime.lock").open("a+b") as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        redact = diagnostics.redactor(game)
        watch_panel_files(plugin, redact)
        mirrored = {}
        storage_bridge.install_hook(folder, storage, mirrored)
        try:
            storage_bridge.migrate_cet(game, folder)
        except OSError:
            pass
        # WolvenKit and .NET are set up by the user from the panel, never shipped in the ZIP.
        setup = startup_setup(folder, plugin, redact)
        status_write(folder / "runtime.json", stage="ready", message="Conversor automatico iniciado.",
                     version=diagnostics.NPV_VERSION, pid=os.getpid(), setup=setup["state"])
        # Written whole: the launcher reads it as soon as it exists (an empty read failed the 0.5.0 isolated run).
        (data / "runtime.pid.tmp").write_text(str(os.getpid()), encoding="ascii")
        os.replace(data / "runtime.pid.tmp", data / "runtime.pid")
        # Files the game held open when a removal was asked are deleted now,
        # before this session loads them; then the in-game list is refreshed.
        try:
            retry_pending_removals(game, plugin)
        except (OSError, ValueError, LookupError):
            pass
        publish_index(plugin, folder)
        # NPV packages installed by Vortex are listed, never converted without a click.
        publish_packages(plugin, folder)
        # No previous runtime can still own a request after acquiring the lock.
        for source in ordered_requests(folder, "*.request.working"):
            run_request(source, game, plugin)
        ticks = 0
        while parent_alive(args.parent_pid):
            bridge(storage, folder, mirrored, plugin, redact)
            for source in ordered_requests(folder, "*.request.json"):
                run_request(source, game, plugin)
            if setup_unpublished:
                publish_setup(folder, tools_state()[1])
            bridge(storage, folder, mirrored, plugin, redact)
            if args.once:
                break
            ticks += 1
            if ticks % 3 == 0:
                publish_packages(plugin, folder)
            time.sleep(1)


if __name__ == "__main__":
    main()
