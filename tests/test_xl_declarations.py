import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

from extract_project_apps import declared_mesh_paths, path_hash


class XlDeclarationTests(unittest.TestCase):
    """Any installed .xl feeds this table; one odd line must not stop every import."""

    def test_hash_claimed_by_two_paths_is_dropped_not_fatal(self):
        import extract_project_apps
        real = extract_project_apps.path_hash
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'a.xl').write_text('mesh: mod\\a.mesh\nother: mod\\b.mesh\nkeep: mod\\c.mesh\n', encoding='utf8')
            # Force a collision between a.mesh and b.mesh.
            extract_project_apps.path_hash = lambda p: 'same' if p.lower() in ('mod\\a.mesh', 'mod\\b.mesh') else real(p)
            try:
                result = declared_mesh_paths([Path(folder)])
            finally:
                extract_project_apps.path_hash = real
        self.assertNotIn('same', result)
        self.assertEqual(result[path_hash('mod\\c.mesh')], 'mod\\c.mesh')


if __name__ == '__main__':
    unittest.main()
