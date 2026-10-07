"""Player-facing text in the game's language (author request 01/10/2026: at least three languages, chosen by
the game's own language setting).

The converter keeps producing its texts in Portuguese, the source language, so the conversion pipeline and its
tests do not change. Translation happens once, where the texts leave for the game: storage_bridge.render. The
game writes its on-screen language to `language.txt` in the storage (NPVMakerStorage.reds). Diagnostics are
translated by code; other messages by exact text or by a template with {placeholders}. A text with no
translation is shown as it is (Portuguese).
"""
from __future__ import annotations

import re
from pathlib import Path

LANGUAGES = ("pt", "en", "es")
SOURCE = "pt"
LANGUAGE_FILE = "language.txt"


def normalize(code: str | None) -> str:
    """The game's language code (pt-br, en-us, es-es, es-mx, fr-fr...) as pt, es or en (the fallback)."""
    value = (code or "").strip().lower()
    if not value:
        return SOURCE
    if value.startswith("pt"):
        return "pt"
    if value.startswith("es"):
        return "es"
    return "en"


def read_language(storage: Path) -> str:
    """The language the game wrote; Portuguese when the game side is older and wrote none."""
    try:
        text = (storage / LANGUAGE_FILE).read_text(encoding="utf8")
    except (OSError, UnicodeDecodeError):
        return SOURCE
    for line in text.splitlines():
        key, _, value = line.partition("\t")
        if key == "lang":
            return normalize(value)
    return SOURCE


