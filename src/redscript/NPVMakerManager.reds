import Codeware.UI.*

// The manager screen of the NPV maker editor (0.5.0, author decision 30/09/2026: everything in game, no CET).
// Author request 01/10/2026: no separate main menu entry; PROXIMO in the editor panel hides the editor and shows this
// screen, VOLTAR AO EDITOR brings the editor back. Replaces the CET overlay windows: imported NPVs (remove, export), the EXPORTAR NPV form, NPV packages
// installed by Vortex (install) and the WolvenKit setup. The converter lists and statuses arrive as
// "<name>.txt" in r6/storages/NPVMaker (tools/storage_bridge.py); requests leave as JSON files there.

// UI-only operation tracking. Reads existing acknowledgements; never writes backend state.
// The session field that holds it is declared inside NPVMakerSession (NPVMaker.reds), never by @addField here.
public class NPVManagerOperation extends IScriptable {
  public let busy: Bool;
  public let kind: String;
  public let file: String;
  public let token: String;
  public let name: String;
  public let stage: String;
  public let message: String;
  public let raw: String;
  private let awaitingSave: Bool;

  public func Begin(kind: String, file: String, token: String, name: String, message: String) -> Void {
    this.busy = true; this.kind = kind; this.file = file; this.token = token;
    this.name = name; this.message = message; this.raw = ""; this.stage = "queued";
    this.awaitingSave = Equals(kind, "create");
  }
  public func Poll() -> Void {
    if !this.busy { return; };
    let session = NPVMakerSession.GetInstance();
    if this.awaitingSave {
      if session.pendingSave { this.stage = "capturing"; this.message = session.lastStatus; return; };
      if StrLen(session.saveToken) == 0 {
        this.busy = false; this.stage = "error"; this.message = session.lastStatus; return;
      };
      let result = NPVFiles.Read("save-" + session.saveToken + ".result.txt");
      if !NPVFiles.Complete(result) { this.stage = "queued"; this.message = session.lastStatus; return; };
      let rows = NPVFiles.Rows(result);
      if NotEquals(NPVFiles.Value(rows, "stage"), "saved") {
        this.busy = false; this.stage = "error"; this.message = NPVFiles.Value(rows, "message"); return;
      };
      this.awaitingSave = false;
      this.token = NPVFiles.Value(rows, "id");
      if NotEquals(NPVFiles.Value(rows, "after"), "build") {
        this.busy = false; this.stage = "saved";
        this.message = NPVText.T("Projeto salvo, mas a conversao nao foi iniciada. Confira TOOLS > WOLVENKIT."); return;
      };
      this.file = this.token + ".txt";
      this.stage = "queued";
      this.message = NPVText.T("Projeto salvo. Aguardando o conversor.");
    };
    let raw = NPVFiles.Read(this.file);
    if !NPVFiles.Complete(raw) { return; };
    this.raw = raw;
    let rows = NPVFiles.Rows(raw);
    this.stage = NPVFiles.Value(rows, "stage");
    if StrLen(NPVFiles.Value(rows, "message")) > 0 { this.message = NPVFiles.Value(rows, "message"); };
    if Equals(this.file, "setup.txt") {
      let state = NPVFiles.Value(rows, "state");
      this.busy = Equals(state, "INSTALLING");
      return;
    };
    if Equals(this.stage, "installed") || Equals(this.stage, "error") || Equals(this.stage, "removed")
      || Equals(this.stage, "exported") || Equals(this.stage, "packaged") || Equals(this.stage, "requirements_ready") {
      this.busy = false;
    };
  }
}

public class NPVExportDep extends IScriptable {
  public let name: String;
  public let author: String;
  public let url: String;
  public let nexus: String;
  public let reason: String;
  public let required: Bool;
  public let include: Bool;
  public let detected: Int32;
}

public class NPVManagerView extends IScriptable {
  private let controller: wref<inkGameController>;
  private let host: wref<inkCompoundWidget>;
  private let root: ref<inkCanvas>;
  private let body: ref<inkVerticalPanel>;
  private let noteText: ref<inkText>;
  private let logText: ref<inkText>;
  private let stageText: ref<inkText>;
  private let activityShade: ref<inkRectangle>;
  private let activityAccent: ref<inkRectangle>;
  private let resultName: ref<inkText>;
  private let resultActions: ref<inkHorizontalPanel>;
  private let resultExport: ref<SimpleButton>;
  private let resultView: ref<SimpleButton>;
  private let npvsTab: ref<SimpleButton>;
  private let toolsTab: ref<SimpleButton>;
  private let headerCreate: ref<SimpleButton>;
  private let headerBack: ref<SimpleButton>;
  private let job: ref<NPVManagerOperation>;
  private let focusToken: String;
  private let hidden: array<wref<inkWidget>>;
  private let ticker: ref<NPVMakerTicker>;
  private let ticks: Int32;
  private let tab: String;
  private let page: Int32;
  private let note: String;
  private let noteFile: String;
  private let noteRaw: String;
  private let confirmToken: String;
  private let importedRaw: String;
  private let packagesRaw: String;
  private let setupRaw: String;
  private let imported: array<ref<NPVRow>>;
  private let packages: array<ref<NPVRow>>;
  private let setup: array<ref<NPVRow>>;
  // EXPORTAR NPV form
  private let exportToken: String;
  private let exportName: String;
  private let draftRaw: String;
  private let draftLoaded: Bool;
  private let characterId: String;
  private let notice: String;
  private let form: array<String>;
  private let inputs: array<wref<HubTextInput>>;
  private let inputIndices: array<Int32>;
  private let exportStep: Int32;
  private let depPage: Int32;
  private let sectionText: ref<inkText>;
  private let deps: array<ref<NPVExportDep>>;
  private let exportedVersions: array<String>;
  private let editing: Int32;
  private let depInputs: array<wref<HubTextInput>>;
  private let setupPath: String;
  private let pathInput: wref<HubTextInput>;
  private let editorMenu: wref<characterCreationBodyMorphMenu>;
  // Mods the published NPV works with (tools/adapters.py); INSTALAR writes their files.
  private let withCompanion: Bool;
  private let withNCA: Bool;
  private let withAMM: Bool;
  private let ncaMerc: Bool;
  private let withPhoto: Bool;
  // Default outfit of the rebuilt NPV (runtime_npc.UNDERWEAR_MODES): bottom, full or none.
  private let underwear: String;

  public static func Open(menu: ref<characterCreationBodyMorphMenu>) -> ref<NPVManagerView> {
    let view = new NPVManagerView();
    view.controller = menu;
    view.editorMenu = menu;
    view.host = menu.GetRootCompoundWidget();
    view.tab = "npvs";
    let session = NPVMakerSession.GetInstance();
    if !IsDefined(session.managerOperation) { session.managerOperation = new NPVManagerOperation(); };
    view.job = session.managerOperation;
    view.editing = -1;
    NPVText.Refresh();
    view.Build();
    return view;
  }

  private func SaveProjectName() -> Void {
    let session = NPVMakerSession.GetInstance();
    if IsDefined(session.nameInput) { session.projectName = session.nameInput.GetText(); };
  }

  public func Close() -> Void {
    this.SaveProjectName();
    NPVMakerSession.GetInstance().nameInput = null;
    NPVMakerSession.GetInstance().bodyButton = null;
    if IsDefined(this.ticker) { this.ticker.Stop(); };
    if IsDefined(this.host) && IsDefined(this.root) { this.host.RemoveChild(this.root); };
    for widget in this.hidden {
      if IsDefined(widget) { widget.SetVisible(true); };
    };
    ArrayClear(this.hidden);
    this.root = null;
  }

  public func IsOpen() -> Bool {
    return IsDefined(this.root);
  }

  public func Typing() -> Bool {
    let nameInput = NPVMakerSession.GetInstance().nameInput;
    if IsDefined(nameInput) && nameInput.IsFocused() { return true; };
    for input in this.inputs {
      if IsDefined(input) && input.IsFocused() { return true; };
    };
    for input in this.depInputs {
      if IsDefined(input) && input.IsFocused() { return true; };
    };
    return IsDefined(this.pathInput) && this.pathInput.IsFocused();
  }

