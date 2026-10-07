import json
import re
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import runtime_resources
from runtime_resources import Resources, archive_xl_resources, path_hash

def write_archive(path: Path, hashes) -> None:
    """Minimal RDAR file listing these path hashes, as every game archive does."""
    entries = b''.join(struct.pack('<Q', int(h)) + bytes(48) for h in hashes)
    index = struct.pack('<IIQIII', 8, 20 + len(entries), 0, len(hashes), 0, 0) + entries
    header = struct.pack('<4sIQIQIQ', b'RDAR', 12, 40, len(index), 0, 0, 40 + len(index))
    path.write_bytes(header + index)


# Shape of Arkhe_Beautiful_Eyebrows_02_FULLER_CCXL.xl (26/09/2026), shortened.
XL = '''customizations:
  female: arkhe\\inkcc\\brows_pwa.inkcharcustomization
resource:
  copy:
    base\\head\\heb_000_pwa__morphs.morphtarget:
      - arkhe_copy\\head\\heb_000_pwa__morphs.morphtarget
    base\\head\\heb_000_pwa_c__basehead.mesh:
      - arkhe_copy\\head\\heb_000_pwa_c__basehead.mesh
  patch:
    arkhe_copy\\head\\heb_000_pwa__morphs.morphtarget:
      props: [ blob, boundingBox, targets ]
      targets: &PWAMorphtargets
        - arkhe\\brows\\heb_000_pwa__morphs_01.morphtarget
        - arkhe\\brows\\heb_000_pwa__morphs_09.morphtarget
    arkhe_copy\\head\\heb_000_pwa_c__basehead.mesh:
      props: renderResourceBlob
      targets:
        - arkhe\\brows\\heb_000_pwa_c__basehead_09.mesh
    bby\\xtra.mesh:
      - base\\a.mesh
  scope:
    player_wa_brows.morphtarget: *PWAMorphtargets
'''
TARGET = 'arkhe\\brows\\heb_000_pwa__morphs_09.morphtarget'
FILES = {
    # The mod file on disk: no face shapes, a placeholder blob and its own handles.
    TARGET: {'Data': {'RootChunk': {
        'baseMesh': {'DepotPath': {'$value': 'arkhe\\brows\\heb_000_pwa_c__basehead_09.mesh'}},
        'blob': {'HandleId': '0', 'Data': {'$type': 'rendRenderMorphTargetMeshBlob', 'placeholder': True}},
        'targets': [],
        'extra': {'HandleId': '1', 'Data': {'kept': True}},
        'extraRef': {'HandleRefId': '1'}}}},
    # Mesh of the mod: no bones on disk (measured on the Arkhe eyebrow 09).
    'arkhe\\brows\\heb_000_pwa_c__basehead_09.mesh': {'Data': {'RootChunk': {
        'renderResourceBlob': {'HandleId': '0', 'Data': {'placeholder': True}},
        'boneNames': [], 'boneRigMatrices': [], 'boneVertexEpsilons': [], 'lodBoneMask': [],
        'appearances': [{'HandleId': '1', 'Data': {'name': {'$value': 'black_carbon'}}}]}}},
    'base\\head\\heb_000_pwa_c__basehead.mesh': {'Data': {'RootChunk': {
        'renderResourceBlob': {'HandleId': '0', 'Data': {'skinned': True}},
        'boneNames': [{'$value': 'Head'}, {'$value': 'l_J_eye_brows_rowA_0_JNT'}],
        'boneRigMatrices': [{'m': 1}, {'m': 2}], 'boneVertexEpsilons': [0.1, 0.2], 'lodBoneMask': [1, 1],
        'appearances': []}}},
    'base\\head\\heb_000_pwa__morphs.morphtarget': {'Data': {'RootChunk': {
        'blob': {'HandleId': '0', 'Data': {'$type': 'rendRenderMorphTargetMeshBlob',
                                           'base': {'HandleId': '1', 'Data': {'vertices': 390}},
                                           'again': {'HandleRefId': '1'}}},
        'boundingBox': {'Max': 1},
        'targets': [{'name': {'$value': 'h101'}, 'regionName': {'$value': 'eyes'}}]}}},
}


