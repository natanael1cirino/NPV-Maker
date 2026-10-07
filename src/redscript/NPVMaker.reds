import Codeware.UI.*
import RedFileSystem.*

public class NPVMakerCompactButton extends SimpleButton {
  protected func CreateWidgets() {
    super.CreateWidgets();
    this.m_root.SetSize(600.0, 64.0);
    this.m_label.SetFontSize(32);
  }

  public static func CreateCompact() -> ref<NPVMakerCompactButton> {
    let button = new NPVMakerCompactButton();
    button.CreateInstance();
    return button;
  }
}

// Appearance Change Unlocker (3.2 and the PT-BR build) declares "module ACU".
// Decided when scripts compile, so wrapper order does not matter. A runtime
// lookup of the bare class name failed in game (0.4.2): the class is
// ACU.CharacterPresetPanel.
@if(ModuleExists("ACU"))
public func NPVMakerPresetModActive() -> Bool = true

@if(!ModuleExists("ACU"))
public func NPVMakerPresetModActive() -> Bool = false

// A project snapshot, not an NPC appearance resource. Internal names survive
// UI reordering better than indices; asset/dependency resolution is a later step.
public class NPVOptionSnapshot extends IScriptable {
  public let name: String;
  public let bodyPart: String;
  public let kind: String;
  public let selectedName: String;
  public let resourcePath: String;
  public let selectedIndex: Uint32;
  public let choiceCount: Int32;
  public let active: Bool;
  public let editable: Bool;
  public let censored: Bool;
}

public class NPVLoadChange extends IScriptable {
  public let name: String;
  public let bodyPart: String;
  public let option: ref<CharacterCustomizationOption>;
  public let index: Uint32;
  public let switcher: Bool;
}

// One visual component of the puppet the editor renders (0.4.14 DEV). The
// converter takes the body from these; measured with the NPV Probe 0.1/0.2.
public class NPVRuntimeComponent extends IScriptable {
  public let name: String;
  public let type: String;
  public let enabled: Bool;
  public let ownerAppearance: String;
  public let ownerApp: String;
  public let field: String;
  public let hash: String;
  public let path: String;
  public let meshAppearance: String;
  public let chunkMask: String;
  public let state: String;
  public let token: ref<ResourceToken>;
}

public class NPVMakerSession extends ScriptableService {
  // NO @addField ON OUR OWN SCRIPT CLASSES. MEASURED 06/10/2026: @addField(NPVMakerSession) in NPVMakerManager.reds
  // made scc 0.5.31 write the field before this class with some mod lists; the game read a field with no owner while
  // loading the scripts and crashed at startup (access violation at 0x8). Fields of NPV classes live in the class body.
  public let managerOperation: ref<NPVManagerOperation>;
  public let active: Bool;
  public let pendingSave: Bool;
  public let exportAfterSave: Bool;
  public let pendingPrivateZip: Bool;
  public let storageReady: Bool;
  public let projectName: String;
  public let bodyMale: Bool;
  public let voiceMale: Bool;
  public let options: array<ref<NPVOptionSnapshot>>;
  public let system: ref<gameuiICharacterCustomizationSystem>;
  public let statusWidget: wref<inkText>;
  // Diagnostics list and copy buttons; the text comes from the converter's
  // status (one diagnostic set feeds panel, report and log).
  public let diagnosticsWidget: wref<inkText>;
  public let copyRow: wref<inkHorizontalPanel>;
  public let pendingCopy: Int32;
  public let nameInput: wref<HubTextInput>;
  public let pendingLoad: Bool;
  public let loadingName: String;
  public let loadingBodyMale: Bool;
  public let loadingVoiceMale: Bool;
  public let loadingOptions: array<ref<NPVOptionSnapshot>>;
  public let loadAll: array<ref<NPVLoadChange>>;
  public let loadQueue: array<ref<NPVLoadChange>>;
  public let loadWaiting: array<ref<NPVLoadChange>>;
  public let loadInactive: array<ref<NPVLoadChange>>;
  public let loadStep: Int32;
  public let loadWait: Int32;
  public let loadRound: Int32;
  public let loadChecks: Int32;
  public let loadApplied: Int32;
  public let loadProgress: Bool;
  public let loadUnresolved: array<String>;
  public let runtimeStatus: String;
  public let runtimeReason: String;
  public let runtimeTemplate: String;
  public let runtimeComponents: array<ref<NPVRuntimeComponent>>;
  // 0.5.0 without CET: files through RedFileSystem (NPVMakerStorage.reds), work driven by NPVMakerTicker.
  public let storage: ref<FileSystemStorage>;
  public let ticks: Int32;
  public let runtimeWait: Int32;
  public let saveToken: String;
  public let saveCounter: Int32;
  public let watchId: String;
  public let statusRaw: String;
  public let reportShown: Bool;
  public let loadStarted: Bool;
  public let bodyStrategy: String;
  public let bodyButton: wref<SimpleButton>;
  // NPVMakerText.reds
  public let text: ref<NPVText>;
  // CRIAR NPV: mods and default outfit of the next import (NPVMakerManager.reds), and the last status shown.
  public let createMods: String;
  public let createUnderwear: String;
  public let lastStatus: String;


  public static func GetInstance() -> ref<NPVMakerSession> {
    return GameInstance.GetScriptableServiceContainer().GetService(n"NPVMakerSession") as NPVMakerSession;
  }

  private cb func OnLoad() {
    // RedFileSystem grants a storage once per session; every file of the game side goes through it.
    this.storage = FileSystem.GetStorage("NPVMaker");
    this.storageReady = IsDefined(this.storage);
    this.bodyStrategy = "selected_tpp";
    ModLog(n"NPVMaker", "0.5.0: storage r6/storages/NPVMaker " + (this.storageReady ? "granted" : "refused (RedFileSystem?)"));
    GameInstance.GetCallbackSystem().RegisterCallback(n"Resource/Ready", this, n"RegisterScenario")
      .AddTarget(ResourceTarget.Path(r"base\\gameplay\\gui\\fullscreen\\main_menu\\pregame_menu.inkmenu"));
  }

  private cb func RegisterScenario(event: ref<ResourceEvent>) {
    let resource = event.GetResource() as inkMenuResource;
    if IsDefined(resource) && !ArrayContains(resource.scenariosNames, n"MenuScenario_NPVMaker") {
      ArrayPush(resource.scenariosNames, n"MenuScenario_NPVMaker");
    };
  }

  // Native preview controllers can attach before their scripted OnInitialize.
  // Prepare the customization state at menu activation, before OpenMenu creates
  // any body-selection widgets or their native preview controllers.
  public func BeginSession(customization: ref<gameuiICharacterCustomizationSystem>) -> Bool {
    if this.active || !IsDefined(customization) { return false; };
    if !customization.InitializeState() {
      ModLog(n"NPVMaker", "0.5.0: InitializeState failed; editor was not opened.");
      return false;
    };
    let state = customization.GetState();
    if !IsDefined(state) {
      customization.ClearState();
      ModLog(n"NPVMaker", "0.5.0: customization state is unavailable.");
      return false;
    };
    state.SetLifePath(t"LifePaths.StreetKid");
    state.SetIsExpansionStandalone(false);
    this.system = customization;
    this.active = true;
    NPVText.Refresh();
    ModLog(n"NPVMaker", "0.5.0: state prepared BEFORE opening body selection.");
    return true;
  }

