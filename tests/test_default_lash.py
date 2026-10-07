import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from runtime_npc import default_lash

APP = 'archive_xl\\characters\\head\\player_base_heads\\appearances\\head\\hel_000_pwa__basehead.app'


def lash(name, index, count=35, active=True):
    return {'name': 'eyelash_color', 'body_part': 'Head', 'kind': 'appearance', 'selected_name': name,
            'resource_path': APP, 'selected_index': index, 'choice_count': count, 'active': active}


class DefaultLashTest(unittest.TestCase):
    """Thai (02/10/2026): eyelash_color with selected_index 43 of 35 and no name; the NPV had no lashes."""

    def test_choice_outside_the_list_gets_the_first_choice(self):
        options, changed = default_lash([lash('', 43)], 'female')
        self.assertEqual(options[0]['selected_name'], 'female__05_brown_liquorice')
        self.assertEqual(len(changed), 1)
        options, _ = default_lash([lash('', -1)], 'male')
        self.assertEqual(options[0]['selected_name'], 'male__05_brown_liquorice')

    def test_valid_or_unrelated_choices_stay(self):
        valid = lash('male__05_brown_liquorice', 0)
        inside_without_name = lash('', 3)
        inactive = lash('', 43, active=False)
        brows = dict(lash('', 43), name='eyebrows_color1')
        options, changed = default_lash([valid, inside_without_name, inactive, brows], 'male')
        self.assertEqual(options, [valid, inside_without_name, inactive, brows])
        self.assertEqual(changed, [])


if __name__ == '__main__':
    unittest.main()
