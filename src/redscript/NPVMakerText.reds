// Player-facing text in the game's language (author request 01/10/2026: at least three languages, picked by the
// game). The source text is Portuguese and is also the key; English and Spanish come from the table below, and
// any other game language falls back to English. Codeware's LocalizationSystem is a ScriptableSystem, which does
// not exist in the main menu where the editor runs, so the language is read here from the same setting it uses
// (/language OnScreen). The converter gets it through "language.txt" in the storage (tools/i18n.py).

public class NPVText extends IScriptable {
  private let keys: array<String>;
  private let english: array<String>;
  private let spanish: array<String>;
  private let lang: String;
  private let written: String;

  public static func Get() -> ref<NPVText> {
    let session = NPVMakerSession.GetInstance();
    if !IsDefined(session.text) {
      let table = new NPVText();
      table.Fill();
      table.lang = NPVText.GameLanguage();
      session.text = table;
    };
    return session.text;
  }

  public static func GameLanguage() -> String {
    let settings = GameInstance.GetSettingsSystem(GetGameInstance());
    if !IsDefined(settings) { return "pt"; };
    let value = settings.GetVar(n"/language", n"OnScreen") as ConfigVarListName;
    if !IsDefined(value) { return "pt"; };
    let code = StrLower(NameToString(value.GetValue()));
    if StrBeginsWith(code, "pt") { return "pt"; };
    if StrBeginsWith(code, "es") { return "es"; };
    if StrLen(code) == 0 { return "pt"; };
    return "en";
  }

  // When a screen opens: the player may have changed the language in the settings.
  public static func Refresh() -> Void {
    let table = NPVText.Get();
    table.lang = NPVText.GameLanguage();
    if NotEquals(table.written, table.lang) && NPVFiles.Write("language.txt", "lang\t" + table.lang + "\nend\t1\n") {
      table.written = table.lang;
    };
  }

  public static func T(text: String) -> String {
    return NPVText.Get().Translate(text);
  }

  public static func F(text: String, a: String) -> String {
    return StrReplace(NPVText.T(text), "%1", a);
  }

  public static func F2(text: String, a: String, b: String) -> String {
    return StrReplace(StrReplace(NPVText.T(text), "%1", a), "%2", b);
  }

  public func Translate(text: String) -> String {
    if Equals(this.lang, "pt") { return text; };
    let i = 0;
    while i < ArraySize(this.keys) {
      if Equals(this.keys[i], text) {
        return Equals(this.lang, "es") ? this.spanish[i] : this.english[i];
      };
      i += 1;
    };
    return text;
  }

  private func Add(pt: String, en: String, es: String) -> Void {
    ArrayPush(this.keys, pt);
    ArrayPush(this.english, en);
    ArrayPush(this.spanish, es);
  }

