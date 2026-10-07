import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import diagnostics
import runtime_head
from runtime_npc import appearance_names, collect_components, head_notes
from runtime_resources import path_hash

VANILLA_APP = 'base\\characters\\head\\player_base_heads\\appearances\\head\\ht_000__basehead.app'
PACK_APP = 'icxrus\\ccxl\\teethpack1\\materials\\icxrus_teeth.app'
PACK_MORPH = 'icxrus\\ccxl\\teethpack1\\meshes\\icxrus_pwa_vamp2teeth.morphtarget'
# Row of the runtime manifest saved by the 0.4.15 editor for "mariko 3.0" (28/09/2026).
PACK_ROW = {'mesh_appearance': 'default', 'chunk_mask': '18446744073709551615', 'state': 'LOADED', 'enabled': True,
            'name': 'icxrus_pwa_vamp2teeth', 'field': 'morphResource', 'type': 'entMorphTargetSkinnedMeshComponent',
            'owner_appearance': 'pwa_vamp2teeth', 'hash': '6514533244060251919', 'owner_app': PACK_APP,
            'path': PACK_MORPH}


def cname(name):
    return {'$type': 'CName', '$storage': 'string', '$value': name}


def morph_part(name, morph, appearance='default', cid='1'):
    return {'$type': 'entMorphTargetSkinnedMeshComponent', 'name': cname(name), 'id': cid,
            'morphResource': {'DepotPath': {'$type': 'ResourcePath', '$value': morph}},
            'meshAppearance': cname(appearance)}


def app(*appearances):
    return {'Data': {'RootChunk': {'appearances': [{'Data': {'name': cname(name), 'components': list(parts)}}
                                                   for name, parts in appearances]}}}


class Reader:
    def __init__(self, resources):
        self.resources, self.patches = resources, {}

    def read(self, path):
        return copy.deepcopy(self.resources[path])

    def register(self, value, suffix):
        return value

    def source(self, path):
        return path


def option(name, resource, choice, part='Head'):
    return dict(name=name, body_part=part, kind='appearance', selected_name=choice, resource_path=resource,
                active=True, editable=True)


def project(options, rows):
    return dict(name='Teste', options=options,
                runtime_manifest=dict(schema=1, status='captured', components=rows))


def resources():
    return {VANILLA_APP: app(('female_ht_000__basehead__silver',
                              [morph_part('ht_000_pwa__basehead', 'base\\teeth.morphtarget', 'teeth_007__silver')])),
            PACK_APP: app(('pwa_sharpteeth', [morph_part('icxrus_pwa_sharpteeth', 'icxrus\\sharp.morphtarget')]),
                          ('pwa_vamp2teeth', [morph_part('icxrus_pwa_vamp2teeth', PACK_MORPH)]))}


def resolve(options, rows, reader):
    return runtime_head.resolve(project(options, rows), options, options, {},
                                lambda a, n: appearance_names(reader, a, n))


def names(result):
    return sorted(p['name']['$value'] for p in result['selected'].values())


