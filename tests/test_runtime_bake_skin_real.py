"""Real data (item 37): the icxrus teeth and Soft Natural lashes baked from the installed game keep their
skin. Needs the game, those mods and WolvenKit; runs only with NPV_REAL_DATA=1 (about a minute)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from runtime_npc import bake_morph, glb_skinned
from runtime_resources import Resources, cli_run

GAME = Path(os.environ.get('NPV_GAME', 'D:/Cyberpunk2077'))
# WolvenKit is no longer in the package: the extracted official Console kept for the build is used.
CLI = next((p for p in (ROOT / 'tools/vendor/wolvenkit-runtime/WolvenKit.CLI.exe',
                        GAME / 'red4ext/plugins/NPVMaker/runtime/wolvenkit/WolvenKit.CLI.exe') if p.is_file()), None)
CASES = {'teeth': ('icxrus\\ccxl\\teethpack1\\meshes\\icxrus_pwa_vamp2teeth.morphtarget', 'h123_mouth'),
         'lashes': ('icxrus\\ccxl\\softnatural_eyelashes\\models\\softnatural_eyelashes_pwa.morphtarget', 'h031_eyes')}


@unittest.skipUnless(os.environ.get('NPV_REAL_DATA') == '1' and CLI and (GAME / 'archive/pc/mod').is_dir(),
                     'NPV_REAL_DATA=1 with the game, the icxrus mods and WolvenKit')
class RealBakeSkinTests(unittest.TestCase):
    def bake(self, morph, shape):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, True)
        reader = Resources(GAME, CLI, temp / 'cache')
        reader.register(morph, '.morphtarget')
        reader.serialize([morph])
        doc = reader.read(morph)
        base = doc['Data']['RootChunk']['baseMesh']['DepotPath']['$value']
        reader.fetch([reader.register(base, '.mesh')])
        folder = temp / 'morphs' / 'piece'
        folder.mkdir(parents=True)
        result = bake_morph(reader, CLI, GAME, morph, doc, [shape], folder, 'npvmaker\\generated\\test', temp / 'source', {})
        self.assertIsNone(result['error'])
        self.assertEqual(result['applied_shapes'], [shape])
        baked_glb = folder / (Path(reader.path(base).name).stem + '.glb')
        self.assertTrue(glb_skinned(baked_glb.read_bytes()))
        mesh = temp / 'source' / Path(*result['resource'].split('\\'))
        cli_run(CLI, 'convert', 'serialize', mesh)
        root = json.loads(Path(str(mesh) + '.json').read_text(encoding='utf-8-sig'))['Data']['RootChunk']
        source_root = reader.read(base)['Data']['RootChunk']
        usages = {e['usage'] for c in root['renderResourceBlob']['Data']['header']['renderChunkInfos']
                  for e in c['chunkVertices']['vertexLayout']['elements']['Elements']}
        self.assertTrue({'PS_SkinIndices', 'PS_SkinWeights'} <= usages)
        self.assertEqual([b['$value'] for b in root['boneNames']], [b['$value'] for b in source_root['boneNames']])

    def test_icxrus_teeth_keep_skin_and_weights(self):
        self.bake(*CASES['teeth'])

    def test_soft_natural_lashes_keep_skin_and_weights(self):
        self.bake(*CASES['lashes'])


if __name__ == '__main__':
    unittest.main()
