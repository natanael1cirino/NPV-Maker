// Preset shapes of NPV pieces that come from mods (BUGS item 67c, author decision 03/10/2026). The NPV keeps those
// pieces as morphtarget components on the mod's own files, and the conversion writes the editor's shape choices to a
// TweakXL flat NPVMaker.morphs_<hash of the entity file> (tools/runtime_import.morph_flat), as target, region pairs:
// one for character.ent and, since BUGS 82, one for the photo mode puppet photomode.ent.
// MEDIDO EM 03/10/2026 (sondas em jogo): Codeware Entity.ApplyMorphTarget finds the entMorphTargetManagerComponent
// of the entity and the mod pieces take the shapes. The weights are not saved by the game: they are applied when the
// entity is attached, and a call is repeated while the appearance is still being built (false until the manager exists).
// BUGS 81/82 (05/10/2026, author in game, probe 80b): the Thai (EKT head) is right only with weight 1; the "teste 3"
// (VirgilHead head) is right with weight 0. Package 35 applied nothing and lost the Thai; this file applies weight 1
// again and the VirgilHead case stays open.
// BUGS 80 (05/10/2026, probes 80/80b): after photo mode the pieces lost their shapes; applying weight 1 again changed
// nothing on screen (logs of packages 33 and 34), while going to 0 and then to 1 brought them back. A refresh goes
// through 0. Inside photo mode the steps follow a UI animation of the photo mode screen; out of it, the DelaySystem.

public class NPVMakerMorphStep extends DelayCallback {
  public let entity: wref<Entity>;
  public let morphs: array<CName>;
  public let value: Float;
  public let tries: Int32;

  public func Call() -> Void {
    this.Run();
  }

  public func Run() -> Bool {
    let entity: ref<Entity> = this.entity;
    if !IsDefined(entity) {
      return false;
    }
    let applied: Bool = true;
    let i: Int32 = 0;
    while i + 1 < ArraySize(this.morphs) {
      if !entity.ApplyMorphTarget(this.morphs[i], this.morphs[i + 1], this.value) {
        applied = false;
      }
      i += 2;
    }
    if !applied && this.tries > 0 {
      let next: ref<NPVMakerMorphStep> = new NPVMakerMorphStep();
      next.entity = entity;
      next.morphs = this.morphs;
      next.value = this.value;
      next.tries = this.tries - 1;
      GameInstance.GetDelaySystem(GetGameInstance()).DelayCallback(next, 1.0, false);
    }
    return applied;
  }
}

public static func NPVMakerMorphList(entity: ref<Entity>) -> array<CName> {
  let hash: Uint64 = ResRef.GetHash(entity.GetTemplatePath());
  return TweakDBInterface.GetCNameArray(TDBID.Create("NPVMaker.morphs_" + ToString(hash)));
}

public static func NPVMakerMorphSchedule(entity: ref<Entity>, morphs: array<CName>, delay: Float, value: Float) -> Void {
  let step: ref<NPVMakerMorphStep> = new NPVMakerMorphStep();
  step.entity = entity;
  step.morphs = morphs;
  step.value = value;
  step.tries = 10;
  GameInstance.GetDelaySystem(GetGameInstance()).DelayCallback(step, delay, false);
}

public static func NPVMakerMorphSet(entity: ref<Entity>, value: Float) -> Bool {
  let step: ref<NPVMakerMorphStep> = new NPVMakerMorphStep();
  step.entity = entity;
  step.morphs = NPVMakerMorphList(entity);
  step.value = value;
  step.tries = 0;
  return step.Run();
}

@wrapMethod(NPCPuppet)
protected cb func OnGameAttached() -> Bool {
  let result: Bool = wrappedMethod();
  let morphs: array<CName> = NPVMakerMorphList(this);
  if ArraySize(morphs) > 1 {
    NPVMakerMorphSchedule(this, morphs, 0.5, 1.0);
    NPVMakerMorphSchedule(this, morphs, 5.0, 1.0);
    NPVMakerMorphWatch.Get().Remember(this);
  }
  return result;
}

// Every NPV entity seen this session: the NPCs of the world and the photo mode puppets (Entity/AfterAttach, which
// also reaches entities that are not NPCs).
public class NPVMakerMorphWatch extends ScriptableService {
  private let ids: array<EntityID>;

  public static func Get() -> ref<NPVMakerMorphWatch> {
    return GameInstance.GetScriptableServiceContainer().GetService(n"NPVMakerMorphWatch") as NPVMakerMorphWatch;
  }