# Diagnostic codes: user text (diagnostics.CODES) in English and Spanish.
CODES = {
    "NPVM-WK-APP-001": ("WolvenKit could not read the file of this piece.",
                        "WolvenKit no pudo leer el archivo de esta pieza."),
    "NPVM-WK-APP-002": ("WolvenKit could not read a required body or head file.",
                        "WolvenKit no pudo leer un archivo obligatorio del cuerpo o de la cabeza."),
    "NPVM-WK-RES-001": ("WolvenKit could not read a mesh of this piece; the piece kept its original look.",
                        "WolvenKit no pudo leer una malla de esta pieza; la pieza mantuvo su apariencia original."),
    "NPVM-WK-CLI-001": ("WolvenKit failed during the conversion.",
                        "WolvenKit falló durante la conversión."),
    "NPVM-RESOURCE-001": ("The file of this piece is not in any installed mod.",
                          "El archivo de esta pieza no está en ningún mod instalado."),
    "NPVM-RESOURCE-002": ("A required body or head file is missing.",
                          "Falta un archivo obligatorio del cuerpo o de la cabeza."),
    "NPVM-RESOURCE-003": ("The mod has no mesh for this piece; it stayed as on V.",
                          "El mod no trae una malla de esta pieza; quedó como en V."),
    "NPVM-APPEAR-001": ("The chosen option does not exist in the file of this piece.",
                        "La opción elegida no existe en el archivo de esta pieza."),
    "NPVM-APPEAR-002": ("The chosen option does not exist in the required body or head file.",
                        "La opción elegida no existe en el archivo obligatorio del cuerpo o de la cabeza."),
    "NPVM-APPEAR-003": ("The chosen skin subtone does not exist on this piece; the base tone was used.",
                        "El subtono de piel elegido no existe en esta pieza; se usó el tono base."),
    "NPVM-APPEAR-004": ("Part of this piece does not have the chosen color and kept its original look.",
                        "Parte de esta pieza no tiene el color elegido y mantuvo su apariencia original."),
    "NPVM-APPEAR-005": ("The editor's eyelash color is outside its list; the NPV uses the game's first color.",
                        "El color de pestañas del editor está fuera de la lista; el NPV usa el primer color del juego."),
    "NPVM-APPEAR-006": ("The default outfit covers the genitals; the NPV leaves them out, as V does when dressed.",
                        "La ropa predeterminada cubre los genitales; el NPV los deja fuera, como V vestido."),
    "NPVM-CONVERT-001": ("This piece cannot be converted.",
                         "Esta pieza no se puede convertir."),
    "NPVM-CONVERT-002": ("A required body or head piece cannot be converted.",
                         "Una pieza obligatoria del cuerpo o de la cabeza no se puede convertir."),
    "NPVM-BAKE-001": ("The face or body shapes could not be applied.",
                      "No se pudieron aplicar las formas de la cara o del cuerpo."),
    "NPVM-BAKE-002": ("The face or body shapes could not be applied to this piece; it kept the default shape.",
                      "No se pudieron aplicar las formas de la cara o del cuerpo a esta pieza; quedó con la forma "
                      "predeterminada."),
    "NPVM-BAKE-003": ("The game does not draw this piece (no level of detail); it was left out of the NPV.",
                      "El juego no dibuja esta pieza (ningún nivel de detalle); quedó fuera del NPV."),
    "NPVM-PACK-001": ("The character file could not be built.",
                      "No se pudo montar el archivo del personaje."),
    "NPVM-IMPORT-001": ("A file of another package is in the character's place.",
                        "Un archivo de otro paquete ocupa el lugar del personaje."),
    "NPVM-IMPORT-002": ("The character files could not be written to the game.",
                        "No se pudieron escribir los archivos del personaje en el juego."),
    "NPVM-IMPORT-003": ("This NPV was imported by another version of NPV Maker.",
                        "Este NPV fue importado por otra versión de NPV Maker."),
    "NPVM-DEPENDENCY-001": ("Companion Expansion is not active.",
                            "Companion Expansion no está activo."),
    "NPVM-DEPENDENCY-002": ("This piece uses an ArchiveXL patch from another mod; the NPV needs that mod installed.",
                            "Esta pieza usa un parche de ArchiveXL de otro mod; el NPV necesita ese mod instalado."),
    "NPVM-PATCH-001": ("An ArchiveXL patch that adds pieces to this option could not be read; those pieces were left out.",
                       "No se pudo leer un parche de ArchiveXL que añade piezas a esta opción; esas piezas quedaron "
                       "fuera."),
    "NPVM-PROJECT-001": ("The saved project is invalid.",
                         "El proyecto guardado no es válido."),
    "NPVM-PROJECT-002": ("The editor saved this option twice with different choices; the first one was used.",
                         "El editor guardó esta opción dos veces con elecciones distintas; se usó la primera."),
    "NPVM-BODY-001": ("The body was built from the character shown in the editor.",
                      "El cuerpo se montó a partir del personaje mostrado en el editor."),
    "NPVM-BODY-002": ("A body piece seen in the editor could not be converted and was left out.",
                      "Una pieza del cuerpo vista en el editor no se pudo convertir y quedó fuera."),
    "NPVM-BODY-003": ("The body was built from the editor options, as before 0.4.14.",
                      "El cuerpo se montó con las opciones del editor, como antes de la 0.4.14."),
    "NPVM-RUNTIME-001": ("The editor showed pieces the NPV does not have; they may be missing in game.",
                         "El editor mostraba piezas que el NPV no tiene; pueden faltar en el juego."),
    "NPVM-HEAD-001": ("This head piece was built from the file the editor showed, not from the option's file.",
                      "Esta pieza de la cabeza se montó con el archivo que mostró el editor, no con el de la opción."),
    "NPVM-HEAD-002": ("The editor showed this head piece coming from another file, but not for sure; the old path "
                      "was used.",
                      "El editor mostró esta pieza de la cabeza desde otro archivo, pero sin certeza; se usó el "
                      "camino antiguo."),
    "NPVM-TEMPLATE-001": ("The chosen color was built from the file's template, as ArchiveXL does in game.",
                          "El color elegido se montó a partir de la plantilla del archivo, como hace ArchiveXL en "
                          "el juego."),
    "NPVM-TEMPLATE-002": ("The color built from the template did not match what the editor showed; what the editor "
                          "showed was used.",
                          "El color montado con la plantilla no coincidió con lo que mostró el editor; se usó lo que "
                          "mostró el editor."),
    "NPVM-INTERNAL-001": ("Unexpected converter error.",
                          "Error inesperado del conversor."),
    "NPVM-STATUS-001": ("The panel could not be updated at that moment; the operation went on.",
                        "No se pudo actualizar el panel en ese momento; la operación continuó."),
    "NPVM-SETUP-001": ("WolvenKit is not ready; the import was not started.",
                       "WolvenKit no está listo; la importación no se inició."),
    "NPVM-SETUP-002": ("The download did not finish (network, server or a source other than the official ones).",
                       "La descarga no terminó (red, servidor o fuente distinta de las oficiales)."),
    "NPVM-SETUP-003": ("The downloaded file does not match the official one and was discarded.",
                       "El archivo descargado no coincide con el oficial y se descartó."),
    "NPVM-SETUP-004": ("The chosen ZIP is not the official WolvenKit Console 8.19.0.",
                       "El ZIP elegido no es el WolvenKit Console 8.19.0 oficial."),
    "NPVM-SETUP-005": ("This WolvenKit is another version; NPV Maker only uses 8.19.0.",
                       "Este WolvenKit es de otra versión; NPV Maker solo usa la 8.19.0."),
    "NPVM-SETUP-006": ("The WolvenKit you pointed to did not run.",
                       "El WolvenKit indicado no se ejecutó."),
    "NPVM-SETUP-007": ("There is no usable .NET 8.",
                       "No hay un .NET 8 utilizable."),
    "NPVM-SETUP-008": ("The NPV Maker tools folder cannot be used (permission or space).",
                       "No se puede usar la carpeta de herramientas de NPV Maker (permiso o espacio)."),
    "NPVM-SETUP-009": ("The WolvenKit installation changed or is incomplete.",
                       "La instalación de WolvenKit cambió o está incompleta."),
    "NPVM-SETUP-010": ("WolvenKit 8.19.0 ready.",
                       "WolvenKit 8.19.0 listo."),
    "NPVM-REMOVE-001": ("The files of this NPV were removed.",
                        "Se eliminaron los archivos de este NPV."),
    "NPVM-REMOVE-002": ("The game is using a file of this NPV; it will be deleted when the game starts again.",
                        "El juego está usando un archivo de este NPV; se borrará cuando el juego se abra de nuevo."),
    "NPVM-REMOVE-003": ("A file of this NPV was changed after the import and was not deleted.",
                        "Un archivo de este NPV se modificó después de la importación y no se borró."),
    "NPVM-REMOVE-004": ("The requested NPV is not in the imported list.",
                        "El NPV pedido no está en la lista de importados."),
    "NPVM-BRIDGE-001": ("A file written by the game could not be read and was discarded.",
                        "Un archivo escrito por el juego no se pudo leer y se descartó."),
    "NPVM-PACKAGE-001": ("The package of this NPV could not be created.",
                         "No se pudo crear el paquete de este NPV."),
    "NPVM-PACKAGE-002": ("NPV package created.",
                         "Paquete del NPV creado."),
    "NPVM-PACKAGE-003": ("Requirements are missing to rebuild this NPV.",
                         "Faltan requisitos para reconstruir este NPV."),
    "NPVM-PACKAGE-004": ("A requirement was not checked or came from another file.",
                         "Un requisito no se comprobó o vino de otro archivo."),
    "NPVM-PACKAGE-005": ("Another version of this NPV is already installed.",
                         "Otra versión de este NPV ya está instalada."),
    "NPVM-PACKAGE-007": ("This version of the NPV was already exported.",
                         "Esta versión del NPV ya se exportó."),
    "NPVM-PACKAGE-006": ("Invalid NPV package, or made for a newer NPV Maker.",
                         "Paquete NPV no válido o hecho para una versión más nueva de NPV Maker."),
    "NPVM-PHOTO-001": ("The photo mode files could not be created; the NPV came out without photo mode.",
                       "No se pudieron crear los archivos del modo foto; el NPV salió sin modo foto."),
}