  // Back key: the export form returns to its list, anything else returns to the editor.
  public func Back() -> Void {
    if Equals(this.tab, "export") {
      this.SaveForm();
      this.tab = "npvs";
      this.editing = -1;
      this.Render();
      return;
    };
    this.ReturnToEditor();
  }

  private func ReturnToEditor() -> Void {
    if this.job.busy { return; };
    this.Close();
    if IsDefined(this.editorMenu) { this.editorMenu.NPVManagerClosed(); };
  }

  private func Build() -> Void {
    // The editor stays underneath; its widgets are hidden so its options cannot take the clicks.
    let i = 0;
    while i < this.host.GetNumChildren() {
      let child = this.host.GetWidgetByIndex(i);
      if IsDefined(child) && child.IsVisible() {
        child.SetVisible(false);
        ArrayPush(this.hidden, child);
      };
      i += 1;
    };
    let root = new inkCanvas();
    root.SetName(n"NPVMakerManager");
    root.SetAnchor(inkEAnchor.Fill);
    root.Reparent(this.host);
    this.root = root;
    let shade = new inkRectangle();
    shade.SetAnchor(inkEAnchor.Fill);
    shade.SetTintColor(new HDRColor(0.045, 0.009, 0.018, 1.0));
    shade.SetOpacity(0.94);
    shade.Reparent(root);
    let column = new inkVerticalPanel();
    column.SetAnchor(inkEAnchor.TopLeft);
    column.SetMargin(new inkMargin(220.0, 160.0, 0.0, 0.0));
    column.SetChildMargin(new inkMargin(0.0, 0.0, 0.0, 10.0));
    column.SetFitToContent(true);
    column.Reparent(root);
    let header = new inkHorizontalPanel();
    header.SetChildMargin(new inkMargin(0.0, 0.0, 20.0, 0.0));
    header.Reparent(column);
    let brand = this.Label(header, "NPV MAKER", 64, true);
    brand.SetSize(1180.0, 84.0); brand.SetFitToContent(false);
    this.headerCreate = this.Button(header, NPVText.T("CRIAR NPV"), n"npvm_open_create", 460.0);
    this.headerBack = this.Button(header, NPVText.T("VOLTAR AO EDITOR"), n"npvm_close", 560.0);
    let tabs = new inkHorizontalPanel();
    tabs.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
    tabs.Reparent(column);
    this.npvsTab = this.Button(tabs, "NPVs", n"npvm_tab_npvs", 320.0);
    this.toolsTab = this.Button(tabs, "TOOLS", n"npvm_tab_tools", 320.0);
    this.sectionText = this.Label(column, "", 34, true);
    let body = new inkVerticalPanel();
    body.SetChildMargin(new inkMargin(0.0, 0.0, 0.0, 8.0));
    body.SetFitToContent(true);
    body.Reparent(column);
    this.body = body;
    // Dedicated activity rail: body redraws and long forms never push feedback off-screen.
    let rail = new inkCanvas();
    rail.SetAnchor(inkEAnchor.TopLeft);
    rail.SetMargin(new inkMargin(2700.0, 160.0, 0.0, 0.0));
    rail.SetSize(900.0, 1720.0);
    rail.Reparent(root);
    let railShade = new inkRectangle();
    railShade.SetAnchor(inkEAnchor.Fill);
    railShade.SetTintColor(new HDRColor(0.065, 0.012, 0.024, 1.0));
    railShade.Reparent(rail);
    this.activityShade = railShade;
    let accent = new inkRectangle();
    accent.SetSize(4.0, 1720.0);
    accent.SetTintColor(ThemeColors.Bittersweet());
    accent.Reparent(rail);
    this.activityAccent = accent;
    // Reuse the native nine-slice frame; the NPV colors and composition are our own.
    let frame = new inkImage();
    frame.SetAtlasResource(r"base\\gameplay\\gui\\common\\shapes\\atlas_shapes_sync.inkatlas");
    frame.SetTexturePart(n"sorting_fg");
    frame.SetNineSliceScale(true);
    frame.SetNineSliceGrid(new inkMargin(50.0, 30.0, 100.0, 30.0));
    frame.SetAnchor(inkEAnchor.Fill);
    frame.SetTintColor(ThemeColors.Bittersweet());
    frame.SetOpacity(0.35);
    frame.Reparent(rail);
    let activity = this.Column(rail);
    activity.SetMargin(new inkMargin(36.0, 32.0, 0.0, 0.0));
    NPVIcons.Add(activity, n"convert", 72.0);
    this.Label(activity, NPVText.T("ATIVIDADE DO CONVERSOR"), 40, true).SetWrapping(true, 820.0);
    this.stageText = this.Label(activity, "", 58, true);
    this.stageText.SetWrapping(true, 820.0);
    this.noteText = this.Label(activity, "", 42, false);
    this.noteText.SetWrapping(true, 820.0);
    this.noteText.SetSize(820.0, 400.0);
    this.noteText.SetFitToContent(false);
    // Steps of the current task with their time, newest last, like a terminal (author request 05/10/2026).
    this.logText = this.Label(activity, "", 26, false);
    this.logText.SetWrapping(true, 820.0);
    this.logText.SetSize(820.0, 580.0);
    this.logText.SetFitToContent(false);
    this.logText.SetVerticalAlignment(textVerticalAlignment.Bottom);
    this.logText.SetTintColor(ThemeColors.ElectricBlue());
    this.logText.SetOpacity(0.75);
    this.resultName = this.Label(activity, "", 46, true);
    this.resultName.SetSize(820.0, 100.0); this.resultName.SetFitToContent(false);
    this.resultName.SetWrapping(true, 820.0);
    this.resultActions = new inkHorizontalPanel();
    this.resultActions.SetChildMargin(new inkMargin(0.0, 0.0, 16.0, 0.0));
    this.resultActions.Reparent(activity);
    this.resultView = this.Button(this.resultActions, NPVText.T("VER NPV"), n"npvm_result_view", 380.0);
    this.resultExport = this.Button(this.resultActions, NPVText.T("EXPORTAR"), n"npvm_result_export", 380.0);
    if !NPVFiles.Ready() {
      this.note = NPVText.T("RedFileSystem ausente: ative-o no Vortex e reinicie o jogo.");
    };
    this.Refresh(true);
    this.Render();
    this.ticker = NPVMakerTicker.Start(root, this);
  }

  // Every 0.15 s (NPVMakerTicker); the files are read about once a second. The editor ticker is stopped while this
  // screen is open, so the editor work (save, import, open, status) ticks from here.
  public func Tick() -> Void {
    let wasBusy = this.job.busy;
    // Poll the save acknowledgement before EditorTick consumes/deletes it.
    this.job.Poll();
    if IsDefined(this.editorMenu) { NPVMakerSession.GetInstance().EditorTick(); };
    this.ticks += 1;
    if NotEquals(wasBusy, this.job.busy) { this.Refresh(true); this.Render(); };
    this.ShowNote();
    if this.ticks % 7 != 0 { return; };
    if this.Refresh(false) && this.editing < 0 && NotEquals(this.tab, "export") { this.Render(); };
    if Equals(this.tab, "export") && !this.draftLoaded { this.LoadDraft(); };
    if Equals(this.noteFile, "") && StrLen(NPVMakerSession.GetInstance().lastStatus) > 0 {
      this.note = NPVMakerSession.GetInstance().lastStatus;
    };
    this.PollNote();
  }

