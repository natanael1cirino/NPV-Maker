import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

from export_project import validate_project

MARIKO = Path(r'D:\Cyberpunk2077\bin\x64\plugins\cyber_engine_tweaks\mods\NPVMaker\projects\npv-20260927T021329Z-0001.npv.json')


def option(name, kind, index, count, active=True):
    return {'name': name, 'body_part': 'Head', 'kind': kind, 'selected_name': '', 'selected_index': index,
            'choice_count': count, 'active': active, 'editable': True, 'censored': False, 'resource_path': ''}


class SwitcherRangeTests(unittest.TestCase):
    """Project "mariko" (27/09/2026): CCXL eyelashes left the active switcher
    eyelashes_options at index 2 of 2 and the import stopped as invalid."""

    def project(self, *options):
        return {'format': 'npv-maker-project', 'schema_version': 1, 'name': 'mariko', 'body': 'female',
                'voice': 'female', 'source': 'native-character-creator', 'tool_version': '0.3.1',
                'created_at': '2026-09-27T02:13:29Z', 'dependencies': [], 'dependency_status': 'unresolved',
                'npc_status': 'not_generated', 'options': list(options)}

    def test_switcher_outside_its_list_does_not_stop_the_import(self):
        validate_project(self.project(option('eyelashes_options', 'switcher', 2, 2)))

    def test_appearance_outside_its_list_is_left_to_the_converter(self):
        # Without a value name the converter leaves the option out.
        validate_project(self.project(option('eyelash_color', 'appearance', 60, 56)))

    @unittest.skipUnless(MARIKO.is_file(), 'captura real do usuario ausente')
    def test_real_mariko_capture_is_accepted(self):
        validate_project(json.loads(MARIKO.read_text(encoding='utf8')))


if __name__ == '__main__':
    unittest.main()