SUPPORT = ("Copy the report and send it to support.", "Copia el informe y envíalo al soporte.")
HINTS = {
    "NPVM-WK-APP-002": SUPPORT,
    "NPVM-WK-CLI-001": SUPPORT,
    "NPVM-RESOURCE-002": ("Enable the body and head mods used on V and try again.",
                          "Activa los mods de cuerpo y cabeza usados en V y vuelve a intentarlo."),
    "NPVM-APPEAR-002": ("Enable the body and head mods used on V and try again.",
                        "Activa los mods de cuerpo y cabeza usados en V y vuelve a intentarlo."),
    "NPVM-CONVERT-002": SUPPORT,
    "NPVM-BAKE-001": SUPPORT,
    "NPVM-PACK-001": SUPPORT,
    "NPVM-IMPORT-001": ("Another package uses the same file. Copy the report and send it to support.",
                        "Otro paquete usa el mismo archivo. Copia el informe y envíalo al soporte."),
    "NPVM-IMPORT-002": ("Close other programs that use the game folder and try again.",
                        "Cierra otros programas que usen la carpeta del juego y vuelve a intentarlo."),
    "NPVM-IMPORT-003": ("Remove this NPV in the NPVs tab, restart the game and import it again.",
                        "Elimina este NPV en la pestaña NPVs, reinicia el juego e impórtalo de nuevo."),
    "NPVM-DEPENDENCY-001": ("Enable Companion Expansion and restart the game before importing.",
                            "Activa Companion Expansion y reinicia el juego antes de importar."),
    "NPVM-PROJECT-001": ("Save the project again in the editor and try once more.",
                         "Guarda el proyecto de nuevo en el editor y vuelve a intentarlo."),
    "NPVM-INTERNAL-001": SUPPORT,
    "NPVM-SETUP-001": ("In the NPV maker editor, use NEXT: MANAGE > WOLVENKIT.",
                       "En el editor de NPV maker, usa SIGUIENTE: GESTIONAR > WOLVENKIT."),
    "NPVM-SETUP-002": ("Try again or use INSTALL ZIP MANUALLY.",
                       "Vuelve a intentarlo o usa INSTALAR ZIP MANUALMENTE."),
    "NPVM-SETUP-003": ("Try downloading again.", "Vuelve a intentar la descarga."),
    "NPVM-SETUP-004": ("Download WolvenKit.Console-8.19.0.zip from the WolvenKit 8.19.0 release on GitHub.",
                       "Descarga WolvenKit.Console-8.19.0.zip de la versión 8.19.0 de WolvenKit en GitHub."),
    "NPVM-SETUP-005": ("Use DOWNLOAD AUTOMATICALLY to install 8.19.0 without touching your installation.",
                       "Usa DESCARGAR AUTOMÁTICAMENTE para instalar la 8.19.0 sin tocar tu instalación."),
    "NPVM-SETUP-006": ("Check the path of WolvenKit.CLI.exe or use DOWNLOAD AUTOMATICALLY.",
                       "Revisa la ruta de WolvenKit.CLI.exe o usa DESCARGAR AUTOMÁTICAMENTE."),
    "NPVM-SETUP-007": ("Use DOWNLOAD AUTOMATICALLY (it downloads .NET 8 from Microsoft) or install .NET 8.",
                       "Usa DESCARGAR AUTOMÁTICAMENTE (descarga .NET 8 de Microsoft) o instala .NET 8."),
    "NPVM-SETUP-008": ("Free up space or permission in %LOCALAPPDATA%\\NPVMaker.",
                       "Libera espacio o permisos en %LOCALAPPDATA%\\NPVMaker."),
    "NPVM-SETUP-009": ("Install again with one of the buttons of the WOLVENKIT tab.",
                       "Vuelve a instalar con uno de los botones de la pestaña WOLVENKIT."),
    "NPVM-RUNTIME-001": SUPPORT,
    "NPVM-REMOVE-002": ("Restart the game; the NPV no longer appears after the restart.",
                        "Reinicia el juego; el NPV ya no aparece después de reiniciar."),
    "NPVM-REMOVE-003": ("Check the file listed in the report before deleting it by hand.",
                        "Revisa el archivo indicado en el informe antes de borrarlo a mano."),
    "NPVM-PACKAGE-001": ("Import this NPV again with this NPV Maker version and try exporting once more.",
                         "Importa este NPV de nuevo con esta versión de NPV Maker y vuelve a exportar."),
    "NPVM-PACKAGE-003": ("Install the requirements marked with x, restart the game and try again.",
                         "Instala los requisitos marcados con x, reinicia el juego y vuelve a intentarlo."),
    "NPVM-PACKAGE-005": ("Remove the installed version in the NPVs tab, restart the game and install again.",
                         "Elimina la versión instalada en la pestaña NPVs, reinicia el juego e instala de nuevo."),
    "NPVM-PACKAGE-007": ("Change the version in 1. DETAILS (e.g. from 1.0.0 to 1.0.1) and export again. "
                         "The previous package stays in Documents\\NPVMaker\\exports.",
                         "Cambia la versión en 1. DATOS (p. ej. de 1.0.0 a 1.0.1) y exporta de nuevo. "
                         "El paquete anterior sigue en Documentos\\NPVMaker\\exports."),
    "NPVM-PACKAGE-006": ("Download the package again or update NPV Maker.",
                         "Descarga el paquete de nuevo o actualiza NPV Maker."),
}

