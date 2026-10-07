import Codeware.UI.*

// Original NPV icon family, rendered from the vector source in src/ui/npv_icons.svg.
public class NPVIconButton extends NPVMakerCompactButton {
  private let glyph: ref<inkImage>;
  private let favorite: Bool;
  private let favoriteControl: Bool;
  private let hint: wref<inkText>;
  private let hintText: String;
  private let previousHint: String;
  protected func CreateWidgets() {
    super.CreateWidgets();
    this.glyph = new inkImage();
    this.glyph.SetAtlasResource(r"npv_maker\\ui\\npv_icons.inkatlas");
    this.glyph.SetSize(36.0, 36.0);
    this.glyph.SetAnchor(inkEAnchor.CenterLeft);
    this.glyph.SetAnchorPoint(new Vector2(0.0, 0.5));
    this.glyph.SetMargin(new inkMargin(16.0, 0.0, 0.0, 0.0));
    this.glyph.SetInteractive(false);
    this.glyph.SetTintColor(ThemeColors.ElectricBlue());
    this.glyph.SetVisible(false);
    this.glyph.Reparent(this.m_root);
  }
  public func SetIcon(part: CName, onlyIcon: Bool) -> Void {
    this.glyph.SetTexturePart(part);
    this.glyph.SetVisible(NotEquals(part, n""));
    if Equals(part, n"") { return; };
    this.m_label.SetVisible(!onlyIcon);
    if onlyIcon {
      this.glyph.SetSize(46.0, 46.0);
      this.glyph.SetAnchor(inkEAnchor.Centered);
      this.glyph.SetAnchorPoint(new Vector2(0.5, 0.5));
      this.glyph.SetMargin(new inkMargin(0.0, 0.0, 0.0, 0.0));
    } else {
      this.m_label.SetMargin(new inkMargin(56.0, 0.0, 12.0, 0.0));
    };
  }
  public func SetFavorite(value: Bool, hint: wref<inkText>) -> Void {
    this.favoriteControl = true;
    this.favorite = value;
    this.hint = hint;
    this.hintText = NPVText.T(value ? "REMOVER FAVORITO" : "ADICIONAR AOS FAVORITOS");
    this.SetIcon(value ? n"star_filled" : n"star_outline", true);
    this.UpdateGlyph();
  }
  protected func ApplyHoveredState() {
    super.ApplyHoveredState();
    this.UpdateGlyph();
    if IsDefined(this.hint) {
      if this.m_isHovered && !this.m_isDisabled {
        this.previousHint = this.hint.GetText();
        this.hint.SetText(this.hintText);
      } else if StrLen(this.previousHint) > 0 {
        this.hint.SetText(this.previousHint);
        this.previousHint = "";
      };
    };
  }
  private func UpdateGlyph() -> Void {
    if !IsDefined(this.glyph) { return; };
    let gold = new HDRColor(1.0, 0.78, 0.24, 1.0);
    this.glyph.SetTintColor(this.favorite ? gold : (this.m_isHovered || !this.favoriteControl ? ThemeColors.ElectricBlue() : ThemeColors.Bittersweet()));
    this.glyph.SetScale(this.m_isHovered ? new Vector2(1.10, 1.10) : new Vector2(1.0, 1.0));
  }
  public static func Make() -> ref<NPVIconButton> {
    let button = new NPVIconButton();
    button.CreateInstance();
    return button;
  }
}

public class NPVIcons extends IScriptable {
  public static func Add(parent: ref<inkCompoundWidget>, part: CName, size: Float) -> ref<inkImage> {
    let icon = new inkImage();
    icon.SetAtlasResource(r"npv_maker\\ui\\npv_icons.inkatlas");
    icon.SetTexturePart(part);
    icon.SetSize(size, size);
    // Stack panels stretch children across their cross axis by default.
    // Keep atlas glyphs square even when a sibling label is much wider.
    icon.SetHAlign(inkEHorizontalAlign.Left);
    icon.SetVAlign(inkEVerticalAlign.Top);
    icon.SetFitToContent(false);
    icon.SetInteractive(false);
    icon.SetTintColor(ThemeColors.ElectricBlue());
    icon.Reparent(parent);
    return icon;
  }
  public static func ForAction(name: CName) -> CName {
    let action = NameToString(name);
    if StrContains(action, "nameclose") || StrContains(action, "close") { return n"close"; };
    if StrContains(action, "clothes") { return n"outfit"; };
    if StrContains(action, "compare") { return n"compare"; };
    if StrContains(action, "previous") { return n"up"; };
    if StrContains(action, "next") { return n"down"; };
    if StrContains(action, "back") { return n"back"; };
    if StrContains(action, "filter") { return n"choices"; };
    if StrContains(action, "save") { return n"save"; };
    if StrContains(action, "project") || Equals(action, "npvui_load") { return n"project"; };
    if StrContains(action, "manage") || Equals(action, "npvm_tab_wk") { return n"manage"; };
    if StrContains(action, "create") || Equals(action, "npvm_tab_pkgs") { return n"convert"; };
    if Equals(action, "npvm_tab_npvs") { return n"npv"; };
    return n"";
  }
}
