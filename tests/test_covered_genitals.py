import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from runtime_npc import covered_genitals

APP = 'base\\characters\\common\\player_base_bodies\\appearances\\i0_000_base__genitals.app'


def option(name, active=True, kind='appearance'):
    return {'name': name, 'body_part': 'Body', 'kind': kind, 'selected_name': 'x', 'resource_path': APP,
            'active': active}


class CoveredGenitalsTest(unittest.TestCase):
    """AFT in photo mode (03/10/2026): with the default boxers the penis went through them on the NPV only."""

    def setUp(self):
        self.options = [option('genitals', kind='switcher'), option('genitals_02'),
                        option('penis_circumcised', kind='morph'), option('penis_circumcised_hairstyle_00'),
                        option('vagina_hairstyle_01', active=False), option('body_color'), option('underpants'),
                        option('eyebrows_color5')]

    def test_covering_outfit_leaves_genitals_out(self):
        for mode in ('bottom', 'full'):
            options, hidden = covered_genitals(self.options, mode)
            self.assertEqual([o['name'] for o in hidden],
                             ['genitals', 'genitals_02', 'penis_circumcised', 'penis_circumcised_hairstyle_00'])
            active = [o['name'] for o in options if o['active']]
            self.assertEqual(active, ['body_color', 'underpants', 'eyebrows_color5'])

    def test_no_outfit_keeps_everything(self):
        options, hidden = covered_genitals(self.options, 'none')
        self.assertEqual(options, self.options)
        self.assertEqual(hidden, [])


class RuntimeMissingTest(unittest.TestCase):
    """Isolated AFT 03/10/2026: NPVM-RUNTIME-001 listed the penis the NPV left out on purpose."""

    def project(self):
        def row(name, app, appearance):
            return {'name': name, 'type': 'entSkinnedMeshComponent', 'enabled': True, 'owner_appearance': appearance,
                    'owner_app': app, 'field': 'mesh', 'hash': '123', 'path': '', 'mesh_appearance': 'default',
                    'chunk_mask': '1', 'state': 'LOADED'}
        return {'runtime_manifest': {'schema': 1, 'status': 'captured', 'components': [
            row('i0_000_pma_base__penis_circumcised', APP, 'i0_000_pma_base__penis_circumcised__01_ca_pale'),
            row('hh_062_ma__slick_back_shadow', 'base\\hair.app', 'hair')]}}

    def test_left_out_genitals_are_not_missing(self):
        from runtime_npc import runtime_missing
        genitals = dict(option('genitals_02'), selected_name='i0_000_pma_base__penis_circumcised__01_ca_pale')
        self.assertEqual(runtime_missing(self.project(), {}, [genitals]), ['hh_062_ma__slick_back_shadow'])
        self.assertEqual(runtime_missing(self.project(), {}),
                         ['i0_000_pma_base__penis_circumcised', 'hh_062_ma__slick_back_shadow'])


if __name__ == '__main__':
    unittest.main()
