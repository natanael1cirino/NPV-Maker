import Codeware.UI.*

// UI06: contextual choice list, bounded height, per-row favorites and original/trial comparison.
// The legacy view name is retained for the editor ticker; no Studio dashboard remains.
public class NPVChoiceButton extends NPVMakerCompactButton {
  private let selection: ref<inkRectangle>;
  protected func CreateWidgets() {
    super.CreateWidgets();
    this.m_root.SetSize(844.0, 80.0);
    this.m_bg.SetVisible(false);
    this.m_frame.SetVisible(false);
    this.m_label.SetFontSize(30);
    this.m_label.SetWrapping(true, 804.0);
    this.m_label.SetHorizontalAlignment(textHorizontalAlignment.Left);
    this.m_label.SetMargin(new inkMargin(20.0, 0.0, 12.0, 0.0));
    let divider = new inkRectangle();
    divider.SetSize(844.0, 1.0);
    divider.SetMargin(new inkMargin(0.0, 79.0, 0.0, 0.0));
    divider.SetTintColor(ThemeColors.RedOxide());
    divider.Reparent(this.m_root);
    this.selection = new inkRectangle();
    this.selection.SetSize(4.0, 64.0);
    this.selection.SetMargin(new inkMargin(0.0, 8.0, 0.0, 0.0));
    this.selection.SetTintColor(ThemeColors.ElectricBlue());
    this.selection.Reparent(this.m_root);
  }
  public func Mark(selected: Bool, favorite: Bool) -> Void {
    this.m_label.UnbindProperty(n"tintColor");
    this.m_label.SetTintColor(selected ? ThemeColors.ElectricBlue() : (favorite ? new HDRColor(1.0, 0.78, 0.24, 1.0) : ThemeColors.Bittersweet()));
    this.m_fill.SetOpacity(selected ? 0.25 : 0.0);
    this.selection.SetVisible(selected);
  }
  public func SetThumbnail(option: ref<CharacterCustomizationOption>, index: Int32) -> Void {
    let appearance = option.info as gameuiAppearanceInfo;
    if !IsDefined(appearance) || index < 0 || index >= ArraySize(appearance.definitions) { return; };
    let definition = appearance.definitions[index];
    let record: ref<UIIcon_Record>;
    if TDBID.IsValid(definition.icon) { record = TweakDBInterface.GetUIIconRecord(definition.icon); };
    let hasImage = IsDefined(record) && ResRef.IsValid(record.AtlasResourcePath()) && IsNameValid(record.AtlasPartName());
    // Follow native color-picker semantics: icon over the option's real color.
    // Non-thumbnail options without an image keep the full-width text layout.
    if !hasImage && !appearance.useThumbnails { return; };
    let preview = new inkCanvas();
    preview.SetName(n"NPVChoiceThumbnail");
    preview.SetSize(72.0, 72.0);
    preview.SetHAlign(inkEHorizontalAlign.Left);
    preview.SetVAlign(inkEVerticalAlign.Top);
    preview.SetMargin(new inkMargin(20.0, 4.0, 0.0, 0.0));
    preview.SetInteractive(false);
    preview.Reparent(this.m_root);
    let color = new inkRectangle();
    color.SetAnchor(inkEAnchor.Fill);
    color.SetTintColor(definition.color);
    color.SetInteractive(false);
    color.Reparent(preview);
    if hasImage {
      let image = new inkImage();
      image.SetAnchor(inkEAnchor.Fill);
      image.SetAtlasResource(record.AtlasResourcePath());
      image.SetTexturePart(record.AtlasPartName());
      image.SetTintColor(new HDRColor(1.0, 1.0, 1.0, 1.0));
      image.SetInteractive(false);
      image.Reparent(preview);
    };
    this.m_label.SetMargin(new inkMargin(108.0, 0.0, 12.0, 0.0));
    this.m_label.SetWrapping(true, 724.0);
  }
  public static func Make() -> ref<NPVChoiceButton> {
    let button = new NPVChoiceButton();
    button.CreateInstance();
    return button;
  }
}

public class NPVStudioView extends IScriptable {
  private let menu: wref<characterCreationBodyMorphMenu>;
  private let root: ref<inkCanvas>;
  private let picker: ref<inkCanvas>;
  private let nameDialog: ref<inkCanvas>;
  private let grid: ref<inkVerticalPanel>;
  private let heading: ref<inkText>;
  private let countLabel: ref<inkText>;
  private let pageLabel: ref<inkText>;
  private let status: ref<inkText>;
  private let nameInput: wref<HubTextInput>;
  private let searchInput: wref<HubTextInput>;
  private let compareButton: ref<SimpleButton>;
  private let originalKey: String;
  private let trialKey: String;
  private let footer: ref<inkHorizontalPanel>;
  private let scrollTrack: ref<inkRectangle>;
  private let scrollThumb: ref<inkRectangle>;
  private let filterButton: ref<SimpleButton>;
  private let previousButton: ref<SimpleButton>;
  private let nextButton: ref<SimpleButton>;
  private let selectedRow: wref<CharacterCreationBodyMorphBaseOption>;
  private let optionName: CName;
  private let bodyPart: String;
  private let option: wref<CharacterCustomizationOption>;
  private let nativeList: wref<inkWidget>;
  private let nativeVisible: Bool;
  private let listHidden: Bool;
  private let query: String;
  private let matches: array<Int32>;
  private let favorites: array<String>;
  private let favoritesLoaded: Bool;
  private let onlyFavorites: Bool;
  private let offset: Int32;
  private let stamp: String;
  private let ticks: Int32;
  private let buttons: ref<inkHorizontalPanel>;
  private let savedNavigationVisible: Bool;
  private let sectionHeading: wref<inkWidget>;
  private let sectionHeadingVisible: Bool;
  private let wheelLogCount: Int32;
  // Measured 06/10/2026 (gamelog): hair_color_cyberware_01 opened 81 times, each closed by the picker itself right
  // after opening. An option this picker cannot keep open goes to the game's own picker for the rest of the session.
  private let openedTick: Int32;
  private let nativeOnly: array<CName>;
  // The row the picker came from: the native list is shown again scrolled to it (it used to come back at the top).
  private let returnName: CName;
  private let returnIndex: Int32;
  private let returnTicks: Int32;

