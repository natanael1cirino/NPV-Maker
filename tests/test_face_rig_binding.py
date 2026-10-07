import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import runtime_npc

RIG = 'base\\characters\\head\\player_base_heads\\player_man_average\\h0_000_pma_c__basehead\\h0_000_pma_c__basehead_skeleton.rig'
BODY = {'Head', 'Neck', 'Hips', 'Spine'}


def ref(path):
    return {'DepotPath': {'$type': 'ResourcePath', '$storage': 'string', '$value': path}, 'Flags': 'Default'}


def binding(name):
    return {'HandleId': '1', 'Data': {'$type': 'entSkinningBinding', 'bindName': {'$type': 'CName', '$value': name}}}


def mesh(name, path):
    return {'$type': 'entSkinnedMeshComponent', 'name': {'$value': name}, 'mesh': ref(path),
            'skinning': binding('root'), 'parentTransform': binding('root')}


def bones(*names):
    return {'boneNames': [{'$value': n} for n in names]}


class Reader:
    def __init__(self, docs):
        self.docs = docs

    def register(self, value, suffix):
        return value

    def read(self, path):
        return {'Data': {'RootChunk': self.docs[path]}}


class FaceRigBindingTest(unittest.TestCase):
    """AFT 03/10/2026: head meshes bound to root had no facial animation; base game NPCs bind them to face_rig."""

    def setUp(self):
        self.reader = Reader({RIG: bones('Head', 'Neck', 'LeftEye', 'jaw', 'lips_upper', 'ear_l', 'brow_l'),
                              'base\\head.mesh': bones('Head', 'jaw', 'lips_upper'),
                              'base\\earring.mesh': bones('Head', 'ear_l'),
                              'base\\v_hair.mesh': bones('Head', 'brow_l'),
                              'base\\shadow.mesh': bones('Head'),
                              'base\\dangle_hair.mesh': bones('Head', 'dyng_hair_01'),
                              'base\\body.mesh': bones('Hips', 'Spine', 'Neck')})
        self.face = {'$type': 'entAnimatedComponent', 'name': {'$value': 'face_rig'}, 'rig': ref(RIG),
                     'graph': ref('base\\animations\\facial\\_facial_graphs\\pma_paperdoll_sermo.animgraph'),
                     'facialSetup': ref('base\\x\\player_rigsetup.facialsetup'), 'skinning': binding('root')}
        self.selected = {'face': self.face, 'head': mesh('head', 'base\\head.mesh'),
                         'earring': mesh('earring', 'base\\earring.mesh'),
                         'v_hair': mesh('v_hair', 'base\\v_hair.mesh'),
                         'shadow': mesh('shadow', 'base\\shadow.mesh'),
                         'dangle_hair': mesh('dangle_hair', 'base\\dangle_hair.mesh'),
                         'body': mesh('body', 'base\\body.mesh')}

    def test_meshes_using_face_only_bones_follow_the_face_rig(self):
        bound = runtime_npc.bind_face_meshes(self.reader, self.selected, 'male', BODY)
        self.assertEqual(sorted(bound), ['earring', 'head', 'v_hair'])
        for key in ('head', 'earring', 'v_hair'):
            for field in ('skinning', 'parentTransform'):
                self.assertEqual(self.selected[key][field]['Data']['bindName']['$value'], 'face_rig')
        for key in ('shadow', 'dangle_hair', 'body'):
            self.assertEqual(self.selected[key]['skinning']['Data']['bindName']['$value'], 'root')

    def test_face_rig_keeps_the_editor_graph(self):
        # BUGS 82 test build (package 38): the world NPC graph (man/woman_average_sermo) plays mood poses at rest;
        # the face rig keeps the graph the editor gave it, while the meshes still follow the face rig.
        runtime_npc.bind_face_meshes(self.reader, self.selected, 'male', BODY)
        self.assertEqual(self.face['graph']['DepotPath']['$value'],
                         'base\\animations\\facial\\_facial_graphs\\pma_paperdoll_sermo.animgraph')
        self.assertEqual(self.selected['head']['skinning']['Data']['bindName']['$value'], 'face_rig')

    def test_without_face_rig_nothing_changes(self):
        del self.selected['face']
        self.assertEqual(runtime_npc.bind_face_meshes(self.reader, self.selected, 'male', BODY), [])
        self.assertEqual(self.selected['head']['skinning']['Data']['bindName']['$value'], 'root')


if __name__ == '__main__':
    unittest.main()