  private func Refresh(force: Bool) -> Bool {
    let changed = force;
    let raw = NPVFiles.Read("imported.txt");
    if NotEquals(raw, this.importedRaw) && NPVFiles.Complete(raw) {
      this.importedRaw = raw;
      this.imported = this.Only(NPVFiles.Rows(raw), "npv");
      changed = true;
    };
    raw = NPVFiles.Read("packages.txt");
    if NotEquals(raw, this.packagesRaw) && NPVFiles.Complete(raw) {
      this.packagesRaw = raw;
      this.packages = this.Only(NPVFiles.Rows(raw), "package");
    };
    raw = NPVFiles.Read("setup.txt");
    if NotEquals(raw, this.setupRaw) && NPVFiles.Complete(raw) {
      this.setupRaw = raw;
      this.setup = NPVFiles.Rows(raw);
      changed = changed || Equals(this.tab, "wk");
    };
    return changed;
  }

  private func Only(rows: array<ref<NPVRow>>, key: String) -> array<ref<NPVRow>> {
    let found: array<ref<NPVRow>>;
    for row in rows {
      if Equals(row.Cell(0), key) { ArrayPush(found, row); };
    };
    return found;
  }

  // The result of the last action (remove, install, export, setup), from its status file.
  private func PollNote() -> Void {
    if Equals(this.noteFile, "") { this.ShowNote(); return; };
    let raw = NPVFiles.Read(this.noteFile);
    if Equals(raw, this.noteRaw) || !NPVFiles.Complete(raw) { return; };
    this.noteRaw = raw;
    let rows = NPVFiles.Rows(raw);
    let text = NPVFiles.Value(rows, "message");
    // Requirements are reviewed on their own paginated step, not appended to the activity headline.
    if Equals(this.noteFile, "setup.txt") {
      let hint = NPVFiles.Value(rows, "hint");
      if StrLen(hint) > 0 { text += " " + hint; };
    };
    if StrLen(text) > 0 { this.note = text; };
    this.ShowNote();
  }

  private func ShowNote() -> Void {
    let active = this.job.busy;
    let tracked = StrLen(this.job.kind) > 0;
    let raw = StrLen(this.noteFile) > 0 ? this.noteRaw : NPVMakerSession.GetInstance().statusRaw;
    let stage = tracked ? this.job.stage : NPVFiles.Value(NPVFiles.Rows(raw), "stage");
    let failed = Equals(stage, "error");
    let success = Equals(stage, "installed") || Equals(stage, "exported") || Equals(stage, "packaged");
    let color = failed ? ThemeColors.Bittersweet() : (success ? new HDRColor(0.35, 1.0, 0.65, 1.0) : ThemeColors.ElectricBlue());
    this.stageText.SetText(this.StageTitle(stage));
    this.stageText.SetFontSize(active || success || failed ? 66 : 44);
    this.stageText.SetTintColor(color);
    this.noteText.SetTintColor(color);
    let message = tracked ? this.job.message : this.note;
    if tracked && Equals(stage, "requirements_ready") { message = NPVText.T("Requisitos identificados. Revise os dados e avance ate EXPORTAR MOD."); };
    if tracked && Equals(stage, "exporting") { message = NPVText.T("Criando o mod para instalar pelo Vortex. Aguarde..."); };
    this.noteText.SetText(StrLen(message) > 0 ? message : NPVText.T("Escolha uma acao para comecar. O progresso aparecera aqui."));
    this.logText.SetText(this.ActivityLog(tracked ? this.job.raw : raw));
    this.noteText.SetOpacity(active || success || failed ? 1.0 : 0.65);
    this.activityShade.SetOpacity(active || failed ? 1.0 : 0.45);
    this.activityAccent.SetTintColor(color);
    this.activityAccent.SetWidth(active || failed ? 8.0 : 4.0);
    this.activityAccent.SetOpacity(active || success || failed ? 1.0 : 0.3);
    let created = Equals(this.job.kind, "create") && Equals(stage, "installed") && !active;
    this.resultName.SetVisible(created);
    this.resultActions.SetVisible(created);
    this.resultName.SetText(this.job.name);
    let resultIndex = this.FindImported(this.job.token);
    this.resultView.SetDisabled(resultIndex < 0);
    let canExport = false;
    if resultIndex >= 0 { canExport = !Equals(this.imported[resultIndex].Cell(5), "1") && StrLen(this.imported[resultIndex].Cell(3)) == 0; };
    this.resultExport.SetDisabled(!canExport);
    this.headerCreate.SetDisabled(active);
    this.headerBack.SetDisabled(active);
  }

  private func ActivityLog(raw: String) -> String {
    let lines: array<String>;
    for row in NPVFiles.Rows(raw) {
      if Equals(row.Cell(0), "log") { ArrayPush(lines, "> " + row.Cell(1) + "  " + row.Cell(2)); };
    };
    let text = "";
    let start = ArraySize(lines) > 10 ? ArraySize(lines) - 10 : 0;
    let i = start;
    while i < ArraySize(lines) {
      text += (i > start ? "\n" : "") + lines[i];
      i += 1;
    };
    return text;
  }

  private func StageTitle(stage: String) -> String {
    switch stage {
      case "capturing": return NPVText.T("SALVANDO APARENCIA");
      case "queued": return NPVText.T("PEDIDO ENVIADO");
      case "building": return NPVText.T("CONVERTENDO PERSONAGEM");
      case "installing": return NPVText.T("IMPORTANDO NPV");
      case "detecting": return NPVText.T("IDENTIFICANDO REQUISITOS");
      case "checking": return NPVText.T("VERIFICANDO REQUISITOS");
      case "exporting": return NPVText.T("EXPORTANDO MOD");
      case "packaging": return NPVText.T("EXPORTANDO MOD");
      case "installed": return NPVText.T("NPV CRIADO");
      case "exported": return NPVText.T("MOD EXPORTADO");
      case "packaged": return NPVText.T("MOD EXPORTADO");
      case "requirements_ready": return NPVText.T("REQUISITOS IDENTIFICADOS");
      case "saved": return NPVText.T("PROJETO SALVO");
      case "removed": return NPVText.T("NPV REMOVIDO");
      case "error": return NPVText.T("PRECISA DE ATENCAO");
      default: return NPVText.T("ACOMPANHAMENTO");
    };
  }

  private func Watch(file: String, text: String) -> Void {
    if StrLen(file) > 0 && NotEquals(file, "setup.txt") {
      this.job.Begin("action", file, "", "", text);
    } else if !this.job.busy { this.job.kind = ""; };
    this.noteFile = file;
    this.noteRaw = "";
    this.note = text;
    this.ShowNote();
  }

  private func Render() -> Void {
    // A redraw (new setup state from the converter) must not drop a path being typed.
    if IsDefined(this.pathInput) { this.setupPath = this.pathInput.GetText(); };
    // Commit the manager name before any tab/action redraw destroys its input widget.
    this.SaveProjectName();
    if Equals(this.tab, "export") { this.SaveForm(); };
    NPVMakerSession.GetInstance().nameInput = null;
    NPVMakerSession.GetInstance().bodyButton = null;
    this.body.RemoveAllChildren();
    ArrayClear(this.inputs);
    ArrayClear(this.inputIndices);
    ArrayClear(this.depInputs);
    this.pathInput = null;
    this.npvsTab.SetText(Equals(this.tab, "npvs") ? "> NPVs" : "NPVs");
    this.toolsTab.SetText(Equals(this.tab, "tools") || Equals(this.tab, "wk") ? "> TOOLS" : "TOOLS");
    this.sectionText.SetText(NPVText.T("SEUS PERSONAGENS"));
    if Equals(this.tab, "tools") { this.sectionText.SetText("TOOLS"); };
    if Equals(this.tab, "wk") { this.sectionText.SetText(NPVText.T("PREPARAR CONVERSOR")); };
    if Equals(this.tab, "export") { this.sectionText.SetText(NPVText.T("COMPARTILHAR NPV")); };
    if Equals(this.tab, "create") { this.sectionText.SetText(NPVText.T("APARENCIA > CONVERSAO > INTEGRACOES")); };
    if Equals(this.tab, "npvs") { this.RenderImported(); };
    if Equals(this.tab, "tools") { this.RenderTools(); };
    if Equals(this.tab, "wk") { this.RenderSetup(); };
    if Equals(this.tab, "export") { this.RenderExport(); };
    if Equals(this.tab, "create") { this.RenderCreate(); };
    if Equals(this.tab, "report") { this.RenderReport(); };
    this.ShowNote();
  }