  public static func Create(menu: ref<characterCreationBodyMorphMenu>, list: wref<inkWidget>) -> ref<NPVStudioView> {
    let view = new NPVStudioView();
    view.menu = menu;
    view.nativeList = list;
    view.Build();
    return view;
  }
  public func Root() -> ref<inkCanvas> { return this.root; }
  public func Typing() -> Bool {
    return (IsDefined(this.nameInput) && this.nameInput.IsFocused()) || (IsDefined(this.searchInput) && this.searchInput.IsFocused());
  }
  public func IsChoosing() -> Bool { return IsDefined(this.picker) && this.picker.IsVisible(); }
  public func SaveName() -> Void {
    if IsDefined(this.nameInput) { NPVMakerSession.GetInstance().projectName = this.nameInput.GetText(); };
  }
  public func Rebind() -> Void {
    NPVMakerSession.GetInstance().nameInput = this.nameInput;
    NPVMakerSession.GetInstance().statusWidget = this.status;
    NPVMakerSession.GetInstance().SetStatus(NPVMakerSession.GetInstance().lastStatus);
  }
  public func Dispose() -> Void {
    this.SaveName();
    if IsDefined(this.sectionHeading) { this.sectionHeading.SetVisible(this.sectionHeadingVisible); };
    this.RestoreList();
    inkWidgetRef.SetVisible(this.menu.m_navigationButtons, this.savedNavigationVisible);
  }
  public func Back() -> Bool {
    if this.IsChoosing() { this.ClosePicker(); return true; };
    if IsDefined(this.nameDialog) { this.CloseName(); return true; };
    return false;
  }
  public func Save() -> Void {
    if !this.menu.NPVCanEdit() { return; };
    this.SaveName();
    if StrLen(NPVMakerSession.GetInstance().projectName) == 0 { this.AskName(); return; };
    this.CloseName();
    NPVMakerSession.GetInstance().Capture();
  }

  private func Build() -> Void {
    this.root = new inkCanvas();
    this.root.SetName(n"NPVMakerEditorTools");
    this.root.SetAnchor(inkEAnchor.Fill);
    this.root.Reparent(this.menu.GetRootCompoundWidget());
    // Measured native layout: 3840x2160; preset column x150..750; options x2550..3500.
    // The user chose the native "Customize Your Look" heading as the tools location.
    this.sectionHeading = this.menu.NPVSectionHeading();
    if IsDefined(this.sectionHeading) {
      this.sectionHeadingVisible = this.sectionHeading.IsVisible();
      this.sectionHeading.SetVisible(false);
    };
    let nav = this.Row(this.root);
    nav.SetAnchor(inkEAnchor.TopRight);
    nav.SetAnchorPoint(new Vector2(1.0, 0.0));
    nav.SetMargin(new inkMargin(0.0, 168.0, 330.0, 0.0));
    this.Button(nav, NPVText.T("PROJETO"), n"npvui_project", 270.0).GetRootWidget().SetHeight(52.0);
    let clothes = this.Button(nav, NPVText.T("ROUPAS / EM BREVE"), n"npvui_clothes", 370.0);
    clothes.SetDisabled(true);
    clothes.GetRootWidget().SetHeight(52.0);
    this.Button(nav, NPVText.T("GERENCIAR"), n"npvui_manage", 300.0).GetRootWidget().SetHeight(52.0);
    // Replace the actual navigation widget, never paint another panel over its buttons.
    this.savedNavigationVisible = inkWidgetRef.IsVisible(this.menu.m_navigationButtons);
    inkWidgetRef.SetVisible(this.menu.m_navigationButtons, false);
    this.buttons = this.Row(this.root);
    this.buttons.SetAnchor(inkEAnchor.BottomRight);
    this.buttons.SetAnchorPoint(new Vector2(1.0, 1.0));
    this.buttons.SetMargin(new inkMargin(0.0, 0.0, 330.0, 240.0));
    this.Button(this.buttons, "ESC  " + NPVText.T("VOLTAR"), n"npvui_back", 240.0);
    this.Button(this.buttons, "F  " + NPVText.T("SALVAR PROJETO"), n"npvui_save", 380.0);
    this.Button(this.buttons, NPVText.T("CRIAR NPV") + "  >", n"npvui_create", 320.0);
    this.status = this.Label(this.root, "", 34, false, 960.0);
    this.status.SetName(n"NPVMakerEditorStatus");
    this.status.SetAnchor(inkEAnchor.BottomRight);
    this.status.SetAnchorPoint(new Vector2(1.0, 1.0));
    this.status.SetMargin(new inkMargin(0.0, 0.0, 330.0, 324.0));
    this.status.SetSize(960.0, 72.0);
    this.status.SetFitToContent(false);
    this.Rebind();
  }

  // Attach after InitializeList as well as CreateEntry: these are the objects actually used on screen.
  public func AttachRows() -> Void {
    let list = this.nativeList as inkCompoundWidget;
    if !IsDefined(list) { return; };
    let i = 0;
    while i < list.GetNumChildren() {
      let row = list.GetWidgetByIndex(i).GetController() as characterCreationBodyMorphOption;
      if IsDefined(row) { row.NPVAttachPicker(this.menu); };
      i += 1;
    };
  }

  // Same conditions Tick uses to keep the picker open, so it never opens only to close on the next frame.
  public func CanOpen(row: ref<CharacterCreationBodyMorphBaseOption>) -> Bool {
    let option = row.NPVChoiceOption();
    if !IsDefined(option) || !IsDefined(option.info) || NPVStudioView.Count(option) < 2 || !this.menu.NPVCanEdit() { return false; };
    return option.isActive && !option.isCensored && !ArrayContains(this.nativeOnly, option.info.name);
  }