  public func SetStatus(message: String) -> Void {
    this.lastStatus = message;
    if IsDefined(this.statusWidget) {
      // The editor has two lines; the manager always reads the complete lastStatus.
      this.statusWidget.SetText(Equals(this.statusWidget.GetName(), n"NPVMakerEditorStatus") && StrLen(message) > 118 ? StrLeft(message, 115) + "..." : message);
    };
  }

  public func SetDiagnostics(details: String, copyable: Bool) -> Void {
    if IsDefined(this.diagnosticsWidget) {
      // The editor footer is a summary; full diagnostics live in the manager report view.
      let summary = "";
      let count = 0;
      for line in StrSplit(details, "\n") {
        if StrLen(line) > 0 && count < 2 {
          summary += (StrLen(line) > 150 ? StrLeft(line, 147) + "..." : line) + "\n";
          count += 1;
        };
      };
      this.diagnosticsWidget.SetText(summary);
      this.diagnosticsWidget.SetVisible(StrLen(details) > 0);
    };
    if IsDefined(this.copyRow) {
      this.copyRow.SetVisible(copyable);
    };
  }

  // Without CET there is no clipboard: VER RELATORIO shows the report in the panel and names its file.
  public func ToggleReport() -> Void {
    if NotEquals(this.watchId, "") && !this.reportShown {
      let report = NPVFiles.Read(this.watchId + ".report.txt");
      if StrLen(report) > 0 {
        // MEDIDO EM 01/10/2026 (print do autor): the whole report ran past the bottom of the screen. The panel shows
        // the result and one line per diagnostic; every field stays in the file.
        let shown = "";
        let count = 0;
        let more = 0;
        for line in StrSplit(report, "\n") {
          if StrBeginsWith(line, "resultado:") {
            shown += line + "\n";
          } else if StrBeginsWith(line, "[") {
            if count < 6 { shown += line + "\n"; count += 1; } else { more += 1; };
          };
        };
        if more > 0 { shown += NPVText.F("+ %1 (veja o relatorio)", ToString(more)) + "\n"; };
        this.reportShown = true;
        this.SetDiagnostics(shown + NPVText.F("Arquivo: %1", "r6/storages/NPVMaker/" + this.watchId + ".report.txt"), true);
        return;
      };
    };
    this.reportShown = false;
    this.statusRaw = "";
    this.PollStatus();
  }

  public func FinishSave(message: String) -> Void {
    this.pendingSave = false;
    this.SetStatus(message);
  }

  public func RequestCompanionBuild() -> Void {
    if !this.active || this.pendingSave || this.pendingLoad { return; };
    this.Capture();
    if this.pendingSave {
      this.exportAfterSave = true;
      this.SetStatus(NPVText.T("Salvando e criando o NPV..."));
    };
  }

  public func RequestCreate(mods: String, underwear: String) -> Void {
    if !this.active || this.pendingSave || this.pendingLoad { return; };
    this.createMods = mods;
    this.createUnderwear = underwear;
    this.RequestCompanionBuild();
  }

