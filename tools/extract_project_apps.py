"""Read appearance metadata from installed mods and framework bundles."""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path


def safe_path(value, suffix: str) -> bool:
    return (isinstance(value, str) and len(value) <= 512 and value.lower().endswith(suffix)
            and all(part not in ('', '.', '..') and ':' not in part
                    for part in value.replace('/', '\\').split('\\')))


def wanted_paths(project: dict) -> list[str]:
    paths = set()
    for option in project['options']:
        if not (option['active'] and option['editable'] and option['kind'] == 'appearance'):
            continue
        if option['name'] == 'skin_color' or option['selected_name'] in ('', 'None'):
            continue
        value = option.get('resource_path')
        if not value:
            continue
        if not safe_path(value, '.app'):
            raise ValueError(f'Unsafe captured appearance resource: {value!r}')
        paths.add(value.replace('/', '\\'))
    return sorted(paths)


def path_hash(path: str) -> str:
    value = 14695981039346656037
    for byte in path.lower().encode('utf8'):
        value = ((value ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return str(value)


def declared_mesh_paths(roots: list[Path]) -> dict[str, str]:
    # Any installed .xl can add a line here; one odd declaration must not stop
    # every conversion, so a hash claimed by two different paths is dropped.
    result, ambiguous = {}, set()
    for root in roots:
        for file in root.rglob('*.xl'):
            text = file.read_text(encoding='utf-8-sig', errors='replace')
            for path in re.findall(r'[A-Za-z0-9_][A-Za-z0-9_\\/.@!+\-]*\.mesh\b', text):
                path = path.replace('/', '\\')
                if not safe_path(path, '.mesh'):
                    continue
                key = path_hash(path)
                if key in result and result[key].lower() != path.lower():
                    ambiguous.add(key)
                result[key] = path
    for key in ambiguous:
        result.pop(key, None)
    return result


def resolve_declared_meshes(value, paths: dict[str, str]) -> None:
    if isinstance(value, dict):
        if value.get('$type') == 'ResourcePath' and str(value.get('$value')) in paths:
            value['$value'] = paths[str(value['$value'])]
            value['$storage'] = 'string'
        for child in value.values():
            resolve_declared_meshes(child, paths)
    elif isinstance(value, list):
        for child in value:
            resolve_declared_meshes(child, paths)


def archive_xl_material_sources(bundle: Path) -> dict[str, str]:
    """Read installed ArchiveXL redirects for legacy eye/brow/lash selections.

    These source apps retain the exact editor choice-to-material mapping used
    by our template. They do not replace arbitrary mod geometry or new colors.
    """
    result, ambiguous = {}, set()
    for name in ('Eyes', 'Brows', 'Lashes'):
        file = bundle / f'PlayerCustomization{name}Fix.xl'
        if not file.is_file():
            continue
        for line in file.read_text(encoding='utf-8-sig').splitlines():
            pair = re.fullmatch(r'\s*(base\\[^\s:]+\.app):\s*(archive_xl\\[^\s:]+\.app)\s*', line)
            if pair and all(safe_path(value, '.app') for value in pair.groups()):
                original, redirected = pair.groups()
                if redirected in result and result[redirected] != original:
                    ambiguous.add(redirected)
                result[redirected] = original
    for redirected in ambiguous:
        result.pop(redirected, None)
    return result


def cli_run(cli: Path, *args: str) -> None:
    result = subprocess.run([str(cli), *args], capture_output=True, text=True,
                            encoding='utf8', errors='replace', timeout=180)
    if result.returncode or '[ 0: Error' in result.stdout + result.stderr:
        raise ValueError('Could not read installed appearance resources: '
                         + (result.stderr or result.stdout)[-1000:])


def unbundle(cli: Path, roots: list[Path], output: Path, selected: list[str]) -> None:
    if not selected:
        return
    regex = '^(?:' + '|'.join(re.escape(path) for path in selected) + ')$'
    for root in roots:
        cli_run(cli, 'unbundle', str(root), '--outpath', str(output), '--regex', regex)


def extract(project: dict, cli: Path, mod_archives: Path, output: Path,
            support_archives: list[Path] | None = None) -> list[str]:
    selected = wanted_paths(project)
    if not selected:
        return []
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    roots = [path for path in [*(support_archives or []), mod_archives] if path.is_dir()]
    redirects = {}
    for root in support_archives or []:
        redirects.update(archive_xl_material_sources(root))
    selected = sorted(set(selected) | {redirects[path] for path in selected if path in redirects})
    declared = declared_mesh_paths(roots)
    unbundle(cli, roots, output, selected)
    found, hair_meshes = [], set()
    for path in selected:
        file = output.joinpath(*path.split('\\'))
        if not file.is_file():
            continue
        cli_run(cli, 'convert', 'serialize', str(file))
        serial = Path(str(file) + '.json')
        if not serial.is_file():
            raise ValueError(f'Missing serialized appearance {path}')
        app = json.loads(serial.read_text(encoding='utf-8-sig'))
        resolve_declared_meshes(app, declared)
        serial.write_text(json.dumps(app, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        found.append(path)
        if any('hair' in option['name'].lower() and option.get('resource_path', '').replace('/', '\\') == path
               for option in project['options'] if option['active'] and option['editable']):
            for appearance in app['Data']['RootChunk']['appearances']:
                for item in appearance['Data']['components']:
                    part = item.get('Data', item)
                    mesh = part.get('mesh', {}).get('DepotPath', {}).get('$value')
                    if safe_path(mesh, '.mesh'):
                        hair_meshes.add(mesh.replace('/', '\\'))
    unbundle(cli, roots, output, sorted(hair_meshes))
    for path in sorted(hair_meshes):
        file = output.joinpath(*path.split('\\'))
        if file.is_file():
            cli_run(cli, 'convert', 'serialize', str(file))
    return found