  public func OpenChoice(row: ref<CharacterCreationBodyMorphBaseOption>) -> Bool {
    if !this.CanOpen(row) { return false; };
    let option = row.NPVChoiceOption();
    this.CloseName();
    this.ClosePicker();
    this.RememberRow(row, option.info.name);
    this.openedTick = this.ticks;
    this.selectedRow = row;
    this.option = option;
    this.optionName = option.info.name;
    this.bodyPart = ToString(option.bodyPart);
    this.query = "";
    this.onlyFavorites = false;
    this.LoadFavorites();
    this.originalKey = NPVStudioView.ChoiceKey(option, Cast<Int32>(row.NPVChoiceIndex()));
    this.trialKey = this.originalKey;
    this.offset = Max(0, Cast<Int32>(row.NPVChoiceIndex()) - 3);
    this.MakePicker();
    // No list is hidden until a populated, usable picker has been created.
    this.HideList();
    this.menu.NPVChoiceCamera(option);
    this.menu.NPVStudioNativeInput(false);
    return true;
  }

  private func RememberRow(row: ref<CharacterCreationBodyMorphBaseOption>, name: CName) -> Void {
    this.returnName = name;
    this.returnIndex = -1;
    let list = this.nativeList as inkCompoundWidget;
    if !IsDefined(list) { return; };
    let i = 0;
    while i < list.GetNumChildren() {
      if list.GetWidgetByIndex(i) == row.GetRootWidget() { this.returnIndex = i; };
      i += 1;
    };
  }

  // Scroll the native list back to the row the picker came from (by option name; by position after a rebuild).
  private func ReturnToRow() -> Void {
    let list = this.nativeList as inkCompoundWidget;
    if !IsDefined(list) || this.listHidden { return; };
    let target: wref<inkWidget>;
    let i = 0;
    while i < list.GetNumChildren() && !IsDefined(target) {
      let widget = list.GetWidgetByIndex(i);
      let row = widget.GetController() as CharacterCreationBodyMorphBaseOption;
      let option = IsDefined(row) ? row.NPVChoiceOption() : null;
      if IsDefined(option) && IsDefined(option.info) && Equals(option.info.name, this.returnName) { target = widget; };
      i += 1;
    };
    if !IsDefined(target) && this.returnIndex >= 0 && this.returnIndex < list.GetNumChildren() {
      target = list.GetWidgetByIndex(this.returnIndex);
    };
    if IsDefined(target) { this.menu.NPVStudioEnsureVisible(target); };
  }

  private func HideList() -> Void {
    if !this.listHidden && IsDefined(this.nativeList) {
      this.nativeVisible = this.nativeList.IsVisible();
      this.nativeList.SetVisible(false);
      this.listHidden = true;
    };
  }
  private func RestoreList() -> Void {
    if this.listHidden && IsDefined(this.nativeList) { this.nativeList.SetVisible(this.nativeVisible); };
    this.listHidden = false;
    this.menu.NPVStudioNativeInput(true);
  }
  public func ClosePicker(opt reason: String) -> Void {
    if !IsDefined(this.picker) { return; };
    if NotEquals(reason, "") {
      ModLog(n"NPVMaker", "picker closed by itself: " + NameToString(this.optionName) + " (" + reason + ")");
      if this.ticks - this.openedTick <= 3 && !ArrayContains(this.nativeOnly, this.optionName) {
        ArrayPush(this.nativeOnly, this.optionName);
      };
    };
    this.returnTicks = 3;
    this.root.RemoveChild(this.picker);
    this.picker = null;
    this.searchInput = null;
    this.selectedRow = null;
    this.option = null;
    this.RestoreList();
    this.menu.NPVStudioClearFocus();
  }
  public func ListRebuilt() -> Void {
    this.ClosePicker("list rebuilt");
    this.AttachRows();
  }

  private func MakePicker() -> Void {
    this.picker = this.Surface(270.0, 1000.0, 1000.0, 330.0);
    this.picker.SetInteractive(true);
    this.wheelLogCount = 0;
    this.heading = this.Label(this.picker, this.Short(this.OptionTitle(), 28), 46, true, 712.0);
    this.heading.SetMargin(new inkMargin(24.0, 16.0, 0.0, 0.0));
    this.Button(this.picker, NPVText.T("FECHAR"), n"npvui_close", 210.0).GetRootWidget().SetMargin(new inkMargin(766.0, 16.0, 0.0, 0.0));
    this.countLabel = this.Label(this.picker, "", 32, false, 936.0);
    this.countLabel.SetMargin(new inkMargin(24.0, 90.0, 0.0, 0.0));
    this.countLabel.SetSize(936.0, 84.0);
    this.countLabel.SetFitToContent(false);
    this.Label(this.picker, NPVText.T("BUSCAR ESCOLHA"), 28, false, 936.0).SetMargin(new inkMargin(68.0, 148.0, 0.0, 0.0));
    NPVIcons.Add(this.picker, n"search", 30.0).SetMargin(new inkMargin(24.0, 148.0, 0.0, 0.0));
    let search = HubTextInput.Create();
    search.SetWidth(936.0);
    search.SetMaxLength(120);
    search.Reparent(this.picker, this.menu);
    search.GetRootWidget().SetMargin(new inkMargin(24.0, 186.0, 0.0, 0.0));
    this.searchInput = search;
    let tools = this.Row(this.picker);
    tools.SetMargin(new inkMargin(24.0, 266.0, 0.0, 0.0));
    this.filterButton = this.Button(tools, NPVText.T("TODAS AS ESCOLHAS"), n"npvui_filter", 456.0);
    this.compareButton = this.Button(tools, NPVText.T("VER ORIGINAL"), n"npvui_compare", 468.0);
    this.grid = new inkVerticalPanel();
    this.grid.SetChildMargin(new inkMargin(0.0, 0.0, 0.0, 4.0));
    this.grid.SetFitToContent(true);
    this.grid.SetMargin(new inkMargin(24.0, 354.0, 0.0, 0.0));
    this.grid.Reparent(this.picker);
    this.scrollTrack = new inkRectangle();
    this.scrollTrack.SetMargin(new inkMargin(970.0, 354.0, 0.0, 0.0));
    this.scrollTrack.SetTintColor(ThemeColors.RedOxide());
    this.scrollTrack.Reparent(this.picker);
    this.scrollThumb = new inkRectangle();
    this.scrollThumb.SetTintColor(ThemeColors.ElectricBlue());
    this.scrollThumb.Reparent(this.picker);
    this.footer = this.Row(this.picker);
    this.previousButton = this.Button(this.footer, "^", n"npvui_previous", 90.0);
    this.pageLabel = this.Label(this.footer, "", 28, false, 732.0);
    this.pageLabel.SetSize(732.0, 64.0);
    this.pageLabel.SetFitToContent(false);
    this.pageLabel.SetHorizontalAlignment(textHorizontalAlignment.Center);
    this.nextButton = this.Button(this.footer, "v", n"npvui_next", 90.0);
    this.BindChoiceWheel(this.picker);
    this.RenderChoices();
    ModLog(n"NPVMaker", "UI08 picker wheel bound: " + NameToString(this.optionName));
  }

