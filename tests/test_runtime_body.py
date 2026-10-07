import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import runtime_body
import runtime_npc
from runtime_resources import path_hash

ARMS_APP = 'base\\characters\\common\\player_base_bodies\\appearances\\a0_000_base__full.app'
BODY_APP = 'base\\characters\\common\\player_base_bodies\\appearances\\t0_000_base__full.app'
FEET_APP = 'base\\characters\\common\\player_base_bodies\\appearances\\l0_000_base__full.app'
HEAD_APP = 'base\\characters\\head\\player_base_heads\\appearances\\head\\h0_000__basehead_d05.app'
TATTOO_APP = 'mod\\tattoo\\back.app'
ARM_MESH = 'base\\characters\\common\\player_base_bodies\\player_female_average\\arms_hq\\a0_000_pwa_base_hq__l.mesh'
BODY_MORPH = 'base\\characters\\common\\player_base_bodies\\player_female_average\\t0_000_pwa_base__full.morphtarget'
EXTRA_MESH = 'some\\author\\body\\extra_piece.mesh'


def option(name, part, app, selected, active=True):
    return dict(name=name, body_part=part, kind='appearance', resource_path=app, selected_name=selected,
                selected_index=0, choice_count=1, active=active, editable=True, censored=False)


OPTIONS = [option('body_color', 'Body', BODY_APP, 't0_000_pwa_base__06_bl_dark'),
           option('lifted_feet', 'Body', FEET_APP, 'l0_000_pwa_base__06_bl_dark'),
           option('h_default_arms_colors_tpp', 'Arms', ARMS_APP, 'a0_000_pwa_base__06_bl_dark'),
           option('h_default_arms_colors_fpp', 'Arms', 'base\\fpp\\a0_000_base__fpp.app', 'fpp_dark'),
           option('your_back_tattoo', 'Body', TATTOO_APP, 'tattoo_10'),
           option('skin_type_05', 'Head', HEAD_APP, 'h0_000_pwa__basehead__06_bl_dark')]


def comp(name, app, owner, path, state='LOADED', field='mesh', appearance='06_bl_dark', mask='18446744073709551615'):
    return dict(name=name, type='entSkinnedMeshComponent' if field == 'mesh' else 'entMorphTargetSkinnedMeshComponent',
                enabled=True, owner_app=app, owner_appearance=owner, field=field,
                hash=path_hash(path) if path != '0' else '0', path=path, mesh_appearance=appearance,
                chunk_mask=mask, state=state)


def puppet():
    """The measured shape of the dark-skin capture (probe 0.2), reduced."""
    return [comp('a0_001_pwa_base_hq__full', ARMS_APP, 'pwa_default', ARM_MESH, appearance='01_ca_pale'),
            comp('t0_000_pwa_base__full', FEET_APP, 'l0_000_pwa_base__06_bl_dark', BODY_MORPH, field='morphResource',
                 mask='18446744073709551584'),
            comp('Body:ANGEL', FEET_APP, 'l0_000_pwa_base__06_bl_dark', '0', state='NONE', appearance='default'),
            comp('t0_000_pwa_base__full', BODY_APP, 't0_000_pwa_base__06_bl_dark', BODY_MORPH, field='morphResource',
                 mask='18446744073709551391'),
            comp('xyz_new_body_piece', BODY_APP, 't0_000_pwa_base__06_bl_dark', EXTRA_MESH),
            comp('Nim_Body_Bits_01', '', 'None', 'base\\t0_000_pwa_extra_01.mesh', state='MISSING'),
            comp('a0_001_pwa_base_hq__full', ARMS_APP, 'a0_000_pwa_base__06_bl_dark', ARM_MESH),
            comp('a0_001_pwa_base_hq__full', 'base\\fpp\\a0_000_base__fpp.app', 'fpp_dark', ARM_MESH),
            comp('your_back_tattoo10', TATTOO_APP, 'tattoo_10', 'mod\\tattoo\\back.mesh'),
            comp('t0_000_pwa_base__full_seamfix', HEAD_APP, 'h0_000_pwa__basehead__06_bl_dark', 'base\\seam.mesh')]


