"""Package only the tested autonomous runtime and editor, never character assets."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


# WORKFLOW section 20 and author decision 29/09/2026: WolvenKit and .NET never enter the ZIP. The check is by
# place, by name and by content (every file of the pinned official Console zip), for staged and overlay files.
DOTNET_NAMES = {'dotnet.exe', 'hostfxr.dll', 'hostpolicy.dll', 'coreclr.dll', 'clrjit.dll'}


def wolvenkit_hashes(root):
    official = root / 'tools/vendor/WolvenKit.Console-8.19.0.zip'
    if not official.is_file():
        raise FileNotFoundError('Official WolvenKit Console zip needed to check the package: ' + str(official))
    with ZipFile(official) as bundle:
        return {hashlib.sha256(bundle.read(info)).hexdigest() for info in bundle.infolist() if not info.is_dir()}


def refused(relative, data, hashes):
    parts = relative.split('/')
    name = parts[-1].lower()
    if parts[:5] in (['red4ext', 'plugins', 'NPVMaker', 'runtime', 'wolvenkit'],
                     ['red4ext', 'plugins', 'NPVMaker', 'runtime', 'dotnet']) or 'Microsoft.NETCore.App' in parts:
        return 'pasta de WolvenKit/.NET'
    if name.startswith('wolvenkit') or name in DOTNET_NAMES:
        return 'arquivo de WolvenKit/.NET pelo nome'
    # 0.5.0 (author decision 30/09/2026): no CET; the game side is REDscript with RedFileSystem.
    if parts[:4] == ['bin', 'x64', 'plugins', 'cyber_engine_tweaks']:
        return 'pasta do CET (o NPV Maker 0.5.0 nao usa CET)'
    if hashlib.sha256(data).hexdigest() in hashes:
        return 'arquivo igual a um do WolvenKit Console oficial'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='Read-only NPV Maker build root')
    parser.add_argument('--delivery', type=Path, default=None,
                        help='Directory for archives; defaults to root/releases')
    parser.add_argument('--runtime-overlay', type=Path, default=None,
                        help='Replacement PyInstaller onedir converter: NPVMakerConverter.exe plus _internal')
    parser.add_argument('--version', default='0.4.14-body-runtime')
    args = parser.parse_args()
    root = args.root.resolve()
    staged = root / 'output/standalone'
    report = json.loads(args.validation.read_text(encoding='utf8'))
    converter = ((args.runtime_overlay / 'NPVMakerConverter.exe') if args.runtime_overlay else
                 staged / 'red4ext/plugins/NPVMaker/runtime/NPVMakerConverter.exe')
    digest = hashlib.sha256(converter.read_bytes()).hexdigest()
    if (not report.get('launcher_real_converter') or report.get('converter_exit') != 0
            or not report.get('projects') or any(p['stage'] != 'installed' for p in report['projects'].values())
            or report.get('converter_sha256') != digest):
        raise ValueError('This exact runtime has not passed standalone conversion/import validation')
    delivery = args.delivery.resolve() if args.delivery else root
    releases = delivery / 'releases'
    releases.mkdir(exist_ok=True)
    release = releases / f'NPV-maker-{args.version}-autonomous-test.zip'
    temporary = release.with_suffix('.tmp')
    hashes = wolvenkit_hashes(root)
    with ZipFile(temporary, 'w', ZIP_DEFLATED) as bundle:
        for file in sorted(staged.rglob('*')):
            if not file.is_file():
                continue
            relative = file.relative_to(staged)
            if 'data' in relative.parts or file.suffix.lower() in ('.archive', '.npv.json'):
                raise ValueError('Generated character data cannot enter the runtime ZIP: ' + str(relative))
            reason = refused(relative.as_posix(), file.read_bytes(), hashes)
            if reason:
                raise ValueError('WolvenKit/.NET cannot enter the NPV Maker ZIP (' + reason + '): ' + str(relative))
            if args.runtime_overlay and relative.parts[:5] == ('red4ext', 'plugins', 'NPVMaker', 'runtime', '_internal'):
                continue
            if args.runtime_overlay and relative.as_posix() == 'red4ext/plugins/NPVMaker/runtime/NPVMakerConverter.exe':
                continue
            bundle.write(file, relative.as_posix())
        if args.runtime_overlay:
            runtime_root = 'red4ext/plugins/NPVMaker/runtime'
            for file in sorted(args.runtime_overlay.rglob('*')):
                if file.is_file():
                    inner = file.relative_to(args.runtime_overlay).as_posix()
                    # The overlay only replaces the frozen converter, never adds other tools.
                    if inner != 'NPVMakerConverter.exe' and not inner.startswith('_internal/'):
                        raise ValueError('Runtime overlay may only hold the converter: ' + inner)
                    reason = refused(runtime_root + '/' + inner, file.read_bytes(), hashes)
                    if reason:
                        raise ValueError('WolvenKit/.NET cannot enter the NPV Maker ZIP (' + reason + '): ' + inner)
                    bundle.write(file, runtime_root + '/' + inner)
        staged_instructions = Path(__file__).resolve().parents[1] / f'docs/INSTALL-{args.version}.md'
        instructions = staged_instructions if staged_instructions.is_file() else root / f'docs/INSTALL-{args.version}.md'
        if not instructions.is_file():
            instructions = root / 'docs/INSTALL-0.4.md'
        bundle.write(instructions, 'NPV-maker-INSTALL.md')
        notices = root / 'tools/vendor/notices'
        for source, name in ((root / 'tools/vendor/RED4ext.SDK/LICENSE.md', 'RED4ext-SDK-LICENSE.md'),):
            bundle.write(source, 'red4ext/plugins/NPVMaker/third-party/' + name)
        python = Path((root / 'tools/build-env/pyvenv.cfg').read_text().split('home = ', 1)[1].splitlines()[0])
        bundle.write(python / 'LICENSE.txt', 'red4ext/plugins/NPVMaker/third-party/Python-LICENSE.txt')
        bundle.write(root / 'tools/build-env/Lib/site-packages/pyinstaller-6.22.0.dist-info/licenses/COPYING.txt',
                     'red4ext/plugins/NPVMaker/third-party/PyInstaller-COPYING.txt')
        bundle.writestr('red4ext/plugins/NPVMaker/third-party/SOURCES.txt',
            'WolvenKit and .NET are NOT included. On request in the panel, the converter downloads\n'
            'from the official sources only, with fixed versions and hashes:\n'
            'WolvenKit Console 8.19.0: https://github.com/WolvenKit/WolvenKit/releases/tag/8.19.0\n'
            '.NET runtime 8.0.31 (only when no .NET 8 is installed): https://dotnet.microsoft.com\n'
            'They are installed under %LOCALAPPDATA%\\NPVMaker\\tools, outside the game.\n'
            'RED4ext SDK: https://github.com/WopsS/RED4ext.SDK\n'
            f'NPV Maker source is provided alongside this release as NPV-maker-{args.version}-source.zip.\n')
    with ZipFile(temporary) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('Corrupt release ZIP')
    temporary.replace(release)
    with ZipFile(releases / f'NPV-maker-{args.version}-source.zip', 'w', ZIP_DEFLATED) as bundle:
        staged_source = Path(__file__).resolve().parents[1]
        overrides = {'tools/test_standalone.py', 'tools/audit_standalone.py',
                     'tools/package_standalone.py', 'tools/runtime_npc.py',
                     'tools/test_packaged_install.py',
                     'tests/test_runtime_hair_colors.py', 'README.md', 'docs/AUTONOMY.md',
                     'docs/INSTALL-0.4.1.md'}
        for directory, glob in (('src', '*'), ('tools', '*.py'), ('tools', '*.ps1'), ('tests', '*'), ('docs', '*.md')):
            files = (root / directory).rglob(glob) if directory in ('src', 'tests') else (root / directory).glob(glob)
            for file in files:
                relative = file.relative_to(root).as_posix()
                if file.is_file() and '__pycache__' not in file.parts and relative not in overrides:
                    bundle.write(file, file.relative_to(root).as_posix())
        for relative in sorted(overrides):
            staged_file = staged_source / relative
            base_file = root / relative
            source = staged_file if staged_file.is_file() else base_file
            if source.is_file():
                bundle.write(source, relative)
    summary = dict(report, release_version=args.version, release=str(release),
                   release_sha256=hashlib.sha256(release.read_bytes()).hexdigest(),
                   gameplay_visually_verified=False, contains_character_archives=False)
    (delivery / 'validation').mkdir(exist_ok=True)
    (delivery / 'validation/standalone-release.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    print(release)


if __name__ == '__main__':
    main()
