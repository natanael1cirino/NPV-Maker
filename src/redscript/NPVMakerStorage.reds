import RedFileSystem.*

// 0.5.0 without CET (docs/SEM-CET-MAPA.md). The game reads and writes only plain files in
// r6/storages/NPVMaker through RedFileSystem; tools/storage_bridge.py moves them to and from the
// converter. MEDIDO EM 30/09/2026 (NPV FS Probe 0.3): the storage is granted once per session (asked in
// NPVMakerSession.OnLoad), sub folders are refused, 200 KB round trips unchanged, accents survive.
// The converter writes "key<TAB>value" lines ending with "end<TAB>1"; a read without that line was
// taken while the file was being replaced and is ignored until the next poll.

public class NPVRow extends IScriptable {
  public let cells: array<String>;

  public func Cell(index: Int32) -> String {
    if index < 0 || index >= ArraySize(this.cells) { return ""; };
    return this.cells[index];
  }
}

public abstract class NPVFiles {
  public static func Storage() -> ref<FileSystemStorage> {
    let session = NPVMakerSession.GetInstance();
    if !IsDefined(session) { return null; };
    return session.storage;
  }

  public static func Ready() -> Bool {
    return IsDefined(NPVFiles.Storage());
  }

  public static func Write(name: String, text: String) -> Bool {
    let storage = NPVFiles.Storage();
    if !IsDefined(storage) { return false; };
    let file = storage.GetFile(name);
    if !IsDefined(file) { return false; };
    return file.WriteText(text, FileSystemWriteMode.Truncate);
  }

  public static func Read(name: String) -> String {
    let storage = NPVFiles.Storage();
    if !IsDefined(storage) || NotEquals(storage.Exists(name), FileSystemStatus.True) { return ""; };
    let file = storage.GetFile(name);
    if !IsDefined(file) { return ""; };
    return file.ReadAsText();
  }

  public static func Delete(name: String) -> Void {
    let storage = NPVFiles.Storage();
    if IsDefined(storage) && Equals(storage.Exists(name), FileSystemStatus.True) {
      storage.DeleteFile(name);
    };
  }

  public static func Complete(text: String) -> Bool {
    return StrContains(text, "end\t1");
  }

  public static func Rows(text: String) -> array<ref<NPVRow>> {
    let rows: array<ref<NPVRow>>;
    if !NPVFiles.Complete(text) { return rows; };
    for line in StrSplit(text, "\n") {
      let clean = StrReplaceAll(line, "\r", "");
      if StrLen(clean) > 0 && NotEquals(clean, "end\t1") {
        let row = new NPVRow();
        row.cells = NPVFiles.Cells(clean);
        ArrayPush(rows, row);
      };
    };
    return rows;
  }

  // Cells of one line, empty ones kept. MEDIDO EM 01/10/2026 (0.5.0 em jogo): StrSplit dropped the empty cells,
  // so "npv<TAB>token<TAB>name<TAB><TAB><TAB>0" moved the removal flag into the package column ("(pacote )" on
  // every NPV and no EXPORTAR button).
  public static func Cells(line: String) -> array<String> {
    // No index arithmetic: the probe saw StrLen report 199500 for a 201600 character text (one less per line).
    let cells: array<String>;
    let rest = line;
    while StrContains(rest, "\t") {
      ArrayPush(cells, StrBeforeFirst(rest, "\t"));
      rest = StrAfterFirst(rest, "\t");
    };
    ArrayPush(cells, rest);
    return cells;
  }

  public static func Value(rows: array<ref<NPVRow>>, key: String) -> String {
    for row in rows {
      if Equals(row.Cell(0), key) { return row.Cell(1); };
    };
    return "";
  }

  public static func Values(rows: array<ref<NPVRow>>, key: String) -> array<String> {
    let found: array<String>;
    for row in rows {
      if Equals(row.Cell(0), key) { ArrayPush(found, row.Cell(1)); };
    };
    return found;
  }

  public static func Json(text: String) -> String {
    let escaped = StrReplaceAll(text, "\\", "\\\\");
    escaped = StrReplaceAll(escaped, "\"", "\\\"");
    escaped = StrReplaceAll(escaped, "\n", "\\n");
    escaped = StrReplaceAll(escaped, "\r", "\\r");
    escaped = StrReplaceAll(escaped, "\t", "\\t");
    return "\"" + escaped + "\"";
  }

  public static func JsonBool(value: Bool) -> String {
    return value ? "true" : "false";
  }

  // A number the author typed (Nexus ID); anything else becomes null.
  public static func JsonId(text: String) -> String {
    let value = StringToInt(text, -1);
    if value <= 0 || NotEquals(ToString(value), text) { return "null"; };
    return ToString(value);
  }

  // Worker request in the converter's format (runtime_entry.REQUEST); `extra` is already JSON members.
  public static func Request(target: String, action: String, extra: String) -> Bool {
    let body = "{\"format\": \"npv-maker-worker-request\", \"schema_version\": 1, \"action\": " + NPVFiles.Json(action)
      + ", \"project_id\": " + NPVFiles.Json(target) + extra + "}";
    return NPVFiles.Write(target + "." + action + ".request.json", body);
  }
}

// Replaces CET onUpdate: an invisible 0.1 s animation replayed from its own OnFinish (measured by the
// probe: 50 ticks in the main menu and in the editor). It dies with the widget, so each screen starts one.
public class NPVMakerTicker extends IScriptable {
  public let widget: wref<inkWidget>;
  public let manager: wref<NPVManagerView>;
  public let studio: wref<NPVStudioView>;
  public let proxy: ref<inkAnimProxy>;
  public let stopped: Bool;

  public static func Start(widget: wref<inkWidget>, manager: wref<NPVManagerView>) -> ref<NPVMakerTicker> {
    let ticker = new NPVMakerTicker();
    ticker.widget = widget;
    ticker.manager = manager;
    ticker.Next();
    return ticker;
  }

  public static func StartStudio(widget: wref<inkWidget>, studio: wref<NPVStudioView>) -> ref<NPVMakerTicker> {
    let ticker = new NPVMakerTicker();
    ticker.widget = widget;
    ticker.studio = studio;
    ticker.Next();
    return ticker;
  }

  public func Stop() -> Void {
    this.stopped = true;
    if IsDefined(this.proxy) { this.proxy.Stop(); };
  }

  private func Next() -> Void {
    if this.stopped || !IsDefined(this.widget) { return; };
    let def = new inkAnimDef();
    let step = new inkAnimTransparency();
    step.SetStartTransparency(this.widget.GetOpacity());
    step.SetEndTransparency(this.widget.GetOpacity());
    step.SetDuration(0.15);
    def.AddInterpolator(step);
    this.proxy = this.widget.PlayAnimation(def);
    this.proxy.RegisterToCallback(inkanimEventType.OnFinish, this, n"OnTick");
  }

  protected cb func OnTick(proxy: ref<inkAnimProxy>) -> Bool {
    if this.stopped { return false; };
    if IsDefined(this.manager) {
      this.manager.Tick();
    } else {
      NPVMakerSession.GetInstance().EditorTick();
      if IsDefined(this.studio) { this.studio.Tick(); };
    };
    this.Next();
    return true;
  }
}