  private func RenderChoices() -> Void {
    if !IsDefined(this.option) || !IsDefined(this.grid) { return; };
    ArrayClear(this.matches);
    let query = StrLower(this.query);
    let count = NPVStudioView.Count(this.option);
    let current = Cast<Int32>(this.selectedRow.NPVChoiceIndex());
    let i = 0;
    while i < count {
      let match = StrLen(query) == 0 || StrContains(StrLower(NPVStudioView.Choice(this.option, i) + " " + NPVStudioView.ChoiceKey(this.option, i)), query);
      if match && (!this.onlyFavorites || this.Favorite(i)) { ArrayPush(this.matches, i); };
      i += 1;
    };
    let total = ArraySize(this.matches);
    this.offset = Max(0, Min(this.offset, total - 12));
    this.grid.RemoveAllChildren();
    i = this.offset;
    while i < total && i < this.offset + 12 {
      let row = this.Row(this.grid);
      let index = this.matches[i];
      let chosen = current == index;
      let favorite = this.Favorite(index);
      let title = NPVStudioView.Choice(this.option, index);
      let key = NPVStudioView.ChoiceKey(this.option, index);
      let button = NPVChoiceButton.Make();
      button.SetName(StringToName("npvui_choice_" + ToString(index)));
      button.SetText((chosen ? "> " : "") + this.Short(title, 52) + "\n" + (StrLen(key) > 0 && NotEquals(key, title) ? this.Short(key, 60) : "#" + ToString(index + 1)));
      button.SetFlipped(true);
      button.ToggleAnimations(true);
      button.ToggleSounds(true);
      button.Reparent(row, this.menu);
      button.GetRootWidget().SetAnchorPoint(new Vector2(0.0, 0.0));
      button.RegisterToCallback(n"OnBtnClick", this, n"OnButton");
      button.Mark(chosen, favorite);
      button.SetThumbnail(this.option, index);
      let star = this.Button(row, "", StringToName("npvui_star_" + ToString(index)), 72.0) as NPVIconButton;
      star.SetFavorite(favorite, this.pageLabel);
      star.SetDisabled(StrLen(key) == 0);
      // Rows are recreated after scrolling/searching; each new hit target needs input.
      this.BindChoiceWheel(row);
      i += 1;
    };
    if total == 0 { this.Label(this.grid, NPVText.T("Nenhuma escolha encontrada. Limpe a busca ou mostre todas."), 32, false, 936.0); };
    let visibleRows = Max(1, Min(12, total));
    let height = Cast<Float>(visibleRows) * 84.0;
    this.picker.SetHeight(452.0 + height);
    this.footer.SetMargin(new inkMargin(24.0, 372.0 + height, 0.0, 0.0));
    this.scrollTrack.SetSize(3.0, height);
    this.scrollTrack.SetVisible(total > 12);
    this.scrollThumb.SetVisible(total > 12);
    if total > 12 {
      let thumbHeight = MaxF(32.0, height * 12.0 / Cast<Float>(total));
      this.scrollThumb.SetSize(5.0, thumbHeight);
      this.scrollThumb.SetMargin(new inkMargin(969.0, 354.0 + (height - thumbHeight) * Cast<Float>(this.offset) / Cast<Float>(total - 12), 0.0, 0.0));
    };
    this.countLabel.SetText(NPVText.T("NO PERSONAGEM") + "  /  " + this.Short(NPVStudioView.Choice(this.option, current), 68));
    this.filterButton.SetText(NPVText.T(this.onlyFavorites ? "SO FAVORITOS" : "TODAS AS ESCOLHAS"));
    let original = this.ResolveChoice(this.originalKey);
    let trial = this.ResolveChoice(this.trialKey);
    this.compareButton.SetText(NPVText.T(current == original && trial != original ? "VER NOVA ESCOLHA" : "VER ORIGINAL"));
    this.compareButton.SetDisabled(original < 0 || trial < 0 || original == trial);
    this.pageLabel.SetText(total == 0 ? "0 " + NPVText.T("opcoes") : ToString(this.offset + 1) + " - " + ToString(Min(this.offset + 12, total)) + " / " + ToString(total) + "  ·  " + NPVText.T("ROLE PARA EXPLORAR"));
    this.previousButton.SetDisabled(this.offset == 0);
    this.nextButton.SetDisabled(this.offset + 12 >= total);
    this.stamp = ToString(current) + ":" + ToString(count);
  }

