import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import runtime_entry as worker
from runtime_npc import collect_components
from runtime_resources import ResourceMissing


def cname(name):
    return {'$type': 'CName', '$storage': 'string', '$value': name}


def app(name, *parts):
    return {'Data': {'RootChunk': {'appearances': [{'Data': {'name': cname(name), 'components': list(parts)}}]}}}


def part(name, mesh):
    return {'$type': 'entSkinnedMeshComponent', 'name': cname(name), 'id': name,
            'mesh': {'DepotPath': {'$value': mesh}}, 'meshAppearance': cname('default')}



def ready_wolvenkit(test):
    """The WolvenKit setup is not what these tests exercise: pretend it is READY."""
    patcher = patch.object(worker, 'require_wolvenkit', return_value=Path('WolvenKit.CLI.exe'))
    patcher.start()
    test.addCleanup(patcher.stop)

class Reader:
    def __init__(self, resources):
        self.resources = resources

    def read(self, path):
        if path not in self.resources:
            raise ResourceMissing('Recurso nao encontrado nos mods instalados: ' + path)
        return copy.deepcopy(self.resources[path])


def option(name, resource, selected='look'):
    return dict(name=name, resource_path=resource, selected_name=selected)


RUTH = 'noladreamer_hair\\nd_hair_ruth\\appearances\\nd_hair_ruth_cyberware.app'


class OptionalPieceTests(unittest.TestCase):
    def setUp(self):
        self.reader = Reader({'body.app': app('look', part('t0_body', 'body.mesh')),
                              'hair.app': app('look', part('hair_1', 'hair.mesh'))})

    def test_broken_mod_piece_is_left_out_and_recorded(self):
        # Measured: Ruth offers an app that exists in no archive.
        result = collect_components(self.reader, [option('body_color', 'body.app'),
                                                  option('nd_hair_ruth_cyberware', RUTH, '05_brown_liquorice'),
                                                  option('hair_color', 'hair.app')], {})
        self.assertEqual(sorted(k[0] for k in result['selected']), ['hair_1', 't0_body'])
        self.assertEqual([s['name'] for s in result['skipped']], ['nd_hair_ruth_cyberware'])
        self.assertIn('ResourceMissing', result['skipped'][0]['reason'])
        self.assertEqual([u['name'] for u in result['used']], ['body_color', 'hair_color'])

    def test_broken_body_or_head_still_stops_the_import(self):
        from diagnostics import DiagnosticError
        for essential in ('body_color', 'skin_type_01', 'tpp_head_face_rig', 'eyes_color', 'lifted_feet'):
            with self.assertRaises(DiagnosticError) as raised:
                collect_components(self.reader, [option(essential, 'missing.app')], {})
            self.assertEqual(raised.exception.diagnostic['code'], 'NPVM-RESOURCE-002')
            self.assertEqual(raised.exception.diagnostic['severity'], 'FATAL')

    def test_piece_failing_midway_adds_nothing(self):
        broken = app('look', part('brow_1', 'brow.mesh'), {'$type': 'entSkinnedMeshComponent'})
        self.reader.resources['brow.app'] = broken
        result = collect_components(self.reader, [option('body_color', 'body.app'),
                                                  option('ark_eyebrows', 'brow.app')], {})
        self.assertEqual([k[0] for k in result['selected']], ['t0_body'])
        self.assertEqual(result['skipped'][0]['name'], 'ark_eyebrows')


class SkippedStatusTests(unittest.TestCase):
    def setUp(self):
        ready_wolvenkit(self)

    def test_in_game_status_names_the_left_out_piece_within_140_characters(self):
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp) / 'game'
            plugin = game / 'red4ext/plugins/NPVMaker'
            folder = game / 'bin/x64/plugins/cyber_engine_tweaks/mods/NPVMaker/projects'
            folder.mkdir(parents=True)
            identity = 'npv-20260926T000000Z-0001'
            project = dict(format='npv-maker-project', schema_version=1, name='Ruth', body='female', voice='female',
                           options=[dict(name='body_color', body_part='Body', kind='appearance', selected_name='x',
                                         selected_index=0, choice_count=1, active=True, editable=False, censored=False)],
                           dependencies=[], dependency_status='unresolved', npc_status='not_generated')
            raw = json.dumps(project).encode()
            digest = hashlib.sha256(raw).hexdigest()
            (folder / (identity + '.npv.json')).write_bytes(raw)
            request = folder / (identity + '.build.request.json')
            request.write_text(json.dumps(dict(format='npv-maker-worker-request', schema_version=1,
                                               action='build', project_id=identity)))
            skipped = [dict(name='nd_hair_ruth_cyberware', selected_name='05_brown_liquorice', resource=RUTH,
                            reason='ResourceMissing: ausente')]

            def fake_build(snapshot, game_root, cli, output, progress):
                output.mkdir(parents=True)
                manifest = dict(format='npv-maker-runtime-npc', project_sha256=digest, skipped_options=skipped)
                (output / 'manifest.json').write_text(json.dumps(manifest))
                return manifest
            with patch.object(worker, 'companion_available', return_value=True), \
                 patch.object(worker, 'build', side_effect=fake_build), \
                 patch.object(worker, 'install', return_value={'record_id': 'Character.test'}):
                worker.process(request, game, plugin)
            status = json.loads((folder / 'exports' / (identity + '.json')).read_text(encoding='utf8'))
        self.assertEqual(status['stage'], 'installed')
        self.assertEqual(status['message'], 'Ruth importado com 1 aviso(s). Reinicie o jogo.')
        self.assertLessEqual(len(status['message']), 140)
        self.assertIn('ResourceMissing', status['diagnostics'][0]['technical_error'])
        self.assertEqual(status['skipped_options'], skipped)


if __name__ == '__main__':
    unittest.main()
