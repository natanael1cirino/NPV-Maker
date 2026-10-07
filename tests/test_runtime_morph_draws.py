import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from runtime_npc import morph_draws


def doc(*lod_masks):
    chunks = [{"numVertices": 150, "lodMask": mask} for mask in lod_masks]
    return {"Data": {"RootChunk": {"blob": {"Data": {"baseBlob": {"Data": {"header": {"renderChunkInfos": chunks}}}}}}}}


class MorphDrawsTest(unittest.TestCase):
    """Shapes measured 02/10/2026: vanilla ht_000_pma__morphs (lodMask 1) and a mod's helper teeth pieces (lodMask 0)."""

    def test_chunk_in_no_lod_is_not_drawn(self):
        self.assertFalse(morph_draws(doc(0)))
        self.assertFalse(morph_draws(doc(0, 0)))

    def test_any_chunk_in_a_lod_is_drawn(self):
        self.assertTrue(morph_draws(doc(1)))
        self.assertTrue(morph_draws(doc(0, 2)))

    def test_unreadable_blob_keeps_previous_path(self):
        self.assertTrue(morph_draws({"Data": {"RootChunk": {}}}))
        self.assertTrue(morph_draws(doc()))


if __name__ == '__main__':
    unittest.main()
