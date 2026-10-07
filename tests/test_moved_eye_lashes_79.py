import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_npc import collect_components  # noqa: E402
from test_runtime_eyelash_chunks import ALL_MASK, EYE_MASK, LASH_MASK, Reader, app, morph_part, option  # noqa: E402

# NPV "teste" (05/10/2026, job df6360f7a0da2dcf): random V, eye color ark_bi02_21 (Arkhe Iris a02) built by the
# ArchiveXL template he_000_pma__basehead__mod on he_000_pma__morphs_normal_fix; the lashes male__27_brown_medium
# stay on the vanilla he_000_pma__morphs. V drew both as he_000_pma__basehead, same id, two files (runtime manifest).
EYE_APP = 'archive_xl\\characters\\head\\player_base_heads\\appearances\\head\\he_000_pma__basehead.app'
LASH_APP = 'archive_xl\\characters\\head\\player_base_heads\\appearances\\head\\hel_000_pma__basehead.app'
VANILLA = 'base\\characters\\head\\player_base_heads\\player_man_average\\he_000_pma__morphs.morphtarget'
FIX = 'archive_xl\\characters\\head\\player_base_heads\\player_man_average\\he_000_pma__morphs_normal_fix.morphtarget'
NAME, CID = 'he_000_pma__basehead', '2024510947074064384'


class ObservedReader(Reader):
    def register(self, resource, suffix):
        return resource


def teste_reader(eye_morph=FIX):
    eye = morph_part(NAME, CID, EYE_MASK, 'ark_bi02_21', eye_morph)
    lash = morph_part(NAME, CID, LASH_MASK, 'blonde_platinum', VANILLA)
    return ObservedReader({EYE_APP: app(('ark_bi02_21', [eye])), LASH_APP: app(('male__27_brown_medium', [lash]))})


def teste_options():
    lash = option('eyelash_color', LASH_APP, 'male__27_brown_medium')
    lash['runtime_observed'] = [dict(name=NAME, field='morphResource', path=VANILLA, hash=None,
                                     mesh_appearance='brown_medium', chunk_mask=LASH_MASK)]
    return [option('eyes_color', EYE_APP, 'ark_bi02_21'), lash]


def parts_by_file(result):
    return {p['morphResource']['DepotPath']['$value']: p for p in result['selected'].values()}


class MovedEyeLashTests(unittest.TestCase):
    """The eye was moved to another file by an ArchiveXL template; the lashes stayed on the vanilla one and the
    NPV came out without them (NPVM-CONVERT-001 'olho de mod sem o componente de cilios do editor')."""

    def test_lashes_on_another_file_become_their_own_component(self):
        result = collect_components(teste_reader(), teste_options(), {})
        parts = parts_by_file(result)
        self.assertEqual(sorted(parts), sorted([FIX, VANILLA]))
        lash = parts[VANILLA]
        self.assertEqual((lash['meshAppearance']['$value'], lash['chunkMask']), ('brown_medium', LASH_MASK))
        self.assertEqual(result['standalone_lashes'], [lash['name']['$value']])

    def test_the_lash_component_does_not_share_name_or_id_with_the_eye(self):
        parts = parts_by_file(collect_components(teste_reader(), teste_options(), {}))
        eye, lash = parts[FIX], parts[VANILLA]
        self.assertEqual(eye['name']['$value'], NAME)
        self.assertNotEqual(lash['name']['$value'], NAME)
        self.assertNotEqual(lash['id'], eye['id'])

    def test_the_eye_keeps_its_own_mask_and_color(self):
        result = collect_components(teste_reader(), teste_options(), {})
        eye = parts_by_file(result)[FIX]
        self.assertEqual((eye['meshAppearance']['$value'], eye['chunkMask']), ('ark_bi02_21', EYE_MASK))
        self.assertIs(result['eye_part'], eye)

    def test_eye_and_lashes_on_the_same_file_keep_the_previous_behaviour(self):
        result = collect_components(teste_reader(eye_morph=VANILLA), teste_options(), {})
        self.assertEqual(len(result['selected']), 1)
        self.assertEqual(result['standalone_lashes'], [])
        self.assertEqual(result['eye_part']['chunkMask'], ALL_MASK)
        self.assertEqual(len(result['eye_lashes']), 1)


if __name__ == '__main__':
    unittest.main()
