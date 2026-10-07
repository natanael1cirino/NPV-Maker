"""Resource references read straight from the .archive files the game mounts (BUGS 68 performance round).

Every CR2W file lists the depot paths it references in its imports table, embedded files included. The
table sits in the file's first segment; archives compress segments with Oodle (KARK header), which the
game's own oo2ext_7_win64.dll decompresses. Measured 04/10/2026 on the 56 .mi/.mlsetup/.mltemplate the RED
material chain reads: 55 equal to the DepotPaths WolvenKit serializes; the other one also lists the layers of
an .mlsetup embedded in the .mi (WolvenKit puts them under EmbeddedFiles). 56 files in about a second instead
of 72 WolvenKit runs (7-15 s each). Read only: the game is never written.
"""
from __future__ import annotations

import ctypes
import json
import struct
from array import array
from pathlib import Path

OODLE = "bin/x64/oo2ext_7_win64.dll"
CACHE_FORMAT = "npv-maker-reference-cache"


class Oodle:
    def __init__(self, game: Path):
        library = ctypes.WinDLL(str(game / OODLE))
        self.call = library.OodleLZ_Decompress
        self.call.restype = ctypes.c_int64
        self.call.argtypes = ([ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64]
                              + [ctypes.c_int] * 3 + [ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p,
                                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int])

    def decompress(self, data: bytes, size: int) -> bytes:
        if data[:4] == b"KARK":
            size = struct.unpack_from("<I", data, 4)[0]
            data = data[8:]
        out = ctypes.create_string_buffer(size)
        got = self.call(data, len(data), out, size, 1, 0, 0, None, 0, None, None, None, 0, 3)
        if got != size:
            raise ValueError("Oodle devolveu %d de %d bytes" % (got, size))
        return out.raw


class ArchiveIndex:
    """File entries and segments of one .archive (RDAR v12 layout, as runtime_resources.archive_hash_array)."""

    def __init__(self, path: Path):
        self.path = path
        with path.open("rb") as file:
            magic, _, index, _ = struct.unpack("<4sIQI", file.read(20))
            if magic != b"RDAR":
                raise ValueError("Arquivo .archive invalido: " + path.name)
            file.seek(index)
            _, _, _, files, segments, _ = struct.unpack("<IIQIII", file.read(28))
            raw = file.read(files * 56)
            self.segment_raw = file.read(segments * 16)
        entries = array("Q")
        entries.frombytes(raw)
        self.raw = raw
        self.position = {value: i for i, value in enumerate(entries[::7])}

    def first_segment(self, key: int) -> tuple[int, int, int] | None:
        at = self.position.get(key)
        if at is None:
            return None
        start = struct.unpack_from("<I", self.raw, at * 56 + 20)[0]
        return struct.unpack_from("<QII", self.segment_raw, start * 16)


def imports(blob: bytes) -> list[str]:
    """Depot paths in the imports table of a CR2W file (header 40 bytes, then 10 tables of offset/count/crc)."""
    if blob[:4] != b"CR2W":
        raise ValueError("Nao e um arquivo CR2W")
    strings, _, _ = struct.unpack_from("<III", blob, 40)
    table, count, _ = struct.unpack_from("<III", blob, 40 + 24)
    found = []
    for i in range(count):
        name = struct.unpack_from("<I", blob, table + 8 * i)[0]
        start = strings + name
        found.append(blob[start:blob.index(b"\0", start)].decode("utf8"))
    return found


class References:
    """references(path) -> depot paths the file the game uses for `path` refers to.

    The serving archive is the one Resources picks (mod archives in load order, then the game). Results
    are cached by archive name, size, time and path hash in one file shared by every NPV."""

    def __init__(self, game: Path, resources, cache_file: Path | None = None):
        self.game, self.resources, self.cache_file = game, resources, cache_file
        if not (game / OODLE).is_file():
            raise OSError("Oodle do jogo ausente: " + OODLE)
        self.oodle = None  # loaded on the first compressed segment
        self.indexes, self.cache, self.dirty = {}, {}, False
        if cache_file is not None and cache_file.is_file():
            try:
                doc = json.loads(cache_file.read_text(encoding="utf8"))
                if doc.get("format") == CACHE_FORMAT:
                    self.cache = doc.get("references") or {}
            except (OSError, ValueError):
                self.cache = {}

    def references(self, path: str) -> list[str]:
        source = self.resources.source(path)
        owners = self.resources.owners(source)
        archive = owners[0] if owners else self.resources.base_owner(source)
        if archive is None:
            raise ValueError("Recurso nao encontrado nos archives montados: " + source)
        key = int(self.resources.key(source))
        stat = archive.stat()
        stamp = "%s|%d|%d|%d" % (archive.name, stat.st_size, stat.st_mtime_ns, key)
        if stamp in self.cache:
            return self.cache[stamp]
        index = self.indexes.get(archive)
        if index is None:
            index = self.indexes[archive] = ArchiveIndex(archive)
        segment = index.first_segment(key)
        if segment is None:
            raise ValueError("Recurso fora do indice de " + archive.name + ": " + source)
        offset, zsize, size = segment
        with archive.open("rb") as file:
            file.seek(offset)
            data = file.read(zsize)
        if zsize != size and self.oodle is None:
            self.oodle = Oodle(self.game)
        found = imports(data if zsize == size else self.oodle.decompress(data, size))
        self.cache[stamp] = found
        self.dirty = True
        return found

    def save(self) -> None:
        if self.cache_file is None or not self.dirty:
            return
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"format": CACHE_FORMAT, "references": self.cache}), encoding="utf8")
        temporary.replace(self.cache_file)
        self.dirty = False
