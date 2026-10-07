# NPV Maker 0.1.0

Turn a character you design in Cyberpunk 2077's character creator into an NPC ("NPV") that lives in the world, and
export it as a mod ZIP that other players can install.

Version 0.1.0 is the first public release (internal build 0.5.0).

## Requirements (tested with)

- Cyberpunk 2077 2.31
- RED4ext 1.30.0
- redscript
- Codeware 1.20.5
- TweakXL 1.11.4
- ArchiveXL 1.27.3
- RedFileSystem 0.15.1

Cyber Engine Tweaks is not used by NPV Maker.

### WolvenKit (downloaded on first use, not included)

NPV Maker converts characters with WolvenKit Console 8.19.0, which needs .NET 8. Neither is included in this ZIP (at
the request of the WolvenKit team). On first use, open NPV MAKER > TOOLS > WOLVENKIT and let NPV Maker download the
official release from the WolvenKit GitHub (fixed version, checked by SHA256). It is installed under
`%LOCALAPPDATA%\NPVMaker\tools`, outside the game folder. You can also point to a WolvenKit Console 8.19.0 you already
have, or install the official ZIP manually from the same screen.

### Optional

- PhotoMode-EX: needed for the PHOTO MODE option (without it the NPV does not show in photo mode).
- Night City Allies, AppearanceMenuMod (AMM), Companion Expansion: used only when you tick them on export.
- Appearance Change Unlocker (ACU): its preset list keeps working inside the NPV Maker editor.

## How to use

1. Main menu > **NPV maker**. This opens the game's character creator in an isolated session: it never starts a new
   game and never touches your saves.
2. Design the character (or load a preset / a saved NPV Maker project).
3. **CREATE NPV**. Conversion runs in the background and usually takes a few minutes (3 to 5 in our tests; characters with many modded parts can take longer).
   The screen stays on the conversion while it runs. Do not close the game until it finishes.
4. Restart the game. The NPV is now available (Night City Allies phone menu, AMM, photo mode, depending on what you
   ticked).
5. **MANAGE > NPVs > EXPORT** on the NPV, fill in the form and **EXPORT MOD**: this builds a ZIP of your NPV that can
   be installed with Vortex.

## Things to know

- An NPV made with pieces from other mods (hair, eyes, makeup, body...) does not copy those mods' files. It points to
  them. Whoever installs your exported NPV needs the same mods; the export lists them as requirements. If one is
  missing, that piece is missing on the NPV.
- Restart the game after creating or removing an NPV.
- Mods that change the eyes or head of the player change the NPV the same way (for example, 3D eye mods).
- Some mod files cannot be read by WolvenKit 8.19 and are left out of the NPV with a message in the report
  (known case: one hair mod that stores `castShadows` in an old format).
- The OUTFITS tab is not available yet.
- Facial expressions are confirmed in photo mode. Expressions in the open world have not been confirmed yet.
- Interface languages: English, Portuguese and Spanish (follows the game language).

## Credits

- WolvenKit team: WolvenKit Console, used to convert files (downloaded from the official release, not redistributed).
- The authors of RED4ext, redscript, Codeware, TweakXL, ArchiveXL and RedFileSystem.
- RED4ext SDK (MIT), Python and PyInstaller: licenses in `red4ext/plugins/NPVMaker/third-party`.

The NPV Maker source code is provided alongside this release (`NPV-Maker-0.1.0-source.zip`).

---

# NPV Maker 0.1.0 (Portugues)

Transforma o personagem que voce cria no editor de personagem do Cyberpunk 2077 em um NPC ("NPV") no mundo, e exporta
esse NPV como um ZIP de mod que outros jogadores podem instalar.

Requisitos (testado com): Cyberpunk 2077 2.31, RED4ext 1.30.0, redscript, Codeware 1.20.5, TweakXL 1.11.4,
ArchiveXL 1.27.3, RedFileSystem 0.15.1. Nao usa o Cyber Engine Tweaks.

WolvenKit: o NPV Maker usa o WolvenKit Console 8.19.0 (com .NET 8), que NAO vem no ZIP. No primeiro uso, va em
NPV MAKER > TOOLS > WOLVENKIT e deixe o NPV Maker baixar a versao oficial do GitHub do WolvenKit (versao fixa,
conferida por SHA256). Fica em `%LOCALAPPDATA%\NPVMaker\tools`, fora da pasta do jogo.

Opcionais: PhotoMode-EX (para o MODO FOTO), Night City Allies, AMM e Companion Expansion (so quando marcados no
export), ACU (a lista de presets continua funcionando no editor).

Como usar: menu do jogo > **NPV maker** > crie o personagem > **CRIAR NPV** (alguns minutos, de 3 a 5 nos nossos testes; nao feche o jogo) >
reinicie o jogo > chame o NPV. **GERENCIAR > NPVs > EXPORTAR** no NPV e depois **EXPORTAR MOD** gera o ZIP para o
Vortex.

Bom saber: pecas de outros mods nao sao copiadas, o NPV aponta para elas (quem baixar precisa dos mesmos mods);
reinicie o jogo depois de criar ou remover um NPV; mods de olho ou cabeca do V mudam o NPV do mesmo jeito; ROUPAS
ainda nao esta disponivel; expressoes faciais confirmadas no modo foto, no mundo ainda nao confirmadas.