  public func ShowReport() -> Void {
    this.tab = "report";
    this.page = 0;
    this.Render();
  }

  private func RenderReport() -> Void {
    this.sectionText.SetText(NPVText.T("VER RELATORIO"));
    let id = NPVMakerSession.GetInstance().watchId;
    let report = NPVFiles.Read(id + ".report.txt");
    let lines = StrSplit(report, "\n");
    let first = this.page * 8;
    let i = first;
    while i < ArraySize(lines) && i < first + 8 {
      this.Label(this.body, StrLen(lines[i]) > 240 ? StrLeft(lines[i], 237) + "..." : lines[i], 32, false).SetWrapping(true, 2200.0);
      i += 1;
    };
    this.Pager(ArraySize(lines));
    this.Label(this.body, NPVText.F("Arquivo: %1", "r6/storages/NPVMaker/" + id + ".report.txt"), 26, false);
  }

  private func Pager(total: Int32) -> Void {
    let size = Equals(this.tab, "npvs") ? 5 : 8;
    if total <= size { return; };
    let row = new inkHorizontalPanel();
    row.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
    row.Reparent(this.body);
    this.Button(row, "<", n"npvm_prev", 200.0);
    this.Label(row, NPVText.F2("pagina %1 de %2", ToString(this.page + 1), ToString((total + size - 1) / size)), 28, false);
    this.Button(row, ">", n"npvm_next", 200.0);
  }

  private func FindImported(token: String) -> Int32 {
    let i = 0;
    while i < ArraySize(this.imported) {
      if Equals(this.imported[i].Cell(1), token) { return i; };
      i += 1;
    };
    return -1;
  }
  private func Integrations(row: ref<NPVRow>) -> String {
    let flags = row.Cell(6);
    let names = "";
    if StrLen(flags) == 4 {
      if StrBeginsWith(flags, "1") { names = "Companion"; };
      if StrBeginsWith(StrRight(flags, 3), "1") { names += (StrLen(names) > 0 ? " + " : "") + "NCA"; };
      if StrBeginsWith(StrRight(flags, 2), "1") { names += (StrLen(names) > 0 ? " + " : "") + "AMM"; };
    };
    if Equals(row.Cell(8), "1") { names += (StrLen(names) > 0 ? " + " : "") + NPVText.T("MODO FOTO"); };
    return names;
  }
  private func RenderImported() -> Void {
    if ArraySize(this.imported) == 0 { this.Label(this.body, NPVText.T("Sua biblioteca esta vazia. Use CRIAR NPV para comecar."), 38, false); };
    this.page = Max(0, Min(this.page, (Max(1, ArraySize(this.imported)) - 1) / 5));
    let i = this.page * 5;
    while i < ArraySize(this.imported) && i < (this.page + 1) * 5 {
      let row = this.imported[i];
      let token = row.Cell(1);
      let pending = Equals(row.Cell(5), "1");
      let item = new inkCanvas();
      item.SetSize(2220.0, 234.0); item.SetHAlign(inkEHorizontalAlign.Left);
      item.Reparent(this.body);
      let title = this.Label(item, (Equals(token, this.focusToken) ? "> " : "") + row.Cell(2), 52, true);
      title.SetSize(2200.0, 68.0); title.SetFitToContent(false);
      let status = NPVText.T(pending ? "REMOCAO PENDENTE - REINICIE O JOGO" : "PRONTO");
      let integrations = this.Integrations(row);
      if StrLen(integrations) > 0 { status += "  /  " + integrations; };
      if StrLen(row.Cell(3)) > 0 { status += "  /  LEGACY"; };
      let subtitle = this.Label(item, status, 30, false);
      subtitle.SetMargin(new inkMargin(0.0, 72.0, 0.0, 0.0));
      subtitle.SetSize(2200.0, 40.0); subtitle.SetFitToContent(false);
      subtitle.SetTintColor(pending ? ThemeColors.Bittersweet() : new HDRColor(0.45, 0.68, 0.70, 1.0));
      if Equals(this.confirmToken, token) {
        this.Button(item, NPVText.T("CONFIRMAR REMOCAO"), StringToName("npvm_rmok_" + token), 500.0).GetRootWidget().SetMargin(new inkMargin(0.0, 130.0, 0.0, 0.0));
        this.Button(item, NPVText.T("CANCELAR"), n"npvm_rmno", 320.0).GetRootWidget().SetMargin(new inkMargin(1880.0, 130.0, 0.0, 0.0));
      } else {
        if StrLen(row.Cell(3)) == 0 {
          let export = this.Button(item, NPVText.T("EXPORTAR"), StringToName("npvm_exp_" + token), 360.0);
          export.GetRootWidget().SetMargin(new inkMargin(0.0, 130.0, 0.0, 0.0));
          export.SetDisabled(pending || this.job.busy);
        };
        let remove = this.Button(item, NPVText.T("REMOVER"), StringToName("npvm_rm_" + token), 320.0);
        remove.GetRootWidget().SetMargin(new inkMargin(1880.0, 130.0, 0.0, 0.0));
        remove.SetDisabled(pending || this.job.busy);
      };
      let separator = new inkRectangle(); separator.SetSize(2200.0, 2.0);
      separator.SetMargin(new inkMargin(0.0, 226.0, 0.0, 0.0));
      separator.SetTintColor(ThemeColors.RedOxide()); separator.Reparent(item);
      i += 1;
    };
    this.Pager(ArraySize(this.imported));
  }

  private func RenderTools() -> Void {
    this.Label(this.body, "WOLVENKIT", 48, true);
    this.Label(this.body, NPVText.T("Preparacao e configuracao do conversor."), 32, false);
    this.Button(this.body, NPVText.T("ABRIR WOLVENKIT"), n"npvm_tools_wk", 680.0);
    this.Label(this.body, NPVText.T("DIAGNOSTICO"), 40, true);
    this.Button(this.body, NPVText.T("VER RELATORIO"), n"npvm_report", 680.0);
  }

  private func RenderPackages() -> Void {
    this.Label(this.body, NPVText.T("Pacotes NPV instalados pelo Vortex (red4ext/plugins/NPVMaker/packages)"), 34, true);
    if ArraySize(this.packages) == 0 { this.Label(this.body, NPVText.T("Nenhum pacote NPV instalado."), 28, false); };
    let first = this.page * 8;
    let i = first;
    while i < ArraySize(this.packages) && i < first + 8 {
      let row = this.packages[i];
      let label = row.Cell(2) + " " + row.Cell(3);
      if StrLen(row.Cell(4)) > 0 { label += NPVText.F(" por %1", row.Cell(4)); };
      let state = row.Cell(5);
      if Equals(state, "available") { label += NPVText.T("  [novo]"); };
      if Equals(state, "installed") { label += NPVText.T("  [instalado]"); };
      if Equals(state, "other_version") { label += NPVText.F("  [instalada a %1: remova na aba NPVs e instale de novo]", row.Cell(7)); };
      if Equals(state, "invalid") { label += NPVText.F("  [invalido: %1]", row.Cell(6)); };
      let line = new inkHorizontalPanel();
      line.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
      line.Reparent(this.body);
      let title = this.Label(line, label, 30, false);
      title.SetSize(1400.0, 100.0);
      title.SetFitToContent(false);
      if Equals(state, "available") { this.Button(line, NPVText.T("INSTALAR"), StringToName("npvm_inst_" + row.Cell(1)), 300.0); };
      i += 1;
    };
    this.Pager(ArraySize(this.packages));
  }