  private func ResolveChoice(key: String) -> Int32 {
    if StrLen(key) == 0 { return -1; };
    let found = -1;
    let i = 0;
    while i < NPVStudioView.Count(this.option) {
      if Equals(NPVStudioView.ChoiceKey(this.option, i), key) {
        if found >= 0 { return -1; };
        found = i;
      };
      i += 1;
    };
    return found;
  }

  private func ScrollChoices(delta: Int32) -> Void {
    let next = Max(0, Min(this.offset + delta, ArraySize(this.matches) - 12));
    if next != this.offset { this.offset = next; this.RenderChoices(); };
  }

  private func BindChoiceWheel(widget: ref<inkWidget>) -> Void {
    // Receive the relative event at the actual hit target, before global post-input.
    // Include button/text-input children and the panel shade, so gaps and stars scroll too.
    widget.RegisterToCallback(n"OnRelative", this.menu, n"NPVOnChoiceWheel");
    let compound = widget as inkCompoundWidget;
    if !IsDefined(compound) { return; };
    let i = 0;
    while i < compound.GetNumChildren() {
      this.BindChoiceWheel(compound.GetWidgetByIndex(i));
      i += 1;
    };
  }

  public func HandleChoiceWheel(evt: ref<inkPointerEvent>) -> Bool {
    if !this.IsChoosing() || !evt.IsAction(n"mouse_wheel") || evt.IsConsumed() { return false; };
    let delta = evt.GetAxisData();
    if delta == 0.0 { return false; };
    // Consume before rebuilding rows: bubbling must not apply the same notch twice,
    // even at the first/last row. No global listener or stale hover flag is involved.
    evt.Handle();
    evt.Consume();
    let previous = this.offset;
    this.ScrollChoices(delta > 0.0 ? -1 : 1);
    if this.wheelLogCount < 6 {
      ModLog(n"NPVMaker", "UI08 wheel delta=" + ToString(delta) + " offset=" + ToString(previous) + "->" + ToString(this.offset) + " matches=" + ToString(ArraySize(this.matches)));
      this.wheelLogCount += 1;
    };
    return true;
  }

  private func LoadFavorites() -> Void {
    if this.favoritesLoaded || !NPVFiles.Ready() { return; };
    this.favorites = NPVFiles.Values(NPVFiles.Rows(NPVFiles.Read("appearance-favorites.txt")), "favorite");
    this.favoritesLoaded = true;
  }
  private func FavoriteKey(index: Int32) -> String {
    let choice = NPVStudioView.ChoiceKey(this.option, index);
    if StrLen(choice) == 0 { return ""; };
    return NPVFiles.Json(this.bodyPart + ":" + NameToString(this.optionName) + ":" + choice);
  }
  private func Favorite(index: Int32) -> Bool {
    return ArrayContains(this.favorites, this.FavoriteKey(index));
  }
  private func ToggleFavorite(index: Int32) -> Void {
    this.LoadFavorites();
    let key = this.FavoriteKey(index);
    if StrLen(key) == 0 { return; };
    if ArrayContains(this.favorites, key) { ArrayRemove(this.favorites, key); } else { ArrayPush(this.favorites, key); };
    let text = "format\tnpv-appearance-favorites-1\n";
    for favorite in this.favorites { text += "favorite\t" + favorite + "\n"; };
    if !NPVFiles.Write("appearance-favorites.txt", text + "end\t1\n") {
      NPVMakerSession.GetInstance().SetStatus(NPVText.T("Favorito nesta sessao. Armazenamento indisponivel para salvar."));
    };
    this.RenderChoices();
  }

  private func AskName() -> Void {
    if IsDefined(this.nameDialog) { return; };
    this.ClosePicker();
    this.nameDialog = this.Surface(320.0, 630.0, 1000.0, 230.0);
    let column = new inkVerticalPanel();
    column.SetMargin(new inkMargin(32.0, 28.0, 0.0, 0.0));
    column.SetChildMargin(new inkMargin(0.0, 0.0, 0.0, 24.0));
    column.SetFitToContent(true);
    column.Reparent(this.nameDialog);
    this.Label(column, NPVText.T("PROJETO NPV"), 48, true, 936.0);
    this.Label(column, NPVText.T("NOME DO PERSONAGEM"), 34, false, 936.0);
    let input = HubTextInput.Create();
    input.SetWidth(936.0);
    input.SetMaxLength(80);
    input.Reparent(column, this.menu);
    input.SetText(NPVMakerSession.GetInstance().projectName);
    this.nameInput = input;
    NPVMakerSession.GetInstance().nameInput = input;
    let actions = this.Row(column);
    this.Button(actions, NPVText.T("SALVAR PROJETO"), n"npvui_save", 580.0);
    this.Button(actions, NPVText.T("FECHAR"), n"npvui_nameclose", 344.0);
    this.Button(column, NPVText.T("ABRIR ULTIMO PROJETO"), n"npvui_load", 936.0);
    this.HideList();
    this.menu.NPVStudioNativeInput(false);
  }
  private func CloseName() -> Void {
    if !IsDefined(this.nameDialog) { return; };
    this.SaveName();
    NPVMakerSession.GetInstance().nameInput = null;
    this.nameInput = null;
    this.root.RemoveChild(this.nameDialog);
    this.nameDialog = null;
    this.RestoreList();
    this.menu.NPVStudioClearFocus();
  }

