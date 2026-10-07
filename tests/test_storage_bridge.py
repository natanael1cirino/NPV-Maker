import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ingame_companion_worker
import storage_bridge as bridge


def project(name='Seila', options=None):
    return {'format': 'npv-maker-project', 'schema_version': 1, 'tool_version': '0.5.0', 'name': name,
            'created_at': '', 'source': 'native-character-creator', 'body': 'female', 'voice': 'female',
            'options': options or [dict(name='body_color', body_part='Body', kind='appearance', selected_name='default',
                                        resource_path='x.app', selected_index=0, choice_count=1, active=True,
                                        editable=False, censored=False)],
            'dependencies': [], 'dependency_status': 'unresolved', 'npc_status': 'not_generated',
            'runtime_manifest': {'schema': 1, 'status': 'unavailable', 'reason': 'teste'}}


def rows(path: Path):
    lines = path.read_text(encoding='utf8').splitlines()
    assert lines[-1] == 'end\t1', lines
    return [line.split('\t') for line in lines[:-1]]


class BridgeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.storage = self.root / 'game/r6/storages/NPVMaker'
        self.folder = self.root / 'game/red4ext/plugins/NPVMaker/data/projects'
        self.storage.mkdir(parents=True)
        self.now = time.time() + 5

    def draft(self, token='abc123', after='none', body=None, strategy='selected_tpp', age=5.0):
        path = self.storage / ('save-' + token + '.draft.json')
        path.write_text(body if body is not None else json.dumps(
            {'format': 'npv-maker-save-request', 'schema_version': 1, 'after_save': after,
             'body_strategy': strategy, 'project': project()}), encoding='utf8')
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_saved_project_gets_a_dated_id_and_the_import_request(self):
        draft = self.draft(after='build', strategy='runtime_tpp')
        taken = bridge.inbound(self.storage, self.folder)
        self.assertFalse(draft.exists())
        saved = list(self.folder.glob('npv-*.npv.json'))
        self.assertEqual(len(saved), 1)
        self.assertRegex(saved[0].name, r'^npv-\d{8}T\d{6}Z-0001\.npv\.json$')
        self.assertEqual(json.loads(saved[0].read_text(encoding='utf8'))['name'], 'Seila')
        project_id = saved[0].name[:-len('.npv.json')]
        request = json.loads((self.folder / (project_id + '.build.request.json')).read_text())
        self.assertEqual((request['action'], request['body_strategy']), ('build', 'runtime_tpp'))
        result = dict((r[0], r[1]) for r in rows(self.storage / 'save-abc123.result.txt'))
        self.assertEqual((result['stage'], result['id'], result['after']), ('saved', project_id, 'build'))
        self.assertEqual(taken, ['salvo ' + project_id])

    def test_two_saves_in_the_same_second_get_different_ids(self):
        self.draft('a')
        self.draft('b')
        bridge.inbound(self.storage, self.folder)
        names = sorted(p.name for p in self.folder.glob('npv-*.npv.json'))
        self.assertEqual([n[-13:] for n in names], ['0001.npv.json', '0002.npv.json'])

    def test_file_still_being_written_waits(self):
        draft = self.draft(age=0.0)
        bridge.inbound(self.storage, self.folder)
        self.assertTrue(draft.exists())
        broken = self.draft('half', body='{"format": "npv-maker-save', age=3.0)
        bridge.inbound(self.storage, self.folder)
        self.assertTrue(broken.exists())

    def test_broken_file_is_refused_after_a_while_and_the_game_is_told(self):
        broken = self.draft('half', body='{"format": "npv-maker-save', age=60.0)
        taken = bridge.inbound(self.storage, self.folder)
        self.assertFalse(broken.exists())
        self.assertEqual(taken, ['recusado save-half.draft.json'])
        self.assertEqual(rows(self.storage / 'save-half.result.txt')[0], ['stage', 'error'])
        invalid = self.draft('bad', body=json.dumps({'format': 'npv-maker-save-request', 'schema_version': 1,
                                                     'project': {'format': 'x'}}), age=60.0)
        bridge.inbound(self.storage, self.folder)
        self.assertFalse(invalid.exists())
        self.assertEqual(list(self.folder.glob('*.npv.json')), [])

    def test_requests_move_to_the_converter_and_nothing_else_does(self):
        names = ['0e790e8bcc899ae5.remove.request.json', 'npv_seila_7c42a91f.install.request.json',
                 'setup.download.request.json', 'latest.txt', 'outro.request.json', 'npv-x.build.request.json']
        for name in names:
            path = self.storage / name
            path.write_text('{"format": "npv-maker-worker-request"}', encoding='utf8')
            os.utime(path, (time.time() - 5, time.time() - 5))
        bridge.inbound(self.storage, self.folder)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), sorted(names[:3]))
        self.assertEqual(sorted(p.name for p in self.storage.iterdir()), sorted(names[3:]))

    def test_status_files_are_mirrored_as_lines(self):
        exports = self.folder / 'exports'
        exports.mkdir(parents=True)
        ingame_companion_worker.status_write(exports / 'npv-20260930T000000Z-0001.json', stage='installed',
                                             message='Seila importado.\nReinicie', lines=['a\tb', 'c'],
                                             restart_required=True, requirements=['v  EKT'])
        (exports / 'imported.json').write_text(json.dumps({'format': 'npv-maker-imported', 'characters': [
            {'token': '0e790e8bcc899ae5', 'name': 'Seila', 'removal_pending': ['x'], 'package': 'npv_a_00000000',
             'package_version': '1.0.0'}]}), encoding='utf8')
        (exports / 'packages.json').write_text(json.dumps({'format': 'npv-maker-packages', 'packages': [
            {'character_id': 'npv_a_00000000', 'display_name': 'A', 'version': '1.0.0', 'author': 'x',
             'state': 'available', 'problem': ''}]}), encoding='utf8')
        (exports / 'setup.json').write_text(json.dumps({'format': 'npv-maker-setup', 'state': 'MISSING',
                                                        'missing': ['wolvenkit'], 'sizes': {'wolvenkit': 45}}))
        (exports / 'tok.export-draft.json').write_text(json.dumps({'format': 'npv-maker-export-draft', 'token': 'tok',
            'fields': {'display_name': 'Seila', 'version': '1.0.0', 'source_preset': {'nexus_mod_id': 24229}},
            'dependencies': [{'name': 'EKT', 'nexus_mod_id': 16930, 'required_for_rebuild': True, 'reason': 'r'}],
            'notice': 'aviso'}))
        (exports / 'npv-20260930T000000Z-0001.report.txt').write_text('relatorio', encoding='utf8')
        seen = {}
        self.assertEqual(bridge.outbound(self.folder, self.storage, seen), 6)
        status = rows(self.storage / 'npv-20260930T000000Z-0001.txt')
        self.assertIn(['message', 'Seila importado. Reinicie'], status)
        self.assertIn(['line', 'a b'], status)
        self.assertIn(['restart', '1'], status)
        self.assertIn(['requirement', 'v  EKT'], status)
        # Cells 6 and 7 (CRIAR NPV choice) were added after the first six, so older game sides read the same cells.
        self.assertEqual(rows(self.storage / 'imported.txt'),
                         [['npv', '0e790e8bcc899ae5', 'Seila', 'npv_a_00000000', '1.0.0', '1', '0000', '', '0']])
        self.assertEqual(rows(self.storage / 'packages.txt')[0][:6],
                         ['package', 'npv_a_00000000', 'A', '1.0.0', 'x', 'available'])
        self.assertIn(['missing', 'wolvenkit'], rows(self.storage / 'setup.txt'))
        draft = rows(self.storage / 'tok.export-draft.txt')
        self.assertIn(['preset_nexus', '24229'], draft)
        self.assertIn(['dep', '0', 'EKT', '', '', '16930', '1', 'r'], draft)
        self.assertEqual((self.storage / 'npv-20260930T000000Z-0001.report.txt').read_text(encoding='utf8'), 'relatorio')
        self.assertEqual(bridge.outbound(self.folder, self.storage, seen), 0)

    def test_status_written_during_a_conversion_reaches_the_game_at_once(self):
        exports = self.folder / 'exports'
        seen = {}
        bridge.install_hook(self.folder, self.storage, seen)
        self.addCleanup(setattr, ingame_companion_worker, 'panel_written_hook', None)
        ingame_companion_worker.status_write(exports / 'npv-20260930T000000Z-0001.json', stage='building',
                                             message='Convertendo formas do personagem...')
        self.assertIn(['stage', 'building'], rows(self.storage / 'npv-20260930T000000Z-0001.txt'))

    def test_latest_project_is_ready_to_open(self):
        self.assertEqual(bridge.latest_rows(self.folder)[0][0], 'error')
        self.folder.mkdir(parents=True)
        options = [dict(name='hair', body_part='Head', kind='appearance', selected_name='a', selected_index=1,
                        choice_count=3, active=True, editable=True, censored=False),
                   dict(name='hair', body_part='Head', kind='appearance', selected_name='b', selected_index=2,
                        choice_count=3, active=True, editable=True, censored=False),
                   dict(name='eyes', body_part='Head', kind='switcher', selected_name='', selected_index=0,
                        choice_count=2, active=False, editable=True, censored=False)]
        (self.folder / 'npv-20260929T000000Z-0001.npv.json').write_text(json.dumps(project('Velha')), encoding='utf8')
        (self.folder / 'npv-20260930T000000Z-0001.npv.json').write_text(json.dumps(project('Nova', options)),
                                                                        encoding='utf8')
        seen = {}
        self.assertTrue(bridge.publish_latest(self.folder, self.storage, seen))
        latest = rows(self.storage / 'latest.txt')
        self.assertEqual(latest[:4], [['id', 'npv-20260930T000000Z-0001'], ['name', 'Nova'], ['body', 'female'],
                                      ['voice', 'female']])
        self.assertEqual(latest[4:], [['option', 'hair', 'Head', 'appearance', 'a', '1', '3', '1', '1'],
                                      ['option', 'eyes', 'Head', 'switcher', '', '0', '2', '0', '1']])
        self.assertFalse(bridge.publish_latest(self.folder, self.storage, seen))

    def test_cet_projects_are_copied_once(self):
        cet = self.root / 'game' / bridge.CET_PROJECTS
        (cet / 'exports').mkdir(parents=True)
        (cet / 'npv-20260929T000000Z-0001.npv.json').write_text('{"a": 1}', encoding='utf8')
        (cet / 'npv-20260929T000000Z-0001.npv.meta.json').write_text('{}', encoding='utf8')
        (cet / 'exports/imported.json').write_text('{}', encoding='utf8')
        (cet / 'npv-20260929T000000Z-0001.build.request.json').write_text('{}', encoding='utf8')
        copied = bridge.migrate_cet(self.root / 'game', self.folder)
        self.assertEqual(sorted(copied), ['npv-20260929T000000Z-0001.npv.json', 'npv-20260929T000000Z-0001.npv.meta.json'])
        (self.folder / 'npv-20260929T000000Z-0001.npv.json').write_text('{"mine": 1}', encoding='utf8')
        self.assertEqual(bridge.migrate_cet(self.root / 'game', self.folder), [])
        self.assertEqual((self.folder / 'npv-20260929T000000Z-0001.npv.json').read_text(), '{"mine": 1}')
        self.assertTrue((cet / 'npv-20260929T000000Z-0001.npv.json').exists())


if __name__ == '__main__':
    unittest.main()