  private func RenderSetup() -> Void {
    let state = NPVFiles.Value(this.setup, "state");
    this.Label(this.body, NPVText.T("WolvenKit (o NPV Maker usa o WolvenKit Console 8.19.0 para converter)"), 34, true);
    if Equals(state, "READY") {
      this.Label(this.body, NPVText.F2("WolvenKit %1 pronto (.NET %2).", NPVFiles.Value(this.setup, "wolvenkit_version"),
                 NPVFiles.Value(this.setup, "dotnet_version")), 28, false);
      return;
    };
    if Equals(state, "INSTALLING") {
      let text = NPVText.F("Instalando... %1", NPVFiles.Value(this.setup, "step"));
      if StringToInt(NPVFiles.Value(this.setup, "total"), 0) > 0 {
        text += NPVText.F2(" %1 de %2 bytes", NPVFiles.Value(this.setup, "done"), NPVFiles.Value(this.setup, "total"));
      };
      this.Label(this.body, text, 28, false);
      return;
    };
    if StrLen(state) == 0 {
      this.Label(this.body, NPVText.T("Esperando o conversor (ele inicia junto com o jogo)."), 28, false);
      return;
    };
    this.Label(this.body, NPVText.T("WolvenKit necessario para importar NPVs."), 28, false);
    if Equals(NPVFiles.Value(this.setup, "failed"), "1") {
      this.Label(this.body, NPVText.F2("Nao deu certo: %1 %2", NPVFiles.Value(this.setup, "message"), NPVFiles.Value(this.setup, "hint")), 26, false);
    };
    let download = NPVText.T("BAIXAR AUTOMATICAMENTE: WolvenKit Console 8.19.0 do GitHub oficial");
    for item in NPVFiles.Values(this.setup, "missing") {
      if Equals(item, "dotnet") { download += NPVText.T(" e o .NET 8.0.31 da Microsoft"); };
    };
    this.Label(this.body, download + NPVText.T("; confere o hash e instala fora da pasta do jogo."), 26, false);
    this.Button(this.body, NPVText.T("BAIXAR AUTOMATICAMENTE"), n"npvm_wk_download", 760.0);
    this.Label(this.body, NPVText.T("Ou o caminho do WolvenKit.CLI.exe (8.19.0) ou do WolvenKit.Console-8.19.0.zip oficial:"), 26, false);
    let input = HubTextInput.Create();
    input.SetWidth(1400.0);
    input.SetMaxLength(1024);
    input.Reparent(this.body, this.controller);
    input.SetText(this.setupPath);
    this.pathInput = input;
    let row = new inkHorizontalPanel();
    row.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
    row.Reparent(this.body);
    this.Button(row, NPVText.T("USAR INSTALACAO EXISTENTE"), n"npvm_wk_existing", 680.0);
    this.Button(row, NPVText.T("INSTALAR ZIP MANUALMENTE"), n"npvm_wk_zip", 680.0);
  }

  // ---------- EXPORTAR NPV ----------
  private func StartExport(token: String) -> Void {
    if this.job.busy { return; };
    let name = token;
    let flags = "1000";
    let outfit = "bottom";
    let photo = false;
    for row in this.imported {
      if Equals(row.Cell(1), token) {
        name = row.Cell(2);
        if StrLen(row.Cell(6)) == 4 { flags = row.Cell(6); };
        if StrLen(row.Cell(7)) > 0 { outfit = row.Cell(7); };
        photo = Equals(row.Cell(8), "1");
      };
    };
    NPVFiles.Delete(token + ".export-draft.txt");
    NPVFiles.Delete(token + ".export.txt");
    this.exportStep = 0;
    this.depPage = 0;
    this.exportToken = token;
    this.exportName = name;
    this.draftRaw = "";
    this.draftLoaded = false;
    ArrayClear(this.deps);
    ArrayClear(this.form);
    this.editing = -1;
    this.withCompanion = StrBeginsWith(flags, "1");
    this.withNCA = StrBeginsWith(StrRight(flags, 3), "1");
    this.withAMM = StrBeginsWith(StrRight(flags, 2), "1");
    this.ncaMerc = StrBeginsWith(StrRight(flags, 1), "1");
    this.withPhoto = photo;
    this.underwear = outfit;
    this.tab = "export";
    if NPVFiles.Request(token, "requirements", "") {
      this.Watch(token + ".export.txt", NPVText.T("Procurando os mods usados por este NPV. Aguarde..."));
    } else {
      this.Watch("", NPVText.T("Nao foi possivel gravar o pedido em r6/storages/NPVMaker."));
    };
    this.Render();
  }

  private func LoadDraft() -> Void {
    let raw = NPVFiles.Read(this.exportToken + ".export-draft.txt");
    if Equals(raw, this.draftRaw) || !NPVFiles.Complete(raw) { return; };
    let rows = NPVFiles.Rows(raw);
    if NotEquals(NPVFiles.Value(rows, "token"), this.exportToken) { return; };
    this.draftRaw = raw;
    this.draftLoaded = true;
    this.characterId = NPVFiles.Value(rows, "character_id");
    this.notice = NPVFiles.Value(rows, "notice");
    ArrayClear(this.form);
    for key in ["display_name", "author", "version", "description", "preset_name", "preset_author", "preset_url",
                "preset_nexus", "preset_version"] {
      ArrayPush(this.form, NPVFiles.Value(rows, key));
    };
    if StrLen(this.form[2]) == 0 { this.form[2] = "1.0.0"; };
    ArrayClear(this.deps);
    ArrayClear(this.exportedVersions);
    for row in rows {
      if Equals(row.Cell(0), "exported") { ArrayPush(this.exportedVersions, row.Cell(1)); };
      if Equals(row.Cell(0), "dep") {
        let dep = new NPVExportDep();
        dep.detected = StringToInt(row.Cell(1), -1);
        dep.name = row.Cell(2);
        dep.author = row.Cell(3);
        dep.url = row.Cell(4);
        dep.nexus = row.Cell(5);
        dep.required = Equals(row.Cell(6), "1");
        dep.reason = row.Cell(7);
        dep.include = true;
        ArrayPush(this.deps, dep);
      };
    };
    this.Render();
  }

  private func SaveForm() -> Void {
    let i = 0;
    while i < ArraySize(this.inputs) && i < ArraySize(this.form) {
      if IsDefined(this.inputs[i]) { this.form[this.inputIndices[i]] = this.inputs[i].GetText(); };
      i += 1;
    };
    if this.editing >= 0 && this.editing < ArraySize(this.deps) && ArraySize(this.depInputs) == 4 {
      let dep = this.deps[this.editing];
      dep.name = this.depInputs[0].GetText();
      dep.author = this.depInputs[1].GetText();
      dep.url = this.depInputs[2].GetText();
      dep.nexus = this.depInputs[3].GetText();
    };
  }

  // BUGS 75: EXPORTAR refuses a version whose package folder exists (NPVM-PACKAGE-007); say so before the click.
  private func VersionTaken() -> Bool {
    for version in this.exportedVersions {
      if Equals(version, this.form[2]) { return true; };
    };
    return false;
  }

  private func NextVersion() -> String {
    let parts = StrSplit(this.form[2], ".");
    if ArraySize(parts) != 3 { return "1.0.1"; };
    let next = parts[0] + "." + parts[1] + "." + ToString(StringToInt(parts[2], 0) + 1);
    while ArrayContains(this.exportedVersions, next) {
      parts = StrSplit(next, ".");
      next = parts[0] + "." + parts[1] + "." + ToString(StringToInt(parts[2], 0) + 1);
    };
    return next;
  }

  private func FormInput(parent: ref<inkCompoundWidget>, label: String, index: Int32, size: Int32) -> Void {
    this.Label(parent, label, 26, false);
    let input = HubTextInput.Create();
    input.SetWidth(1200.0);
    input.SetMaxLength(size);
    input.Reparent(parent, this.controller);
    input.SetText(this.form[index]);
    ArrayPush(this.inputs, input);
    ArrayPush(this.inputIndices, index);
  }

  private func Column(parent: ref<inkCompoundWidget>) -> ref<inkVerticalPanel> {
    let column = new inkVerticalPanel();
    column.SetChildMargin(new inkMargin(0.0, 0.0, 0.0, 8.0));
    column.SetFitToContent(true);
    column.Reparent(parent);
    return column;
  }

