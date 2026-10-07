"""WolvenKit Console 8.19.0 and .NET 8 for the converter, set up by the user, never shipped in the ZIP.

Author decisions (29/09/2026, WORKFLOW section 20, docs/WOLVENKIT-SETUP-DESENHO.md): the NPV Maker release
carries neither WolvenKit (maintainer's request) nor .NET; the user sets them up from the panel with an
explicit action; only official sources, a fixed version and a fixed hash (never "latest", never a silent
version change); tools live outside the game and Vortex folders. The pipeline was built and validated on
WolvenKit 8.19.0 and writes 8.19 type names (runtime_npc), so no other version is accepted in V1.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import msvcrt
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

WOLVENKIT_VERSION = "8.19.0"
WOLVENKIT_ZIP = "WolvenKit.Console-8.19.0.zip"
WOLVENKIT_URL = "https://github.com/WolvenKit/WolvenKit/releases/download/8.19.0/WolvenKit.Console-8.19.0.zip"
WOLVENKIT_SIZE = 45927847
# Digest published by GitHub for the release asset (read 29/09/2026), equal to the tested package.
WOLVENKIT_SHA256 = "b14916c8a15ca3610640d9211c7e83fb234d5d1df1a109dd64e03451e15159f2"
# The application package of the same release (not the Console), recognised to explain the refusal.
WOLVENKIT_APP_SHA256 = "a6e80e25efb020b751413640344b519bc2737c5c49f2ac8fd64d340be5db5f5b"
ESSENTIAL = ("WolvenKit.CLI.exe", "WolvenKit.CLI.dll", "WolvenKit.CLI.runtimeconfig.json")

# WolvenKit.CLI.runtimeconfig.json asks Microsoft.NETCore.App 8.0.0 with the default roll-forward: any
# .NET 8.x runs it, .NET 9 and 10 do not. Portable runtime from Microsoft's release metadata (29/09/2026).
DOTNET_VERSION = "8.0.31"
DOTNET_URL = "https://builds.dotnet.microsoft.com/dotnet/Runtime/8.0.31/dotnet-runtime-8.0.31-win-x64.zip"
DOTNET_SIZE = 33322727
DOTNET_SHA512 = ("9c55c58694676ee64b0eed2cd6d8cbf58b9aa8288420acc66841e15ca0099c75"
                 "d4af0182d23a641c2342e5a151a325df4a12fa0bde2e47c0fb7e9a33e7b09896")

# Hosts the downloads may come from; GitHub release assets redirect to its asset storage.
OFFICIAL_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
                  "builds.dotnet.microsoft.com")
CHUNK = 1 << 20


class SetupError(Exception):
    """A setup failure with its diagnostic code (NPVM-SETUP-xxx) and a technical detail."""

    def __init__(self, code: str, detail: str, found_version: str = ""):
        super().__init__(code + ": " + detail)
        self.code, self.detail, self.found_version = code, detail, found_version


def tools_root() -> Path:
    """%LOCALAPPDATA%\\NPVMaker\\tools; NPV_TOOLS_ROOT overrides it for tests and isolated validation."""
    override = os.environ.get("NPV_TOOLS_ROOT")
    if override and Path(override).is_absolute():
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise SetupError("NPVM-SETUP-008", "LOCALAPPDATA nao definido")
    return Path(base) / "NPVMaker" / "tools"


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@contextlib.contextmanager
def tools_lock(tools: Path):
    """One setup at a time in the shared tools folder (it serves every game install of the user)."""
    tools.mkdir(parents=True, exist_ok=True)
    handle = (tools / "setup.lock").open("a+b")
    try:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise SetupError("NPVM-SETUP-008", "a pasta de ferramentas esta em uso por outro conversor do NPV Maker")
    try:
        yield
    finally:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        handle.close()


def replace_dir(source: Path, target: Path, attempts: int = 10, delay: float = 0.2) -> None:
    """Move a finished folder into place; an old one is set aside first and removed only after.
    A brief lock (antivirus scanning the new files) is retried."""
    aside = target.with_name(target.name + ".old")
    shutil.rmtree(aside, ignore_errors=True)
    for attempt in range(attempts):
        try:
            if target.exists():
                os.replace(target, aside)
            os.replace(source, target)
            break
        except PermissionError:
            if aside.exists() and not target.exists():
                os.replace(aside, target)
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
    shutil.rmtree(aside, ignore_errors=True)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")
    os.replace(temporary, path)


def dotnet_version(root: Path) -> str | None:
    """Highest Microsoft.NETCore.App 8.x in a .NET root that has dotnet.exe and a host resolver."""
    try:
        if not (root / "dotnet.exe").is_file() or not any((root / "host/fxr").iterdir()):
            return None
        versions = [p.name for p in (root / "shared/Microsoft.NETCore.App").iterdir()
                    if p.is_dir() and p.name.startswith("8.")]
    except OSError:
        return None
    return max(versions, key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")]) if versions else None


def dotnet_candidates(tools: Path, environ: dict | None = None) -> list[tuple[Path, str]]:
    """Where a usable .NET 8 may be, in the order the setup trusts them."""
    environ = os.environ if environ is None else environ
    found = [(tools / "dotnet" / DOTNET_VERSION, "managed")]
    if environ.get("DOTNET_ROOT"):
        found.append((Path(environ["DOTNET_ROOT"]), "env"))
    for variable in ("ProgramW6432", "ProgramFiles"):
        if environ.get(variable):
            found.append((Path(environ[variable]) / "dotnet", "global"))
    return found


def find_dotnet(tools: Path, environ: dict | None = None) -> tuple[Path, str, str] | None:
    for root, source in dotnet_candidates(tools, environ):
        if source == "managed" and not (root / "install.json").is_file():
            continue
        version = dotnet_version(root)
        if version:
            return root, source, version
    return None


def dotnet_env(root: Path) -> dict:
    return {"DOTNET_ROOT": str(root), "DOTNET_ROOT_X64": str(root), "DOTNET_MULTILEVEL_LOOKUP": "0"}


def cli_version(exe: Path, dotnet_root: Path) -> str:
    """What `WolvenKit.CLI.exe --version` prints (last line); SetupError NPVM-SETUP-006 if it does not run."""
    env = dict(os.environ, **dotnet_env(dotnet_root))
    try:
        done = subprocess.run([str(exe), "--version"], capture_output=True, encoding="utf8", errors="replace",
                              timeout=120, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as error:
        raise SetupError("NPVM-SETUP-006", type(error).__name__ + ": " + str(error))
    lines = [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]
    if done.returncode or not lines:
        text = ((done.stdout or "") + (done.stderr or "")).strip()
        raise SetupError("NPVM-SETUP-006", "codigo " + str(done.returncode) + ": " + text[-400:])
    return lines[-1]


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def official(url: str, hosts: tuple) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").lower() in hosts


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    """Every redirect hop must stay on an official https host, not only the final one."""

    def __init__(self, hosts: tuple):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official(newurl, self.hosts):
            raise SetupError("NPVM-SETUP-002", "redirecionado para fora das fontes oficiais: " + newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, destination: Path, size: int, algorithm: str, expected: str, progress=None,
             hosts: tuple = OFFICIAL_HOSTS, opener=None) -> Path:
    """Fetch one pinned official file, verify size and hash, then move it into place (a .part never
    counts as downloaded; a cut download leaves only the .part)."""
    if not official(url, hosts):
        raise SetupError("NPVM-SETUP-002", "fonte fora das oficiais: " + url)
    opener = opener or urllib.request.build_opener(OfficialRedirects(hosts)).open
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    try:
        with opener(urllib.request.Request(url, headers={"User-Agent": "NPVMaker-setup"}), timeout=60) as response:
            final = response.geturl() if hasattr(response, "geturl") else url
            if not official(final, hosts):
                raise SetupError("NPVM-SETUP-002", "redirecionado para fora das fontes oficiais: " + final)
            done = 0
            with part.open("wb") as stream:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    stream.write(block)
                    done += len(block)
                    if done > size:
                        raise SetupError("NPVM-SETUP-003", "arquivo maior que o esperado (" + str(size) + " bytes)")
                    if progress:
                        progress(done, size)
    except SetupError:
        part.unlink(missing_ok=True)
        raise
    except (OSError, ValueError) as error:
        part.unlink(missing_ok=True)
        raise SetupError("NPVM-SETUP-002", type(error).__name__ + ": " + str(error))
    got_size, got = part.stat().st_size, file_digest(part, algorithm)
    if got_size != size or got != expected:
        part.unlink(missing_ok=True)
        raise SetupError("NPVM-SETUP-003", "tamanho " + str(got_size) + ", " + algorithm + " " + got[:16] + "...")
    os.replace(part, destination)
    return destination


def extract(archive: Path, target: Path) -> None:
    """Unzip into a fresh folder, refusing entries that would land outside it."""
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    base = target.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = (target / member.filename).resolve()
            if path != base and base not in path.parents:
                raise SetupError("NPVM-SETUP-004", "entrada fora da pasta no zip: " + member.filename)
        bundle.extractall(target)


def package_root(folder: Path) -> Path:
    """The folder holding WolvenKit.CLI.exe (the official zip has the files at its root)."""
    if (folder / "WolvenKit.CLI.exe").is_file():
        return folder
    inner = [p for p in folder.iterdir() if p.is_dir() and (p / "WolvenKit.CLI.exe").is_file()]
    return inner[0] if len(inner) == 1 else folder


def console_package(folder: Path) -> None:
    missing = [name for name in ESSENTIAL if not (folder / name).is_file()]
    if missing:
        raise SetupError("NPVM-SETUP-004", "pacote sem " + ", ".join(missing))
    config = read_json(folder / "WolvenKit.CLI.runtimeconfig.json") or {}
    if (config.get("runtimeOptions") or {}).get("tfm") != "net8.0":
        raise SetupError("NPVM-SETUP-004", "WolvenKit.CLI.runtimeconfig.json nao e net8.0")


def require_dotnet(tools: Path, allow_download: bool, progress=None, **fetch) -> tuple[Path, str, str]:
    found = find_dotnet(tools)
    if found:
        return found
    if not allow_download:
        raise SetupError("NPVM-SETUP-007", ".NET 8 nao encontrado")
    downloads = tools / "downloads"
    archive = download(DOTNET_URL, downloads / Path(urllib.parse.urlsplit(DOTNET_URL).path).name, DOTNET_SIZE,
                       "sha512", DOTNET_SHA512, (lambda d, t: progress("dotnet", d, t)) if progress else None, **fetch)
    staging = tools / "dotnet" / (DOTNET_VERSION + ".tmp")
    final = tools / "dotnet" / DOTNET_VERSION
    try:
        extract(archive, staging)
        if dotnet_version(staging) != DOTNET_VERSION:
            raise SetupError("NPVM-SETUP-007", "o .NET baixado nao tem Microsoft.NETCore.App " + DOTNET_VERSION)
        replace_dir(staging, final)
    except SetupError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise SetupError("NPVM-SETUP-008", type(error).__name__ + ": " + str(error))
    write_json(final / "install.json", {"tool": ".NET runtime", "version": DOTNET_VERSION, "url": DOTNET_URL,
                                        "sha512": DOTNET_SHA512})
    archive.unlink(missing_ok=True)
    return final, "managed", DOTNET_VERSION


def install_zip(archive: Path, tools: Path, dotnet: tuple[Path, str, str], progress=None,
                keep_archive: bool = True) -> dict:
    """Install the official Console zip (downloaded or chosen by the user) into the managed folder."""
    if progress:
        progress("verificando", 0, 0)
    try:
        size, sha = archive.stat().st_size, file_digest(archive, "sha256")
    except OSError as error:
        raise SetupError("NPVM-SETUP-004", type(error).__name__ + ": " + str(error))
    if sha != WOLVENKIT_SHA256:
        what = "e o pacote do aplicativo WolvenKit, nao o Console" if sha == WOLVENKIT_APP_SHA256 else "nao e o pacote oficial"
        raise SetupError("NPVM-SETUP-004", archive.name + " " + what + " (" + str(size) + " bytes, sha256 " + sha[:16] + "...)")
    staging = tools / "wolvenkit" / (WOLVENKIT_VERSION + ".tmp")
    final = tools / "wolvenkit" / WOLVENKIT_VERSION
    try:
        if progress:
            progress("extraindo", 0, 0)
        extract(archive, staging)
        root = package_root(staging)
        console_package(root)
        if progress:
            progress("testando", 0, 0)
        version = cli_version(root / "WolvenKit.CLI.exe", dotnet[0])
        if version != WOLVENKIT_VERSION:
            raise SetupError("NPVM-SETUP-005", "o pacote respondeu " + version, version)
        replace_dir(root, final)
        shutil.rmtree(staging, ignore_errors=True)
    except SetupError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise SetupError("NPVM-SETUP-008", type(error).__name__ + ": " + str(error))
    write_json(final / "install.json", {"tool": "WolvenKit Console", "version": WOLVENKIT_VERSION,
                                        "url": WOLVENKIT_URL, "sha256": WOLVENKIT_SHA256, "package": archive.name})
    if not keep_archive:
        archive.unlink(missing_ok=True)
    return select(tools, "managed", final / "WolvenKit.CLI.exe", dotnet)


def fingerprint(exe: Path) -> list:
    """Size and date of the apphost and of the dll that really carries the version."""
    found = []
    for path in (exe, exe.with_name("WolvenKit.CLI.dll")):
        stat = path.stat()
        found.append([stat.st_size, int(stat.st_mtime)])
    return found


def select(tools: Path, mode: str, exe: Path, dotnet: tuple[Path, str, str]) -> dict:
    stat = exe.stat()
    setup = {"format": "npv-maker-tools", "schema_version": 1, "mode": mode, "wolvenkit": str(exe),
             "wolvenkit_version": WOLVENKIT_VERSION, "exe_size": stat.st_size, "exe_mtime": int(stat.st_mtime),
             "fingerprint": fingerprint(exe),
             "dotnet_root": str(dotnet[0]), "dotnet_source": dotnet[1], "dotnet_version": dotnet[2]}
    write_json(tools / "setup.json", setup)
    return check(tools)


def use_existing(exe: Path, tools: Path, progress=None) -> dict:
    """Accept a WolvenKit Console already on disk only if it answers exactly 8.19.0."""
    with tools_lock(tools):
        return _use_existing(exe, tools, progress)


def _use_existing(exe: Path, tools: Path, progress=None) -> dict:
    if exe.name.lower() != "wolvenkit.cli.exe" or not exe.is_file() or not exe.with_name("WolvenKit.CLI.dll").is_file():
        raise SetupError("NPVM-SETUP-006", "nao e um WolvenKit.CLI.exe existente: " + str(exe))
    dotnet = require_dotnet(tools, allow_download=False)
    if progress:
        progress("testando", 0, 0)
    version = cli_version(exe, dotnet[0])
    if version != WOLVENKIT_VERSION:
        raise SetupError("NPVM-SETUP-005", "a instalacao respondeu " + version, version)
    config = read_json(exe.with_name("WolvenKit.CLI.runtimeconfig.json")) or {}
    if (config.get("runtimeOptions") or {}).get("tfm") != "net8.0":
        raise SetupError("NPVM-SETUP-006", "WolvenKit.CLI.runtimeconfig.json ausente ou nao e net8.0")
    return select(tools, "existing", exe, dotnet)


def install_manual(archive: Path, tools: Path, progress=None) -> dict:
    with tools_lock(tools):
        dotnet = require_dotnet(tools, allow_download=False)
        return install_zip(archive, tools, dotnet, progress)


def download_all(tools: Path, progress=None, **fetch) -> dict:
    """BAIXAR AUTOMATICAMENTE: only what is missing, from the official sources."""
    with tools_lock(tools):
        return _download_all(tools, progress, **fetch)


def _download_all(tools: Path, progress=None, **fetch) -> dict:
    dotnet = require_dotnet(tools, allow_download=True, progress=progress, **fetch)
    current = check(tools)
    if current["state"] == "READY":
        # Only .NET was missing: an existing or managed 8.19.0 already in use is kept.
        return current
    archive = download(WOLVENKIT_URL, tools / "downloads" / WOLVENKIT_ZIP, WOLVENKIT_SIZE, "sha256",
                       WOLVENKIT_SHA256, (lambda d, t: progress("wolvenkit", d, t)) if progress else None, **fetch)
    return install_zip(archive, tools, dotnet, progress, keep_archive=False)


def cleanup(tools: Path) -> None:
    """Remove what a cut download or install left (the next start sees the tool as missing).
    Never while another converter holds the tools folder, and never raising."""
    try:
        with tools_lock(tools):
            for pattern in ("downloads/*", "wolvenkit/*.tmp", "dotnet/*.tmp", "wolvenkit/*.old", "dotnet/*.old"):
                for leftover in tools.glob(pattern):
                    try:
                        if leftover.is_dir():
                            shutil.rmtree(leftover, ignore_errors=True)
                        else:
                            leftover.unlink(missing_ok=True)
                    except OSError:
                        pass
    except (SetupError, OSError):
        pass


def check(tools: Path) -> dict:
    """Quick state at every start and before every import; runs nothing, only looks at files."""
    dotnet = find_dotnet(tools)
    setup = read_json(tools / "setup.json")
    state = {"state": "MISSING", "missing": [], "mode": None, "wolvenkit": None, "wolvenkit_version": None,
             "dotnet_root": str(dotnet[0]) if dotnet else None, "dotnet_source": dotnet[1] if dotnet else None,
             "dotnet_version": dotnet[2] if dotnet else None}
    if not dotnet:
        state["missing"].append("dotnet")
    if not setup or setup.get("wolvenkit_version") != WOLVENKIT_VERSION or not setup.get("wolvenkit"):
        state["missing"].append("wolvenkit")
        return state
    exe = Path(setup["wolvenkit"])
    state.update(mode=setup.get("mode"), wolvenkit=str(exe), wolvenkit_version=WOLVENKIT_VERSION)
    try:
        stat = exe.stat()
    except OSError:
        state["state"] = "BROKEN"
        state["missing"].append("wolvenkit")
        return state
    if setup.get("mode") == "managed" and not (exe.parent / "install.json").is_file():
        state["state"] = "BROKEN"
        return state
    if setup.get("mode") == "existing":
        try:
            changed = fingerprint(exe) != setup.get("fingerprint")
        except OSError:
            changed = True
        if changed:
            state["state"] = "BROKEN"
            return state
    if dotnet:
        state["state"] = "READY"
    return state