  public func Tick() -> Void {
    this.ticks += 1;
    // Native confirmation can restore its navigation. Keep one visible set outside that modal.
    let confirming = inkWidgetRef.IsVisible(this.menu.m_backConfirmation);
    this.buttons.SetVisible(!confirming);
    if !confirming { inkWidgetRef.SetVisible(this.menu.m_navigationButtons, false); };
    if this.ticks % 7 == 0 { this.AttachRows(); };
    if !this.IsChoosing() {
      if this.returnTicks > 0 { this.returnTicks -= 1; this.ReturnToRow(); };
      return;
    };
    if !IsDefined(this.selectedRow) { this.ClosePicker("row gone"); return; };
    let fresh = this.selectedRow.NPVChoiceOption();
    let reason = "";
    if !IsDefined(fresh) || !IsDefined(fresh.info) { reason = "option gone";
    } else if NotEquals(fresh.info.name, this.optionName) { reason = "option now " + NameToString(fresh.info.name);
    } else if NotEquals(ToString(fresh.bodyPart), this.bodyPart) { reason = "body part changed";
    } else if !fresh.isActive { reason = "inactive";
    } else if fresh.isCensored { reason = "censored"; };
    if NotEquals(reason, "") {
      this.ClosePicker(reason);
      return;
    };
    this.option = fresh;
    if NotEquals(this.searchInput.GetText(), this.query) {
      this.query = this.searchInput.GetText();
      this.offset = 0;
      this.RenderChoices();
    } else if NotEquals(this.stamp, ToString(this.selectedRow.NPVChoiceIndex()) + ":" + ToString(NPVStudioView.Count(fresh))) {
      this.RenderChoices();
    };
  }

  protected cb func OnButton(widget: wref<inkWidget>) -> Bool {
    let name = NameToString(widget.GetName());
    this.menu.NPVStudioClearFocus();
    if Equals(name, "npvui_project") { this.AskName();
    } else if Equals(name, "npvui_save") { this.Save();
    } else if Equals(name, "npvui_back") { if !this.Back() { this.menu.NPVEditorBack(); };
    } else if Equals(name, "npvui_close") { this.ClosePicker();
    } else if Equals(name, "npvui_nameclose") { this.CloseName();
    } else if Equals(name, "npvui_load") { this.CloseName(); NPVMakerSession.GetInstance().RequestLoad();
    } else if Equals(name, "npvui_create") || Equals(name, "npvui_manage") {
      this.SaveName(); this.CloseName(); this.ClosePicker();
      this.menu.NPVStudioManager(Equals(name, "npvui_create"), false);
    } else if Equals(name, "npvui_previous") { this.ScrollChoices(-1);
    } else if Equals(name, "npvui_next") { this.ScrollChoices(1);
    } else if Equals(name, "npvui_filter") { this.onlyFavorites = !this.onlyFavorites; this.offset = 0; this.RenderChoices();
    } else if StrBeginsWith(name, "npvui_star_") {
      this.ToggleFavorite(StringToInt(StrAfterFirst(name, "npvui_star_"), -1));
    } else if Equals(name, "npvui_compare") {
      let original = this.ResolveChoice(this.originalKey);
      let trial = this.ResolveChoice(this.trialKey);
      if original >= 0 && trial >= 0 {
        this.menu.NPVApplyChoice(this.selectedRow, Cast<Int32>(this.selectedRow.NPVChoiceIndex()) == original ? trial : original);
        this.RenderChoices();
      };
    } else if StrBeginsWith(name, "npvui_choice_") {
      let index = StringToInt(StrAfterFirst(name, "npvui_choice_"), -1);
      if this.menu.NPVCanEdit() && index >= 0 && index < NPVStudioView.Count(this.option) {
        this.trialKey = NPVStudioView.ChoiceKey(this.option, index);
        this.menu.NPVApplyChoice(this.selectedRow, index);
        this.RenderChoices();
      };
    };
    return true;
  }

  private func OptionTitle() -> String {
    let title = GetLocalizedText(this.option.info.localizedName);
    return StrLen(title) > 0 ? title : NameToString(this.option.info.name);
  }
  private func Short(text: String, limit: Int32) -> String {
    return StrLen(text) > limit ? StrLeft(text, limit - 3) + "..." : text;
  }
  public static func Count(option: ref<CharacterCustomizationOption>) -> Int32 {
    if !IsDefined(option) || !IsDefined(option.info) { return 0; };
    let switcher = option.info as gameuiSwitcherInfo;
    if IsDefined(switcher) { return ArraySize(switcher.options); };
    let morph = option.info as gameuiMorphInfo;
    if IsDefined(morph) { return ArraySize(morph.morphNames); };
    let appearance = option.info as gameuiAppearanceInfo;
    return IsDefined(appearance) ? ArraySize(appearance.definitions) : 0;
  }
  public static func ChoiceKey(option: ref<CharacterCustomizationOption>, index: Int32) -> String {
    if index < 0 || index >= NPVStudioView.Count(option) { return ""; };
    let switcher = option.info as gameuiSwitcherInfo;
    if IsDefined(switcher) {
      let key = "";
      for name in switcher.options[index].names {
        key += (StrLen(key) > 0 ? "|" : "") + NameToString(name);
      };
      return key;
    };
    let morph = option.info as gameuiMorphInfo;
    if IsDefined(morph) { return NameToString(morph.morphNames[index].morphName); };
    let appearance = option.info as gameuiAppearanceInfo;
    return IsDefined(appearance) ? NameToString(appearance.definitions[index].name) : "";
  }
  public static func Choice(option: ref<CharacterCustomizationOption>, index: Int32) -> String {
    if index < 0 || index >= NPVStudioView.Count(option) { return ""; };
    let raw = "";
    let switcher = option.info as gameuiSwitcherInfo;
    let morph = option.info as gameuiMorphInfo;
    let appearance = option.info as gameuiAppearanceInfo;
    if IsDefined(switcher) { raw = switcher.options[index].localizedName;
    } else if IsDefined(morph) { raw = morph.morphNames[index].localizedName;
    } else if IsDefined(appearance) { raw = appearance.definitions[index].localizedName; };
    let title = GetLocalizedText(raw);
    if StrLen(title) == 0 { title = NPVStudioView.ChoiceKey(option, index); };
    return StrLen(title) > 0 ? title : "#" + ToString(index + 1);
  }
  private func Surface(y: Float, height: Float, width: Float, right: Float) -> ref<inkCanvas> {
    let canvas = new inkCanvas();
    canvas.SetAnchor(inkEAnchor.TopRight);
    canvas.SetAnchorPoint(new Vector2(1.0, 0.0));
    canvas.SetMargin(new inkMargin(0.0, y, right, 0.0));
    canvas.SetSize(width, height);
    canvas.Reparent(this.root);
    let shade = new inkRectangle();
    shade.SetAnchor(inkEAnchor.Fill);
    shade.SetTintColor(new HDRColor(0.045, 0.009, 0.018, 1.0));
    shade.SetOpacity(0.98);
    shade.SetInteractive(true);
    shade.Reparent(canvas);
    let frame = new inkImage();
    frame.SetAtlasResource(r"base\\gameplay\\gui\\common\\shapes\\atlas_shapes_sync.inkatlas");
    frame.SetTexturePart(n"sorting_fg");
    frame.SetNineSliceScale(true);
    frame.SetNineSliceGrid(new inkMargin(50.0, 30.0, 100.0, 30.0));
    frame.SetAnchor(inkEAnchor.Fill);
    frame.SetTintColor(ThemeColors.Bittersweet());
    frame.Reparent(canvas);
    return canvas;
  }
  private func Row(parent: ref<inkCompoundWidget>) -> ref<inkHorizontalPanel> {
    let row = new inkHorizontalPanel();
    row.SetChildMargin(new inkMargin(0.0, 0.0, 12.0, 0.0));
    row.SetFitToContent(true);
    row.Reparent(parent);
    return row;
  }
  private func Label(parent: ref<inkCompoundWidget>, text: String, size: Int32, strong: Bool, width: Float) -> ref<inkText> {
    let label = new inkText();
    label.SetFontFamily("base\\gameplay\\gui\\fonts\\raj\\raj.inkfontfamily");
    label.SetFontStyle(strong ? n"Semi-Bold" : n"Medium");
    label.SetFontSize(size);
    label.SetTintColor(strong ? ThemeColors.Bittersweet() : ThemeColors.ElectricBlue());
    label.SetWrapping(true, width);
    label.SetFitToContent(true);
    label.SetText(text);
    label.Reparent(parent);
    return label;
  }
  private func Button(parent: ref<inkCompoundWidget>, text: String, name: CName, width: Float) -> ref<SimpleButton> {
    let button = NPVIconButton.Make();
    button.SetName(name);
    button.SetText(text);
    button.SetIcon(NPVIcons.ForAction(name), Equals(name, n"npvui_previous") || Equals(name, n"npvui_next"));
    button.SetWidth(width);
    button.SetFlipped(true);
    button.ToggleAnimations(true);
    button.ToggleSounds(true);
    button.Reparent(parent, this.menu);
    button.GetRootWidget().SetAnchorPoint(new Vector2(0.0, 0.0));
    button.RegisterToCallback(n"OnBtnClick", this, n"OnButton");
    return button;
  }
}