  // Two columns: MEDIDO EM 01/10/2026 (pacote 3 em jogo, export da mako) one column ran past the bottom of the
  // screen and CRIAR PACOTE could not be reached (the screen has no scrolling).
  private func RenderExport() -> Void {
    this.Label(this.body, NPVText.F("Exportar NPV: %1", this.exportName), 38, true);
    if this.job.busy && Equals(this.job.kind, "export") {
      this.Label(this.body, NPVText.T("Operacao em andamento. Acompanhe as etapas no painel a direita."), 38, false);
      return;
    };
    let steps = new inkHorizontalPanel();
    steps.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
    steps.Reparent(this.body);
    let names: array<String> = [NPVText.T("1. DADOS"), NPVText.T("2. CREDITOS"), NPVText.T("3. REQUISITOS"), NPVText.T("4. EXPORTAR")];
    let index = 0;
    for name in names {
      this.Button(steps, (this.exportStep == index ? "> " : "") + name, StringToName("npvm_step_" + ToString(index)), 480.0);
      index += 1;
    };
    if !this.draftLoaded { return; };
    let right = this.Column(this.body);
    if this.exportStep == 0 {
      this.FormInput(right, NPVText.T("Nome"), 0, 64);
      this.FormInput(right, NPVText.T("Autor"), 1, 64);
      this.FormInput(right, NPVText.T("Versao (1.0.0)"), 2, 14);
      if this.VersionTaken() {
        this.Label(right, NPVText.F2("A versao %1 ja foi exportada. Para exportar de novo, use outra versao (ex.: %2).",
                   this.form[2], this.NextVersion()), 26, false);
      };
      this.FormInput(right, NPVText.T("Descricao"), 3, 2000);
    };
    if this.exportStep == 1 {
      this.Label(right, NPVText.T("Preset original (creditos)"), 30, true);
      this.FormInput(right, NPVText.T("Nome do preset"), 4, 120);
      this.FormInput(right, NPVText.T("Autor do preset"), 5, 64);
      this.FormInput(right, NPVText.T("URL do preset"), 6, 300);
      this.FormInput(right, NPVText.T("Nexus ID do preset"), 7, 10);
      this.FormInput(right, NPVText.T("Versao do preset"), 8, 40);
    };
    if this.exportStep == 2 {
      this.Label(right, NPVText.T("Requisitos (detectados; revise). NPV Maker entra sempre como requisito."), 30, true);
      if this.editing >= 0 && this.editing < ArraySize(this.deps) {
      let dep = this.deps[this.editing];
        let captions: array<String> = [NPVText.T("Nome"), NPVText.T("Autor"), "URL", "Nexus ID"];
        let fieldIndex = 0;
        for field in [dep.name, dep.author, dep.url, dep.nexus] {
          this.Label(right, captions[fieldIndex], 30, true);
          fieldIndex += 1;
          let input = HubTextInput.Create();
          input.SetWidth(1200.0);
          input.SetMaxLength(300);
          input.Reparent(right, this.controller);
          input.SetText(field);
          ArrayPush(this.depInputs, input);
        };
        this.Label(right, NPVText.T("(nome, autor, URL, Nexus ID)"), 24, false);
        this.Button(right, "OK", n"npvm_dok", 240.0);
      };
      if this.editing < 0 {
    let i = this.depPage * 3;
    while i < ArraySize(this.deps) && i < (this.depPage + 1) * 3 {
      let dep = this.deps[i];
      let line = new inkHorizontalPanel();
      line.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
      line.Reparent(right);
      if dep.detected < 0 {
        this.Button(line, NPVText.T(dep.include ? "[x] INCLUIR" : "[ ] INCLUIR"), StringToName("npvm_dinc_" + ToString(i)), 300.0);
      };
      this.Button(line, NPVText.T(dep.required ? "OBRIGATORIO" : "OPCIONAL"), StringToName("npvm_dreq_" + ToString(i)), 300.0);
      let label = StrLen(dep.name) > 0 ? dep.name : NPVText.T("(sem nome)");
      if StrLen(dep.nexus) > 0 { label += "  (Nexus " + dep.nexus + ")"; };
      label += NPVText.T(dep.detected < 0 ? "  [adicionado]" : "  [detectado]");
      if dep.detected >= 0 && StrLen(dep.nexus) == 0 { label += NPVText.T("  [sem Nexus ID: use EDITAR]"); };
      let width = dep.detected < 0 ? 560.0 : 872.0;
      let text = this.Label(line, label, 26, false);
      text.SetWrapping(true, width);
      text.SetSize(width, 64.0);
      text.SetFitToContent(false);
      text.SetVerticalAlignment(textVerticalAlignment.Center);
      this.Button(line, NPVText.T("EDITAR"), StringToName("npvm_dedit_" + ToString(i)), 240.0);
      if dep.detected < 0 {
        this.Button(line, NPVText.T("REMOVER"), StringToName("npvm_drem_" + ToString(i)), 240.0);
      };
      if StrLen(dep.reason) > 0 { this.Label(right, "    " + dep.reason, 24, false).SetWrapping(true, 1700.0); };
      i += 1;
    };
        let pager = new inkHorizontalPanel();
        pager.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
        pager.Reparent(right);
        this.Button(pager, "<", n"npvm_dep_prev", 160.0);
        this.Label(pager, NPVText.F2("pagina %1 de %2", ToString(this.depPage + 1), ToString(Max(1, (ArraySize(this.deps) + 2) / 3))), 30, false);
        this.Button(pager, ">", n"npvm_dep_next", 160.0);
        this.Button(right, NPVText.T("ADICIONAR REQUISITO"), n"npvm_dadd", 600.0);
      };
    };
    if this.exportStep == 3 {
      this.Label(right, this.form[0] + "  /  " + this.form[2], 38, true);
      this.RenderMods(right);
      this.Label(right, this.notice, 28, false).SetWrapping(true, 2200.0);
      if this.VersionTaken() {
        this.Label(right, NPVText.F2("A versao %1 ja foi exportada. Troque a versao em 1. DADOS (ex.: %2) para exportar de novo.",
                   this.form[2], this.NextVersion()), 32, false).SetWrapping(true, 2200.0);
      };
      this.Button(right, NPVText.T("EXPORTAR MOD"), n"npvm_create", 760.0);
    };
    let navigation = new inkHorizontalPanel();
    navigation.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
    navigation.Reparent(this.body);
    this.Button(navigation, NPVText.T("VOLTAR"), n"npvm_back", 300.0);
    if this.exportStep > 0 { this.Button(navigation, NPVText.T("ETAPA ANTERIOR"), n"npvm_step_prev", 420.0); };
    if this.exportStep < 3 { this.Button(navigation, NPVText.T("PROXIMA ETAPA"), n"npvm_step_next", 420.0); };
  }

  // "Funciona com" and the default outfit: CRIAR NPV and EXPORTAR share them (tools/adapters.py, UNDERWEAR_MODES).
  private func RenderMods(parent: ref<inkCompoundWidget>) -> Void {
    this.Label(parent, NPVText.T("Funciona com (opcional; o NPV Maker instala o necessario em cada um):"), 30, true).SetWrapping(true, 1700.0);
    let mods = new inkHorizontalPanel();
    mods.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
    mods.Reparent(parent);
    this.Button(mods, (this.withCompanion ? "[x] " : "[ ] ") + "COMPANION EXPANSION", n"npvm_int_companion", 520.0);
    this.Button(mods, (this.withNCA ? "[x] " : "[ ] ") + "NIGHT CITY ALLIES", n"npvm_int_nca", 520.0);
    this.Button(mods, (this.withAMM ? "[x] " : "[ ] ") + "AMM", n"npvm_int_amm", 300.0);
    this.Button(mods, (this.withPhoto ? "[x] " : "[ ] ") + NPVText.T("MODO FOTO"), n"npvm_int_photo", 360.0);
    if this.withNCA {
      this.Button(parent, NPVText.T(this.ncaMerc ? "NCA: MERCENARIO" : "NCA: COMPANHEIRO"), n"npvm_int_merc", 600.0);
    };
    let outfit = "ROUPA PADRAO: SO CALCINHA";
    if Equals(this.underwear, "full") { outfit = "ROUPA PADRAO: COMPLETA"; };
    if Equals(this.underwear, "none") { outfit = "ROUPA PADRAO: NENHUMA"; };
    this.Button(parent, NPVText.T(outfit), n"npvm_underwear", 760.0);
    if this.withPhoto {
      this.Label(parent, NPVText.T("Modo foto: o NPV so aparece com o PhotoMode-EX (Nexus 18839) instalado; ele entra nos requisitos."), 24, false).SetWrapping(true, 1700.0);
    };
    if this.withNCA && this.withAMM {
      this.Label(parent, NPVText.T("NCA + AMM juntos ainda nao foram testados: o NPV pode aparecer duas vezes no NCA."), 24, false).SetWrapping(true, 1700.0);
    };
  }