ACTIONS = {
    "skipped": ("piece skipped", "pieza omitida"),
    "kept_captured": ("kept the original look", "mantuvo la apariencia original"),
    "base_tone": ("used the base tone", "usó el tono base"),
    "stopped": ("import stopped", "importación detenida"),
    "external_reference": ("reference to the mod's original file", "referencia al archivo original del mod"),
    "archivexl_patch": ("ArchiveXL patch applied to the copy", "parche de ArchiveXL aplicado a la copia"),
    "removed": ("removed", "eliminado"),
    "removal_pending": ("will be deleted on the next start", "se borrará en el próximo inicio"),
    "kept_modified": ("kept (changed)", "conservado (modificado)"),
    "default_shape": ("kept the default shape", "quedó con la forma predeterminada"),
    "first_choice": ("first choice used", "se usó la primera elección"),
    "reported": ("noted in the report", "indicado en el informe"),
    "runtime_origin": ("origin seen in the editor", "origen visto en el editor"),
    "legacy_head": ("old head path", "camino antiguo de la cabeza"),
    "archivexl_template": ("ArchiveXL template", "plantilla de ArchiveXL"),
    "runtime_preferred": ("used what the editor showed", "se usó lo que mostró el editor"),
    "runtime_body": ("body of the editor character", "cuerpo del personaje del editor"),
    "legacy_body": ("body from the editor options", "cuerpo por las opciones del editor"),
    "exported": ("package created", "paquete creado"),
    "requirements_checked": ("requirements checked", "requisitos comprobados"),
}

