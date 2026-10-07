import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from export_project import validate_project
from runtime_npc import appearance_components, read_selection

GENITALS = 'base\\characters\\common\\player_base_bodies\\appearances\\i0_000_base__genitals.app'


def cname(name):
    return {'$type': 'CName', '$storage': 'string', '$value': name}


def app(*names):
    return {'Data': {'RootChunk': {'appearances': [
        {'Data': {'name': cname(n), 'components': [{'name': cname('part_' + n)}]}} for n in names]}}}


class Reader:
    def __init__(self, resources):
        self.resources = resources

    def read(self, path):
        return copy.deepcopy(self.resources[path])


def option(name, body_part='Head', active=False, selected='', resource=None):
    result = dict(name=name, body_part=body_part, kind='appearance', selected_name=selected,
                  selected_index=0 if active else 4294967295, choice_count=12,
                  active=active, editable=active, censored=False)
    if resource:
        result['resource_path'] = resource
    return result


def project(*options):
    return dict(format='npv-maker-project', schema_version=1, name='teste mod 1', body='female',
                voice='female', options=list(options), dependencies=[], dependency_status='unresolved',
                npc_status='not_generated')


class DuplicateOptionTests(unittest.TestCase):
    def test_mod_option_registered_twice_inactive_is_accepted(self):
        # Captured in game: bby_xtra_face_cyberware lists bby_cyberware_06 twice.
        twin = option('bby_cyberware_06', resource='bby_xtra_face_cyberware\\bby_extra_cyberware_app.app')
        validate_project(project(option('hair', active=True, selected='h1'), twin, copy.deepcopy(twin)))

    def test_identical_active_copies_are_accepted(self):
        chosen = option('bby_cyberware_06', active=True, selected='c3', resource='mod.app')
        validate_project(project(chosen, copy.deepcopy(chosen)))

    def test_inactive_copy_does_not_conflict_with_active_choice(self):
        validate_project(project(option('x', active=False, selected='a'),
                                 option('x', active=True, selected='b')))

    def test_conflicting_active_copies_use_the_first_and_are_reported(self):
        from runtime_npc import first_choices
        first, second = option('x', active=True, selected='a'), option('x', active=True, selected='b')
        validate_project(project(first, second))
        kept, conflicts = first_choices([first, second, option('x', active=False, selected='c')])
        self.assertEqual([o['selected_name'] for o in kept], ['a', 'c'])
        self.assertEqual(conflicts, [second])

    def test_identical_active_copies_are_not_reported(self):
        from runtime_npc import first_choices
        chosen = option('y', active=True, selected='c3', resource='mod.app')
        kept, conflicts = first_choices([chosen, copy.deepcopy(chosen)])
        self.assertEqual((len(kept), conflicts), (1, []))


class SkinSubtoneTests(unittest.TestCase):
    def selection(self, selected, *available):
        reader = Reader({GENITALS: app(*available)})
        chosen = option('genitals_01', 'Body', True, selected, GENITALS)
        return read_selection(reader, chosen, {})[1]['name']['$value']

    def test_missing_subtone_uses_base_tone_of_same_app(self):
        # Measured in the installed i0_000_base__genitals.app.
        self.assertEqual(self.selection('i0_000_pwa_base__vagina__03_ca_senna_01_honey',
                                        'i0_000_pwa_base__vagina__03_ca_senna',
                                        'i0_000_pma_base__vagina__03_ca_senna_01_honey'),
                         'i0_000_pwa_base__vagina__03_ca_senna')

    def test_two_word_subtone(self):
        self.assertEqual(self.selection('i0_000_pwa_base__vagina__01_ca_pale_00_warm_ivory',
                                        'i0_000_pwa_base__vagina__01_ca_pale'),
                         'i0_000_pwa_base__vagina__01_ca_pale')

    def test_exact_subtone_is_preferred(self):
        self.assertEqual(self.selection('i0_000_pwa_base__penis__03_ca_senna_01_honey',
                                        'i0_000_pwa_base__penis__03_ca_senna',
                                        'i0_000_pwa_base__penis__03_ca_senna_01_honey'),
                         'i0_000_pwa_base__penis__03_ca_senna_01_honey')

    def test_empty_female_vagina_appearance_adds_no_component(self):
        # The installed pwa vagina base tone has no components (null in JSON).
        doc = app('i0_000_pwa_base__vagina__03_ca_senna')
        doc['Data']['RootChunk']['appearances'][0]['Data'].pop('components')
        doc['Data']['RootChunk']['appearances'][0]['Data']['components'] = None
        reader = Reader({GENITALS: doc})
        chosen = option('genitals_01', 'Body', True, 'i0_000_pwa_base__vagina__03_ca_senna_01_honey', GENITALS)
        self.assertEqual(appearance_components(read_selection(reader, chosen, {})[1]), [])

    def test_other_body_rig_is_never_used(self):
        with self.assertRaisesRegex(ValueError, 'Aparencia nao encontrada'):
            self.selection('i0_000_pwa_base__vagina__03_ca_senna_01_honey',
                           'i0_000_pma_base__vagina__03_ca_senna_01_honey',
                           'i0_000_pma_base__vagina__03_ca_senna')


if __name__ == '__main__':
    unittest.main()