  private cb func OnLoad() {
    GameInstance.GetCallbackSystem().RegisterCallback(n"Entity/AfterAttach", this, n"OnEntityAttached");
  }

  private cb func OnEntityAttached(event: ref<EntityLifecycleEvent>) {
    let entity: ref<Entity> = event.GetEntity();
    if !IsDefined(entity) {
      return;
    }
    let morphs: array<CName> = NPVMakerMorphList(entity);
    if ArraySize(morphs) > 1 {
      this.Remember(entity);
      NPVMakerMorphSet(entity, 1.0);
    }
  }

  public func Remember(entity: ref<Entity>) -> Void {
    let id: EntityID = entity.GetEntityID();
    if !ArrayContains(this.ids, id) {
      ArrayPush(this.ids, id);
    }
  }

  public func Present() -> array<wref<Entity>> {
    let kept: array<EntityID>;
    let found: array<wref<Entity>>;
    for id in this.ids {
      let entity: ref<Entity> = GameInstance.FindEntityByID(GetGameInstance(), id);
      if IsDefined(entity) {
        ArrayPush(kept, id);
        ArrayPush(found, entity);
      }
    }
    this.ids = kept;
    return found;
  }

  public func SetAll(value: Float) -> Int32 {
    let took: Int32 = 0;
    for entity in this.Present() {
      if NPVMakerMorphSet(entity, value) {
        took += 1;
      }
    }
    return took;
  }

  public func RefreshAfterPhotoMode() -> Void {
    let found: array<wref<Entity>> = this.Present();
    ModLog(n"NPVMaker", "morphs: photo mode closed, refreshing " + ToString(ArraySize(found)) + " NPVs through 0");
    for entity in found {
      let morphs: array<CName> = NPVMakerMorphList(entity);
      NPVMakerMorphSchedule(entity, morphs, 0.5, 0.0);
      NPVMakerMorphSchedule(entity, morphs, 0.7, 1.0);
      NPVMakerMorphSchedule(entity, morphs, 2.0, 0.0);
      NPVMakerMorphSchedule(entity, morphs, 2.2, 1.0);
    }
  }
}

// Inside photo mode: the first two steps take every NPV to 0 and back to 1; every later step applies 1 again, which
// reaches the puppets the photo mode spawns. It runs on the photo mode screen and stops with it.
public class NPVMakerMorphPulse extends IScriptable {
  public let widget: wref<inkWidget>;
  public let proxy: ref<inkAnimProxy>;
  public let step: Int32;

  public static func Start(widget: wref<inkWidget>) -> ref<NPVMakerMorphPulse> {
    let pulse = new NPVMakerMorphPulse();
    pulse.widget = widget;
    ModLog(n"NPVMaker", "morphs: photo mode open, " + ToString(NPVMakerMorphWatch.Get().SetAll(1.0)) + " NPVs");
    pulse.Next();
    return pulse;
  }

  private func Next() -> Void {
    if !IsDefined(this.widget) {
      return;
    }
    let def = new inkAnimDef();
    let wait = new inkAnimTransparency();
    wait.SetStartTransparency(this.widget.GetOpacity());
    wait.SetEndTransparency(this.widget.GetOpacity());
    wait.SetDuration(0.25);
    def.AddInterpolator(wait);
    this.proxy = this.widget.PlayAnimation(def);
    this.proxy.RegisterToCallback(inkanimEventType.OnFinish, this, n"OnStep");
  }

  protected cb func OnStep(proxy: ref<inkAnimProxy>) -> Bool {
    this.step += 1;
    let value: Float = 1.0;
    if this.step == 1 {
      value = 0.0;
    }
    NPVMakerMorphWatch.Get().SetAll(value);
    this.Next();
    return true;
  }
}

@addField(gameuiPhotoModeMenuController)
private let npvMorphPulse: ref<NPVMakerMorphPulse>;

@wrapMethod(gameuiPhotoModeMenuController)
protected cb func OnShow(reversedUI: Bool) -> Bool {
  let result: Bool = wrappedMethod(reversedUI);
  this.npvMorphPulse = NPVMakerMorphPulse.Start(this.GetRootWidget());
  return result;
}

@wrapMethod(gameuiPhotoModeMenuController)
protected cb func OnUninitialize() -> Bool {
  let result: Bool = wrappedMethod();
  NPVMakerMorphWatch.Get().RefreshAfterPhotoMode();
  return result;
}
