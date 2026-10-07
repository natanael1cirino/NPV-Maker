# Building NPV Maker 0.1.0

NPV Maker has three parts. Only two of them are compiled: the RED4ext plugin (`NPVMakerRuntime.dll`) and the
converter (`NPVMakerConverter.exe`). The game scripts in `src/redscript` are plain REDscript, compiled by the game.

All commands run on Windows, from the repository root, in PowerShell.

## 1. RED4ext plugin (NPVMakerRuntime.dll)

Requirements:

- Visual Studio 2022 with "Desktop development with C++" (MSVC x64), or the Build Tools with CMake.
- CMake 3.21 or newer (the one bundled with Visual Studio works).
- RED4ext.SDK at commit `ad7277714ad30d6885d7050c5ba24fa0102f6920`.

```powershell
git clone https://github.com/WopsS/RED4ext.SDK.git tools/vendor/RED4ext.SDK
git -C tools/vendor/RED4ext.SDK checkout ad7277714ad30d6885d7050c5ba24fa0102f6920
cmake -S src/native -B output/native-build -G "Visual Studio 17 2022" -A x64
cmake --build output/native-build --config Release
```

Result: `output/native-build/Release/NPVMakerRuntime.dll`.

`tools/build_native.ps1` runs the same two CMake commands and then the launcher test
(`tools/test_native_launcher.ps1`), which starts the plugin in a fake game folder and checks the converter is
launched with the right paths and closed with the game.

The plugin only finds the game folder and starts the converter. It does not hook or patch any engine function.

## 2. Converter (NPVMakerConverter.exe)

Requirements:

- Python 3.12.10 from python.org (64-bit).
- PyInstaller 6.22.0. The converter itself uses only the Python standard library.

```powershell
py -3.12 -m venv build-env
build-env\Scripts\python.exe -m pip install pyinstaller==6.22.0
build-env\Scripts\python.exe -m PyInstaller --noconfirm --onedir --name NPVMakerConverter --distpath output/frozen --workpath output/freeze-work --specpath output/freeze-work tools/runtime_entry.py
```

Result: `output/frozen/NPVMakerConverter/` (the exe plus its `_internal` folder). In the release this folder is
`red4ext/plugins/NPVMaker/runtime/`.

`_internal/base_library.zip` is created by PyInstaller in every build: it is the part of the Python standard library
needed to start the program. It is not a separate mod archive.

PyInstaller builds are not byte-for-byte reproducible (timestamps and paths are embedded), so a rebuilt exe has a
different SHA256 from the released one, with the same code inside.

## 3. Game scripts

`src/redscript/*.reds` go to `r6/scripts/NPVMaker/` as they are. redscript compiles them when the game starts.
`src/ui` holds the sources of the small UI archive (`archive/pc/mod/npv-maker-ui.archive`).

## 4. Tests

```powershell
py -3.12 -m unittest discover -s tests -p "test_*.py"
```

The tests use only the standard library. A few panel tests need `lupa` and the old CET panel, which is not part of
this source; they are skipped.

## What is not here

- WolvenKit Console and .NET are not part of NPV Maker. The converter downloads WolvenKit Console 8.19.0 from the
  official WolvenKit GitHub release (and the official .NET 8 runtime, if missing) on first use, checks them by
  SHA256 and installs them under `%LOCALAPPDATA%\NPVMaker\tools`. See `tools/wolvenkit_setup.py`.
- No character assets, presets or files from other mods are included.