# diagnostics.slot_label values.
SLOTS = {"Cilios": ("Eyelashes", "Pestañas"), "Sobrancelha": ("Eyebrows", "Cejas"), "Cabelo": ("Hair", "Cabello"),
         "Barba": ("Beard", "Barba"), "Olhos": ("Eyes", "Ojos"), "Cyberware": ("Cyberware", "Ciberware"),
         "Maquiagem": ("Makeup", "Maquillaje"), "Piercing": ("Piercing", "Piercing"),
         "Tatuagem": ("Tattoo", "Tatuaje"), "Cicatriz": ("Scar", "Cicatriz"), "Unhas": ("Nails", "Uñas"),
         "Genitalia": ("Genitals", "Genitales"), "Corpo": ("Body", "Cuerpo"), "Dentes": ("Teeth", "Dientes"),
         "Cabeca": ("Head", "Cabeza"), "Peca": ("Piece", "Pieza")}

# Other messages, by exact text or template. {name!t} is translated too; any other {name} is kept as it is.
TEXTS = {
    # headlines (diagnostics.headline)
    "{name} removido do Companion. Reinicie o jogo para concluir.":
        ("{name} removed from Companion. Restart the game to finish.",
         "{name} eliminado de Companion. Reinicia el juego para terminar."),
    "{name} removido. Reinicie o jogo.": ("{name} removed. Restart the game.", "{name} eliminado. Reinicia el juego."),
    "{name} importado com {count} aviso(s). Reinicie o jogo.":
        ("{name} imported with {count} warning(s). Restart the game.",
         "{name} importado con {count} aviso(s). Reinicia el juego."),
    "{name} importado! Reinicie o jogo.":
        ("{name} imported! Restart the game.", "¡{name} importado! Reinicia el juego."),
    "Exportacao falhou": ("Export failed", "La exportación falló"),
    "Instalacao do pacote falhou": ("Package install failed", "La instalación del paquete falló"),
    "Importacao falhou": ("Import failed", "La importación falló"),
    # progress
    "Preparando {name} para Companion...": ("Preparing {name} for Companion...", "Preparando {name} para Companion..."),
    "Reconstruindo {name} a partir do pacote...": ("Rebuilding {name} from the package...",
                                                  "Reconstruyendo {name} a partir del paquete..."),
    "Importando {name}...": ("Importing {name}...", "Importando {name}..."),
    "Lendo aparencias e corpo dos arquivos instalados...": ("Reading looks and body from the installed files...",
                                                            "Leyendo apariencias y cuerpo de los archivos instalados..."),
    "Lendo aparencias e corpo do personagem do editor...": ("Reading looks and body of the editor character...",
                                                            "Leyendo apariencias y cuerpo del personaje del editor..."),
    "Convertendo formas do personagem...": ("Converting the character's shapes...",
                                            "Convirtiendo las formas del personaje..."),
    "Gerando arquivos do personagem...": ("Creating the character files...", "Generando los archivos del personaje..."),
    "Convertendo formas: peca {done} de {total} ({name})...": ("Converting shapes: piece {done} of {total} ({name})...",
                                                             "Convirtiendo formas: pieza {done} de {total} ({name})..."),
    "Convertendo formas: peca {done} de {total}...": ("Converting shapes: piece {done} of {total}...",
                                                    "Convirtiendo formas: pieza {done} de {total}..."),
    "extraindo {count} arquivo(s) de {archive}": ("extracting {count} file(s) from {archive}",
                                                  "extrayendo {count} archivo(s) de {archive}"),
    "convertendo {count} arquivo(s) para leitura": ("converting {count} file(s) for reading",
                                                    "convirtiendo {count} archivo(s) para lectura"),
    "corpo: {count} pecas do editor": ("body: {count} pieces from the editor", "cuerpo: {count} piezas del editor"),
    "cilios: componente proprio ({look})": ("eyelashes: own component ({look})", "pestañas: componente propio ({look})"),
    "montando archive: {count} arquivos": ("packing archive: {count} files", "empaquetando archive: {count} archivos"),
    "Procurando os mods usados por este NPV...": ("Looking for the mods this NPV uses...",
                                                  "Buscando los mods que usa este NPV..."),
    "{count} requisito(s) detectado(s). Revise e clique CRIAR PACOTE.":
        ("{count} requirement(s) found. Review them and click CREATE PACKAGE.",
         "{count} requisito(s) detectado(s). Revísalos y haz clic en CREAR PAQUETE."),
    "Criando o pacote...": ("Creating the package...", "Creando el paquete..."),
    "Pacote criado em {folder}. Revise o NEXUS.txt antes de publicar.":
        ("Package created in {folder}. Review NEXUS.txt before publishing.",
         "Paquete creado en {folder}. Revisa NEXUS.txt antes de publicar."),
    "Conferindo os requisitos de {name}...": ("Checking the requirements of {name}...",
                                              "Comprobando los requisitos de {name}..."),
    "Instalando o WolvenKit...": ("Installing WolvenKit...", "Instalando WolvenKit..."),
    "Conversor automatico iniciado.": ("Automatic converter started.", "Conversor automático iniciado."),
    "Projeto mudou durante a importacao; tente novamente.": ("The project changed during the import; try again.",
                                                            "El proyecto cambió durante la importación; vuelve a intentarlo."),
    # WolvenKit setup (runtime_entry.SETUP_TEXT and progress steps)
    "WolvenKit 8.19.0 pronto.": ("WolvenKit 8.19.0 ready.", "WolvenKit 8.19.0 listo."),
    "WolvenKit necessario para importar NPVs.": ("WolvenKit is needed to import NPVs.",
                                                 "Se necesita WolvenKit para importar NPVs."),
    "A instalacao do WolvenKit mudou ou esta incompleta; instale de novo.":
        ("The WolvenKit installation changed or is incomplete; install it again.",
         "La instalación de WolvenKit cambió o está incompleta; vuelve a instalarla."),
    "iniciando": ("starting", "iniciando"),
    "verificando": ("checking", "comprobando"),
    "extraindo": ("extracting", "extrayendo"),
    "testando": ("testing", "probando"),
    # storage_bridge
    "Nao foi possivel salvar: {reason}": ("Could not save: {reason}", "No se pudo guardar: {reason}"),
    "Nenhum projeto salvo nesta instalacao.": ("No project saved in this installation.",
                                               "No hay ningún proyecto guardado en esta instalación."),
    "Projeto invalido: {reason}": ("Invalid project: {reason}", "Proyecto no válido: {reason}"),
    # export form (npv_package)
    "Este pacote pode conter ou depender de conteudo criado por terceiros. Verifique as permissoes dos respectivos "
    "autores e forneca os creditos e requisitos necessarios antes de distribuir o NPV.":
        ("This package may contain or depend on content made by others. Check the permissions of their authors and "
         "give the credits and requirements needed before distributing the NPV.",
         "Este paquete puede contener o depender de contenido creado por terceros. Revisa los permisos de sus "
         "autores y da los créditos y requisitos necesarios antes de distribuir el NPV."),
    "substitui arquivos do jogo": ("replaces game files", "reemplaza archivos del juego"),
    "arquivos do proprio mod": ("the mod's own files", "archivos propios del mod"),
    "patch do ArchiveXL herdado": ("inherited ArchiveXL patch", "parche de ArchiveXL heredado"),
    "a aparencia escolhida pode nao usar": ("the chosen look may not use it", "puede que la apariencia elegida no lo use"),
    # requirement lines (npv_package.requirement_lines / requirement_report)
    "NPV Maker (obrigatorio; reconstroi este NPV no seu PC)":
        ("NPV Maker (required; it rebuilds this NPV on your PC)",
         "NPV Maker (obligatorio; reconstruye este NPV en tu PC)"),
    "NPV Maker (obrigatorio; aplica no jogo as formas do rosto e do corpo)":
        ("NPV Maker (required; it applies the face and body shapes in game)",
         "NPV Maker (obligatorio; aplica en el juego las formas de la cara y del cuerpo)"),
}

