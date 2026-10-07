"""Head options from the origin the editor puppet shows (0.4.16 DEV).

The saved option names the .app the editor option points to. A CCXL pack can add
choices to a vanilla option whose appearances live in the pack's own .app: the
project keeps the vanilla .app and the old path does not find the choice there.
MEDIDO EM 28/09/2026 ("mariko 3.0", docs/HEAD-MAPA.md): the teeth option points to
ht_000__basehead.app, the choice pwa_vamp2teeth is an appearance of the pack's
.app, and the puppet shows the teeth component with that .app and appearance as
origin. The old path stopped the import (NPVM-APPEAR-002).

Rule: an active Head option whose choice the puppet shows, LOADED, coming only
from one other .app and one appearance, that no other option claims, and that
its own .app does not also show, is read from that observed origin. Anything
else stays on the old path. Pieces the puppet does not record (face rig,
animations) and the face sliders keep coming from the project.
"""
from __future__ import annotations
from runtime_body import manifest, _norm, _chooses

HEAD_PART = "Head"


def _claims(option: dict, app: str, appearance: str) -> bool:
    if not option.get("active") or option.get("kind") != "appearance":
        return False
    return _norm(option.get("resource_path")) == app or (
        option.get("selected_name") not in ("", "None", None) and _chooses(option, appearance))


def resolve(project: dict, project_options: list[dict], options: list[dict], redirects: dict,
            definition) -> tuple[list[dict], list[dict]]:
    """Options to convert, with observed origins applied, and one decision per Head option.

    `definition(app, appearance)` returns the component names of that appearance
    as the converter reads it (patches included) or raises when it cannot be read.
    """
    components, reason = manifest(project)
    if components is None:
        return options, []
    loaded = [c for c in components if c["state"] == "LOADED" and c.get("owner_app")]
    result, decisions = [], []
    for option in options:
        if option.get("body_part") != HEAD_PART:
            result.append(option)
            continue
        own = {_norm(option["resource_path"]), _norm(redirects.get(option["resource_path"]))} - {""}
        chosen = [c for c in loaded if _chooses(option, c.get("owner_appearance") or "")]
        record = dict(option=option["name"], choice=option["selected_name"], resource=option["resource_path"])
        others = [c for c in chosen if _norm(c["owner_app"]) not in own]
        if len(others) < len(chosen) or not chosen:
            # Its own .app shows the choice too (the second head copy of the
            # preview is one of these): the old path already matches the editor.
            record["decision"] = "own_app" if chosen else "no_evidence"
            decisions.append(record)
            result.append(option)
            continue
        apps = sorted({_norm(c["owner_app"]) for c in others})
        appearances = sorted({c["owner_appearance"] for c in others})
        record["observed"] = [dict(name=c["name"], owner_app=c["owner_app"], owner_appearance=c["owner_appearance"],
                                   field=c["field"], path=c.get("path"), hash=c.get("hash"),
                                   mesh_appearance=c.get("mesh_appearance")) for c in others]
        rivals = [o["name"] for o in project_options if o["name"] != option["name"]
                  and any(_claims(o, app, appearance) for app in apps for appearance in appearances)]
        if len(apps) > 1 or len(appearances) > 1 or rivals:
            record.update(decision="ambiguous", apps=apps, appearances=appearances, rivals=rivals)
            decisions.append(record)
            result.append(option)
            continue
        app, appearance = others[0]["owner_app"], appearances[0]
        try:
            names = set(definition(app, appearance))
        except (ValueError, KeyError, TypeError) as error:
            record.update(decision="no_definition", error=type(error).__name__ + ": " + str(error)[:300])
            decisions.append(record)
            result.append(option)
            continue
        absent = sorted({c["name"] for c in others} - names)
        if absent:
            record.update(decision="no_definition", error="componentes ausentes da aparencia: " + ", ".join(absent))
            decisions.append(record)
            result.append(option)
            continue
        record.update(decision="runtime_origin", app=app, appearance=appearance)
        decisions.append(record)
        result.append(dict(option, resource_path=app, selected_name=appearance,
                           runtime_origin=dict(resource=option["resource_path"], choice=option["selected_name"]),
                           runtime_components=record["observed"]))
    return result, decisions