class PropsParserTests(unittest.TestCase):
    def test_property_patches_are_read_with_anchors(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'brows.xl').write_text(XL, encoding='utf8')
            props = {}
            copies, patches = archive_xl_resources([Path(folder)], props)
        self.assertEqual(props[int(path_hash(TARGET))],
                         ('arkhe_copy\\head\\heb_000_pwa__morphs.morphtarget', ['blob', 'boundingBox', 'targets']))
        self.assertEqual(props[int(path_hash('arkhe\\brows\\heb_000_pwa_c__basehead_09.mesh'))],
                         ('arkhe_copy\\head\\heb_000_pwa_c__basehead.mesh', ['renderResourceBlob']))
        self.assertEqual(len(props), 3)
        self.assertEqual(patches, {'base\\a.mesh': ['bby\\xtra.mesh']})
        self.assertEqual(copies['arkhe_copy\\head\\heb_000_pwa__morphs.morphtarget'],
                         'base\\head\\heb_000_pwa__morphs.morphtarget')


class PropsReaderTests(unittest.TestCase):
    """The cached mod file must look like ArchiveXL leaves it in game."""

    def fake_cli(self, cli, *args):
        # Reads the arguments as WolvenKit does: several inputs before the options, --outpath optional
        # for convert (the binary goes beside its JSON without it).
        args = [str(a) for a in args]
        start = 2 if args[0] == 'convert' else 1
        inputs = []
        for value in args[start:]:
            if value.startswith('--'):
                break
            inputs.append(value)
        options = dict(zip(args[start + len(inputs)::2], args[start + len(inputs) + 1::2]))
        if args[0] == 'unbundle':
            out = Path(options['--outpath'])
            wanted = (lambda p: re.fullmatch(options['--regex'], p)) if '--regex' in options else (
                lambda p: path_hash(p) in Path(options['--hash']).read_text().split())
            for path, doc in FILES.items():
                if wanted(path):
                    target = out.joinpath(*path.split('\\'))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(doc), encoding='utf8')
        elif args[:2] == ['convert', 'serialize']:
            for source in inputs:
                shutil.copy(source, source + '.json')
        elif args[:2] == ['convert', 'deserialize']:
            for source in map(Path, inputs):
                folder = Path(options['--outpath']) if '--outpath' in options else source.parent
                shutil.copy(source, folder / source.name[:-len('.json')])
        return ''

    def read(self, by_hash, resource=TARGET, suffix='.morphtarget'):
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder)
            (game / 'archive/pc/content').mkdir(parents=True)
            (game / 'archive/pc/mod').mkdir(parents=True)
            (game / 'archive/pc/mod/brows.xl').write_text(XL, encoding='utf8')
            write_archive(game / 'archive/pc/content/basegame.archive',
                          [path_hash(p) for p in FILES if p.startswith('base\\')])
            write_archive(game / 'archive/pc/mod/arkhe.archive',
                          [path_hash(p) for p in FILES if not p.startswith('base\\')])
            reader = Resources(game, game / 'cli.exe', game / 'cache')
            with patch.object(runtime_resources, 'cli_run', side_effect=self.fake_cli):
                key = reader.register(path_hash(resource), suffix) if by_hash else resource
                self.donor = reader.props_donor(key) if hasattr(reader, 'props_donor') else 'ausente'
                self.patched = reader.patched(key) if hasattr(reader, 'patched') else 'ausente'
                return reader.read(key)['Data']['RootChunk']

    def test_patched_geometry_brings_the_bones_it_points_to(self):
        # THAILEND 0.4.8: the Arkhe mesh got the EKT geometry without its bones
        # and the eyebrows were not drawn on the face.
        root = self.read(by_hash=False, resource='arkhe\\brows\\heb_000_pwa_c__basehead_09.mesh', suffix='.mesh')
        donor = FILES['base\\head\\heb_000_pwa_c__basehead.mesh']['Data']['RootChunk']
        self.assertEqual(root['renderResourceBlob']['Data'], {'skinned': True})
        for prop in ('boneNames', 'boneRigMatrices', 'boneVertexEpsilons', 'lodBoneMask'):
            self.assertEqual(root[prop], donor[prop])
        self.assertEqual(root['appearances'][0]['Data']['name'], {'$value': 'black_carbon'})
        self.assertTrue(self.patched)
        self.assertIsNone(self.donor)

    def test_morph_export_uses_the_patch_source(self):
        self.read(by_hash=True)
        self.assertEqual(self.donor, 'base\\head\\heb_000_pwa__morphs.morphtarget')

    def test_morphtarget_gets_the_face_shapes_of_the_patch_source(self):
        root = self.read(by_hash=False)
        self.assertEqual(root['targets'], FILES['base\\head\\heb_000_pwa__morphs.morphtarget']['Data']['RootChunk']['targets'])
        self.assertEqual(root['boundingBox'], {'Max': 1})
        self.assertEqual(root['blob']['Data']['base']['Data'], {'vertices': 390})
        self.assertEqual(root['baseMesh']['DepotPath']['$value'], 'arkhe\\brows\\heb_000_pwa_c__basehead_09.mesh')

    def test_grafted_handles_do_not_collide_with_the_file_handles(self):
        root = self.read(by_hash=True)
        grafted = [root['blob']['HandleId'], root['blob']['Data']['base']['HandleId'],
                   root['blob']['Data']['again']['HandleId']]
        self.assertEqual(len(set(grafted)), 3)
        self.assertNotIn('1', grafted)
        self.assertEqual(root['extra'], {'HandleId': '1', 'Data': {'kept': True}})
        self.assertEqual(root['extraRef'], {'HandleRefId': '1'})