  public func RequestPrivateZip() -> Void {
    if !this.active || this.pendingSave || this.pendingLoad { return; };
    this.pendingPrivateZip = true;
    this.SetStatus(NPVText.T("Solicitando ZIP privado com assets externos..."));
  }

public func RequestLoad() -> Void {
  if !this.active || this.pendingSave || this.pendingLoad || !IsDefined(this.system) { return; };
  if !this.storageReady {
    this.SetStatus(NPVText.T("Projeto indisponivel: ative o RedFileSystem e reinicie o jogo."));
    return;
  };
  this.pendingLoad = true;
  this.SetStatus(NPVText.T("Procurando ultimo projeto..."));
}

public func FinishLoad(message: String) -> Void {
  this.pendingLoad = false;
  this.loadStarted = false;
  ArrayClear(this.loadingOptions);
  this.ClearLoadQueue();
  ArrayClear(this.loadUnresolved);
  this.SetStatus(message);
}

public func StartLoading(name: String, male: Bool, voiceMale: Bool) -> Void {
  this.loadingName = name;
  this.loadingBodyMale = male;
  this.loadingVoiceMale = voiceMale;
  ArrayClear(this.loadingOptions);
}

public func AddLoadingOption(name: String, bodyPart: String, kind: String, selectedName: String,
                             selectedIndex: Uint32, choiceCount: Int32, active: Bool, editable: Bool) -> Void {
  let entry = new NPVOptionSnapshot();
  entry.name = name;
  entry.bodyPart = bodyPart;
  entry.kind = kind;
  entry.selectedName = selectedName;
  entry.selectedIndex = selectedIndex;
  entry.choiceCount = choiceCount;
  entry.active = active;
  entry.editable = editable;
  ArrayPush(this.loadingOptions, entry);
}

// Resolve every saved value before touching the preview; StepLoadingProject
// applies them. Cyclic switchers activate their child appearance options, so
// switchers come first in the queue, then colors and morphs.
public func PrepareLoadingProject() -> String {
  if !this.active || !IsDefined(this.system) { return NPVText.T("Editor nao esta ativo."); };
  let state = this.system.GetState();
  if !IsDefined(state) { return NPVText.T("Estado do editor indisponivel."); };
  if NotEquals(state.IsBodyGenderMale(), this.loadingBodyMale) {
    return NPVText.T("Corpo diferente. Selecione o corpo do projeto antes de abrir.");
  };
  let available = this.system.GetUnitedOptions(true, true, true);
  let switchers: array<ref<NPVLoadChange>>;
  let appearances: array<ref<NPVLoadChange>>;
  let change: ref<NPVLoadChange>;
  ArrayClear(this.loadUnresolved);
  for wanted in this.loadingOptions {
    if wanted.active && wanted.editable {
      change = this.ResolveLoadingOption(wanted, available);
      if IsDefined(change) {
        if Equals(wanted.kind, "switcher") {
          ArrayPush(switchers, change);
        } else {
          ArrayPush(appearances, change);
        };
      };
    };
  };
  if ArraySize(switchers) + ArraySize(appearances) == 0 {
    return NPVText.T("Nenhuma aparencia aplicavel encontrada.");
  };
  this.ClearLoadQueue();
  for item in switchers {
    item.switcher = true;
    ArrayPush(this.loadAll, item);
  };
  for item in appearances { ArrayPush(this.loadAll, item); };
  this.RestartLoadQueue(this.loadAll);
  return "";
}

// The saved values are applied one per call; the editor ticker calls this every 0.15 s until
// it returns a message. MEDIDO EM 26/09/2026 (THAILEND): applying all 50 in the
// same frame left the default hair stuck in the preview, even after changing
// the hairstyle by hand, and "Olhos" back at 01. A switcher swaps preview
// components asynchronously, so the next change waits 4 calls after one. An
// option that is not active yet waits for a later pass (asia and THAILEND
// stopped at hairstyle before 0.4.9). At the end every value is checked and the
// ones that changed back are applied again. Stepping as the fix for the stuck
// hair is a hypothesis until checked in game.
public func StepLoadingProject() -> String {
  if !this.active || !IsDefined(this.system) { return NPVText.T("Editor nao esta ativo."); };
  if this.loadWait > 0 {
    this.loadWait -= 1;
    return "";
  };
  let match: ref<CharacterCustomizationOption>;
  if this.loadStep < ArraySize(this.loadQueue) {
    let item = this.loadQueue[this.loadStep];
    this.loadStep += 1;
    match = this.ActiveLoadingOption(item.name, item.bodyPart);
    if !IsDefined(match) {
      ArrayPush(this.loadWaiting, item);
      return "";
    };
    this.loadProgress = true;
    if match.currIndex != item.index {
      this.system.ApplyChangeToOption(match, item.index);
      this.loadApplied += 1;
      if item.switcher { this.loadWait = 4; } else { this.loadWait = 1; };
    };
    this.SetStatus(NPVText.F2("Abrindo projeto... %1/%2", ToString(this.loadStep), ToString(ArraySize(this.loadQueue))));
    return "";
  };
  if ArraySize(this.loadWaiting) > 0 && this.loadProgress && this.loadRound < 4 {
    this.loadRound += 1;
    this.RestartLoadQueue(this.loadWaiting);
    return "";
  };
  if this.loadChecks == 0 {
    ArrayClear(this.loadInactive);
    for item in this.loadWaiting { ArrayPush(this.loadInactive, item); };
  };
  let wrong: array<ref<NPVLoadChange>>;
  for item in this.loadAll {
    match = this.ActiveLoadingOption(item.name, item.bodyPart);
    if IsDefined(match) && match.currIndex != item.index { ArrayPush(wrong, item); };
  };
  if ArraySize(wrong) > 0 && this.loadChecks < 3 {
    this.loadChecks += 1;
    this.RestartLoadQueue(wrong);
    this.loadWait = 4;
    return "";
  };
  let state = this.system.GetState();
  if IsDefined(state) { state.SetIsBrainGenderMale(this.loadingVoiceMale); };
  this.projectName = this.loadingName;
  if IsDefined(this.nameInput) { this.nameInput.SetText(this.projectName); };
  let total = ArraySize(this.loadAll);
  let skipped: String = "";
  for name in this.loadUnresolved { skipped += " " + name; };
  for item in this.loadInactive {
    ModLog(n"NPVMaker", "0.5.0: load skipped inactive option " + item.bodyPart + "/" + item.name);
    skipped += " " + item.name;
  };
  for item in wrong {
    ModLog(n"NPVMaker", "0.5.0: load value did not stay " + item.bodyPart + "/" + item.name);
    skipped += " " + item.name;
  };
  if StrLen(skipped) > 0 {
    return NPVText.F2("Projeto aberto (%1 opcoes). Nao aplicadas:%2", ToString(total), skipped);
  };
  return NPVText.F("Projeto aberto: %1 opcoes.", ToString(total));
}

// Find the saved value of one option in the current editor. A value that can
// no longer be found is skipped and listed at the end instead of stopping the
// whole load. MEDIDO EM 27/09/2026: the CCXL eyelashes switcher of "mariko" was
// saved at index 2 of 2 and would have stopped the load with every other option.
private func ResolveLoadingOption(wanted: ref<NPVOptionSnapshot>,
                                  available: array<ref<CharacterCustomizationOption>>) -> ref<NPVLoadChange> {
  let match: ref<CharacterCustomizationOption>;
  let matched: Int32 = 0;
  for current in available {
    if IsDefined(current) && IsDefined(current.info)
       && Equals(NameToString(current.info.name), wanted.name)
       && Equals(ToString(current.bodyPart), wanted.bodyPart) {
      match = current;
      matched += 1;
    };
  };
  if matched != 1 { return this.SkipLoadingOption(wanted, "opcao ausente ou duplicada"); };
  let selected: Int32 = -1;
  let ambiguous: Bool = false;
  let i: Int32 = 0;
  if Equals(wanted.kind, "switcher") {
    let switcher = match.info as gameuiSwitcherInfo;
    if !IsDefined(switcher) { return this.SkipLoadingOption(wanted, "tipo de switcher alterado"); };
    if NotEquals(wanted.selectedName, "") {
      while i < ArraySize(switcher.options) {
        if Equals(switcher.options[i].localizedName, wanted.selectedName) {
          if selected >= 0 { ambiguous = true; } else { selected = i; };
        };
        i += 1;
      };
      if ambiguous {
        if wanted.choiceCount != ArraySize(switcher.options)
           || wanted.selectedIndex >= Cast<Uint32>(ArraySize(switcher.options))
           || NotEquals(switcher.options[Cast<Int32>(wanted.selectedIndex)].localizedName,
                        wanted.selectedName) {
          return this.SkipLoadingOption(wanted, "valor ambiguo");
        };
        selected = Cast<Int32>(wanted.selectedIndex);
      };
    } else {
      // Projects saved before 0.2.1, or values the game reports outside the
      // list, have no switcher value name. Only reuse their index when the
      // option count still matches exactly.
      if wanted.choiceCount != ArraySize(switcher.options)
         || wanted.selectedIndex >= Cast<Uint32>(ArraySize(switcher.options)) {
        return this.SkipLoadingOption(wanted, "valor fora da lista");
      };
      selected = Cast<Int32>(wanted.selectedIndex);
    };
  } else {
    if Equals(wanted.kind, "appearance") {
      let appearance = match.info as gameuiAppearanceInfo;
      if !IsDefined(appearance) || Equals(wanted.selectedName, "") {
        return this.SkipLoadingOption(wanted, "valor de aparencia invalido");
      };
      while i < ArraySize(appearance.definitions) {
        if Equals(NameToString(appearance.definitions[i].name), wanted.selectedName) {
          if selected >= 0 { ambiguous = true; };
          selected = i;
        };
        i += 1;
      };
    } else {
      if !Equals(wanted.kind, "morph") { return this.SkipLoadingOption(wanted, "tipo desconhecido"); };
      let morph = match.info as gameuiMorphInfo;
      if !IsDefined(morph) || Equals(wanted.selectedName, "") {
        return this.SkipLoadingOption(wanted, "valor de morph invalido");
      };
      while i < ArraySize(morph.morphNames) {
        if Equals(NameToString(morph.morphNames[i].morphName), wanted.selectedName) {
          if selected >= 0 { ambiguous = true; };
          selected = i;
        };
        i += 1;
      };
    };
    if ambiguous { return this.SkipLoadingOption(wanted, "valor ambiguo"); };
  };
  if selected < 0 { return this.SkipLoadingOption(wanted, "valor ausente"); };
  let change = new NPVLoadChange();
  change.name = wanted.name;
  change.bodyPart = wanted.bodyPart;
  change.option = match;
  change.index = Cast<Uint32>(selected);
  return change;
}

private func SkipLoadingOption(wanted: ref<NPVOptionSnapshot>, reason: String) -> ref<NPVLoadChange> {
  ModLog(n"NPVMaker", "0.5.0: load skipped " + wanted.bodyPart + "/" + wanted.name + ": " + reason);
  ArrayPush(this.loadUnresolved, wanted.name);
  return null;
}

private func RestartLoadQueue(items: array<ref<NPVLoadChange>>) -> Void {
  let copy: array<ref<NPVLoadChange>>;
  for item in items { ArrayPush(copy, item); };
  ArrayClear(this.loadQueue);
  for item in copy { ArrayPush(this.loadQueue, item); };
  ArrayClear(this.loadWaiting);
  this.loadStep = 0;
  this.loadProgress = false;
}

private func ClearLoadQueue() -> Void {
  ArrayClear(this.loadAll);
  ArrayClear(this.loadQueue);
  ArrayClear(this.loadWaiting);
  ArrayClear(this.loadInactive);
  this.loadStep = 0;
  this.loadWait = 0;
  this.loadRound = 0;
  this.loadChecks = 0;
  this.loadApplied = 0;
  this.loadProgress = false;
}

private func ActiveLoadingOption(name: String, bodyPart: String) -> ref<CharacterCustomizationOption> {
  let found: ref<CharacterCustomizationOption>;
  let count: Int32 = 0;
  for current in this.system.GetUnitedOptions(true, true, true) {
    if IsDefined(current) && IsDefined(current.info) && current.isActive && current.isEditable
       && Equals(NameToString(current.info.name), name)
       && Equals(ToString(current.bodyPart), bodyPart) {
      found = current;
      count += 1;
    };
  };
  if count != 1 { return null; };
  return found;
}

