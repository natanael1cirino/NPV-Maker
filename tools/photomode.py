"""Photo mode for an NPV (author request 02/10/2026: "[ ] PHOTO MODE", the NPV shows up in photo mode).

Measured on 02/10/2026 before writing this:
- Published NPVs (Joi, Canon FemV, Raven, Sina) use the same three pieces: a photo mode .ent copied from a base game
  photo mode character with its appearance list pointing to the NPV's .app; a TweakXL record
  `Character.<x>_Photomode_Puppet` (persistentName PhotomodePuppet, displayName, attachmentSlots, a PhotoModeSticker
  icon); and an ArchiveXL .xl that adds the .ent to the scope `photomode_wa.ent` (ArchiveXL Bundle/PhotoModeScope.xl
  lists every base game photo mode character there; male ones are in `photomode_ma.ent`).
- The NPV .app binds its meshes to face_rig, hair_dangle and jaw, which the .app itself carries, and to root, which
  judy_photomode.ent has, so the NPV .app is used as it is (HIPOTESE until seen in game).
- The base game has no generic photo mode icon (photomode_npc_icons_atlas*.inkatlas only has named characters), so
  the NPV gets its own 256x256 icon: a plain PNG written here and turned into .xbm by WolvenKit.

The .ent and the icon always go in the NPV archive (small, inert); the record and the scope are written by the install
only when the photo mode integration is chosen (adapters.py).
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

TEMPLATES = {
    "female": "base\\characters\\entities\\player\\photo_mode\\judy_alvarez\\judy_photomode.ent",
    "male": "base\\characters\\entities\\player\\photo_mode\\goro_takemura\\goro_photomode.ent",
}
SCOPES = {"female": "photomode_wa.ent", "male": "photomode_ma.ent"}
ICON_SIZE = 256
ICON_PART = "npv_icon"

# 5x7 capital letters and digits for the icon's initial.
FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10011", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "?": ["01110", "10001", "00001", "00110", "00100", "00000", "00100"],
}


def initial(name: str) -> str:
    for char in (name or "").upper():
        if char in FONT and char != "?":
            return char
    return "?"


def icon_png(name: str) -> bytes:
    """A 256x256 RGBA PNG: dark panel, red frame, the name's initial (no image library in the converter)."""
    size = ICON_SIZE
    glyph = FONT[initial(name)]
    scale = 22
    width, height = 5 * scale, 7 * scale
    left, top = (size - width) // 2, (size - height) // 2 - 6
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            shade = 18 + (y * 30) // size
            r, g, b = shade, shade // 2, shade + 10
            if x < 6 or y < 6 or x >= size - 6 or y >= size - 6:
                r, g, b = 220, 40, 50
            gx, gy = (x - left) // scale, (y - top) // scale
            if 0 <= gx < 5 and 0 <= gy < 7 and x >= left and y >= top and glyph[gy][gx] == "1":
                r, g, b = 90, 230, 240
            row += bytes((r, g, b, 255))
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def cname(value: str) -> dict:
    return {"$type": "CName", "$storage": "string", "$value": value}


def ref(path: str) -> dict:
    return {"DepotPath": {"$type": "ResourcePath", "$storage": "string", "$value": path}, "Flags": "Soft"}


def _facial_components(node, out):
    """Animated components that carry a facial setup (the face rig), wherever the document nests them."""
    if isinstance(node, dict):
        setup = ((node.get("facialSetup") or {}).get("DepotPath") or {}).get("$value")
        if node.get("$type") == "entAnimatedComponent" and setup not in (None, "", "0"):
            out.append(node)
        for value in node.values():
            _facial_components(value, out)
    elif isinstance(node, list):
        for value in node:
            _facial_components(value, out)
    return out


def template_app_path(template_doc: dict) -> str:
    appearances = template_doc["Data"]["RootChunk"].get("appearances") or []
    return ((appearances[0].get("appearanceResource") or {}).get("DepotPath") or {}).get("$value", "") if appearances else ""