def project(components=None, **extra):
    section = dict(schema=1, status='captured', source='character_editor_preview', template='player_wa_tpp.ent',
                   components=puppet() if components is None else components)
    return dict(dict(name='Teste', runtime_manifest=section), **extra)


class ManifestTests(unittest.TestCase):
    def test_old_project_has_no_runtime_record(self):
        components, reason = runtime_body.manifest(dict(name='x'))
        self.assertIsNone(components)
        self.assertIn('antes da 0.4.14', reason)

    def test_schema_and_status_are_checked(self):
        self.assertIsNone(runtime_body.manifest(dict(runtime_manifest=dict(schema=2, status='captured')))[0])
        components, reason = runtime_body.manifest(dict(runtime_manifest=dict(schema=1, status='unavailable',
                                                                              reason='preview_not_registered')))
        self.assertIsNone(components)
        self.assertIn('preview_not_registered', reason)
        bad = project([dict(comp('x', BODY_APP, 'a', EXTRA_MESH), hash='12ab')])
        self.assertIsNone(runtime_body.manifest(bad)[0])

    def test_states_are_normalized_in_one_place(self):
        components, _ = runtime_body.manifest(project([
            comp('zero', BODY_APP, 'a', '0', state='LOADED'), comp('gone', BODY_APP, 'a', EXTRA_MESH, state='MISSING'),
            comp('odd', BODY_APP, 'a', EXTRA_MESH, state='PENDING'), comp('ok', BODY_APP, 'a', EXTRA_MESH)]))
        self.assertEqual([c['state'] for c in components], ['NONE', 'MISSING', 'UNOBSERVED', 'LOADED'])


class SelectionTests(unittest.TestCase):
    def rows(self, strategy):
        components, _ = runtime_body.manifest(project())
        return runtime_body.select(components, OPTIONS, strategy)

    def test_selected_tpp_takes_only_the_editor_choice(self):
        selection = self.rows('selected_tpp')
        included = [(c['name'], c['owner_appearance']) for c in selection['included']]
        self.assertEqual(included, [('t0_000_pwa_base__full', 'l0_000_pwa_base__06_bl_dark'),
                                    ('t0_000_pwa_base__full', 't0_000_pwa_base__06_bl_dark'),
                                    ('xyz_new_body_piece', 't0_000_pwa_base__06_bl_dark'),
                                    ('a0_001_pwa_base_hq__full', 'a0_000_pwa_base__06_bl_dark')])
        reasons = {(c['name'], c['owner_appearance']): c['reason'] for c in selection['skipped']}
        self.assertEqual(reasons[('a0_001_pwa_base_hq__full', 'pwa_default')], 'nao_escolhido_no_editor')
        self.assertEqual(reasons[('Body:ANGEL', 'l0_000_pwa_base__06_bl_dark')], 'recurso_none')
        self.assertEqual(reasons[('a0_001_pwa_base_hq__full', 'fpp_dark')], 'perspectiva_fpp')
        self.assertEqual(reasons[('your_back_tattoo10', 'tattoo_10')], 'fora_da_fatia')

    def test_runtime_tpp_keeps_the_preview_copy_too(self):
        included = [(c['name'], c['owner_appearance']) for c in self.rows('runtime_tpp')['included']]
        self.assertIn(('a0_001_pwa_base_hq__full', 'pwa_default'), included)
        self.assertIn(('a0_001_pwa_base_hq__full', 'a0_000_pwa_base__06_bl_dark'), included)
        self.assertNotIn(('a0_001_pwa_base_hq__full', 'fpp_dark'), included)

    def test_head_and_template_components_are_not_body(self):
        names = {c['name'] for s in ('included', 'skipped') for c in self.rows('runtime_tpp')[s]}
        self.assertNotIn('t0_000_pwa_base__full_seamfix', names)
        self.assertNotIn('Nim_Body_Bits_01', names)

    def test_missing_and_failed_loads_stay_out(self):
        components, _ = runtime_body.manifest(project([
            comp('gone', BODY_APP, 't0_000_pwa_base__06_bl_dark', EXTRA_MESH, state='MISSING'),
            comp('broken', BODY_APP, 't0_000_pwa_base__06_bl_dark', EXTRA_MESH, state='EXISTS_NOT_LOADED'),
            comp('late', BODY_APP, 't0_000_pwa_base__06_bl_dark', EXTRA_MESH, state='UNOBSERVED')]))
        selection = runtime_body.select(components, OPTIONS, 'runtime_tpp')
        self.assertEqual([c['name'] for c in selection['included']], ['late'])
        self.assertEqual({c['name']: c['reason'] for c in selection['skipped']},
                         {'gone': 'recurso_missing', 'broken': 'recurso_exists_not_loaded'})

    def test_slice_options_leave_head_tattoo_and_censorship_on_the_old_path(self):
        body, rest = runtime_body.slice_options(OPTIONS + [option('underpants', 'Body', 'base\\i0.app', 'default')])
        self.assertEqual([o['name'] for o in body],
                         ['body_color', 'lifted_feet', 'h_default_arms_colors_tpp', 'h_default_arms_colors_fpp'])
        self.assertEqual({o['name'] for o in rest}, {'your_back_tattoo', 'skin_type_05', 'underpants'})

    def test_no_production_rule_names_a_mod_preset_or_body(self):
        pattern = re.compile(r'hyst|angel|vtk|mariko|\bmia\b|songbird|nim_|raenef|arkhe|wingdeer', re.I)
        code = (ROOT / 'tools/runtime_body.py').read_text(encoding='utf8')
        build = (ROOT / 'tools/runtime_npc.py').read_text(encoding='utf8')
        route = build[build.index('def runtime_body_route'):build.index('def build(')]
        body = '\n'.join(line for line in code.splitlines() if not line.strip().startswith('#'))
        body = re.sub(r'"""[\s\S]*?"""', '', body)
        self.assertIsNone(pattern.search(body))
        self.assertIsNone(pattern.search(route))


