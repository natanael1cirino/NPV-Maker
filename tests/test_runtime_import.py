import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_import import install
from runtime_npc import expanded, handles, renumber, selected_appearances


class RuntimeImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = Path(self.tmp.name) / 'Jogo com espaços'
        companion = self.game / 'r6/scripts/Companion/AikoNPVFramework.reds'
        companion.parent.mkdir(parents=True)
        companion.write_text('public class AikoNPVRegistrySystem extends ScriptableSystem {}')
        self.archive = Path(self.tmp.name) / 'test.archive'
        self.archive.write_bytes(b'generated-test-archive')
        digest = hashlib.sha256(b'project').hexdigest()
        self.manifest = dict(format='npv-maker-runtime-npc', local_use_only=True,
            project_sha256=digest, record_id='Character.NPVMaker_' + digest[:16],
            entity_path='npvmaker\\generated\\' + digest[:16] + '\\character.ent',
            archive=str(self.archive), name='Érica "azul"', body='female',
            appearance_name='default', base_record='Character.bella')

    def test_install_two_characters_and_idempotent_retry(self):
        first = install(self.game, self.manifest)
        again = install(self.game, self.manifest)
        self.assertEqual(first, again)
        other = copy.deepcopy(self.manifest)
        digest = hashlib.sha256(b'other').hexdigest()
        other.update(project_sha256=digest, name='Outro', record_id='Character.NPVMaker_' + digest[:16],
                     entity_path='npvmaker\\generated\\' + digest[:16] + '\\character.ent')
        second = install(self.game, other)
        self.assertTrue(set(first['files']).isdisjoint(second['files']))
        self.assertTrue(first['restart_required'])
        yaml = next(self.game.rglob('*.yaml')).read_text(encoding='utf8')
        self.assertIn('Érica', yaml)

    def test_never_overwrite_foreign_file(self):
        first = install(self.game, self.manifest)
        file = self.game / next(iter(first['files']))
        file.write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError, 'outro pacote'):
            install(self.game, self.manifest)
        self.assertEqual(file.read_bytes(), b'foreign')

    def test_failed_commit_rolls_back_only_new_files(self):
        original = Path.rename
        calls = []
        def fail_second(source, target):
            calls.append(target)
            if len(calls) == 2:
                raise PermissionError('test interruption')
            return original(source, target)
        with patch.object(Path, 'rename', fail_second):
            with self.assertRaises(PermissionError):
                install(self.game, self.manifest)
        self.assertFalse(list(self.game.rglob('*.archive')))
        self.assertFalse(list(self.game.rglob('*.npv-pending')))
        self.assertTrue(list(self.game.rglob('AikoNPVFramework.reds')))

    def test_cannot_install_outside_namespace(self):
        self.manifest['entity_path'] = 'foreign\\character.ent'
        with self.assertRaises(ValueError):
            install(self.game, self.manifest)
        self.assertFalse(list(self.game.rglob('*.archive')))

    def test_expand_binding_from_another_appearance(self):
        source = {'first': {'HandleId': '3', 'Data': {'$type': 'binding', 'bindName': 'root'}},
                  'second': {'parentTransform': {'HandleRefId': '3'}}}
        independent = expanded(source['second'], handles(source))
        renumber(independent)
        self.assertEqual(independent['parentTransform']['Data']['bindName'], 'root')
        self.assertNotEqual(independent['parentTransform']['HandleId'], '3')

    def test_include_hidden_body_but_exclude_alternative_fpp(self):
        def option(name):
            return dict(name=name, active=True, editable=False, kind='appearance',
                        resource_path='base\\body.app', selected_name='default')
        result = selected_appearances({'options': [option('body_color'), option('hair_fpp'),
                                      option('body_color_censored'), option('skin_type_01')]})
        self.assertEqual([o['name'] for o in result], ['body_color', 'skin_type_01'])


if __name__ == '__main__':
    unittest.main()