  public func Capture() -> Void {
    if !this.active || this.pendingSave || !IsDefined(this.system) { return; };
    if !this.storageReady {
      this.SetStatus(NPVText.T("Salvamento indisponivel: ative o RedFileSystem e reinicie o jogo."));
      return;
    };
    if IsDefined(this.nameInput) { this.projectName = this.nameInput.GetText(); };
    if StrLen(this.projectName) == 0 {
      this.SetStatus(NPVText.T("Digite um nome para o personagem."));
      return;
    };
    let state = this.system.GetState();
    if !IsDefined(state) { this.SetStatus(NPVText.T("Editor ainda nao esta pronto.")); return; };
    this.bodyMale = state.IsBodyGenderMale();
    this.voiceMale = state.IsBrainGenderMale();
    ArrayClear(this.options);
    let available = this.system.GetUnitedOptions(true, true, true);
    let appearance: ref<gameuiAppearanceInfo>;
    let morph: ref<gameuiMorphInfo>;
    let switcher: ref<gameuiSwitcherInfo>;
    let entry: ref<NPVOptionSnapshot>;
  let index: Int32;
  let i: Int32;
    for option in available {
      if IsDefined(option) && IsDefined(option.info) {
        entry = new NPVOptionSnapshot();
        entry.name = NameToString(option.info.name);
        entry.bodyPart = ToString(option.bodyPart);
        entry.selectedIndex = option.currIndex;
        entry.active = option.isActive;
        entry.editable = option.isEditable;
        entry.censored = option.isCensored;
        index = Cast<Int32>(option.currIndex);
        appearance = option.info as gameuiAppearanceInfo;
        morph = option.info as gameuiMorphInfo;
        switcher = option.info as gameuiSwitcherInfo;
        if IsDefined(appearance) {
          entry.kind = "appearance";
          entry.resourcePath = ResRef.ToString(ResourceAsyncRef.GetPath(appearance.resource));
          entry.choiceCount = ArraySize(appearance.definitions);
          if index >= 0 && index < entry.choiceCount {
            entry.selectedName = NameToString(appearance.definitions[index].name);
          };
        } else {
          if IsDefined(morph) {
            entry.kind = "morph";
            entry.choiceCount = ArraySize(morph.morphNames);
            if index >= 0 && index < entry.choiceCount {
              entry.selectedName = NameToString(morph.morphNames[index].morphName);
            };
          } else {
            if IsDefined(switcher) {
              entry.kind = "switcher";
              entry.choiceCount = ArraySize(switcher.options);
              if index >= 0 && index < entry.choiceCount {
                entry.selectedName = switcher.options[index].localizedName;
                i = 0;
                while i < entry.choiceCount {
                  if i != index && Equals(switcher.options[i].localizedName, entry.selectedName) {
                    entry.selectedName = "";
                    break;
                  };
                  i += 1;
                };
              };
            } else { entry.kind = "unknown"; };
          };
        };
        ArrayPush(this.options, entry);
      };
    };
    if ArraySize(this.options) == 0 {
      this.SetStatus(NPVText.T("Nenhuma opcao carregada. Aguarde o editor."));
      return;
    };
    this.CaptureRuntime();
    this.SetStatus(NPVText.T("Salvando projeto..."));
    this.pendingSave = true;
  }

  // Read-only: the visual components the game mounted on the editor puppet,
  // with the .app and appearance that made each one and the state of its file.
  private func CaptureRuntime() -> Void {
    ArrayClear(this.runtimeComponents);
    this.runtimeStatus = "unavailable";
    this.runtimeReason = "";
    this.runtimeTemplate = "";
    let controller = this.system.GetPuppetPreviewGameController();
    if !IsDefined(controller) {
      this.runtimeReason = "preview_not_registered";
      return;
    };
    let puppet = controller.GetGamePuppet();
    if !IsDefined(puppet) {
      this.runtimeReason = "no_puppet";
      return;
    };
    this.runtimeTemplate = ResRef.ToString(puppet.GetTemplatePath());
    let depot = GameInstance.GetResourceDepot();
    let entry: ref<NPVRuntimeComponent>;
    for component in puppet.GetComponents() {
      entry = this.RuntimeComponent(component, depot);
      if IsDefined(entry) { ArrayPush(this.runtimeComponents, entry); };
    };
    this.runtimeStatus = "captured";
  }

  private func RuntimeComponent(component: ref<IComponent>, depot: ref<ResourceDepot>) -> ref<NPVRuntimeComponent> {
    if !IsDefined(component) { return null; };
    let skinned = component as entSkinnedMeshComponent;
    let morph = component as entMorphTargetSkinnedMeshComponent;
    let mesh = component as MeshComponent;
    let entry = new NPVRuntimeComponent();
    let reference: ResourceAsyncRef;
    if IsDefined(skinned) {
      entry.field = "mesh";
      reference = skinned.mesh;
      entry.meshAppearance = NameToString(skinned.meshAppearance);
      entry.chunkMask = ToString(skinned.chunkMask);
    } else {
      if IsDefined(morph) {
        entry.field = "morphResource";
        reference = morph.morphResource;
        entry.meshAppearance = NameToString(morph.meshAppearance);
        entry.chunkMask = ToString(morph.chunkMask);
      } else {
        if !IsDefined(mesh) { return null; };
        entry.field = "mesh";
        reference = mesh.mesh;
        entry.meshAppearance = NameToString(mesh.meshAppearance);
        entry.chunkMask = ToString(mesh.chunkMask);
      };
    };
    entry.name = NameToString(component.GetName());
    entry.type = NameToString(component.GetClassName());
    entry.enabled = component.IsEnabled();
    entry.ownerAppearance = NameToString(component.GetAppearanceName());
    entry.ownerApp = ResRef.ToString(component.appearancePath);
    entry.hash = ToString(ResourceAsyncRef.GetHash(reference));
    entry.path = ResRef.ToString(ResourceAsyncRef.GetPath(reference));
    if ResourceAsyncRef.IsEmpty(reference) || Equals(entry.hash, "0") {
      entry.state = "NONE";
    } else {
      if !depot.ResourceExists(ResourceAsyncRef.GetPath(reference)) {
        entry.state = "MISSING";
      } else {
        entry.token = depot.LoadResource(ResourceAsyncRef.GetPath(reference));
        entry.state = IsDefined(entry.token) ? "PENDING" : "UNOBSERVED";
      };
    };
    return entry;
  }

  // The editor ticker waits for this before writing the project (a few frames).
  public func RuntimeReady() -> Bool {
    let pending = false;
    for entry in this.runtimeComponents {
      if Equals(entry.state, "PENDING") {
        if entry.token.IsFinished() {
          entry.state = entry.token.IsLoaded() ? "LOADED" : "EXISTS_NOT_LOADED";
          entry.token = null;
        } else {
          pending = true;
        };
      };
    };
    return !pending;
  }

  public func FinishRuntime() -> Void {
    for entry in this.runtimeComponents {
      if Equals(entry.state, "PENDING") { entry.state = "UNOBSERVED"; };
      entry.token = null;
    };
  }

