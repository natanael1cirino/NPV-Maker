import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import photomode

PAPERDOLL = 'base\\animations\\facial\\_facial_graphs\\pma_paperdoll_sermo.animgraph'
PHOTO = 'base\\animations\\facial\\_facial_graphs\\player_man_photomode_sermo.animgraph'


def ref(path):
    return {'DepotPath': {'$type': 'ResourcePath', '$storage': 'string', '$value': path}, 'Flags': 'Obligatory'}


def animated(name, graph, setup):
    return {'$type': 'entAnimatedComponent', 'name': {'$value': name}, 'graph': ref(graph),
            'facialSetup': {'DepotPath': {'$storage': 'uint64' if setup == '0' else 'string', '$value': setup}}}


def app(*components):
    return {'Data': {'RootChunk': {'appearances': [{'Data': {
        'components': list(components),
        'compiledData': {'Data': {'Chunks': copy.deepcopy(list(components))}}}}]}}}


class PhotoModeFaceTest(unittest.TestCase):
    """AFT in photo mode (03/10/2026): no expressions; its face_rig kept the editor's paperdoll graph."""

    def test_template_graph_comes_from_its_face_rig(self):
        goro = app(animated('collar', 'base\\x\\collar.animgraph', '0'),
                   animated('face_rig', PHOTO, 'base\\x\\takemura_rigsetup.facialsetup'))
        self.assertEqual(photomode.template_face_graph(goro)['DepotPath']['$value'], PHOTO)
        self.assertIsNone(photomode.template_face_graph(app(animated('collar', 'base\\x\\c.animgraph', '0'))))

    def test_copy_takes_the_graph_only_on_the_face_rig(self):
        npv = app(animated('face_rig', PAPERDOLL, 'base\\x\\player_rigsetup.facialsetup'),
                  animated('penis_dangles', 'base\\x\\dangle.animgraph', '0'))
        doc, changed = photomode.face_graph_app(npv, ref(PHOTO))
        self.assertEqual(changed, 2)
        parts = doc['Data']['RootChunk']['appearances'][0]['Data']
        for components in (parts['components'], parts['compiledData']['Data']['Chunks']):
            self.assertEqual(components[0]['graph']['DepotPath']['$value'], PHOTO)
            self.assertEqual(components[1]['graph']['DepotPath']['$value'], 'base\\x\\dangle.animgraph')
        original = npv['Data']['RootChunk']['appearances'][0]['Data']['components'][0]
        self.assertEqual(original['graph']['DepotPath']['$value'], PAPERDOLL)

    def test_copy_takes_the_template_expressions(self):
        sets = {'gameplay': [{'animSet': ref('base\\animations\\ui\\photomode\\photomode_male_facial.anims'),
                              'priority': 128}], 'cinematics': []}
        goro = app(dict(animated('face_rig', PHOTO, 'base\\x\\takemura_rigsetup.facialsetup'), animations=sets))
        self.assertEqual(photomode.template_face_animations(goro), sets)
        npv = app(animated('face_rig', PAPERDOLL, 'base\\x\\player_rigsetup.facialsetup'))
        doc, _ = photomode.face_graph_app(npv, ref(PHOTO), photomode.template_face_animations(goro))
        face = doc['Data']['RootChunk']['appearances'][0]['Data']['components'][0]
        self.assertEqual(face['animations'], sets)
        self.assertIsNone(photomode.template_face_animations(app(animated('face_rig', PHOTO, 'base\\x\\s.facialsetup'))))

    def test_template_app_path_reads_the_first_appearance(self):
        ent = {'Data': {'RootChunk': {'appearances': [{'appearanceResource': ref('base\\x\\goro.app')}]}}}
        self.assertEqual(photomode.template_app_path(ent), 'base\\x\\goro.app')
        self.assertEqual(photomode.template_app_path({'Data': {'RootChunk': {}}}), '')


if __name__ == '__main__':
    unittest.main()