def definition(name, path, field='mesh', appearance='default', mask='9223372036854775807', cid='100'):
    key = 'morphResource' if field == 'morphResource' else 'mesh'
    return {'$type': 'entSkinnedMeshComponent' if key == 'mesh' else 'entMorphTargetSkinnedMeshComponent',
            'name': {'$type': 'CName', '$storage': 'string', '$value': name}, 'id': cid,
            key: {'DepotPath': {'$type': 'ResourcePath', '$storage': 'string', '$value': path}, 'Flags': 'Default'},
            'meshAppearance': {'$type': 'CName', '$storage': 'string', '$value': appearance}, 'chunkMask': mask}


APPS = {
    BODY_APP: [definition('t0_000_pwa_base__full', BODY_MORPH, 'morphResource', cid='1'),
               definition('xyz_new_body_piece', EXTRA_MESH, cid='2')],
    FEET_APP: [definition('t0_000_pwa_base__full', BODY_MORPH, 'morphResource', cid='1'),
               definition('Body:ANGEL', '0', cid='3')],
    ARMS_APP: [definition('a0_001_pwa_base_hq__full', ARM_MESH, cid='4')],
}


def fake_collect(reader, options, redirects, character='', redact=None):
    selected, skipped = {}, []
    for o in options:
        for part in APPS.get(o['resource_path'], []):
            selected[(part['name']['$value'], o['name'])] = copy.deepcopy(part)
        if o['resource_path'] not in APPS:
            skipped.append(dict(name=o['name'], reason='sem app', code='NPVM-RESOURCE-001'))
    return dict(selected=selected, used=[], skipped=skipped, diagnostics=[], lash_material=None,
                eye_part=None, app_doc={'Header': {}, 'Data': {}})


def build_parts(strategy, components=None):
    parsed, _ = runtime_body.manifest(project(components))
    selection = runtime_body.select(parsed, OPTIONS, strategy)
    return runtime_body.body_parts(None, {}, selection, OPTIONS, fake_collect, lambda h, s: h,
                                   runtime_npc.safe_path, path_hash), selection