  // What CET onUpdate did before 0.5.0, every 0.15 s while the editor panel exists.
  public func EditorTick() -> Void {
    this.ticks += 1;
    if this.pendingSave {
      // The puppet resources finish loading a few frames after the capture; at most 20 ticks (3 s),
      // then the remaining ones are saved UNOBSERVED.
      if this.runtimeWait < 20 && !this.RuntimeReady() {
        this.runtimeWait += 1;
        return;
      };
      this.FinishRuntime();
      this.runtimeWait = 0;
      this.WriteSave();
      return;
    };
    if NotEquals(this.saveToken, "") { this.PollSave(); };
    if this.pendingLoad { this.LoadTick(); };
    if this.ticks % 7 == 0 { this.PollStatus(); };
  }

  public func CycleBodyStrategy() -> Void {
    this.bodyStrategy = Equals(this.bodyStrategy, "selected_tpp") ? "runtime_tpp" : "selected_tpp";
    if IsDefined(this.bodyButton) { this.bodyButton.SetText(NPVText.F("CORPO: %1", StrUpper(this.bodyStrategy))); };
  }

  private func WolvenKitReady() -> Bool {
    return Equals(NPVFiles.Value(NPVFiles.Rows(NPVFiles.Read("setup.txt")), "state"), "READY");
  }

  // The project goes to the storage as a save request; storage_bridge gives it its dated id (the game has no
  // real clock) and, for IMPORTAR, queues the import with the chosen body strategy.
  private func WriteSave() -> Void {
    let build = this.exportAfterSave;
    this.exportAfterSave = false;
    this.pendingSave = false;
    if build && !this.WolvenKitReady() {
      build = false;
      this.SetStatus(NPVText.T("WolvenKit necessario para importar: PROXIMO: GERENCIAR > WOLVENKIT. Salvando so o projeto..."));
    };
    this.saveCounter += 1;
    this.saveToken = ToString(RandRange(100000, 999999)) + "x" + ToString(this.saveCounter);
    let create = "";
    if build && StrLen(this.createMods) > 0 {
      create = ", \"integrations\": " + this.createMods + ", \"underwear\": " + NPVFiles.Json(this.createUnderwear);
    };
    let body = "{\"format\": \"npv-maker-save-request\", \"schema_version\": 1, \"after_save\": "
      + NPVFiles.Json(build ? "build" : "none") + ", \"body_strategy\": " + NPVFiles.Json(this.bodyStrategy) + create
      + ", \"project\": " + this.ProjectJson() + "}";
    if !NPVFiles.Write("save-" + this.saveToken + ".draft.json", body) {
      this.saveToken = "";
      this.SetStatus(NPVText.T("Falha ao gravar o projeto em r6/storages/NPVMaker."));
      return;
    };
    if build {
      this.SetStatus(NPVText.F("Salvando e pedindo a importacao (corpo %1)...", StrUpper(this.bodyStrategy)));
    } else {
      this.SetStatus(NPVText.T("Salvando projeto..."));
    };
  }

  private func ProjectJson() -> String {
    let options = "";
    let first = true;
    for entry in this.options {
      if !first { options += ", "; };
      first = false;
      options += "{\"name\": " + NPVFiles.Json(entry.name) + ", \"body_part\": " + NPVFiles.Json(entry.bodyPart)
        + ", \"kind\": " + NPVFiles.Json(entry.kind) + ", \"selected_name\": " + NPVFiles.Json(entry.selectedName)
        + ", \"resource_path\": " + NPVFiles.Json(entry.resourcePath)
        + ", \"selected_index\": " + ToString(entry.selectedIndex) + ", \"choice_count\": " + ToString(entry.choiceCount)
        + ", \"active\": " + NPVFiles.JsonBool(entry.active) + ", \"editable\": " + NPVFiles.JsonBool(entry.editable)
        + ", \"censored\": " + NPVFiles.JsonBool(entry.censored) + "}";
    };
    return "{\"format\": \"npv-maker-project\", \"schema_version\": 1, \"tool_version\": \"0.5.0\", \"name\": "
      + NPVFiles.Json(this.projectName) + ", \"created_at\": \"\", \"source\": \"native-character-creator\", \"body\": "
      + NPVFiles.Json(this.bodyMale ? "male" : "female") + ", \"voice\": " + NPVFiles.Json(this.voiceMale ? "male" : "female")
      + ", \"options\": [" + options + "], \"dependencies\": [], \"dependency_status\": \"unresolved\""
      + ", \"npc_status\": \"not_generated\", \"runtime_manifest\": " + this.RuntimeJson() + "}";
  }

  // Same fields as storage.lua Storage.runtime (CET versions): the converter reads them unchanged.
  private func RuntimeJson() -> String {
    if NotEquals(this.runtimeStatus, "captured") {
      let reason = StrLen(this.runtimeReason) > 0 ? this.runtimeReason : "sem captura";
      return "{\"schema\": 1, \"status\": \"unavailable\", \"reason\": " + NPVFiles.Json(reason) + "}";
    };
    let components = "";
    let first = true;
    for c in this.runtimeComponents {
      if !first { components += ", "; };
      first = false;
      components += "{\"name\": " + NPVFiles.Json(c.name) + ", \"type\": " + NPVFiles.Json(c.type)
        + ", \"enabled\": " + NPVFiles.JsonBool(c.enabled) + ", \"owner_appearance\": " + NPVFiles.Json(c.ownerAppearance)
        + ", \"owner_app\": " + NPVFiles.Json(c.ownerApp) + ", \"field\": " + NPVFiles.Json(c.field)
        + ", \"hash\": " + NPVFiles.Json(c.hash) + ", \"path\": " + NPVFiles.Json(c.path)
        + ", \"mesh_appearance\": " + NPVFiles.Json(c.meshAppearance) + ", \"chunk_mask\": " + NPVFiles.Json(c.chunkMask)
        + ", \"state\": " + NPVFiles.Json(c.state) + "}";
    };
    return "{\"schema\": 1, \"status\": \"captured\", \"source\": \"character_editor_preview\", \"template\": "
      + NPVFiles.Json(this.runtimeTemplate) + ", \"components\": [" + components + "]}";
  }

  private func PollSave() -> Void {
    let name = "save-" + this.saveToken + ".result.txt";
    let rows = NPVFiles.Rows(NPVFiles.Read(name));
    if ArraySize(rows) == 0 { return; };
    NPVFiles.Delete(name);
    this.saveToken = "";
    if NotEquals(NPVFiles.Value(rows, "stage"), "saved") {
      this.SetStatus(NPVFiles.Value(rows, "message"));
      return;
    };
    this.watchId = NPVFiles.Value(rows, "id");
    this.statusRaw = "";
    this.reportShown = false;
    this.SetDiagnostics("", false);
    if Equals(NPVFiles.Value(rows, "after"), "build") {
      this.SetStatus(NPVText.F("Projeto salvo. Importacao pedida (corpo %1). Preparando personagem...", StrUpper(this.bodyStrategy)));
    } else {
      this.SetStatus(NPVText.T("Projeto salvo! Voce pode continuar editando."));
    };
    ModLog(n"NPVMaker", "0.5.0: saved " + this.watchId);
  }

  // The converter status of the last saved or opened project, mirrored as "<id>.txt".
  public func PollStatus() -> Void {
    if Equals(this.watchId, "") || this.reportShown { return; };
    let raw = NPVFiles.Read(this.watchId + ".txt");
    if Equals(raw, this.statusRaw) { return; };
    let rows = NPVFiles.Rows(raw);
    if ArraySize(rows) == 0 { return; };
    this.statusRaw = raw;
    let message = NPVFiles.Value(rows, "message");
    // Full converter message: the activity card wraps it; the report remains separate.
    this.SetStatus(message);
    let lines = NPVFiles.Values(rows, "line");
    let shown = "";
    let i = 0;
    while i < ArraySize(lines) {
      if i == 3 {
        shown += NPVText.F("+ %1 (veja o relatorio)", ToString(ArraySize(lines) - 3));
        break;
      };
      shown += lines[i] + "\n";
      i += 1;
    };
    let report = StrLen(NPVFiles.Read(this.watchId + ".report.txt")) > 0;
    this.SetDiagnostics(shown, report);
  }

