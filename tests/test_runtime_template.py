import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import runtime_npc
from runtime_npc import collect_components
from runtime_resources import archive_xl_resources, expand_scope

LASHES_APP = 'mod\\lashes\\appearances\\lashes_pwa.app'
EYES_APP = 'archive_xl\\characters\\head\\player_base_heads\\appearances\\head\\he_000_pwa__basehead.app'
OTHER_APP = 'mod\\hat\\hat.app'


def cname(name):
    return {'$type': 'CName', '$storage': 'string', '$value': name}


def morph(name, path, appearance):
    return {'$type': 'entMorphTargetSkinnedMeshComponent', 'name': cname(name), 'id': '1',
            'morphResource': {'DepotPath': {'$type': 'ResourcePath', '$value': path}},
            'meshAppearance': cname(appearance)}


def app(*appearances):
    return {'Data': {'RootChunk': {'appearances': [{'Data': {'name': cname(name), 'components': list(parts)}}
                                                   for name, parts in appearances]}}}


class Reader:
    """Installed files and the .app files of the player customization scope."""

    def __init__(self, resources, customization=()):
        self.resources, self.customization, self.patches = resources, set(customization), {}

    def read(self, path):
        return copy.deepcopy(self.resources[path])

    def register(self, value, suffix):
        return value

    def source(self, path):
        return path

    def in_scope(self, scope, path):
        return scope == 'player_customization.app' and path in self.customization


def reader():
    # Shapes of Soft Natural Eyelashes (one template) and of the ArchiveXL eye
    # .app (two appearances, the second a template), measured 28/09/2026.
    return Reader({
        LASHES_APP: app(('01_blonde_platinum', [morph('lashes', 'mod\\lashes.morphtarget', 'blonde_platinum')])),
        EYES_APP: app(('he_000_pwa__basehead__01_blood_gradient_black',
                       [morph('eye', 'base\\he_morphs.morphtarget', 'blood_gradient_black')]),
                      ('he_000_pwa__basehead__mod', [morph('eye', '2971506501429392748', 'blood_gradient_black')])),
        OTHER_APP: app(('red', [morph('hat', 'mod\\hat.morphtarget', 'red')]))},
        customization={LASHES_APP, EYES_APP})


def option(name, resource, choice):
    return dict(name=name, body_part='Head', kind='appearance', resource_path=resource, selected_name=choice,
                active=True, editable=True)


def only_part(result):
    parts = list(result['selected'].values())
    assert len(parts) == 1, parts
    return parts[0]