class HeadOriginTests(unittest.TestCase):
    def test_choice_shown_from_another_app_is_read_from_that_app(self):
        # The saved option points to the vanilla teeth .app; the puppet shows
        # the choice coming from the pack's .app. The old path stops there.
        reader = Reader(resources())
        teeth = option('teeth', VANILLA_APP, 'pwa_vamp2teeth')
        with self.assertRaises(diagnostics.DiagnosticError):
            collect_components(reader, [teeth], {})
        options, decisions = resolve([teeth], [PACK_ROW], reader)
        self.assertEqual([d['decision'] for d in decisions], ['runtime_origin'])
        result = collect_components(reader, options, {})
        self.assertEqual(names(result), ['icxrus_pwa_vamp2teeth'])
        self.assertEqual(result['used'][0]['runtime_origin'], {'resource': VANILLA_APP, 'choice': 'pwa_vamp2teeth'})
        self.assertEqual([n['code'] for n in head_notes(decisions, 'Teste', None)], ['NPVM-HEAD-001'])

    def test_observed_file_and_mesh_appearance_are_used(self):
        reader = Reader(resources())
        row = dict(PACK_ROW, mesh_appearance='bloody', path='icxrus\\other.morphtarget',
                   hash=path_hash('icxrus\\other.morphtarget'))
        options, _ = resolve([option('teeth', VANILLA_APP, 'pwa_vamp2teeth')], [row], reader)
        part = next(iter(collect_components(reader, options, {})['selected'].values()))
        self.assertEqual(part['morphResource']['DepotPath']['$value'], 'icxrus\\other.morphtarget')
        self.assertEqual(part['meshAppearance']['$value'], 'bloody')

    def test_two_candidate_origins_are_not_guessed(self):
        reader = Reader(resources())
        second = dict(PACK_ROW, name='other_teeth', owner_app='another\\pack\\teeth.app')
        teeth = option('teeth', VANILLA_APP, 'pwa_vamp2teeth')
        options, decisions = resolve([teeth], [PACK_ROW, second], reader)
        self.assertEqual(options, [teeth])
        self.assertEqual(decisions[0]['decision'], 'ambiguous')
        self.assertEqual([n['code'] for n in head_notes(decisions, 'Teste', None)], ['NPVM-HEAD-002'])

    def test_choice_name_claimed_by_another_option_is_not_guessed(self):
        reader = Reader(resources())
        teeth = option('teeth', VANILLA_APP, 'pwa_vamp2teeth')
        other = option('other_option', 'some\\other.app', 'pwa_vamp2teeth')
        options, decisions = resolve([teeth, other], [PACK_ROW], reader)
        self.assertEqual(options[0], teeth)
        self.assertEqual(decisions[0]['decision'], 'ambiguous')
        self.assertEqual(decisions[0]['rivals'], ['other_option'])

    def test_without_runtime_evidence_the_old_path_stays(self):
        reader = Reader(resources())
        teeth = option('teeth', VANILLA_APP, 'pwa_vamp2teeth')
        for rows in ([], [dict(PACK_ROW, state='UNOBSERVED')], [dict(PACK_ROW, state='MISSING')]):
            options, decisions = resolve([teeth], rows, reader)
            self.assertEqual(options, [teeth])
            self.assertEqual([d['decision'] for d in decisions], ['no_evidence'])
        options, decisions = runtime_head.resolve(dict(name='Antigo', options=[teeth]), [teeth], [teeth], {},
                                                  lambda a, n: [])
        self.assertEqual((options, decisions), ([teeth], []))

    def test_vanilla_choice_from_its_own_app_keeps_the_old_path(self):
        # The preview also carries a second copy of the head from another
        # .app; the option's own .app shows the choice, so nothing changes.
        reader = Reader(resources())
        teeth = option('teeth', VANILLA_APP, 'female_ht_000__basehead__silver')
        own = dict(PACK_ROW, name='ht_000_pwa__basehead', owner_app=VANILLA_APP,
                   owner_appearance='female_ht_000__basehead__silver')
        copy_row = dict(own, owner_app='base\\characters\\head\\another_copy.app')
        options, decisions = resolve([teeth], [own, copy_row], reader)
        self.assertEqual(options, [teeth])
        self.assertEqual(decisions[0]['decision'], 'own_app')

    def test_origin_without_that_appearance_on_disk_keeps_the_old_path(self):
        reader = Reader(resources())
        row = dict(PACK_ROW, owner_appearance='pwa_generated_in_game')
        teeth = option('teeth', VANILLA_APP, 'pwa_generated_in_game')
        options, decisions = resolve([teeth], [row], reader)
        self.assertEqual(options, [teeth])
        self.assertEqual(decisions[0]['decision'], 'no_definition')

    def test_only_head_options_take_the_observed_origin(self):
        reader = Reader(resources())
        body = option('body_thing', VANILLA_APP, 'pwa_vamp2teeth', part='Body')
        options, decisions = resolve([body], [PACK_ROW], reader)
        self.assertEqual((options, decisions), ([body], []))


if __name__ == '__main__':
    unittest.main()