class BodyPartsTests(unittest.TestCase):
    def names(self, built):
        return [(p['name']['$value'], p['meshAppearance']['$value']) for p in built['parts']]

    def test_body_halves_become_one_component_with_all_their_chunks(self):
        built, _ = build_parts('selected_tpp')
        body = [p for p in built['parts'] if p['name']['$value'] == 't0_000_pwa_base__full']
        self.assertEqual(len(body), 1)
        self.assertEqual(int(body[0]['chunkMask']), 18446744073709551584 | 18446744073709551391)
        self.assertEqual(built['merged'], ['t0_000_pwa_base__full'])

    def test_unknown_body_piece_comes_from_its_appearance(self):
        # A body add-on no rule names: it is in the appearance the editor
        # selected, so it is converted with the other body components.
        built, _ = build_parts('selected_tpp')
        self.assertIn(('xyz_new_body_piece', '06_bl_dark'), self.names(built))

    def test_runtime_tpp_keeps_both_arm_copies_and_the_chosen_one_keeps_the_name(self):
        built, _ = build_parts('runtime_tpp')
        arms = [(p['name']['$value'], p['meshAppearance']['$value'], p['id']) for p in built['parts']
                if p['name']['$value'].startswith('a0_001')]
        self.assertEqual(arms[0][:2], ('a0_001_pwa_base_hq__full', '06_bl_dark'))
        self.assertEqual(arms[1][:2], ('a0_001_pwa_base_hq__full__npv_rt1', '01_ca_pale'))
        self.assertNotEqual(arms[0][2], arms[1][2])

    def test_selected_tpp_has_one_arm_copy(self):
        built, _ = build_parts('selected_tpp')
        self.assertEqual([n for n, _ in self.names(built) if n.startswith('a0_001')], ['a0_001_pwa_base_hq__full'])

    def test_runtime_file_and_appearance_replace_the_app_values(self):
        other = 'some\\author\\body\\other_extra.mesh'
        built, _ = build_parts('selected_tpp', [comp('xyz_new_body_piece', BODY_APP, 't0_000_pwa_base__06_bl_dark',
                                                     other, appearance='custom_skin', mask='7')])
        part = built['parts'][0]
        self.assertEqual(part['mesh']['DepotPath']['$value'], other)
        self.assertEqual((part['meshAppearance']['$value'], part['chunkMask']), ('custom_skin', '7'))

    def test_component_missing_from_its_appearance_is_reported(self):
        built, _ = build_parts('selected_tpp', [comp('ghost', BODY_APP, 't0_000_pwa_base__06_bl_dark', EXTRA_MESH)])
        self.assertEqual(built['parts'], [])
        self.assertIn('ghost', [f['name'] for f in built['failures']])

    def test_essential_body_options_must_be_covered(self):
        built, selection = build_parts('selected_tpp')
        self.assertEqual(runtime_body.essential_missing(built['used'], selection, OPTIONS, runtime_npc.ESSENTIAL_OPTION), [])
        only_arms = [c for c in puppet() if c['owner_app'] == ARMS_APP]
        built, selection = build_parts('selected_tpp', only_arms)
        self.assertEqual(runtime_body.essential_missing(built['used'], selection, OPTIONS, runtime_npc.ESSENTIAL_OPTION),
                         ['body_color', 'lifted_feet'])

    def test_merged_body_half_still_counts_for_its_option(self):
        # Mariko capture: body_color's only own piece is the body half that is
        # united with the feet half; body_color must not look uncovered.
        halves = [c for c in puppet() if c['name'] == 't0_000_pwa_base__full'
                  or c['owner_app'] == ARMS_APP and c['owner_appearance'] != 'pwa_default']
        built, selection = build_parts('selected_tpp', halves)
        self.assertEqual(runtime_body.essential_missing(built['used'], selection, OPTIONS, runtime_npc.ESSENTIAL_OPTION), [])

    def test_piece_added_by_an_archivexl_app_patch_is_found_in_the_patch(self):
        # ArchiveXL `resource: patch` merges same-named appearances of a patch
        # .app into the target .app; the puppet names the target as origin.
        patch_app = 'any\\author\\patch_pieces.app'
        APPS[patch_app] = [definition('added_by_patch', 'any\\author\\piece.mesh', cid='9')]
        self.addCleanup(APPS.pop, patch_app)
        parsed, _ = runtime_body.manifest(project([comp('added_by_patch', BODY_APP, 't0_000_pwa_base__06_bl_dark',
                                                        'any\\author\\piece.mesh')]))
        selection = runtime_body.select(parsed, OPTIONS, 'selected_tpp')
        without = runtime_body.body_parts(None, {}, selection, OPTIONS, fake_collect, lambda h, s: h,
                                          runtime_npc.safe_path, path_hash)
        self.assertEqual(without['parts'], [])
        found = runtime_body.body_parts(None, {}, selection, OPTIONS, fake_collect, lambda h, s: h,
                                        runtime_npc.safe_path, path_hash, patches={BODY_APP.lower(): [patch_app]})
        self.assertEqual([p['name']['$value'] for p in found['parts']], ['added_by_patch'])

    def test_comparison_lists_what_the_old_converter_lacked(self):
        built, _ = build_parts('runtime_tpp')
        legacy = [definition('t0_000_pwa_base__full', BODY_MORPH, 'morphResource', '06_bl_dark'),
                  definition('a0_001_pwa_base_hq__full', ARM_MESH, appearance='06_bl_dark'),
                  definition('i0_000_pwa_base_full_censored', 'base\\underpants.mesh')]
        diff = runtime_body.compare(legacy, built['parts'], path_hash)
        self.assertTrue(any(a.startswith('xyz_new_body_piece') for a in diff['added']))
        self.assertTrue(any(l.startswith('i0_000_pwa_base_full_censored') for l in diff['lost']))
        self.assertTrue(any(e.startswith('a0_001_pwa_base_hq__full__npv_rt1') for e in diff['extra_copies']))