# Pieces inside requirement lines (the names around them are mod names and stay as they are).
PIECES = {
    " (opcional)": (" (optional)", " (opcional)"),
    " (obrigatorio)": (" (required)", " (obligatorio)"),
    "  (nao conferido)": ("  (not checked)", "  (no comprobado)"),
    "  (servido por ": ("  (served by ", "  (servido por "),
    " por ": (" by ", " por "),
    "Preset original: ": ("Original preset: ", "Preset original: "),
}

_compiled: list[tuple[re.Pattern, str]] | None = None


def _index(lang: str) -> int:
    return 0 if lang == "en" else 1


def _patterns() -> list[tuple[re.Pattern, str]]:
    global _compiled
    if _compiled is None:
        _compiled = []
        for source in TEXTS:
            if "{" not in source:
                continue
            pattern = ""
            for literal, name, spec in re.findall(r"([^{]*)(?:\{(\w+)(!t)?\})?", source):
                pattern += re.escape(literal)
                if name:
                    pattern += "(?P<" + name + ">.+?)"
            _compiled.append((re.compile(pattern + r"\Z", re.S), source))
    return _compiled


def text(value, lang: str):
    """One message in `lang`; unknown messages are returned unchanged."""
    if lang == SOURCE or not isinstance(value, str) or not value:
        return value
    pair = TEXTS.get(value)
    if pair:
        return pair[_index(lang)]
    for pattern, source in _patterns():
        match = pattern.match(value)
        if match:
            target = TEXTS[source][_index(lang)]
            for name, captured in match.groupdict().items():
                kept = text(captured, lang) if "{" + name + "!t}" in source else captured
                target = target.replace("{" + name + "}", kept)
            return target
    for piece, pair in PIECES.items():
        if piece in value:
            value = value.replace(piece, pair[_index(lang)])
    return value


def code_text(code: str, lang: str, fallback: str) -> str:
    if lang == SOURCE or code not in CODES:
        return fallback
    return CODES[code][_index(lang)]


def hint_text(code: str, lang: str, fallback: str) -> str:
    if lang == SOURCE or code not in HINTS:
        return fallback
    return HINTS[code][_index(lang)]


def action_text(action: str, lang: str, fallback: str) -> str:
    if lang == SOURCE or action not in ACTIONS:
        return fallback
    return ACTIONS[action][_index(lang)]


def slot_text(slot: str, lang: str) -> str:
    if lang == SOURCE or slot not in SLOTS:
        return slot
    return SLOTS[slot][_index(lang)]


def reason_text(reason: str, lang: str) -> str:
    """A requirement reason: KIND_TEXT pieces joined by ', ' with an optional '; ' note."""
    if lang == SOURCE or not reason:
        return reason
    return "; ".join(", ".join(text(part, lang) for part in clause.split(", ")) for clause in reason.split("; "))