  private func LoadTick() -> Void {
    if !this.loadStarted {
      let rows = NPVFiles.Rows(NPVFiles.Read("latest.txt"));
      if ArraySize(rows) == 0 {
        this.FinishLoad(NPVText.T("A lista de projetos ainda nao chegou do conversor. Tente de novo em alguns segundos."));
        return;
      };
      let problem = NPVFiles.Value(rows, "error");
      if StrLen(problem) > 0 {
        this.FinishLoad(problem);
        return;
      };
      this.StartLoading(NPVFiles.Value(rows, "name"), Equals(NPVFiles.Value(rows, "body"), "male"),
                        Equals(NPVFiles.Value(rows, "voice"), "male"));
      for row in rows {
        if Equals(row.Cell(0), "option") {
          this.AddLoadingOption(row.Cell(1), row.Cell(2), row.Cell(3), row.Cell(4),
                                Cast<Uint32>(StringToInt(row.Cell(5), 0)), StringToInt(row.Cell(6), 0),
                                Equals(row.Cell(7), "1"), Equals(row.Cell(8), "1"));
        };
      };
      // An old status (for example "importado", then removed) must not replace the result of opening.
      this.watchId = NPVFiles.Value(rows, "id");
      this.statusRaw = NPVFiles.Read(this.watchId + ".txt");
      this.reportShown = false;
      this.SetDiagnostics("", false);
      let prepared = this.PrepareLoadingProject();
      if StrLen(prepared) > 0 {
        this.FinishLoad(prepared);
        return;
      };
      this.loadStarted = true;
      return;
    };
    let result = this.StepLoadingProject();
    if StrLen(result) > 0 {
      this.FinishLoad(result);
      ModLog(n"NPVMaker", "0.5.0: " + result);
    };
  }

  public func EndSession() -> Void {
    this.active = false;
    this.pendingLoad = false;
    this.pendingPrivateZip = false;
    ArrayClear(this.loadingOptions);
    this.ClearLoadQueue();
    ArrayClear(this.loadUnresolved);
    // Do not discard an outstanding snapshot: the ticker may persist it next frame.
    this.nameInput = null;
    this.statusWidget = null;
    if IsDefined(this.system) { this.system.ClearState(); };
    this.system = null;
  }
}

@wrapMethod(SingleplayerMenuGameController)
private func PopulateMenuItemList() -> Void {
  wrappedMethod();
  this.AddMenuItem("NPV maker", n"OnOpenNPVMaker");
}

@wrapMethod(SingleplayerMenuGameController)
protected func HandleMenuItemActivate(data: ref<PauseMenuListItemData>) -> Bool {
  if IsDefined(data) && Equals(data.eventName, n"OnOpenNPVMaker") {
    if !NPVMakerSession.GetInstance().BeginSession(GameInstance.GetCharacterCustomizationSystem(this.GetPlayerControlledObject().GetGame())) {
      // Consume a failed activation; never construct previews with a null state.
      return true;
    };
  };
  return wrappedMethod(data);
}

@addMethod(MenuScenario_SingleplayerMenu)
protected cb func OnOpenNPVMaker() -> Bool {
  this.CloseSubMenu();
  this.SwitchToScenario(n"MenuScenario_NPVMaker");
}

// One isolated scenario owns only the stock body and appearance menus.
// No transition to stats, summary, FinalizeState or StartNewGame exists here.
public class MenuScenario_NPVMaker extends MenuScenario_PreGameSubMenu {
  private let editingAppearance: Bool;

  protected cb func OnEnterScenario(prevScenario: CName, userData: ref<IScriptable>) -> Bool {
    super.OnEnterScenario(prevScenario, userData);
    let session = NPVMakerSession.GetInstance();
    if !session.active || !IsDefined(session.system) {
      this.SwitchToScenario(n"MenuScenario_SingleplayerMenu");
      return false;
    };
    this.editingAppearance = false;
    ModLog(n"NPVMaker", "0.5.0: opening native body-selection preview.");
    this.GetMenusState().OpenMenu(n"character_customization_background");
    this.GetMenusState().OpenMenu(n"gender_selection");
  }

  protected cb func OnAccept() -> Bool {
    if this.editingAppearance {
      NPVMakerSession.GetInstance().Capture();
      return true;
    };
    this.editingAppearance = true;
    this.GetMenusState().CloseMenu(n"gender_selection");
    let data = new MorphMenuUserData();
    data.m_optionsListInitialized = false;
    data.m_updatingFinalizedState = false;
    data.m_editMode = gameuiCharacterCustomizationEditTag.NewGame;
    this.GetMenusState().OpenMenu(n"player_puppet");
    this.GetMenusState().OpenMenu(n"character_customization", data);
  }

  protected cb func OnBack() -> Bool {
    if this.editingAppearance {
      this.GetMenusState().CloseMenu(n"character_customization");
      this.GetMenusState().CloseMenu(n"player_puppet");
      this.editingAppearance = false;
      this.GetMenusState().OpenMenu(n"gender_selection");
    } else {
      this.SwitchToScenario(n"MenuScenario_SingleplayerMenu");
    };
  }

  protected cb func OnLeaveScenario(nextScenario: CName) -> Bool {
    this.GetMenusState().CloseMenu(n"character_customization");
    this.GetMenusState().CloseMenu(n"player_puppet");
    this.GetMenusState().CloseMenu(n"gender_selection");
    this.GetMenusState().CloseMenu(n"character_customization_background");
    NPVMakerSession.GetInstance().EndSession();
    super.OnLeaveScenario(nextScenario);
  }
}

@wrapMethod(CharacterCreationGenderSelectionMenu)
protected cb func OnPuppetReadyToBeDisplayed(evt: ref<gameuiPuppetPreview_ReadyToBeDisplayed>) -> Bool {
  if NPVMakerSession.GetInstance().active {
    ModLog(n"NPVMaker", "0.5.0: body preview ready, male=" + ToString(evt.isMale));
  };
  return wrappedMethod(evt);
}

// Author request 06/10/2026: the body type screen says NPV, not V. Measured in character_creation_step_1.inkwidget:
// top_bar_holder/top_elements/title_levles_desc/descHolder/desc (LocKey#35480, raj Regular 38, UpperCase, wrapping at
// 1430, style MainColors.Red / MainColors.ReadableSmall). It carries the same inkTextReplaceAnimationController that
// wrote the key back over SetText on the editor title (02/10/2026), so the stock text is hidden and a text with its
// measured style takes its place, as with the title.
@wrapMethod(CharacterCreationGenderSelectionMenu)
protected cb func OnInitialize() -> Bool {
  let result = wrappedMethod();
  if NPVMakerSession.GetInstance().active {
    let desc = NPVFindNamedChild(this.GetRootCompoundWidget(), n"descHolder", n"desc") as inkText;
    if IsDefined(desc) {
      let holder = desc.GetParentWidget() as inkCompoundWidget;
      if IsDefined(holder) {
        desc.SetVisible(false);
        let text = new inkText();
        text.SetName(n"NPVMakerBodyDesc");
        text.SetFontFamily("base\\gameplay\\gui\\fonts\\raj\\raj.inkfontfamily");
        text.SetFontStyle(n"Regular");
        text.SetFontSize(38);
        text.SetLetterCase(textLetterCase.UpperCase);
        text.SetTintColor(desc.GetTintColor());
        text.BindProperty(n"tintColor", n"MainColors.Red");
        text.BindProperty(n"fontSize", n"MainColors.ReadableSmall");
        text.SetHorizontalAlignment(textHorizontalAlignment.Left);
        text.SetAnchor(inkEAnchor.TopLeft);
        text.SetMargin(new inkMargin(0.0, 17.0, 0.0, 0.0));
        text.SetSize(new Vector2(1430.0, 96.0));
        text.SetFitToContent(true);
        text.SetWrapping(true, 1430.0);
        text.SetText(NPVText.T("Escolha o tipo de corpo do NPV. Ocasionalmente, a aparencia do NPV pode afetar o comportamento de outros personagens."));
        text.Reparent(holder);
      };
    };
  };
  return result;
}