  private func ModsJson() -> String {
    return "{\"companion\": " + NPVFiles.JsonBool(this.withCompanion) + ", \"nca\": " + NPVFiles.JsonBool(this.withNCA)
      + ", \"amm\": " + NPVFiles.JsonBool(this.withAMM) + ", \"photomode\": " + NPVFiles.JsonBool(this.withPhoto)
      + ", \"nca_merc\": " + NPVFiles.JsonBool(this.withNCA && this.ncaMerc) + "}";
  }

  // ---------- CRIAR NPV (author request 01/10/2026: replaces IMPORTAR NO COMPANION) ----------
  public func ShowCreate() -> Void {
    this.tab = "create";
    this.editing = -1;
    this.confirmToken = "";
    this.Render();
  }

  private func RenderCreate() -> Void {
    let session = NPVMakerSession.GetInstance();
    if this.job.busy {
      this.Label(this.body, this.job.name, 60, true);
      this.Label(this.body, NPVText.T("Operacao em andamento. Acompanhe as etapas no painel a direita."), 38, false);
      return;
    };
    if Equals(this.job.kind, "create") && Equals(this.job.stage, "installed") {
      this.Label(this.body, NPVText.T("NPV CRIADO"), 60, true);
      this.Label(this.body, this.job.name, 48, true);
      this.Label(this.body, NPVText.T("Use VER NPV ou EXPORTAR no painel a direita."), 36, false);
      return;
    };
    this.Label(this.body, NPVText.T("NOME DO PERSONAGEM"), 32, true);
    let input = HubTextInput.Create();
    input.SetWidth(1200.0);
    input.SetMaxLength(80);
    input.Reparent(this.body, this.controller);
    input.SetText(session.projectName);
    session.nameInput = input;
    this.Label(this.body, NPVText.T("A aparencia vem do editor. Volte ao editor para ajustar o visual."), 28, false);
    let project = new inkHorizontalPanel();
    project.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
    project.Reparent(this.body);
    this.Button(project, NPVText.T("SALVAR PROJETO"), n"npvm_save_project", 600.0);
    this.Button(project, NPVText.T("ABRIR ULTIMO PROJETO"), n"npvm_load_project", 600.0);
    this.Button(project, NPVText.T("VER RELATORIO"), n"npvm_report", 400.0);
    session.bodyButton = this.Button(this.body, NPVText.F("CORPO: %1", StrUpper(session.bodyStrategy)), n"npvm_body", 760.0);
    this.RenderMods(this.body);
    this.Button(this.body, NPVText.T("CRIAR NPV"), n"npvm_make", 600.0);
  }

  private func Id(text: String) -> String {
    return NPVFiles.JsonId(text);
  }

  private func RequestExport() -> Void {
    if this.job.busy || !this.draftLoaded { return; };
    this.SaveForm();
    let fields = ", \"fields\": {\"display_name\": " + NPVFiles.Json(this.form[0]) + ", \"author\": " + NPVFiles.Json(this.form[1])
      + ", \"version\": " + NPVFiles.Json(this.form[2]) + ", \"description\": " + NPVFiles.Json(this.form[3])
      + ", \"source_preset\": {\"name\": " + NPVFiles.Json(this.form[4]) + ", \"author\": " + NPVFiles.Json(this.form[5])
      + ", \"url\": " + NPVFiles.Json(this.form[6]) + ", \"nexus_mod_id\": " + this.Id(this.form[7])
      + ", \"version\": " + NPVFiles.Json(this.form[8]) + "}}";
    let list = "";
    let first = true;
    for dep in this.deps {
      if !first { list += ", "; };
      first = false;
      list += "{\"name\": " + NPVFiles.Json(dep.name) + ", \"author\": " + NPVFiles.Json(dep.author)
        + ", \"url\": " + NPVFiles.Json(dep.url) + ", \"nexus_mod_id\": " + this.Id(dep.nexus)
        + ", \"required_for_rebuild\": " + NPVFiles.JsonBool(dep.required) + ", \"include\": " + NPVFiles.JsonBool(dep.include)
        + ", \"reason\": " + NPVFiles.Json(dep.reason) + ", \"detected\": " + (dep.detected >= 0 ? ToString(dep.detected) : "null") + "}";
    };
    let mods = ", \"integrations\": " + this.ModsJson() + ", \"underwear\": " + NPVFiles.Json(this.underwear);
    NPVFiles.Delete(this.exportToken + ".export.txt");
    if NPVFiles.Request(this.exportToken, "export", fields + mods + ", \"dependencies\": [" + list + "]") {
      this.Watch(this.exportToken + ".export.txt", NPVText.T("Criando o mod para instalar pelo Vortex. Aguarde..."));
      this.job.kind = "export";
      this.Render();
    } else {
      this.Watch("", NPVText.T("Nao foi possivel gravar o pedido em r6/storages/NPVMaker."));
    };
  }

  // ---------- actions ----------
  private func RequestSetup(action: String) -> Void {
    let path = "";
    if NotEquals(action, "download") {
      if IsDefined(this.pathInput) { path = this.pathInput.GetText(); };
      this.setupPath = path;
      path = StrReplaceAll(path, "\"", "");
      let lower = StrLower(path);
      let wanted = Equals(action, "existing") ? ".exe" : ".zip";
      if StrLen(path) < 5 || NotEquals(StrRight(lower, 4), wanted) {
        this.Watch("", NPVText.T(Equals(action, "existing") ? "Informe o caminho completo do WolvenKit.CLI.exe."
                                                             : "Informe o caminho completo do WolvenKit.Console-8.19.0.zip."));
        return;
      };
    };
    let body = "{\"format\": \"npv-maker-setup-request\", \"schema_version\": 1, \"action\": " + NPVFiles.Json(action);
    if NotEquals(action, "download") { body += ", \"path\": " + NPVFiles.Json(path); };
    if NPVFiles.Write("setup." + action + ".request.json", body + "}") {
      this.Watch("setup.txt", NPVText.T("Pedido enviado ao conversor. Aguarde..."));
    } else {
      this.Watch("", NPVText.T("Nao foi possivel gravar o pedido em r6/storages/NPVMaker."));
    };
  }

  private func Remove(token: String) -> Void {
    this.confirmToken = "";
    NPVFiles.Delete(token + ".txt");
    if NPVFiles.Request(token, "remove", "") {
      this.Watch(token + ".txt", NPVText.T("Remocao pedida. Aguarde alguns segundos."));
    } else {
      this.Watch("", NPVText.T("Nao foi possivel gravar o pedido em r6/storages/NPVMaker."));
    };
    this.Render();
  }

  private func Install(id: String) -> Void {
    NPVFiles.Delete(id + ".txt");
    if NPVFiles.Request(id, "install", "") {
      this.Watch(id + ".txt", NPVText.T("Conferindo requisitos e reconstruindo. Pode levar varios minutos..."));
    } else {
      this.Watch("", NPVText.T("Nao foi possivel gravar o pedido em r6/storages/NPVMaker."));
    };
  }