class PropsCacheTests(PropsReaderTests):
    """A cached file is reused only when it came from the archive the game uses
    now and got every patch ArchiveXL applies."""

    def game(self, folder):
        game = Path(folder)
        (game / 'archive/pc/content').mkdir(parents=True)
        (game / 'archive/pc/mod').mkdir(parents=True)
        (game / 'archive/pc/mod/brows.xl').write_text(XL, encoding='utf8')
        write_archive(game / 'archive/pc/content/basegame.archive',
                      [path_hash(p) for p in FILES if p.startswith('base\\')])
        write_archive(game / 'archive/pc/mod/arkhe.archive',
                      [path_hash(p) for p in FILES if not p.startswith('base\\')])
        return game

    def targets(self, game):
        reader = Resources(game, game / 'cli.exe', game / 'cache')
        with patch.object(runtime_resources, 'cli_run', side_effect=self.fake_cli):
            return reader.read(TARGET)['Data']['RootChunk']['targets']

    def test_patch_is_applied_when_the_same_fetch_has_a_missing_file(self):
        # Sweep of 27/09/2026: a batch with a hair_shadow.mesh no archive ships
        # raised before the patches; the Arkhe eyebrow morphtarget stayed in the
        # cache with 0 face shapes (105 when read alone) and was never patched.
        with tempfile.TemporaryDirectory() as folder:
            game = self.game(folder)
            reader = Resources(game, game / 'cli.exe', game / 'cache')
            with patch.object(runtime_resources, 'cli_run', side_effect=self.fake_cli):
                with self.assertRaises(runtime_resources.ResourceMissing):
                    reader.fetch(['raenef\\acacia\\meshes\\hair_shadow.mesh', TARGET])
            self.assertEqual(len(self.targets(game)), 1)

    def test_unpatched_copy_left_in_the_cache_is_extracted_again(self):
        with tempfile.TemporaryDirectory() as folder:
            game = self.game(folder)
            stale = game / 'cache' / Path(*TARGET.split('\\'))
            stale.parent.mkdir(parents=True)
            stale.write_text(json.dumps(FILES[TARGET]), encoding='utf8')
            Path(str(stale) + '.json').write_text(json.dumps(FILES[TARGET]), encoding='utf8')
            self.assertEqual(len(self.targets(game)), 1)

    def test_updated_mod_archive_replaces_the_cached_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            game = self.game(folder)
            self.assertEqual(len(self.targets(game)), 1)
            cached = game / 'cache' / Path(*TARGET.split('\\'))
            cached.write_text('old', encoding='utf8')
            Path(str(cached) + '.json').write_text(json.dumps(FILES[TARGET]), encoding='utf8')
            archive = game / 'archive/pc/mod/arkhe.archive'
            write_archive(archive, [path_hash(p) for p in FILES if not p.startswith('base\\')] + [1])
            reader = Resources(game, game / 'cli.exe', game / 'cache')
            with patch.object(runtime_resources, 'cli_run', side_effect=self.fake_cli):
                reader.fetch([TARGET])
            self.assertNotEqual(cached.read_text(encoding='utf8'), 'old')


if __name__ == '__main__':
    unittest.main()