public func NPVFindNamedChild(parent: wref<inkCompoundWidget>, holder: CName, name: CName) -> wref<inkWidget> {
  if !IsDefined(parent) { return null; };
  let i = 0;
  while i < parent.GetNumChildren() {
    let child = parent.GetWidgetByIndex(i);
    if Equals(parent.GetName(), holder) && Equals(child.GetName(), name) { return child; };
    let found = NPVFindNamedChild(child as inkCompoundWidget, holder, name);
    if IsDefined(found) { return found; };
    i += 1;
  };
  return null;
}

@addField(characterCreationBodyMorphMenu)
private let npvPanel: ref<inkCanvas>;

@addField(characterCreationBodyMorphMenu)
private let npvStudio: ref<NPVStudioView>;

@addField(characterCreationBodyMorphMenu)
private let npvControlsPanel: ref<inkVerticalPanel>;

@addField(characterCreationBodyMorphMenu)
private let npvActions: ref<inkHorizontalPanel>;

@addField(characterCreationBodyMorphMenu)
private let npvUtilities: ref<inkHorizontalPanel>;

@addField(characterCreationBodyMorphMenu)
private let npvActivity: ref<inkVerticalPanel>;

@addField(characterCreationBodyMorphMenu)
private let npvToggleButton: ref<SimpleButton>;

@addField(characterCreationBodyMorphMenu)
private let npvExpanded: Bool;

@wrapMethod(characterCreationBodyMorphMenu)
protected cb func OnInitialize() -> Bool {
  let result = wrappedMethod();
  let session = NPVMakerSession.GetInstance();
  if session.active {
    inkTextRef.SetText(this.m_nextPageBtnText, NPVText.T("SALVAR PROJETO"));
    // Author request 01/10/2026: the header says NPV, not V. Measured in character_creation_step_2.inkwidget:
    // top_bar_holder/top_elements/title_levles_desc/title_line/title (LocKey#23122).
    // SetText on the stock title failed in game (02/10/2026): its inkTextReplaceAnimationController
    // (playOnInitialize, targetTextLocalized LocKey#23122) writes the key back, and that class is not
    // exposed to scripts. The stock title is hidden and a text with its measured style takes its place.
    let title = this.NPVFindChild(this.GetRootCompoundWidget(), n"title_line", n"title") as inkText;
    if IsDefined(title) {
      let line = title.GetParentWidget() as inkCompoundWidget;
      if IsDefined(line) {
        title.SetVisible(false);
        let header = new inkText();
        header.SetName(n"NPVMakerTitle");
        header.SetFontFamily("base\\gameplay\\gui\\fonts\\raj\\raj.inkfontfamily");
        header.SetFontStyle(n"Medium");
        header.SetFontSize(70);
        header.SetLetterCase(textLetterCase.UpperCase);
        header.SetTintColor(title.GetTintColor());
        header.BindProperty(n"tintColor", n"MainColors.Blue");
        header.BindProperty(n"fontSize", n"MainColors.TitleHeader");
        header.SetMargin(new inkMargin(10.0, 0.0, 0.0, 0.0));
        header.SetVAlign(inkEVerticalAlign.Center);
        header.SetFitToContent(true);
        header.SetText(NPVText.T("DEFINIR APARENCIA DO NPV"));
        header.Reparent(line);
      };
    };
    this.npvStudio = NPVStudioView.Create(this, inkWidgetRef.Get(this.m_optionsList));
    this.npvPanel = this.npvStudio.Root();

  };
  return result;
}

@addMethod(characterCreationBodyMorphMenu)
private func NPVFindChild(parent: wref<inkCompoundWidget>, holder: CName, name: CName) -> wref<inkWidget> {
  if !IsDefined(parent) { return null; };
  let i = 0;
  while i < parent.GetNumChildren() {
    let child = parent.GetWidgetByIndex(i);
    if Equals(parent.GetName(), holder) && Equals(child.GetName(), name) { return child; };
    let found = this.NPVFindChild(child as inkCompoundWidget, holder, name);
    if IsDefined(found) { return found; };
    i += 1;
  };
  return null;
}

// Author request 01/10/2026: no VOZ (voice) option in the NPV editor; an NPC does not use V's voice. The game creates
// the switcher as item 0 of the list (InitializeList, NewGame edit mode) and RefreshList/UpdateOption count on that
// index, so it is hidden, never removed.
@wrapMethod(characterCreationBodyMorphMenu)
public final func InitializeList() -> Void {
  wrappedMethod();
  if NPVMakerSession.GetInstance().active {
    let first = inkCompoundRef.GetWidgetByIndex(this.m_optionsList, 0);
    if IsDefined(first) && IsDefined(first.GetController() as characterCreationVoiceOverSwitcher) {
      first.SetVisible(false);
      first.SetAffectsLayoutWhenHidden(false);
    };
    if IsDefined(this.npvStudio) { this.npvStudio.ListRebuilt(); };
  };
}

@addMethod(characterCreationBodyMorphMenu)
protected cb func OnNPVToggleClicked(widget: wref<inkWidget>) -> Bool {
  return this.OnNPVManageClicked(widget);
}

@wrapMethod(characterCreationBodyMorphMenu)
protected func NextMenu() -> Void {
  if NPVMakerSession.GetInstance().active {
    if NotEquals(this.m_busySwitchingAppearance, BusySwitchingReason.AVAILABLE) { return; };
    if IsDefined(this.npvStudio) { this.npvStudio.Save(); } else { NPVMakerSession.GetInstance().Capture(); };
    return;
  };
  wrappedMethod();
}

@wrapMethod(characterCreationBodyMorphMenu)
protected cb func OnButtonRelease(evt: ref<inkPointerEvent>) -> Bool {
  let session = NPVMakerSession.GetInstance();
  if session.active && IsDefined(this.npvManager) && this.npvManager.IsOpen() {
    // The editor keys (save, randomize, back to body selection) stay off on the manager screen.
    if evt.IsAction(n"back") {
      if this.npvManager.Typing() { this.RequestSetFocus(null); } else { this.npvManager.Back(); };
      evt.Handle();
    };
    return false;
  };
  if session.active && IsDefined(this.npvStudio) && this.npvStudio.Typing() {
    if evt.IsAction(n"back") { this.RequestSetFocus(null); evt.Handle(); };
    return false;
  };
  if session.active && IsDefined(this.npvStudio) && evt.IsAction(n"back") && this.npvStudio.Back() {
    evt.Handle();
    return true;
  };
  if session.active && IsDefined(this.npvStudio) && this.npvStudio.IsChoosing() && (evt.IsAction(n"one_click_confirm") || evt.IsAction(n"character_preview_randomize")) {
    evt.Handle();
    return true;
  };
  if session.active && IsDefined(session.nameInput) && session.nameInput.IsFocused() {
    // Typing F/R in the name must not save/randomize the character.
    if evt.IsAction(n"back") {
      this.RequestSetFocus(null);
      evt.Handle();
    };
    return false;
  };
  return wrappedMethod(evt);
}

