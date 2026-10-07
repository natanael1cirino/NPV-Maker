"""Optional integrations of an NPV package (docs/ADAPTERS-MAPA.md, author decisions 30/09/2026; asked for again and
implemented 01/10/2026 so a published NPV can name the mods it works with).

The NPV itself (record, .ent, appearance, rebuilt assets) needs no consumer. The author marks in EXPORTAR which mods
the NPV is made for; the package carries only that choice (`integrations` in npv-package.json) and the files are
written by INSTALAR, after the rebuild, into the same receipt, so REMOVER deletes them too. Each file is harmless
when its mod is not installed (map, section 1), so a mod installed later works without installing the NPV again.

Formats measured on the published mods (map, section 1): Night City Allies 1.6.6 registers characters from a class
that extends NCAModule (Sina); AMM 2.12.5 reads custom entities from Lua tables in Collabs/Custom Entities (Joi).
NCA + AMM at the same time is PENDING RUNTIME (map, section 4): with loadAMMCharacters on (NCA default), the NPV may
show twice in NCA. Both can be marked; the form says so.
"""
from __future__ import annotations

import re

import photomode

KEYS = ("companion", "nca", "amm", "photomode")
# NCA type: companion (NCA.R().Character) or mercenary (NCA.R().Merc, as the NCA Mox mercs module). NCA 1.6.6 has
# no rarity on the builder (the old Lua API had one); a merc takes the rarity of its record.
OPTIONS = ("nca_merc",)
# What a package made before 01/10/2026 got: the Companion bridge was always written.
LEGACY = {"companion": True, "nca": False, "amm": False, "photomode": False, "nca_merc": False}
NCA_MODULE = "NightCityAllies.Modules"
AMM_FOLDER = "bin/x64/plugins/cyber_engine_tweaks/mods/AppearanceMenuMod/Collabs/Custom Entities"
# Requirements text of each integration (REQUIREMENTS.txt, NEXUS.txt); only the marked ones are listed. Nexus IDs
# from the Vortex staging folders (Night City Allies - AIO 27625, Appearance Menu Mod-790); Companion Expansion has
# no published page known here, so it goes by name only.
REQUIREMENT = {
    "companion": ("Companion Expansion", ""),
    "nca": ("Night City Allies", "https://www.nexusmods.com/cyberpunk2077/mods/27625"),
    "amm": ("Appearance Menu Mod (AMM) + Cyber Engine Tweaks", "https://www.nexusmods.com/cyberpunk2077/mods/790"),
    # photomode.py writes the photo mode entity; the NPV only shows there with PhotoMode-EX installed (author,
    # 02/10/2026, BUGS 59: without it no NPV appears). Nexus ID from its Vortex folder PhotoMode-EX-18839-1-4-1-....
    "photomode": ("PhotoMode-EX (the NPV shows in photo mode only with it)",
                  "https://www.nexusmods.com/cyberpunk2077/mods/18839"),
}
# How to call the NPV in NCA, measured by the author 03/10/2026 (BUGS 68): without GetMod the command fails. Only
# for a companion; the mercenary type (NCA.R().Merc) was not measured, so no command is given for it.
NCA_COMMAND = 'NCA = GetMod("NightCityAllies"); NCA:ForceSpawnCharacter("{record}")'
USAGE = {"pt": "NCA: no console do CET, digite: ", "en": "NCA: in the CET console, type: ",
         "es": "NCA: en la consola de CET, escribe: "}


class AdapterError(ValueError):
    pass


def clean(value) -> dict:
    """The author's choice from the export form; a package without one gets LEGACY."""
    if value is None:
        return dict(LEGACY)
    if not isinstance(value, dict) or any(key not in KEYS + OPTIONS for key in value):
        raise AdapterError("integracoes invalidas")
    if any(not isinstance(value.get(key, False), bool) for key in KEYS + OPTIONS):
        raise AdapterError("integracoes invalidas")
    return {key: bool(value.get(key, False)) for key in KEYS + OPTIONS}


def from_package(manifest: dict) -> dict:
    return clean(manifest.get("integrations"))


def reds_text(text: str) -> str:
    """A redscript string literal; the name is free text from the author."""
    safe = "".join(c for c in str(text) if c >= " ")
    return '"' + safe.replace("\\", "\\\\").replace('"', '\\"') + '"'


def lua_text(text: str) -> str:
    safe = "".join(c for c in str(text) if c >= " ")
    return '"' + safe.replace("\\", "\\\\").replace('"', '\\"') + '"'


