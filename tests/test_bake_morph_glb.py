from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bake_morph_glb import bake, unpack_glb


def fixture() -> bytes:
    chunks = [
        ("POSITION", "<fff", (1.0, 2.0, 3.0)),
        ("NORMAL", "<fff", (0.0, 0.0, 1.0)),
        ("TANGENT", "<ffff", (1.0, 0.0, 0.0, -1.0)),
        ("JOINTS_1", "<4H", (4, 5, 6, 7)),
        ("WEIGHTS_1", "<4f", (0.1, 0.2, 0.3, 0.4)),
        ("MORPH_POSITION", "<fff", (0.5, -1.0, 0.25)),
        ("MORPH_NORMAL", "<fff", (0.0, 1.0, 0.0)),
        ("MORPH_TANGENT", "<fff", (0.0, 1.0, 0.0)),
    ]
    binary = b""
    views = []
    accessors = []
    for name, fmt, values in chunks:
        payload = struct.pack(fmt, *values)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(payload)})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5123 if name == "JOINTS_1" else 5126,
                          "count": 1, "type": "VEC4" if name in ("TANGENT", "JOINTS_1", "WEIGHTS_1") else "VEC3"})
        binary += payload
    doc = {
        "asset": {"version": "2.0"}, "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views, "accessors": accessors,
        "meshes": [{"extras": {"targetNames": ["h012_nose"]}, "primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1, "TANGENT": 2,
                           "JOINTS_1": 3, "WEIGHTS_1": 4},
            "targets": [{"POSITION": 5, "NORMAL": 6, "TANGENT": 7}],
        }]}],
    }
    data = json.dumps(doc).encode()
    data += b" " * ((-len(data)) % 4)
    binary += b"\0" * ((-len(binary)) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(data) + 8 + len(binary))
            + struct.pack("<I4s", len(data), b"JSON") + data
            + struct.pack("<I4s", len(binary), b"BIN\0") + binary)


class MorphBakeTests(unittest.TestCase):
    def test_bakes_shape_and_keeps_secondary_joint_weights(self):
        source, before = unpack_glb(fixture())
        result = bake(fixture(), "h012_nose")
        doc, after = unpack_glb(result)
        primitive = doc["meshes"][0]["primitives"][0]
        self.assertNotIn("targets", primitive)
        self.assertIn("JOINTS_1", primitive["attributes"])
        self.assertEqual(struct.unpack_from("<fff", after, 0), (1.5, 1.0, 3.25))
        self.assertEqual(after[40:64], before[40:64])  # JOINTS_1 and WEIGHTS_1 bytes
        self.assertEqual(struct.unpack_from("<f", after, 36)[0], -1.0)  # tangent sign

    def test_missing_shape_fails(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            bake(fixture(), "h999")

    def test_morph_list_rejects_ambiguous_duplicate(self):
        with self.assertRaisesRegex(ValueError, "distinct"):
            bake(fixture(), ["h012_nose", "h012_nose"])


if __name__ == "__main__":
    unittest.main()