  private func Fill() -> Void {
    this.Add("Requisitos identificados. Revise os dados e avance ate EXPORTAR MOD.", "Requirements identified. Review the details and continue to EXPORT MOD.", "Requisitos identificados. Revisa los datos y avanza hasta EXPORTAR MOD.");
    this.Add("Projeto salvo, mas a conversao nao foi iniciada. Confira TOOLS > WOLVENKIT.", "Project saved, but conversion did not start. Check TOOLS > WOLVENKIT.", "Proyecto guardado, pero la conversion no inicio. Revisa TOOLS > WOLVENKIT.");
    this.Add("Projeto salvo. Aguardando o conversor.", "Project saved. Waiting for the converter.", "Proyecto guardado. Esperando al conversor.");
    this.Add("VER NPV", "VIEW NPV", "VER NPV");
    this.Add("SALVANDO APARENCIA", "SAVING APPEARANCE", "GUARDANDO APARIENCIA");
    this.Add("PEDIDO ENVIADO", "REQUEST SENT", "SOLICITUD ENVIADA");
    this.Add("NPV CRIADO", "NPV CREATED", "NPV CREADO");
    this.Add("EXPORTANDO MOD", "EXPORTING MOD", "EXPORTANDO MOD");
    this.Add("MOD EXPORTADO", "MOD EXPORTED", "MOD EXPORTADO");
    this.Add("Sua biblioteca esta vazia. Use CRIAR NPV para comecar.", "Your library is empty. Use CREATE NPV to get started.", "Tu biblioteca esta vacia. Usa CREAR NPV para empezar.");
    this.Add("REMOCAO PENDENTE - REINICIE O JOGO", "REMOVAL PENDING - RESTART THE GAME", "ELIMINACION PENDIENTE - REINICIA EL JUEGO");
    this.Add("PRONTO", "READY", "LISTO");
    this.Add("CONFIRMAR REMOCAO", "CONFIRM REMOVAL", "CONFIRMAR ELIMINACION");
    this.Add("Preparacao e configuracao do conversor.", "Converter preparation and configuration.", "Preparacion y configuracion del conversor.");
    this.Add("ABRIR WOLVENKIT", "OPEN WOLVENKIT", "ABRIR WOLVENKIT");
    this.Add("DIAGNOSTICO", "DIAGNOSTICS", "DIAGNOSTICO");
    this.Add("Operacao em andamento. Acompanhe as etapas no painel a direita.", "Operation in progress. Follow the steps in the panel on the right.", "Operacion en curso. Sigue las etapas en el panel de la derecha.");
    this.Add("Use VER NPV ou EXPORTAR no painel a direita.", "Use VIEW NPV or EXPORT in the panel on the right.", "Usa VER NPV o EXPORTAR en el panel de la derecha.");
    this.Add("Criando o mod para instalar pelo Vortex. Aguarde...", "Creating the mod for installation with Vortex. Please wait...", "Creando el mod para instalar con Vortex. Espera...");
    this.Add("4. EXPORTAR", "4. EXPORT", "4. EXPORTAR");
    this.Add("EXPORTAR MOD", "EXPORT MOD", "EXPORTAR MOD");
    this.Add("Preset original (creditos)", "Original preset (credits)", "Preset original (creditos)");
    this.Add("ADICIONAR AOS FAVORITOS", "ADD TO FAVORITES", "ANADIR A FAVORITOS");
    this.Add("VER ORIGINAL", "SHOW ORIGINAL", "VER ORIGINAL");
    this.Add("VER NOVA ESCOLHA", "SHOW NEW CHOICE", "VER NUEVA OPCION");
    this.Add("NO PERSONAGEM", "ON CHARACTER", "EN EL PERSONAJE");
    this.Add("ROLE PARA EXPLORAR", "SCROLL TO EXPLORE", "DESPLAZA PARA EXPLORAR");
    this.Add("PROJETO", "PROJECT", "PROYECTO");
    this.Add("ROUPAS / EM BREVE", "OUTFIT / SOON", "ROPA / PRONTO");
    this.Add("FECHAR", "CLOSE", "CERRAR");
    this.Add("BUSCAR ESCOLHA", "SEARCH CHOICES", "BUSCAR OPCIONES");
    this.Add("TODAS AS ESCOLHAS", "ALL CHOICES", "TODAS LAS OPCIONES");
    this.Add("FAVORITAR ATUAL", "FAVORITE CURRENT", "GUARDAR FAVORITO");
    this.Add("REMOVER FAVORITO", "REMOVE FAVORITE", "QUITAR FAVORITO");
    this.Add("SO FAVORITOS", "FAVORITES ONLY", "SOLO FAVORITOS");
    this.Add("IR PARA ATUAL", "SHOW CURRENT", "VER ACTUAL");
    this.Add("ATUAL", "CURRENT", "ACTUAL");
    this.Add("opcoes", "choices", "opciones");
    this.Add("VER OPCOES", "VIEW CHOICES", "VER OPCIONES");
    this.Add("Nenhuma escolha encontrada. Limpe a busca ou mostre todas.", "No choices found. Clear the search or show all choices.", "Sin resultados. Borra la busqueda o muestra todas las opciones.");
    this.Add("Favorito nesta sessao. Armazenamento indisponivel para salvar.", "Favorited for this session. Storage is unavailable to save it.", "Favorito para esta sesion. Almacenamiento no disponible para guardarlo.");
    this.Add("CONVERTENDO PERSONAGEM", "CONVERTING CHARACTER", "CONVIRTIENDO PERSONAJE");
    this.Add("IMPORTANDO NPV", "IMPORTING NPV", "IMPORTANDO NPV");
    this.Add("IDENTIFICANDO REQUISITOS", "FINDING REQUIREMENTS", "IDENTIFICANDO REQUISITOS");
    this.Add("VERIFICANDO REQUISITOS", "CHECKING REQUIREMENTS", "VERIFICANDO REQUISITOS");
    this.Add("EXPORTANDO PACOTE", "EXPORTING PACKAGE", "EXPORTANDO PAQUETE");
    this.Add("NPV IMPORTADO", "NPV IMPORTED", "NPV IMPORTADO");
    this.Add("PACOTE EXPORTADO", "PACKAGE EXPORTED", "PAQUETE EXPORTADO");
    this.Add("REQUISITOS IDENTIFICADOS", "REQUIREMENTS FOUND", "REQUISITOS IDENTIFICADOS");
    this.Add("PROJETO SALVO", "PROJECT SAVED", "PROYECTO GUARDADO");
    this.Add("NPV REMOVIDO", "NPV REMOVED", "NPV ELIMINADO");
    this.Add("PRECISA DE ATENCAO", "NEEDS ATTENTION", "REQUIERE ATENCION");
    this.Add("ACOMPANHAMENTO", "ACTIVITY", "ACTIVIDAD");
    this.Add("APARENCIA > ROUPAS > PROJETO", "APPEARANCE > OUTFIT > PROJECT", "APARIENCIA > ROPA > PROYECTO");
    this.Add("01 APARENCIA", "01 APPEARANCE", "01 APARIENCIA");
    this.Add("03 PROJETO", "03 PROJECT", "03 PROYECTO");
    this.Add("02 ROUPAS", "02 OUTFIT", "02 ROPA");
    this.Add("Em breve", "Coming soon", "Proximamente");
    this.Add("GERENCIAR", "MANAGE", "GESTIONAR");
    this.Add("CATALOGO DE APARENCIA", "APPEARANCE CATALOG", "CATALOGO DE APARIENCIA");
    this.Add("Clique em uma escolha para ver no personagem.", "Click a choice to see it on the character.", "Haz clic en una opcion para verla en el personaje.");
    this.Add("TODAS AS OPCOES", "ALL OPTIONS", "TODAS LAS OPCIONES");
    this.Add("TODAS", "ALL", "TODAS");
    this.Add("ROSTO / CABELO", "FACE / HAIR", "ROSTRO / CABELLO");
    this.Add("CORPO", "BODY", "CUERPO");
    this.Add("BUSCAR POR NOME", "SEARCH BY NAME", "BUSCAR POR NOMBRE");
    this.Add("ESCOLHA ATUAL: %1", "CURRENT CHOICE: %1", "ELECCION ACTUAL: %1");
    this.Add("%1 escolhas", "%1 choices", "%1 opciones");
    this.Add("Nenhuma escolha encontrada.", "No choices found.", "No se encontraron opciones.");
    this.Add("PROJETO NPV", "NPV PROJECT", "PROYECTO NPV");
    this.Add("VOLTAR AOS PRESETS", "BACK TO PRESETS", "VOLVER A LOS PRESETS");
    this.Add("NPV MAKER / GERENCIAR", "NPV MAKER / MANAGE", "NPV MAKER / GESTIONAR");
    this.Add("A aparencia vem do editor. Volte ao editor para ajustar o visual.",
             "Appearance comes from the editor. Return to the editor to adjust the look.",
             "La apariencia viene del editor. Vuelve al editor para ajustar el aspecto.");
    this.Add("ATIVIDADE DO CONVERSOR", "CONVERTER ACTIVITY", "ACTIVIDAD DEL CONVERSOR");
    this.Add("Acompanhe aqui o processo e o resultado.", "Follow the process and its result here.", "Sigue aqui el proceso y su resultado.");
    this.Add("Escolha uma acao para comecar. O progresso aparecera aqui.", "Choose an action to begin. Progress will appear here.", "Elige una accion para comenzar. El progreso aparecera aqui.");
    this.Add("SEUS PERSONAGENS", "YOUR CHARACTERS", "TUS PERSONAJES");
    this.Add("RECONSTRUIR PACOTES", "REBUILD PACKAGES", "RECONSTRUIR PAQUETES");
    this.Add("PREPARAR CONVERSOR", "SET UP CONVERTER", "PREPARAR CONVERSOR");
    this.Add("COMPARTILHAR NPV", "SHARE NPV", "COMPARTIR NPV");
    this.Add("APARENCIA > CONVERSAO > INTEGRACOES", "APPEARANCE > CONVERSION > INTEGRATIONS", "APARIENCIA > CONVERSION > INTEGRACIONES");
    this.Add("1. DADOS", "1. DETAILS", "1. DATOS");
    this.Add("2. CREDITOS", "2. CREDITS", "2. CREDITOS");
    this.Add("3. REQUISITOS", "3. REQUIREMENTS", "3. REQUISITOS");
    this.Add("4. PACOTE", "4. PACKAGE", "4. PAQUETE");
    this.Add("ETAPA ANTERIOR", "PREVIOUS STEP", "PASO ANTERIOR");
    this.Add("PROXIMA ETAPA", "NEXT STEP", "SIGUIENTE PASO");
    // editor panel
    this.Add("SALVAR PROJETO", "SAVE PROJECT", "GUARDAR PROYECTO");
    this.Add("DEFINIR APARENCIA DO NPV", "DEFINE THE NPV'S APPEARANCE", "DEFINIR LA APARIENCIA DEL NPV");
    this.Add("Escolha o tipo de corpo do NPV. Ocasionalmente, a aparencia do NPV pode afetar o comportamento de outros personagens.",
             "Select the NPV's body type. The NPV's appearance may sometimes affect the behavior of other characters.",
             "Elige el tipo de cuerpo del NPV. A veces, la apariencia del NPV puede afectar al comportamiento de otros personajes.");
    this.Add("NPV MAKER / RECOLHER", "NPV MAKER / COLLAPSE", "NPV MAKER / CONTRAER");
    this.Add("NPV MAKER / ABRIR", "NPV MAKER / EXPAND", "NPV MAKER / ABRIR");
    this.Add("NOME DO PERSONAGEM", "CHARACTER NAME", "NOMBRE DEL PERSONAJE");
    this.Add("Edite a aparencia e clique em SALVAR PROJETO.", "Edit the look and click SAVE PROJECT.",
             "Edita la apariencia y haz clic en GUARDAR PROYECTO.");
    this.Add("ABRIR ULTIMO PROJETO", "OPEN LAST PROJECT", "ABRIR ÚLTIMO PROYECTO");
    this.Add("CORPO: %1", "BODY: %1", "CUERPO: %1");
    this.Add("CRIAR NPV", "CREATE NPV", "CREAR NPV");
    this.Add("Criar NPV: %1", "Create NPV: %1", "Crear NPV: %1");
    this.Add("O nome e a aparencia vem do editor (VOLTAR AO EDITOR para mudar).",
             "The name and the look come from the editor (BACK TO EDITOR to change them).",
             "El nombre y la apariencia vienen del editor (VOLVER AL EDITOR para cambiarlos).");
    this.Add("PROXIMO: GERENCIAR", "NEXT: MANAGE", "SIGUIENTE: GESTIONAR");
    this.Add("VER RELATORIO", "VIEW REPORT", "VER INFORME");
    this.Add("Arquivo: %1", "File: %1", "Archivo: %1");
    this.Add("Salvando e criando o NPV...", "Saving and creating the NPV...", "Guardando y creando el NPV...");
    this.Add("Solicitando ZIP privado com assets externos...", "Requesting a private ZIP with external assets...",
             "Solicitando un ZIP privado con assets externos...");
    this.Add("Projeto indisponivel: ative o RedFileSystem e reinicie o jogo.",
             "Project unavailable: enable RedFileSystem and restart the game.",
             "Proyecto no disponible: activa RedFileSystem y reinicia el juego.");
    this.Add("Procurando ultimo projeto...", "Looking for the last project...", "Buscando el último proyecto...");
    this.Add("Editor nao esta ativo.", "The editor is not active.", "El editor no está activo.");
    this.Add("Estado do editor indisponivel.", "Editor state unavailable.", "Estado del editor no disponible.");
    this.Add("Corpo diferente. Selecione o corpo do projeto antes de abrir.",
             "Different body. Select the project's body before opening.",
             "Cuerpo distinto. Selecciona el cuerpo del proyecto antes de abrir.");
    this.Add("Nenhuma aparencia aplicavel encontrada.", "No applicable look found.",
             "No se encontró ninguna apariencia aplicable.");
    this.Add("Abrindo projeto... %1/%2", "Opening project... %1/%2", "Abriendo proyecto... %1/%2");
    this.Add("Projeto aberto (%1 opcoes). Nao aplicadas:%2", "Project opened (%1 options). Not applied:%2",
             "Proyecto abierto (%1 opciones). No aplicadas:%2");
    this.Add("Projeto aberto: %1 opcoes.", "Project opened: %1 options.", "Proyecto abierto: %1 opciones.");
    this.Add("Salvamento indisponivel: ative o RedFileSystem e reinicie o jogo.",
             "Saving unavailable: enable RedFileSystem and restart the game.",
             "Guardado no disponible: activa RedFileSystem y reinicia el juego.");
    this.Add("Digite um nome para o personagem.", "Type a name for the character.", "Escribe un nombre para el personaje.");
    this.Add("Editor ainda nao esta pronto.", "The editor is not ready yet.", "El editor aún no está listo.");
    this.Add("Nenhuma opcao carregada. Aguarde o editor.", "No option loaded. Wait for the editor.",
             "Ninguna opción cargada. Espera al editor.");
    this.Add("Salvando projeto...", "Saving project...", "Guardando proyecto...");
    this.Add("WolvenKit necessario para importar: PROXIMO: GERENCIAR > WOLVENKIT. Salvando so o projeto...",
             "WolvenKit is needed to import: NEXT: MANAGE > WOLVENKIT. Saving only the project...",
             "Se necesita WolvenKit para importar: SIGUIENTE: GESTIONAR > WOLVENKIT. Guardando solo el proyecto...");
    this.Add("Falha ao gravar o projeto em r6/storages/NPVMaker.", "Could not write the project to r6/storages/NPVMaker.",
             "No se pudo escribir el proyecto en r6/storages/NPVMaker.");
    this.Add("Salvando e pedindo a importacao (corpo %1)...", "Saving and requesting the import (body %1)...",
             "Guardando y pidiendo la importación (cuerpo %1)...");
    this.Add("Projeto salvo. Importacao pedida (corpo %1). Preparando personagem...",
             "Project saved. Import requested (body %1). Preparing the character...",
             "Proyecto guardado. Importación pedida (cuerpo %1). Preparando el personaje...");
    this.Add("Projeto salvo! Voce pode continuar editando.", "Project saved! You can keep editing.",
             "¡Proyecto guardado! Puedes seguir editando.");
    this.Add("A lista de projetos ainda nao chegou do conversor. Tente de novo em alguns segundos.",
             "The project list has not arrived from the converter yet. Try again in a few seconds.",
             "La lista de proyectos aún no llegó del conversor. Vuelve a intentarlo en unos segundos.");
    this.Add("+ %1 (veja o relatorio)", "+ %1 (see the report)", "+ %1 (mira el informe)");
    this.Add("RedFileSystem ausente: ative-o no Vortex e reinicie o jogo para salvar projetos.",
             "RedFileSystem missing: enable it in Vortex and restart the game to save projects.",
             "Falta RedFileSystem: actívalo en Vortex y reinicia el juego para guardar proyectos.");
    // manager screen
    this.Add("NPV MAKER - GERENCIAR", "NPV MAKER - MANAGE", "NPV MAKER - GESTIONAR");
    this.Add("PACOTES", "PACKAGES", "PAQUETES");
    this.Add("VOLTAR AO EDITOR", "BACK TO EDITOR", "VOLVER AL EDITOR");
    this.Add("RedFileSystem ausente: ative-o no Vortex e reinicie o jogo.",
             "RedFileSystem missing: enable it in Vortex and restart the game.",
             "Falta RedFileSystem: actívalo en Vortex y reinicia el juego.");
    this.Add("pagina %1 de %2", "page %1 of %2", "página %1 de %2");
    this.Add("NPVs importados", "Imported NPVs", "NPVs importados");
    this.Add("Nenhum NPV importado.", "No NPV imported.", "Ningún NPV importado.");
    this.Add("  (pacote %1)", "  (package %1)", "  (paquete %1)");
    this.Add("  (remocao pendente: reinicie o jogo)", "  (removal pending: restart the game)",
             "  (eliminación pendiente: reinicia el juego)");
    this.Add("CONFIRMAR", "CONFIRM", "CONFIRMAR");
    this.Add("CANCELAR", "CANCEL", "CANCELAR");
    this.Add("EXPORTAR", "EXPORT", "EXPORTAR");
    this.Add("REMOVER", "REMOVE", "ELIMINAR");
    this.Add("Pacotes NPV instalados pelo Vortex (red4ext/plugins/NPVMaker/packages)",
             "NPV packages installed by Vortex (red4ext/plugins/NPVMaker/packages)",
             "Paquetes NPV instalados por Vortex (red4ext/plugins/NPVMaker/packages)");
    this.Add("Nenhum pacote NPV instalado.", "No NPV package installed.", "Ningún paquete NPV instalado.");
    this.Add(" por %1", " by %1", " por %1");
    this.Add("  [novo]", "  [new]", "  [nuevo]");
    this.Add("  [instalado]", "  [installed]", "  [instalado]");
    this.Add("  [instalada a %1: remova na aba NPVs e instale de novo]",
             "  [%1 installed: remove it in the NPVs tab and install again]",
             "  [instalada la %1: elimínala en la pestaña NPVs e instala de nuevo]");
    this.Add("  [invalido: %1]", "  [invalid: %1]", "  [no válido: %1]");
    this.Add("INSTALAR", "INSTALL", "INSTALAR");
    this.Add("WolvenKit (o NPV Maker usa o WolvenKit Console 8.19.0 para converter)",
             "WolvenKit (NPV Maker uses WolvenKit Console 8.19.0 to convert)",
             "WolvenKit (NPV Maker usa WolvenKit Console 8.19.0 para convertir)");
    this.Add("WolvenKit %1 pronto (.NET %2).", "WolvenKit %1 ready (.NET %2).", "WolvenKit %1 listo (.NET %2).");
    this.Add("Instalando... %1", "Installing... %1", "Instalando... %1");
    this.Add(" %1 de %2 bytes", " %1 of %2 bytes", " %1 de %2 bytes");
    this.Add("Esperando o conversor (ele inicia junto com o jogo).", "Waiting for the converter (it starts with the game).",
             "Esperando al conversor (se inicia con el juego).");
    this.Add("WolvenKit necessario para importar NPVs.", "WolvenKit is needed to import NPVs.",
             "Se necesita WolvenKit para importar NPVs.");
    this.Add("Nao deu certo: %1 %2", "It did not work: %1 %2", "No funcionó: %1 %2");
    this.Add("BAIXAR AUTOMATICAMENTE: WolvenKit Console 8.19.0 do GitHub oficial",
             "DOWNLOAD AUTOMATICALLY: WolvenKit Console 8.19.0 from the official GitHub",
             "DESCARGAR AUTOMÁTICAMENTE: WolvenKit Console 8.19.0 del GitHub oficial");
    this.Add(" e o .NET 8.0.31 da Microsoft", " and .NET 8.0.31 from Microsoft", " y .NET 8.0.31 de Microsoft");
    this.Add("; confere o hash e instala fora da pasta do jogo.", "; it checks the hash and installs outside the game folder.",
             "; comprueba el hash e instala fuera de la carpeta del juego.");
    this.Add("BAIXAR AUTOMATICAMENTE", "DOWNLOAD AUTOMATICALLY", "DESCARGAR AUTOMÁTICAMENTE");
    this.Add("Ou o caminho do WolvenKit.CLI.exe (8.19.0) ou do WolvenKit.Console-8.19.0.zip oficial:",
             "Or the path of WolvenKit.CLI.exe (8.19.0) or of the official WolvenKit.Console-8.19.0.zip:",
             "O la ruta de WolvenKit.CLI.exe (8.19.0) o del WolvenKit.Console-8.19.0.zip oficial:");
    this.Add("USAR INSTALACAO EXISTENTE", "USE EXISTING INSTALL", "USAR INSTALACIÓN EXISTENTE");
    this.Add("INSTALAR ZIP MANUALMENTE", "INSTALL ZIP MANUALLY", "INSTALAR ZIP MANUALMENTE");
    this.Add("Procurando os mods usados por este NPV. Aguarde...", "Looking for the mods this NPV uses. Please wait...",
             "Buscando los mods que usa este NPV. Espera...");
    this.Add("Nao foi possivel gravar o pedido em r6/storages/NPVMaker.", "Could not write the request to r6/storages/NPVMaker.",
             "No se pudo escribir la petición en r6/storages/NPVMaker.");
    this.Add("Exportar NPV: %1", "Export NPV: %1", "Exportar NPV: %1");
    this.Add("VOLTAR", "BACK", "VOLVER");
    this.Add("Nome", "Name", "Nombre");
    this.Add("Autor", "Author", "Autor");
    this.Add("Versao (1.0.0)", "Version (1.0.0)", "Versión (1.0.0)");
    this.Add("Descricao", "Description", "Descripción");
    this.Add("O character_id sera criado neste primeiro export e nao muda nas proximas versoes.",
             "The character_id is created on this first export and does not change in later versions.",
             "El character_id se crea en esta primera exportación y no cambia en las próximas versiones.");
    this.Add("Preset original (creditos; nao e necessario para reconstruir)", "Original preset (credits; not needed to rebuild)",
             "Preset original (créditos; no es necesario para reconstruir)");
    this.Add("Nome do preset", "Preset name", "Nombre del preset");
    this.Add("Autor do preset", "Preset author", "Autor del preset");
    this.Add("URL do preset", "Preset URL", "URL del preset");
    this.Add("Nexus ID do preset", "Preset Nexus ID", "Nexus ID del preset");
    this.Add("Versao do preset", "Preset version", "Versión del preset");
    this.Add("Requisitos (detectados; revise). NPV Maker entra sempre como requisito.",
             "Requirements (detected; review them). NPV Maker is always a requirement.",
             "Requisitos (detectados; revísalos). NPV Maker siempre es un requisito.");
    this.Add("[x] INCLUIR", "[x] INCLUDE", "[x] INCLUIR");
    this.Add("[ ] INCLUIR", "[ ] INCLUDE", "[ ] INCLUIR");
    this.Add("OBRIGATORIO", "REQUIRED", "OBLIGATORIO");
    this.Add("OPCIONAL", "OPTIONAL", "OPCIONAL");
    this.Add("(sem nome)", "(no name)", "(sin nombre)");
    this.Add("  [adicionado]", "  [added]", "  [añadido]");
    this.Add("  [detectado]", "  [detected]", "  [detectado]");
    this.Add("  [sem Nexus ID: use EDITAR]", "  [no Nexus ID: use EDIT]", "  [sin Nexus ID: usa EDITAR]");
    this.Add("Modo foto: o NPV so aparece com o PhotoMode-EX (Nexus 18839) instalado; ele entra nos requisitos.",
             "Photo mode: the NPV only shows with PhotoMode-EX (Nexus 18839) installed; it goes into the requirements.",
             "Modo foto: el NPV solo aparece con PhotoMode-EX (Nexus 18839) instalado; entra en los requisitos.");
    this.Add("A versao %1 ja foi exportada. Para exportar de novo, use outra versao (ex.: %2).",
             "Version %1 was already exported. To export again, use another version (e.g. %2).",
             "La versión %1 ya se exportó. Para exportar de nuevo, usa otra versión (p. ej. %2).");
    this.Add("A versao %1 ja foi exportada. Troque a versao em 1. DADOS (ex.: %2) para exportar de novo.",
             "Version %1 was already exported. Change the version in 1. DETAILS (e.g. %2) to export again.",
             "La versión %1 ya se exportó. Cambia la versión en 1. DATOS (p. ej. %2) para exportar de nuevo.");
    this.Add("EDITAR", "EDIT", "EDITAR");
    this.Add("(nome, autor, URL, Nexus ID)", "(name, author, URL, Nexus ID)", "(nombre, autor, URL, Nexus ID)");
    this.Add("ADICIONAR REQUISITO", "ADD REQUIREMENT", "AÑADIR REQUISITO");
    this.Add("CRIAR PACOTE", "CREATE PACKAGE", "CREAR PAQUETE");
    this.Add("NCA: COMPANHEIRO", "NCA: COMPANION", "NCA: COMPAÑERO");
    this.Add("MODO FOTO", "PHOTO MODE", "MODO FOTO");
    this.Add("NCA: MERCENARIO", "NCA: MERCENARY", "NCA: MERCENARIO");
    this.Add("ROUPA PADRAO: SO CALCINHA", "DEFAULT OUTFIT: BOTTOM ONLY", "ROPA PREDETERMINADA: SOLO BRAGA");
    this.Add("ROUPA PADRAO: COMPLETA", "DEFAULT OUTFIT: FULL UNDERWEAR", "ROPA PREDETERMINADA: COMPLETA");
    this.Add("ROUPA PADRAO: NENHUMA", "DEFAULT OUTFIT: NONE", "ROPA PREDETERMINADA: NINGUNA");
    this.Add("Funciona com (opcional; o NPV Maker instala o necessario em cada um):",
             "Works with (optional; NPV Maker installs what each one needs):",
             "Funciona con (opcional; NPV Maker instala lo necesario en cada uno):");
    this.Add("NCA + AMM juntos ainda nao foram testados: o NPV pode aparecer duas vezes no NCA.",
             "NCA + AMM together are not tested yet: the NPV may show twice in NCA.",
             "NCA + AMM juntos aún no se probaron: el NPV puede aparecer dos veces en NCA.");
    this.Add("Criando o pacote. Aguarde...", "Creating the package. Please wait...", "Creando el paquete. Espera...");
    this.Add("Informe o caminho completo do WolvenKit.CLI.exe.", "Enter the full path of WolvenKit.CLI.exe.",
             "Escribe la ruta completa de WolvenKit.CLI.exe.");
    this.Add("Informe o caminho completo do WolvenKit.Console-8.19.0.zip.",
             "Enter the full path of WolvenKit.Console-8.19.0.zip.",
             "Escribe la ruta completa de WolvenKit.Console-8.19.0.zip.");
    this.Add("Pedido enviado ao conversor. Aguarde...", "Request sent to the converter. Please wait...",
             "Petición enviada al conversor. Espera...");
    this.Add("Remocao pedida. Aguarde alguns segundos.", "Removal requested. Wait a few seconds.",
             "Eliminación pedida. Espera unos segundos.");
    this.Add("Conferindo requisitos e reconstruindo. Pode levar varios minutos...",
             "Checking requirements and rebuilding. It can take several minutes...",
             "Comprobando requisitos y reconstruyendo. Puede tardar varios minutos...");
  }
}
