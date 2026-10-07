"""Bake one Cyberpunk morph target into a WolvenKit-exported GLB mesh.

Only the selected vertex deltas are changed; original joints, weights, UVs,
materials and skin metadata are preserved. This is a local NPC build helper.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path


def unpack_glb(raw: bytes) -> tuple[dict, bytearray]:
    if len(raw) < 28 or struct.unpack_from("<4sI", raw) != (b"glTF", 2):
        raise ValueError("Expected a GLB 2.0 file")
    if struct.unpack_from("<I", raw, 8)[0] != len(raw):
        raise ValueError("Invalid GLB length")
    chunks = []
    position = 12
    while position < len(raw):
        size, kind = struct.unpack_from("<I4s", raw, position)
        position += 8
        chunks.append((kind, raw[position:position + size]))
        position += size
    if position != len(raw) or len(chunks) != 2 or chunks[0][0] != b"JSON" or chunks[1][0] != b"BIN\x00":
        raise ValueError("Expected a JSON and a BIN chunk")
    doc = json.loads(chunks[0][1].decode("utf-8"))
    if len(doc.get("buffers", [])) != 1:
        raise ValueError("Only one embedded GLB buffer is supported")
    return doc, bytearray(chunks[1][1])


def accessor(doc: dict, binary: bytearray, index: int, components: int) -> tuple[int, int, int]:
    value = doc["accessors"][index]
    if value.get("componentType") != 5126 or value.get("type") != f"VEC{components}" or "sparse" in value:
        raise ValueError("Unsupported morph accessor layout")
    view = doc["bufferViews"][value["bufferView"]]
    if view.get("buffer") != 0:
        raise ValueError("Accessor uses another buffer")
    stride = view.get("byteStride", components * 4)
    if stride < components * 4 or stride % 4:
        raise ValueError("Invalid float accessor stride")
    start = view.get("byteOffset", 0) + value.get("byteOffset", 0)
    count = value["count"]
    if start < 0 or start + (count - 1) * stride + components * 4 > len(binary):
        raise ValueError("Accessor is outside the BIN chunk")
    return start, stride, count


def bake_attribute(doc: dict, binary: bytearray, base_index: int, delta_index: int,
                   base_components: int, normalise: bool) -> tuple[list[float], list[float]]:
    base_start, base_stride, count = accessor(doc, binary, base_index, base_components)
    delta_start, delta_stride, delta_count = accessor(doc, binary, delta_index, 3)
    if count != delta_count:
        raise ValueError("Morph and base vertex counts differ")
    minima = [math.inf] * 3
    maxima = [-math.inf] * 3
    for i in range(count):
        base_at = base_start + i * base_stride
        delta_at = delta_start + i * delta_stride
        base = list(struct.unpack_from("<" + "f" * base_components, binary, base_at))
        delta = struct.unpack_from("<fff", binary, delta_at)
        for axis in range(3):
            base[axis] += delta[axis]
        if normalise:
            length = math.sqrt(sum(base[axis] ** 2 for axis in range(3)))
            if length:
                for axis in range(3):
                    base[axis] /= length
        if not all(math.isfinite(number) for number in base):
            raise ValueError("Non-finite baked vertex")
        for axis in range(3):
            minima[axis] = min(minima[axis], base[axis])
            maxima[axis] = max(maxima[axis], base[axis])
        struct.pack_into("<" + "f" * base_components, binary, base_at, *base)
    return minima, maxima


def bake(raw: bytes, shape: str | list[str]) -> bytes:
    doc, binary = unpack_glb(raw)
    shapes = [shape] if isinstance(shape, str) else shape
    if not shapes or len(set(shapes)) != len(shapes):
        raise ValueError("Provide distinct morph names")
    found = set()
    for mesh in doc.get("meshes", []):
        names = mesh.get("extras", {}).get("targetNames", [])
        present = [name for name in shapes if name in names]
        if not present:
            continue
        for primitive in mesh.get("primitives", []):
            targets = primitive.get("targets", [])
            attrs = primitive["attributes"]
            for name in present:
                target_index = names.index(name)
                if target_index >= len(targets) or "POSITION" not in targets[target_index]:
                    raise ValueError(f"Morph {name!r} lacks POSITION deltas")
                target = targets[target_index]
                bounds = bake_attribute(doc, binary, attrs["POSITION"], target["POSITION"], 3, False)
                doc["accessors"][attrs["POSITION"]]["min"] = bounds[0]
                doc["accessors"][attrs["POSITION"]]["max"] = bounds[1]
                for key, components in (("NORMAL", 3), ("TANGENT", 4)):
                    if key in attrs and key in target:
                        bake_attribute(doc, binary, attrs[key], target[key], components, True)
                found.add(name)
            primitive.pop("targets", None)
        mesh.pop("weights", None)
        mesh.get("extras", {}).pop("targetNames", None)
    missing = set(shapes) - found
    if missing:
        raise ValueError(f"Morphs not found: {', '.join(sorted(missing))}")
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((-len(payload)) % 4)
    # Binary length has not changed: preserving every non-morph attribute byte.
    binary += b"\0" * ((-len(binary)) % 4)
    total = 12 + 8 + len(payload) + 8 + len(binary)
    return (struct.pack("<4sII", b"glTF", 2, total)
            + struct.pack("<I4s", len(payload), b"JSON") + payload
            + struct.pack("<I4s", len(binary), b"BIN\0") + binary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--shape", required=True, action="append", help="Can be repeated")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError(args.output)
        result = bake(args.source.read_bytes(), args.shape)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(result)
        print(args.output)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Morph bake failed: {exc}\n")


if __name__ == "__main__":
    main()