def template_face_graph(template_app_doc: dict) -> dict | None:
    """The facial animation graph of the photo mode template's face rig.

    MEDIDO EM 03/10/2026 (AFT no modo foto, autor: o NPV nao faz expressao, o V faz): the NPV face_rig keeps the
    graph of the character editor, pma_paperdoll_sermo.animgraph; goro_photomode_appearance.app gives its face_rig
    player_man_photomode_sermo.animgraph, the graph photo mode drives the expressions through.
    """
    faces = _facial_components(template_app_doc, [])
    graphs = [f.get("graph") for f in faces if ((f.get("graph") or {}).get("DepotPath") or {}).get("$value")]
    return graphs[0] if graphs else None


def template_face_animations(template_app_doc: dict) -> dict | None:
    """The animation sets of the photo mode template's face rig.

    MEDIDO EM 03/10/2026 (pacote 18 no jogo: grafo certo e ainda sem expressao): goro_photomode_appearance.app and
    judy_photomode.app give their face_rig photomode_male_facial.anims / photomode_female_facial.anims (the photo
    mode expressions; the Sina NPV carries the female one in an extension); the NPV face_rig had no animation set.
    """
    for face in _facial_components(template_app_doc, []):
        animations = face.get("animations") or {}
        if any(animations.get(group) for group in ("gameplay", "cinematics")):
            return animations
    return None


def face_graph_app(app_doc: dict, graph: dict, animations: dict | None = None) -> tuple[dict, int]:
    """A copy of the NPV .app whose face rig uses `graph` (and `animations`); returns it and how many changed."""
    import copy
    doc = copy.deepcopy(app_doc)
    faces = _facial_components(doc, [])
    for face in faces:
        face["graph"] = copy.deepcopy(graph)
        if animations is not None:
            face["animations"] = copy.deepcopy(animations)
    return doc, len(faces)


def entity(template_doc: dict, app_path: str) -> dict:
    """The photo mode .ent: the base game template with the NPV appearance as its only appearance."""
    root = template_doc["Data"]["RootChunk"]
    root["appearances"] = [{"$type": "entTemplateAppearance", "name": cname("default"),
                           "appearanceName": cname("default"), "appearanceResource": ref(app_path)}]
    root["defaultAppearance"] = cname("default")
    return template_doc


def atlas(atlas_template: dict, texture_path: str) -> dict:
    """An inkatlas with one texture and one part covering all of it (the vanilla atlas as the document shape)."""
    root = atlas_template["Data"]["RootChunk"]
    slots = root["slots"]["Elements"]
    slots[0]["texture"] = ref(texture_path)
    slots[0]["parts"] = [{"$type": "inkTextureAtlasMapper",
                          "clippingRectInPixels": {"$type": "Rect", "bottom": 0, "left": 0, "right": 0, "top": 0},
                          "clippingRectInUVCoords": {"$type": "RectF", "Bottom": 1.0, "Left": 0.0, "Right": 1.0,
                                                     "Top": 0.0},
                          "partName": cname(ICON_PART)}]
    for slot in slots[1:]:
        slot["parts"] = []
    return atlas_template


ATLAS_TEMPLATE = "base\\gameplay\\gui\\fullscreen\\photo_mode\\npcs\\photomode_npc_icons_atlas.inkatlas"


def record_yaml(token: str, entity_path: str, name_key: str, atlas_path: str) -> str:
    record = "Character.NPVMaker_" + token + "_Photomode_Puppet"
    return (f"{record}:\n"
            f"  $type: Character\n"
            f"  entityTemplatePath: \"{entity_path.replace(chr(92), chr(92) * 2)}\"\n"
            f"  displayName: \"{name_key}\"\n"
            f"  persistentName: PhotomodePuppet\n"
            f"  attachmentSlots: [ AttachmentSlots.WeaponRight, AttachmentSlots.WeaponLeft ]\n"
            f"\n"
            f"{record}.icon:\n"
            f"  $type: PhotoModeSticker\n"
            f"  atlasName: \"{atlas_path.replace(chr(92), chr(92) * 2)}\"\n"
            f"  imagePartName: {ICON_PART}\n")


def scope_xl(body: str, entity_path: str) -> str:
    return ("resource:\n"
            "  scope:\n"
            f"    {SCOPES[body]}:\n"
            f"      - {entity_path}\n")