def nca_module(token: str, record: str, name: str, appearance: str, merc: bool = False) -> str:
    if not re.fullmatch(r"[0-9a-f]{16}", token) or not re.fullmatch(r"Character\.NPVMaker_[0-9a-f]{16}", record):
        raise AdapterError("identidade invalida para o NCA")
    # Measured (map, section 1): with @if on the imports and the class the file compiles without NCA.
    # MEDIDO EM 03/10/2026 (NCA 1.6.6, PersistenceSystem/NCARegistration): the phone lists only companions in Standby
    # (GetStandbyCompanions); a character registered without Locked() starts as Unacquired, so the NPV could only be
    # spawned by command ("Looks like nobody is on standby"). Author request 03/10/2026: an NPV made with NCA is
    # callable by phone. NCA.R().UnlockCharacter moves Unacquired to Standby; a saved state (Squad, Unavailable,
    # Commuting, Locked by another rule) is left as it is.
    return (f'module NPVMakerAdapters.NCA{token}\n\n'
            f'@if(ModuleExists("{NCA_MODULE}"))\nimport NightCityAllies.*\n'
            f'@if(ModuleExists("{NCA_MODULE}"))\nimport NightCityAllies.Modules.*\n'
            f'@if(ModuleExists("{NCA_MODULE}"))\nimport NightCityAllies.Persistence.*\n\n'
            f'// Written by NPV Maker when this NPV package was installed (Night City Allies integration).\n'
            f'@if(ModuleExists("{NCA_MODULE}"))\n'
            f'public class NPVMakerNCA{token}Module extends NCAModule {{\n'
            f'  public func GetName() -> String {{\n    return {reds_text("NPV Maker " + name)};\n  }}\n\n'
            f'  public func GetPass() -> Int32 {{\n    return 1;\n  }}\n\n'
            f'  public func Load() -> Void {{\n'
            f'    NCA.R().{"Merc" if merc else "Character"}(t"{record}", {reds_text(name)})'
            f'.Outfit(n"casual", n"{appearance}");\n'
            f'    let index: Int32 = NCA.Persistence().GetIndex(t"{record}");\n'
            f'    if index >= 0 && Equals(NCA.Persistence().m_companionRegistry[index].spawnState, '
            f'CompanionSpawnState.Unacquired) {{\n'
            f'      NCA.R().UnlockCharacter(t"{record}");\n'
            f'    }};\n'
            f'  }}\n}}\n')


def amm_entity(character_id: str, record: str, name: str, author: str, entity: str, appearance: str) -> str:
    if not re.fullmatch(r"npv_[a-z0-9_]{1,24}_[0-9a-f]{8}", character_id):
        raise AdapterError("character_id invalido para o AMM")
    if entity != entity.lower():
        raise AdapterError("o AMM exige o caminho do .ent em minusculas")
    return ("-- Written by NPV Maker when this NPV package was installed (AMM integration).\n"
            "return {\n"
            f"  modder = {lua_text(author or 'NPV Maker')},\n"
            f"  unique_identifier = {lua_text(character_id)},\n"
            "  entity_info = {\n"
            f"    name = {lua_text(name)},\n"
            f"    path = {lua_text(entity)},\n"
            f"    record = {lua_text(record)},\n"
            "    type = \"Character\",\n"
            "    customName = true\n"
            "  },\n"
            f"  appearances = {{\n    {lua_text(appearance)},\n  }},\n"
            "  attributes = {\n  },\n"
            "}\n")


def files(chosen: dict, token: str, record: str, entity: str, appearance: str, name: str, author: str,
          character_id: str, photo: dict | None = None, name_key: str = "", body: str = "female") -> dict:
    """Relative path -> text of the NCA, AMM and photo mode adapters (the Companion bridge stays in runtime_import).
    Photo mode needs the .ent and icon the build put in the archive (`photo`, manifest "photomode")."""
    out = {}
    # Without the files (older build, or NPVM-PHOTO-001 at build) the NPV is installed without photo mode.
    if chosen.get("photomode") and photo and photo.get("entity"):
        out[f"r6/tweaks/NPVMaker/generated_{token}_photomode.yaml"] = photomode.record_yaml(
            token, photo["entity"], name_key, photo["atlas"])
        out[f"archive/pc/mod/npvmaker_{token}_photomode.xl"] = photomode.scope_xl(body, photo["entity"])
    if chosen.get("nca"):
        out[f"r6/scripts/NPVMakerAdapters/{token}_nca.reds"] = nca_module(token, record, name, appearance,
                                                                          chosen.get("nca_merc", False))
    if chosen.get("amm"):
        out[f"{AMM_FOLDER}/{character_id}.lua"] = amm_entity(character_id, record, name, author, entity, appearance)
    return out


def requirement_lines(chosen: dict) -> list[str]:
    return [REQUIREMENT[key][0] + (" - " + REQUIREMENT[key][1] if REQUIREMENT[key][1] else "")
            for key in KEYS if chosen.get(key)]


def usage_lines(chosen: dict, record: str, lang: str = "en") -> list[str]:
    """How to use the NPV in the marked mods (REQUIREMENTS.txt, NEXUS.txt)."""
    if not chosen.get("nca") or chosen.get("nca_merc") or not record:
        return []
    return [USAGE.get(lang, USAGE["en"]) + NCA_COMMAND.format(record=record)]