class TemplateTests(unittest.TestCase):
    def test_single_template_takes_the_chosen_name_as_mesh_appearance(self):
        result = collect_components(reader(), [option('lashes_option', LASHES_APP, 'black_carbon')], {})
        self.assertEqual(result['skipped'], [])
        self.assertEqual(only_part(result)['meshAppearance']['$value'], 'black_carbon')
        record = result['used'][0]['archivexl_template']
        self.assertEqual((record['template'], record['rule'], record['runtime']),
                         ('01_blonde_platinum', 'whole_name', 'sem evidencia'))
        self.assertIn('NPVM-TEMPLATE-001', [d['code'] for d in result['diagnostics']])

    def test_several_appearances_use_the_second_as_archivexl_does(self):
        result = collect_components(reader(), [option('eyes_color', EYES_APP, 'protoss_dg13')], {})
        part = only_part(result)
        self.assertEqual(part['morphResource']['DepotPath']['$value'], '2971506501429392748')
        self.assertEqual(part['meshAppearance']['$value'], 'protoss_dg13')
        self.assertEqual(result['used'][0]['archivexl_template']['template'], 'he_000_pwa__basehead__mod')

    def test_numbered_and_prefixed_names_follow_the_archivexl_rules(self):
        numbered = only_part(collect_components(reader(), [option('eyes_color', EYES_APP, '05_brown')], {}))
        self.assertEqual((numbered['morphResource']['DepotPath']['$value'], numbered['meshAppearance']['$value']),
                         ('2971506501429392748', 'brown'))
        prefixed = only_part(collect_components(
            reader(), [option('eyes_color', EYES_APP, 'he_000_pwa__basehead__12_gradient_brown')], {}))
        self.assertEqual((prefixed['morphResource']['DepotPath']['$value'], prefixed['meshAppearance']['$value']),
                         ('base\\he_morphs.morphtarget', 'gradient_brown'))

    def test_existing_appearance_keeps_the_old_path(self):
        result = collect_components(
            reader(), [option('eyes_color', EYES_APP, 'he_000_pwa__basehead__01_blood_gradient_black')], {})
        self.assertNotIn('archivexl_template', result['used'][0])
        self.assertEqual(only_part(result)['meshAppearance']['$value'], 'blood_gradient_black')

    def test_app_outside_the_customization_scope_is_not_rebuilt(self):
        result = collect_components(reader(), [option('hat_option', OTHER_APP, 'green_neon')], {})
        self.assertEqual([s['code'] for s in result['skipped']], ['NPVM-APPEAR-001'])

    def test_names_without_a_valid_template_are_not_guessed(self):
        for name in ('ab', 'x__ab'):
            result = collect_components(reader(), [option('lashes_option', LASHES_APP, name)], {})
            self.assertEqual([s['code'] for s in result['skipped']], ['NPVM-APPEAR-001'], name)

    def test_editor_matching_the_rebuild_is_accepted(self):
        seen = [dict(name='eye', field='morphResource', path='archive_xl\\eyes_normal_fix.morphtarget',
                     hash='2971506501429392748', mesh_appearance='protoss_dg13')]
        result = collect_components(reader(), [dict(option('eyes_color', EYES_APP, 'protoss_dg13'),
                                                    runtime_observed=seen)], {})
        self.assertEqual(result['used'][0]['archivexl_template']['runtime'], 'confere')
        self.assertNotIn('NPVM-TEMPLATE-002', [d['code'] for d in result['diagnostics']])

    def test_editor_contradicting_the_rebuild_wins_and_is_reported(self):
        seen = [dict(name='lashes', field='morphResource', path='mod\\lashes.morphtarget', hash='',
                     mesh_appearance='other_color')]
        result = collect_components(reader(), [dict(option('lashes_option', LASHES_APP, 'black_carbon'),
                                                     runtime_observed=seen)], {})
        self.assertEqual(only_part(result)['meshAppearance']['$value'], 'other_color')
        self.assertEqual(result['used'][0]['archivexl_template']['runtime'], 'diverge')
        self.assertIn('NPVM-TEMPLATE-002', [d['code'] for d in result['diagnostics']])


class CustomizationScopeTests(unittest.TestCase):
    def test_mod_app_joins_the_customization_scope_through_the_bundle(self):
        with tempfile.TemporaryDirectory() as mods, tempfile.TemporaryDirectory() as bundle:
            (Path(mods) / 'lashes.xl').write_text(
                'resource:\n  scope:\n    player_wa_lashes.app:\n      - mod\\lashes\\appearances\\lashes_pwa.app\n',
                encoding='utf8')
            (Path(bundle) / 'LashesScope.xl').write_text(
                'resource:\n  scope:\n    player_customization.app:\n      - player_wa_lashes.app\n'
                '    player_wa_lashes.app:\n      - archive_xl\\hel_000_pwa__basehead.app\n', encoding='utf8')
            scopes = {}
            archive_xl_resources([Path(mods)], scope_folders=[Path(bundle)], scopes_out=scopes)
        expanded = [p.lower() for p in expand_scope('player_customization.app', scopes)]
        self.assertEqual(sorted(expanded), sorted(['archive_xl\\hel_000_pwa__basehead.app', LASHES_APP]))


if __name__ == '__main__':
    unittest.main()