@wrapMethod(characterCreationBodyMorphMenu)
protected cb func OnRelease(evt: ref<inkPointerEvent>) -> Bool {
  let session = NPVMakerSession.GetInstance();
  if session.active && evt.IsAction(n"click") && IsDefined(evt.GetTarget()) && !evt.GetTarget().CanSupportFocus() {
    this.RequestSetFocus(null);
  };
  return wrappedMethod(evt);
}

@wrapMethod(characterCreationBodyMorphMenu)
protected cb func OnUninitialize() -> Bool {
  let session = NPVMakerSession.GetInstance();
  if IsDefined(this.npvPanel) {
    if IsDefined(session.nameInput) { session.projectName = session.nameInput.GetText(); };
    session.nameInput = null;
    session.statusWidget = null;
    session.diagnosticsWidget = null;
    session.copyRow = null;
    this.npvActions = null;
    this.npvUtilities = null;
    this.npvActivity = null;
    this.npvControlsPanel = null;
    this.npvToggleButton = null;
    if IsDefined(this.npvStudio) { this.npvStudio.Dispose(); };
    this.npvStudio = null;
    this.npvPanel = null;
  };
  return wrappedMethod();
}

@addField(characterCreationBodyMorphMenu)
private let npvLoadButton: ref<SimpleButton>;

@addField(characterCreationBodyMorphMenu)
private let npvBuildButton: ref<SimpleButton>;

@addField(characterCreationBodyMorphMenu)
private let npvPrivateZipButton: ref<SimpleButton>;

@addField(characterCreationBodyMorphMenu)
private let npvCopySummaryButton: ref<SimpleButton>;

@addField(characterCreationBodyMorphMenu)
private let npvCopyReportButton: ref<SimpleButton>;

@addField(characterCreationBodyMorphMenu)
private let npvBodyButton: ref<SimpleButton>;

@addField(characterCreationBodyMorphMenu)
private let npvTicker: ref<NPVMakerTicker>;

@addField(characterCreationBodyMorphMenu)
private let npvManagerButton: ref<SimpleButton>;

@addField(characterCreationBodyMorphMenu)
private let npvManager: ref<NPVManagerView>;

@wrapMethod(characterCreationBodyMorphMenu)
protected cb func OnInitialize() -> Bool {
  let result = wrappedMethod();
  if NPVMakerSession.GetInstance().active && IsDefined(this.npvPanel) {
    if !NPVMakerSession.GetInstance().storageReady {
      NPVMakerSession.GetInstance().SetStatus(NPVText.T("RedFileSystem ausente: ative-o no Vortex e reinicie o jogo para salvar projetos."));
    };
    NPVMakerSession.GetInstance().statusRaw = "";
    this.npvTicker = NPVMakerTicker.StartStudio(this.npvPanel, this.npvStudio);
  };
  return result;
}

@addMethod(characterCreationBodyMorphMenu)
protected cb func OnNPVLoadClicked(widget: wref<inkWidget>) -> Bool {
  NPVMakerSession.GetInstance().RequestLoad();
  return true;
}

@addMethod(characterCreationBodyMorphMenu)
protected cb func OnNPVBuildClicked(widget: wref<inkWidget>) -> Bool {
  // CRIAR NPV: the mods are chosen in the manager before the import (author request 01/10/2026).
  this.OnNPVManageClicked(widget);
  if IsDefined(this.npvManager) { this.npvManager.ShowCreate(); };
  return true;
}

@addMethod(characterCreationBodyMorphMenu)
protected cb func OnNPVCopySummaryClicked(widget: wref<inkWidget>) -> Bool {
  this.OnNPVManageClicked(widget);
  if IsDefined(this.npvManager) { this.npvManager.ShowReport(); };
  return true;
}

@addMethod(characterCreationBodyMorphMenu)
protected cb func OnNPVBodyClicked(widget: wref<inkWidget>) -> Bool {
  NPVMakerSession.GetInstance().CycleBodyStrategy();
  return true;
}

@addMethod(characterCreationBodyMorphMenu)
protected cb func OnNPVManageClicked(widget: wref<inkWidget>) -> Bool {
  if IsDefined(this.npvManager) && this.npvManager.IsOpen() { return true; };
  let session = NPVMakerSession.GetInstance();
  if IsDefined(this.npvStudio) { this.npvStudio.SaveName(); };
  if IsDefined(session.nameInput) { session.projectName = session.nameInput.GetText(); };
  this.RequestSetFocus(null);
  // The editor ticker runs on a widget the manager hides; the manager ticks the editor work instead.
  if IsDefined(this.npvTicker) {
    this.npvTicker.Stop();
    this.npvTicker = null;
  };
  this.npvManager = NPVManagerView.Open(this);
  return true;
}

@addMethod(characterCreationBodyMorphMenu)
public func NPVManagerClosed() -> Void {
  this.RequestSetFocus(null);
  if IsDefined(this.npvStudio) { this.npvStudio.Rebind(); };
  if IsDefined(this.npvPanel) && !IsDefined(this.npvTicker) {
    this.npvTicker = NPVMakerTicker.StartStudio(this.npvPanel, this.npvStudio);
  };
}

@addMethod(characterCreationBodyMorphMenu)
protected cb func OnNPVPrivateZipClicked(widget: wref<inkWidget>) -> Bool {
  NPVMakerSession.GetInstance().RequestPrivateZip();
  return true;
}

@wrapMethod(characterCreationBodyMorphMenu)
protected cb func OnUninitialize() -> Bool {
  if IsDefined(this.npvToggleButton) {
    this.npvToggleButton.UnregisterFromCallback(n"OnBtnClick", this, n"OnNPVToggleClicked");
  };
  if IsDefined(this.npvLoadButton) {
    this.npvLoadButton.UnregisterFromCallback(n"OnBtnClick", this, n"OnNPVLoadClicked");
    this.npvLoadButton = null;
  };
  if IsDefined(this.npvBuildButton) {
    this.npvBuildButton.UnregisterFromCallback(n"OnBtnClick", this, n"OnNPVBuildClicked");
    this.npvBuildButton = null;
  };
  if IsDefined(this.npvPrivateZipButton) {
    this.npvPrivateZipButton.UnregisterFromCallback(n"OnBtnClick", this, n"OnNPVPrivateZipClicked");
    this.npvPrivateZipButton = null;
  };
  if IsDefined(this.npvCopySummaryButton) {
    this.npvCopySummaryButton.UnregisterFromCallback(n"OnBtnClick", this, n"OnNPVCopySummaryClicked");
    this.npvCopySummaryButton = null;
  };
  if IsDefined(this.npvBodyButton) {
    this.npvBodyButton.UnregisterFromCallback(n"OnBtnClick", this, n"OnNPVBodyClicked");
    this.npvBodyButton = null;
    NPVMakerSession.GetInstance().bodyButton = null;
  };
  if IsDefined(this.npvManagerButton) {
    this.npvManagerButton.UnregisterFromCallback(n"OnBtnClick", this, n"OnNPVManageClicked");
    this.npvManagerButton = null;
  };
  if IsDefined(this.npvManager) {
    this.npvManager.Close();
    this.npvManager = null;
  };
  if IsDefined(this.npvTicker) {
    this.npvTicker.Stop();
    this.npvTicker = null;
  };
  return wrappedMethod();
}