@addField(characterCreationBodyMorphOption)
private let npvChoiceButton: ref<SimpleButton>;
@addField(characterCreationBodyMorphOption)
private let npvChoiceMenu: wref<characterCreationBodyMorphMenu>;

@addMethod(characterCreationBodyMorphOption)
public func NPVAttachPicker(menu: ref<characterCreationBodyMorphMenu>) -> Void {
  if !NPVMakerSession.GetInstance().active { return; };
  let available = this.m_isVisible && NPVStudioView.Count(this.GetSelectorOption()) > 1;
  if IsDefined(this.npvChoiceButton) {
    this.npvChoiceButton.GetRootWidget().SetVisible(available);
    return;
  };
  if !available { return; };
  // If CCUI is installed, its native gallery already owns this exact row.
  if NPVExternalGallery() { return; };
  this.npvChoiceMenu = menu;
  let root = this.GetRootCompoundWidget();
  let left = root.GetWidget(n"hitAreaLeft");
  let right = root.GetWidget(n"hitAreaRight");
  if IsDefined(left) { left.SetWidth(300.0); };
  if IsDefined(right) { right.SetWidth(310.0); };
  let button = NPVIconButton.Make();
  button.SetText(NPVText.T("VER OPCOES"));
  button.SetIcon(n"choices", false);
  button.SetWidth(290.0);
  button.SetFlipped(true);
  button.ToggleSounds(true);
  button.ToggleAnimations(true);
  button.Reparent(root, menu);
  button.GetRootWidget().SetAnchor(inkEAnchor.BottomCenter);
  button.GetRootWidget().SetAnchorPoint(new Vector2(0.5, 1.0));
  button.GetRootWidget().SetMargin(new inkMargin(0.0, 0.0, 0.0, 6.0));
  button.RegisterToCallback(n"OnBtnClick", this, n"NPVOnChoices");
  this.npvChoiceButton = button;
}
@addMethod(characterCreationBodyMorphOption)
protected cb func NPVOnChoices(widget: wref<inkWidget>) -> Bool {
  if this.m_inputDisabled || !this.m_isVisible || !IsDefined(this.npvChoiceMenu) { return false; };
  this.npvChoiceMenu.NPVOpenChoice(this);
  return true;
}

@if(ModuleExists("CPUIImprovements.CharacterCreator"))
public func NPVExternalGallery() -> Bool = true
@if(!ModuleExists("CPUIImprovements.CharacterCreator"))
public func NPVExternalGallery() -> Bool = false

