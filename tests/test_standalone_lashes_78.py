import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_body  # noqa: E402
import runtime_npc  # noqa: E402
from runtime_npc import collect_components  # noqa: E402
from test_runtime_eyelash_chunks import (ALL_MASK, EYE_APP, EYE_MASK, LASH_APP, LASH_MASK, Reader, app, cname,  # noqa: E402
                                         morph_part, option)

# NPV HETERO (05/10/2026, project of b7c6614c37e80860): heterochromia on, eyes_color off, two eye components of the
# mod and the lashes as their own component of the bundle's hel_000_pwa__basehead.app.
SPLIT = 'icxrus\\ccxl\\heterochromia\\meshes\\heterochromia_pwa_split_eyes_nullnormal.morphtarget'
LEFT_APP = 'icxrus\\ccxl\\heterochromia\\appearances\\heterochromia_pwa__eyes_left.app'
RIGHT_APP = 'icxrus\\ccxl\\heterochromia\\appearances\\heterochromia_pwa__eyes_right.app'
LEFT_MASK = '18446744073709551608'
RIGHT_MASK = '18446744073709551590'
LASH = 'MorphTargetSkinnedMesh3637'


class ObservedReader(Reader):
    def register(self, resource, suffix):
        return resource


def hetero_reader(lash_mask=LASH_MASK):
    left = morph_part('heterochromia_pwa_eye_left', '11', LEFT_MASK, 'multilayer_nicola', SPLIT)
    right = morph_part('heterochromia_pwa_eye_right', '12', RIGHT_MASK, 'multilayer_nicola_black', SPLIT)
    lash = morph_part(LASH, '2133220414002642944', lash_mask, 'eyelashes__brown_liquorice')
    eye = morph_part(LASH, '2133220414002642944', EYE_MASK, 'gradient_grey')
    return ObservedReader({
        LEFT_APP: app(('46_multilayer_nicola', [left])),
        RIGHT_APP: app(('47_multilayer_nicola_black', [right])),
        LASH_APP: app(('female__05_brown_liquorice', [lash])),
        EYE_APP: app(('he_000_pwa__basehead__14_gradient_grey', [eye])),
    })


def hetero_options(observed=None):
    lash = option('eyelash_color', LASH_APP, 'female__05_brown_liquorice')
    if observed is not None:
        lash['runtime_observed'] = observed
    return [option('eyes_color_left', LEFT_APP, '46_multilayer_nicola'),
            option('eyes_color_right', RIGHT_APP, '47_multilayer_nicola_black'), lash]


def by_name(result):
    found = {}
    for part in result['selected'].values():
        found.setdefault(part['name']['$value'], []).append(part)
    return found


class StandaloneLashTests(unittest.TestCase):
    """BUGS 78: without an eyes_color component the lashes were dropped; V draws them as their own component."""

    def test_normal_eyes_keep_the_previous_behaviour(self):
        result = collect_components(hetero_reader(), [option('eyes_color', EYE_APP, 'he_000_pwa__basehead__14_gradient_grey'),
                                                     option('eyelash_color', LASH_APP, 'female__05_brown_liquorice')], {})
        parts = by_name(result)
        self.assertEqual(list(parts), [LASH])
        self.assertEqual(parts[LASH][0]['chunkMask'], ALL_MASK)
        self.assertEqual(parts[LASH][0]['meshAppearance']['$value'], 'gradient_grey')
        self.assertEqual(result['standalone_lashes'], [])
        self.assertEqual(result['lash_material'], 'eyelashes__brown_liquorice')

    def test_lashes_become_their_own_component_without_eyes_color(self):
        result = collect_components(hetero_reader(), hetero_options(), {})
        parts = by_name(result)
        self.assertEqual(sorted(parts), sorted(['heterochromia_pwa_eye_left', 'heterochromia_pwa_eye_right', LASH]))
        self.assertTrue(all(len(v) == 1 for v in parts.values()))
        lash = parts[LASH][0]
        self.assertEqual((lash['meshAppearance']['$value'], lash['chunkMask']), ('eyelashes__brown_liquorice', LASH_MASK))
        self.assertIsNone(result['eye_part'])
        self.assertEqual(result['standalone_lashes'], [LASH])

    def test_heterochromia_is_left_untouched(self):
        parts = by_name(collect_components(hetero_reader(), hetero_options(), {}))
        self.assertEqual((parts['heterochromia_pwa_eye_left'][0]['meshAppearance']['$value'],
                          parts['heterochromia_pwa_eye_left'][0]['chunkMask']), ('multilayer_nicola', LEFT_MASK))
        self.assertEqual((parts['heterochromia_pwa_eye_right'][0]['meshAppearance']['$value'],
                          parts['heterochromia_pwa_eye_right'][0]['chunkMask']), ('multilayer_nicola_black', RIGHT_MASK))

    def test_what_v_showed_is_used(self):
        observed = [dict(name=LASH, field='morphResource', path=None, hash=None, mesh_appearance='brown_liquorice',
                         chunk_mask=LASH_MASK)]
        result = collect_components(hetero_reader(lash_mask=ALL_MASK), hetero_options(observed), {})
        lash = by_name(result)[LASH][0]
        self.assertEqual((lash['meshAppearance']['$value'], lash['chunkMask']), ('brown_liquorice', LASH_MASK))

    def test_editor_chunk_mask_reaches_the_observed_rows(self):
        project = {'runtime_manifest': {'schema': runtime_body.SCHEMA, 'status': 'captured', 'components': [
            {'name': LASH, 'type': 'entMorphTargetSkinnedMeshComponent', 'state': 'LOADED', 'field': 'morphResource',
             'owner_app': LASH_APP, 'owner_appearance': 'female__05_brown_liquorice', 'mesh_appearance': 'brown_liquorice',
             'chunk_mask': LASH_MASK, 'path': 'x.morphtarget', 'hash': '1'}]}}
        lash = option('eyelash_color', LASH_APP, 'female__05_brown_liquorice')
        seen = runtime_npc.attach_observed(project, [lash], {})[0]['runtime_observed']
        self.assertEqual(seen[0]['chunk_mask'], LASH_MASK)


if __name__ == '__main__':
    unittest.main()