class RouteTests(unittest.TestCase):
    """runtime_npc.runtime_body_route: the new input next to the old path."""

    def route(self, data, strategy='selected_tpp'):
        reader = type('R', (), {'register': staticmethod(lambda h, s: h), 'read': lambda self, p: {},
                                'source': lambda self, p: p})()
        options = [o for o in OPTIONS if not o['name'].endswith('_fpp')]
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runtime_npc, 'collect_components', side_effect=fake_collect):
            collected, notes = runtime_npc.runtime_body_route(reader, {}, data, OPTIONS, options, strategy,
                                                              None, Path(folder))
            record = json.loads((Path(folder) / 'body-runtime.json').read_text(encoding='utf8')) \
                if (Path(folder) / 'body-runtime.json').is_file() else None
        return collected, notes, record

    def test_old_project_falls_back_with_a_warning(self):
        collected, notes, record = self.route(dict(name='Antigo'))
        self.assertIsNone(collected)
        self.assertEqual([n['code'] for n in notes], ['NPVM-BODY-003'])
        self.assertIsNone(record)

    def test_runtime_body_replaces_the_body_options_only(self):
        collected, notes, record = self.route(project())
        names = [p['name']['$value'] for p in collected['selected'].values()]
        self.assertIn('xyz_new_body_piece', names)
        self.assertEqual([n['code'] for n in notes], ['NPVM-BODY-001'])
        self.assertIn('estrategia SELECTED_TPP', notes[0]['technical_error'])
        self.assertEqual(record['strategy'], 'selected_tpp')
        self.assertEqual({u['body_source'] for u in collected['used'] if 'body_source' in u}, {'runtime_selected_tpp'})

    def test_missing_essential_piece_falls_back(self):
        only_arms = [c for c in puppet() if c['owner_app'] == ARMS_APP]
        collected, notes, _ = self.route(project(only_arms))
        self.assertIsNone(collected)
        self.assertIn('body_color', notes[-1]['technical_error'])


class IdentityTests(unittest.TestCase):
    def test_each_strategy_is_its_own_npc_and_legacy_keeps_the_project_hash(self):
        digest = '0' * 64
        ids = {s: runtime_npc.build_identity(digest, s) for s in runtime_body.STRATEGIES}
        self.assertEqual(ids['legacy'], digest)
        self.assertEqual(len(set(ids.values())), 3)


if __name__ == '__main__':
    unittest.main()