@wrapMethod(characterCreationBodyMorphMenu)
public final func CreateEntry(const option: ref<CharacterCustomizationOption>) -> wref<inkWidget> {
  let widget = wrappedMethod(option);
  if NPVMakerSession.GetInstance().active && IsDefined(widget) {
    let row = widget.GetController() as characterCreationBodyMorphOption;
    if IsDefined(row) { row.NPVAttachPicker(this); };
  };
  return widget;
}
@addMethod(characterCreationBodyMorphMenu)
public func NPVOpenChoice(row: ref<CharacterCreationBodyMorphBaseOption>) -> Void {
  if NPVMakerSession.GetInstance().active && IsDefined(this.npvStudio) { this.npvStudio.OpenChoice(row); };
}
@addMethod(characterCreationBodyMorphMenu)
public func NPVCanEdit() -> Bool {
  return NPVMakerSession.GetInstance().active && Equals(this.m_busySwitchingAppearance, BusySwitchingReason.AVAILABLE) && !this.m_inputDisabled;
}
@addMethod(characterCreationBodyMorphMenu)
public func NPVChoiceCamera(option: ref<CharacterCustomizationOption>) -> Void { this.RequestCameraChange(this.GetSlotName(option)); }
@addMethod(characterCreationBodyMorphMenu)
public func NPVApplyChoice(row: ref<CharacterCreationBodyMorphBaseOption>, index: Int32) -> Void {
  if !this.NPVCanEdit() || !IsDefined(row) { return; };
  let option = row.NPVChoiceOption();
  if !IsDefined(option) || !option.isActive || !option.isEditable || option.isCensored || index < 0 || index >= NPVStudioView.Count(option) { return; };
  if index == Cast<Int32>(row.NPVChoiceIndex()) { return; };
  // Use the same setters and OnSliderChange callback as the native arrows.
  // They update the displayed index immediately and preserve other mods' native callbacks.
  let appearance = option.info as gameuiAppearanceInfo;
  let morph = option.info as gameuiMorphInfo;
  let switcher = option.info as gameuiSwitcherInfo;
  let colorRow = row as characterCreationBodyMorphColorOption;
  let selectorRow = row as characterCreationBodyMorphOption;
  if IsDefined(colorRow) && IsDefined(appearance) {
    // This setter emits the native OnColorChange exactly once.
    colorRow.SetSelectedAppearanceDefinitionColor(appearance, index);
  } else if IsDefined(selectorRow) {
    if IsDefined(appearance) { selectorRow.SetSelectedAppearanceDefinition(appearance, index);
    } else if IsDefined(morph) { selectorRow.SetSelectedMorphName(morph, index);
    } else if IsDefined(switcher) { selectorRow.SetSelectedSwitcherOption(switcher, index); };
  };
  this.PlaySound(n"Button", n"OnPress");
}
@addMethod(characterCreationBodyMorphMenu)
public func NPVStudioNativeInput(enabled: Bool) -> Void {
  if IsDefined(this.m_scrollController) { this.m_scrollController.SetInputDisabled(!enabled); };
}
@addMethod(characterCreationBodyMorphMenu)
public func NPVStudioClearFocus() -> Void { this.RequestSetFocus(null); }
@addMethod(characterCreationBodyMorphMenu)
public func NPVStudioEnsureVisible(widget: wref<inkWidget>) -> Void {
  if IsDefined(this.m_scrollController) && IsDefined(widget) { this.m_scrollController.EnsureVisible(widget); };
}
@addMethod(characterCreationBodyMorphMenu)
public func NPVEditorBack() -> Void { if this.NPVCanEdit() { this.PriorMenu(); }; }
@addMethod(characterCreationBodyMorphMenu)
public func NPVStudioManager(create: Bool, report: Bool) -> Void {
  this.OnNPVManageClicked(null);
  if IsDefined(this.npvManager) {
    if create { this.npvManager.ShowCreate(); };
    if report { this.npvManager.ShowReport(); };
  };
}

@addMethod(characterCreationBodyMorphMenu)
protected cb func NPVOnChoiceWheel(evt: ref<inkPointerEvent>) -> Bool {
  if !NPVMakerSession.GetInstance().active || !IsDefined(this.npvStudio) { return false; };
  return this.npvStudio.HandleChoiceWheel(evt);
}

@addMethod(characterCreationBodyMorphMenu)
public func NPVSectionHeading() -> wref<inkWidget> {
  return this.NPVFindChild(this.GetRootCompoundWidget(), n"GroupListArea", n"list_header");
}

// Shared access without substituting the native option identity or its index.
@addMethod(CharacterCreationBodyMorphBaseOption)
public func NPVChoiceOption() -> wref<CharacterCustomizationOption> {
  let selector = this as characterCreationBodyMorphOption;
  if IsDefined(selector) { return selector.GetSelectorOption(); };
  let color = this as characterCreationBodyMorphColorOption;
  if IsDefined(color) { return color.GetColorPickerOption(); };
  return null;
}
@addMethod(CharacterCreationBodyMorphBaseOption)
public func NPVChoiceIndex() -> Uint32 {
  let selector = this as characterCreationBodyMorphOption;
  if IsDefined(selector) { return selector.GetSelectorIndex(); };
  let color = this as characterCreationBodyMorphColorOption;
  return IsDefined(color) ? color.GetColorIndex() : 0u;
}

@addMethod(characterCreationBodyMorphColorOption)
public func NPVResetThumbnailTrigger() -> Void {
  let button = inkWidgetRef.GetController(this.m_colorPickerBtn) as characterCreationBodyMorphOptionColorPickerButton;
  if IsDefined(button) { button.Trigger(false); };
}

@wrapMethod(characterCreationBodyMorphMenu)
protected cb func OnColorPickerTriggered(widget: wref<inkWidget>) -> Bool {
  // Use the existing gallery button for eyes/colors; no extra overlapping control.
  // Normal character creation, mirrors and external galleries keep their path.
  if !NPVMakerSession.GetInstance().active || NPVExternalGallery() || !IsDefined(this.npvStudio) || !IsDefined(widget) {
    return wrappedMethod(widget);
  };
  let row = widget.GetController() as characterCreationBodyMorphColorOption;
  if !IsDefined(row) { return wrappedMethod(widget); };
  // A color the NPV picker cannot keep open (inactive, or closed by itself right after opening) uses the game's
  // own color picker, with the button state untouched.
  if !this.npvStudio.CanOpen(row) { return wrappedMethod(widget); };
  let triggered = row.IsColorPickerTriggered();
  row.NPVResetThumbnailTrigger();
  if triggered && this.NPVCanEdit() { this.npvStudio.OpenChoice(row); };
  return true;
}
