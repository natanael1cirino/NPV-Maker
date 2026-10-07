import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import runtime_resources
from runtime_resources import Resources, path_hash

HEAD = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa__morphs.morphtarget'
VANILLA = 'base\\characters\\common\\player_base_bodies\\player_female_average\\t0_000_pwa_base__full.mesh'


def write_archive(path: Path, resources: list[str]) -> None:
    """Minimal RDAR file: 40-byte header, 28-byte index, 56-byte entries."""
    entries = b''.join(struct.pack('<Q', int(path_hash(r))) + bytes(48) for r in resources)
    index = struct.pack('<IIQIII', 8, 20 + len(entries), 0, len(resources), 0, 0) + entries
    header = struct.pack('<4sIQIQIQ', b'RDAR', 12, 40, len(index), 0, 0, 40 + len(index))
    path.write_bytes(header + index)


class ModPriorityTests(unittest.TestCase):
    """Two installed mods replace the same file; the game uses the first one."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / 'game'
        self.content = self.game / 'archive/pc/content'
        self.mods = self.game / 'archive/pc/mod'
        self.content.mkdir(parents=True)
        self.mods.mkdir(parents=True)
        # Real case, 26/09/2026: both mods ship the player head morphtarget.
        self.shipped = {'003_EKT_CC_AsianVersion_VTK_Unique_eyes_V4.archive': [HEAD],
                        'vtk_VanillaHD_Head_xBaebsae.archive': [HEAD],
                        'Beautiful_Eyebrows.archive': []}
        for name, resources in self.shipped.items():
            write_archive(self.mods / name, resources)
        self.calls = []

    def fake_cli(self, cli, command, root, flag, out, *rest):
        # WolvenKit unbundle on a folder walks its archives in name order and
        # each one overwrites the previous: the LAST archive wins.
        root, wanted = Path(root), rest[-1]
        self.calls.append(root)
        archives = sorted(root.glob('*.archive')) if root.is_dir() else [root]
        sources = [(a.stem, self.shipped.get(a.name, [])) for a in archives]
        for label, resources in sources:
            for resource in resources:
                if runtime_resources.re.fullmatch(wanted, resource):
                    target = Path(out).joinpath(*resource.split('\\'))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(label, encoding='utf8')
        return ''

    def fetch(self, resources):
        reader = Resources(self.game, self.game / 'cli.exe', self.game / 'cache')
        with patch.object(runtime_resources, 'cli_run', side_effect=self.fake_cli):
            reader.fetch(resources)
        return reader

    def test_archive_index_lists_the_path_hashes(self):
        from runtime_resources import archive_hashes
        found = archive_hashes(self.mods / 'vtk_VanillaHD_Head_xBaebsae.archive')
        self.assertEqual(found, {int(path_hash(HEAD))})

    def test_file_shipped_by_two_mods_comes_from_the_first_in_load_order(self):
        reader = self.fetch([HEAD])
        self.assertEqual(reader.path(HEAD).read_text(encoding='utf8'), '003_EKT_CC_AsianVersion_VTK_Unique_eyes_V4')
        self.assertNotIn(self.mods, self.calls)

    def test_provider_lists_the_mods_in_load_order(self):
        reader = Resources(self.game, self.game / 'cli.exe', self.game / 'cache')
        self.assertEqual(reader.provider(HEAD), ['003_EKT_CC_AsianVersion_VTK_Unique_eyes_V4',
                                                 'vtk_VanillaHD_Head_xBaebsae'])

    def game_archives(self):
        write_archive(self.content / 'basegame_1.archive', [VANILLA, HEAD])
        write_archive(self.content / 'basegame_2.archive', [])
        self.shipped['basegame_1.archive'] = [VANILLA, HEAD]
        self.shipped['basegame_2.archive'] = []

    def test_file_in_no_mod_comes_from_the_game_archive_that_ships_it(self):
        self.game_archives()
        reader = self.fetch([VANILLA])
        self.assertEqual(reader.path(VANILLA).read_text(encoding='utf8'), 'basegame_1')
        self.assertEqual(self.calls, [self.content / 'basegame_1.archive'])

    def test_file_in_no_archive_is_missing_without_scanning_folders(self):
        # Sweep of 27/09/2026: every choice of a CCXL app that points to a
        # hair_shadow.mesh no archive ships ran unbundle on content, ep1, the
        # ArchiveXL bundle and the mod folder again; 750 apps took 9 hours.
        self.game_archives()
        absent = 'raenef\\acacia\\meshes\\hair_shadow.mesh'
        reader = Resources(self.game, self.game / 'cli.exe', self.game / 'cache')
        with patch.object(runtime_resources, 'cli_run', side_effect=self.fake_cli):
            for _ in range(2):
                with self.assertRaises(runtime_resources.ResourceMissing):
                    reader.fetch([absent, VANILLA])
        self.assertEqual(self.calls, [self.content / 'basegame_1.archive'])
        self.assertEqual(reader.path(VANILLA).read_text(encoding='utf8'), 'basegame_1')

    def test_archive_with_unreadable_index_is_still_searched(self):
        self.game_archives()
        (self.mods / 'broken.archive').write_bytes(b'not an archive')
        self.shipped['broken.archive'] = ['bby\\only_here.mesh']
        reader = self.fetch(['bby\\only_here.mesh'])
        self.assertEqual(reader.path('bby\\only_here.mesh').read_text(encoding='utf8'), 'broken')
        self.assertEqual(self.calls, [self.mods / 'broken.archive'])

    def test_archive_in_a_subfolder_of_the_mod_folder_is_not_used(self):
        # Measured 27/09/2026 (NPV Probe 0.2): ResourceDepot.ArchiveExists
        # answered 85/85 archives directly in archive/pc/mod and 0/110 in its
        # subfolders; the 10 files only in subfolders never loaded on the
        # puppet. Here the subfolder copy would come first by name.
        pack = self.mods / 'Pack'
        pack.mkdir()
        write_archive(pack / '000_first.archive', [HEAD, 'bby\\only_in_subfolder.mesh'])
        self.shipped['000_first.archive'] = [HEAD, 'bby\\only_in_subfolder.mesh']
        reader = self.fetch([HEAD])
        self.assertEqual(reader.path(HEAD).read_text(encoding='utf8'), '003_EKT_CC_AsianVersion_VTK_Unique_eyes_V4')
        self.assertNotIn('000_first', reader.provider(HEAD))
        with self.assertRaises(runtime_resources.ResourceMissing):
            self.fetch(['bby\\only_in_subfolder.mesh'])
        self.assertNotIn(pack / '000_first.archive', self.calls)

    def test_game_file_in_content_and_ep1_keeps_the_ep1_copy(self):
        # Before the index, content and then ep1 were unbundled into the same
        # cache and the ep1 copy stayed. Kept; the game's own order between
        # them was not measured.
        self.game_archives()
        (self.game / 'archive/pc/ep1').mkdir(parents=True)
        write_archive(self.game / 'archive/pc/ep1/ep1_1.archive', [VANILLA])
        self.shipped['ep1_1.archive'] = [VANILLA]
        reader = self.fetch([VANILLA])
        self.assertEqual(reader.path(VANILLA).read_text(encoding='utf8'), 'ep1_1')


if __name__ == '__main__':
    unittest.main()