  protected cb func OnButton(widget: wref<inkWidget>) -> Bool {
    let name = NameToString(widget.GetName());
    this.SaveProjectName();
    if Equals(this.tab, "export") { this.SaveForm(); };
    if this.job.busy && this.LockedAction(name) { return true; };
    if Equals(name, "npvm_open_create") {
      if !this.job.busy { this.job.kind = ""; };
      this.ShowCreate(); return true;
    };
    if Equals(name, "npvm_result_export") {
      let resultIndex = this.FindImported(this.job.token);
      if resultIndex >= 0 && !Equals(this.imported[resultIndex].Cell(5), "1") && StrLen(this.imported[resultIndex].Cell(3)) == 0 { this.StartExport(this.job.token); };
      return true;
    };
    if Equals(name, "npvm_result_view") {
      this.Refresh(true);
      this.focusToken = this.job.token;
      this.page = Max(0, this.FindImported(this.focusToken)) / 5;
      this.tab = "npvs"; this.Render(); return true;
    };
    if Equals(name, "npvm_tools_wk") { this.tab = "wk"; this.Render(); return true; };
    if Equals(name, "npvm_close") {
      this.ReturnToEditor();
      return true;
    };
    if StrBeginsWith(name, "npvm_tab_") {
      this.tab = StrAfterFirst(name, "npvm_tab_");
      this.page = 0;
      this.editing = -1;
      this.confirmToken = "";
    } else if Equals(name, "npvm_step_prev") {
      if this.exportStep > 0 { this.exportStep -= 1; };
      this.editing = -1;
    } else if Equals(name, "npvm_step_next") {
      if this.exportStep < 3 { this.exportStep += 1; };
      this.editing = -1;
    } else if StrBeginsWith(name, "npvm_step_") {
      this.exportStep = StringToInt(StrAfterFirst(name, "npvm_step_"), 0);
      this.editing = -1;
    } else if Equals(name, "npvm_dep_prev") {
      if this.depPage > 0 { this.depPage -= 1; };
    } else if Equals(name, "npvm_dep_next") {
      if (this.depPage + 1) * 3 < ArraySize(this.deps) { this.depPage += 1; };
    } else if Equals(name, "npvm_prev") {
      if this.page > 0 { this.page -= 1; };
    } else if Equals(name, "npvm_next") {
      this.page += 1;
    } else if StrBeginsWith(name, "npvm_rmok_") {
      this.Remove(StrAfterFirst(name, "npvm_rmok_"));
      return true;
    } else if Equals(name, "npvm_rmno") {
      this.confirmToken = "";
    } else if StrBeginsWith(name, "npvm_rm_") {
      this.confirmToken = StrAfterFirst(name, "npvm_rm_");
    } else if StrBeginsWith(name, "npvm_exp_") {
      this.StartExport(StrAfterFirst(name, "npvm_exp_"));
      return true;
    } else if StrBeginsWith(name, "npvm_inst_") {
      this.Install(StrAfterFirst(name, "npvm_inst_"));
      return true;
    } else if StrBeginsWith(name, "npvm_wk_") {
      this.RequestSetup(StrAfterFirst(name, "npvm_wk_"));
      return true;
    } else if Equals(name, "npvm_back") {
      this.tab = "npvs";
      this.editing = -1;
    } else if StrBeginsWith(name, "npvm_dinc_") {
      let dep = this.deps[StringToInt(StrAfterFirst(name, "npvm_dinc_"), 0)];
      if dep.detected < 0 { dep.include = !dep.include; };
    } else if StrBeginsWith(name, "npvm_dreq_") {
      let dep = this.deps[StringToInt(StrAfterFirst(name, "npvm_dreq_"), 0)];
      dep.required = !dep.required;
    } else if StrBeginsWith(name, "npvm_dedit_") {
      this.editing = StringToInt(StrAfterFirst(name, "npvm_dedit_"), -1);
    } else if StrBeginsWith(name, "npvm_drem_") {
      let index = StringToInt(StrAfterFirst(name, "npvm_drem_"), 0);
      if this.deps[index].detected < 0 { ArrayErase(this.deps, index); };
      this.editing = -1;
      if this.depPage > 0 && this.depPage * 3 >= ArraySize(this.deps) { this.depPage -= 1; };
    } else if Equals(name, "npvm_dok") {
      this.editing = -1;
    } else if Equals(name, "npvm_dadd") {
      let dep = new NPVExportDep();
      dep.required = true;
      dep.include = true;
      dep.detected = -1;
      ArrayPush(this.deps, dep);
      this.editing = ArraySize(this.deps) - 1;
    } else if Equals(name, "npvm_int_companion") {
      this.withCompanion = !this.withCompanion;
    } else if Equals(name, "npvm_int_nca") {
      this.withNCA = !this.withNCA;
    } else if Equals(name, "npvm_save_project") {
      NPVMakerSession.GetInstance().Capture();
      this.Watch("", NPVMakerSession.GetInstance().lastStatus);
    } else if Equals(name, "npvm_load_project") {
      NPVMakerSession.GetInstance().RequestLoad();
      this.Watch("", NPVMakerSession.GetInstance().lastStatus);
    } else if Equals(name, "npvm_body") {
      NPVMakerSession.GetInstance().CycleBodyStrategy();
    } else if Equals(name, "npvm_report") {
      this.ShowReport();
      return true;
    } else if Equals(name, "npvm_make") {
      let session = NPVMakerSession.GetInstance();
      if session.pendingSave || session.pendingLoad || StrLen(session.saveToken) > 0 { return true; };
      session.RequestCreate(this.ModsJson(), this.underwear);
      if session.pendingSave {
        this.job.Begin("create", "", "", session.projectName, session.lastStatus);
      } else { this.job.kind = ""; this.Watch("", session.lastStatus); };
    } else if Equals(name, "npvm_underwear") {
      if Equals(this.underwear, "bottom") {
        this.underwear = "full";
      } else if Equals(this.underwear, "full") {
        this.underwear = "none";
      } else {
        this.underwear = "bottom";
      };
    } else if Equals(name, "npvm_int_photo") {
      this.withPhoto = !this.withPhoto;
    } else if Equals(name, "npvm_int_merc") {
      this.ncaMerc = !this.ncaMerc;
    } else if Equals(name, "npvm_int_amm") {
      this.withAMM = !this.withAMM;
    } else if Equals(name, "npvm_create") {
      this.RequestExport();
      return true;
    };
    this.Render();
    return true;
  }

  private func LockedAction(name: String) -> Bool {
    return !(StrBeginsWith(name, "npvm_tab_") || Equals(name, "npvm_prev") || Equals(name, "npvm_next")
      || Equals(name, "npvm_back") || Equals(name, "npvm_report") || Equals(name, "npvm_tools_wk"));
  }

  // ---------- widgets ----------
  private func Label(parent: ref<inkCompoundWidget>, text: String, size: Int32, strong: Bool) -> ref<inkText> {
    let label = new inkText();
    label.SetFontFamily("base\\gameplay\\gui\\fonts\\raj\\raj.inkfontfamily");
    label.SetFontStyle(strong ? n"Semi-Bold" : n"Medium");
    label.SetFontSize(size);
    label.SetTintColor(strong ? ThemeColors.ElectricBlue() : ThemeColors.Bittersweet());
    label.SetWrapping(true, 1800.0);
    label.SetFitToContent(true);
    label.SetText(text);
    label.Reparent(parent);
    return label;
  }

  private func Button(parent: ref<inkCompoundWidget>, text: String, name: CName, width: Float) -> ref<SimpleButton> {
    let button = NPVIconButton.Make();
    button.SetName(name);
    button.SetText(text);
    button.SetIcon(NPVIcons.ForAction(name), false);
    button.SetWidth(width);
    button.GetRootWidget().SetAnchorPoint(new Vector2(0.0, 0.0));
    button.SetFlipped(true);
    button.ToggleAnimations(true);
    button.ToggleSounds(true);
    button.Reparent(parent, this.controller);
    button.RegisterToCallback(n"OnBtnClick", this, n"OnButton");
    button.SetDisabled(this.job.busy && this.LockedAction(NameToString(name)));
    return button;
  }
}
