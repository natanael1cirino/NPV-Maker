import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import runtime_entry as worker



def ready_wolvenkit(test):
    """The WolvenKit setup is not what these tests exercise: pretend it is READY."""
    patcher = patch.object(worker, 'require_wolvenkit', return_value=Path('WolvenKit.CLI.exe'))
    patcher.start()
    test.addCleanup(patcher.stop)

class RuntimeQueueTests(unittest.TestCase):
    def setUp(self):
        ready_wolvenkit(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / 'game'
        self.plugin = self.game / 'red4ext/plugins/NPVMaker'
        self.folder = self.game / 'bin/x64/plugins/cyber_engine_tweaks/mods/NPVMaker/projects'
        self.folder.mkdir(parents=True)
        self.identity = 'npv-20260924T000000Z-0001'
        self.request = self.folder / (self.identity + '.build.request.json')
        self.status = self.folder / 'exports' / (self.identity + '.json')
        self.project = dict(format='npv-maker-project', schema_version=1, name='Teste', body='female', voice='female',
            options=[dict(name='body_color', body_part='Body', kind='appearance', selected_name='default',
                          selected_index=0, choice_count=1, active=True, editable=False, censored=False)],
            dependencies=[], dependency_status='unresolved', npc_status='not_generated')
        raw = json.dumps(self.project).encode()
        self.digest = hashlib.sha256(raw).hexdigest()
        (self.folder / (self.identity + '.npv.json')).write_bytes(raw)

    def queue(self):
        self.request.write_text(json.dumps(dict(format='npv-maker-worker-request', schema_version=1,
            action='build', project_id=self.identity)))

    def fake_build(self, snapshot, game, cli, output, progress):
        output.mkdir(parents=True)
        manifest = dict(format='npv-maker-runtime-npc', project_sha256=self.digest)
        (output / 'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_retry_after_install_failure_reuses_completed_conversion(self):
        self.queue()
        with patch.object(worker, 'companion_available', return_value=True), \
             patch.object(worker, 'build', side_effect=self.fake_build) as build, \
             patch.object(worker, 'install', side_effect=PermissionError('disk denied')):
            worker.process(self.request, self.game, self.plugin)
            build.assert_called_once()
        self.assertEqual(json.loads(self.status.read_text())['stage'], 'error')
        self.queue()
        with patch.object(worker, 'companion_available', return_value=True), \
             patch.object(worker, 'build') as build, \
             patch.object(worker, 'install', return_value={'record_id': 'Character.test'}) as install:
            worker.process(self.request, self.game, self.plugin)
            build.assert_not_called()
            install.assert_called_once()
        self.assertEqual(json.loads(self.status.read_text())['stage'], 'installed')
        self.assertFalse(self.request.exists())

    def test_body_strategy_is_a_separate_build_not_the_cached_one(self):
        # 0.4.14 DEV: the same saved project imported with the old body and
        # with a runtime strategy must be two NPCs, never one reused build.
        seen = []

        def fake(snapshot, game, cli, output, progress, body_strategy='legacy'):
            seen.append(body_strategy)
            identity = worker.build_identity(self.digest, body_strategy)
            output.mkdir(parents=True)
            manifest = dict(format='npv-maker-runtime-npc', project_sha256=identity, name='Teste')
            (output / 'manifest.json').write_text(json.dumps(manifest))
            return manifest
        for strategy in ('legacy', 'runtime_tpp', 'runtime_tpp'):
            fields = dict(format='npv-maker-worker-request', schema_version=1, action='build',
                          project_id=self.identity)
            if strategy != 'legacy':
                fields['body_strategy'] = strategy
            self.request.write_text(json.dumps(fields))
            with patch.object(worker, 'companion_available', return_value=True), \
                 patch.object(worker, 'build', side_effect=fake), \
                 patch.object(worker, 'install', return_value={'record_id': 'Character.test'}):
                worker.process(self.request, self.game, self.plugin)
        self.assertEqual(seen, ['legacy', 'runtime_tpp'])
        receipts = sorted(p.stem for p in (self.plugin / 'data/imports').glob('*.json'))
        self.assertEqual(receipts, sorted([self.digest, worker.build_identity(self.digest, 'runtime_tpp')]))

    def old_version_build(self, installed):
        # A conversion finished by the 0.4.14 converter: its ready marker has
        # no version; the receipt exists when its files went into the game.
        job = self.plugin / 'data/jobs/old/npc'
        job.mkdir(parents=True)
        (job / 'manifest.json').write_text(json.dumps(dict(format='npv-maker-runtime-npc', project_sha256=self.digest)))
        ready = self.plugin / 'data/ready' / (self.digest + '.json')
        ready.parent.mkdir(parents=True)
        ready.write_text(json.dumps({'manifest': str(job / 'manifest.json')}))
        if installed:
            receipt = self.plugin / 'data/imports' / (self.digest + '.json')
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({'record_id': 'Character.test', 'name': 'Teste'}))

    def test_npv_installed_by_another_version_is_not_reinstalled_as_it_was(self):
        self.old_version_build(installed=True)
        self.queue()
        with patch.object(worker, 'companion_available', return_value=True), \
             patch.object(worker, 'build') as build, patch.object(worker, 'install') as install:
            worker.process(self.request, self.game, self.plugin)
            build.assert_not_called()
            install.assert_not_called()
        status = json.loads(self.status.read_text())
        self.assertEqual(status['stage'], 'error')
        self.assertIn('NPVM-IMPORT-003', json.dumps(status))

    def test_conversion_of_another_version_never_installed_is_redone(self):
        self.old_version_build(installed=False)
        self.queue()
        with patch.object(worker, 'companion_available', return_value=True), \
             patch.object(worker, 'build', side_effect=self.fake_build) as build, \
             patch.object(worker, 'install', return_value={'record_id': 'Character.test'}):
            worker.process(self.request, self.game, self.plugin)
            build.assert_called_once()
        ready = json.loads((self.plugin / 'data/ready' / (self.digest + '.json')).read_text())
        self.assertEqual(ready['npv_version'], worker.diagnostics.NPV_VERSION)
        self.assertEqual(json.loads(self.status.read_text())['stage'], 'installed')

    def test_unknown_body_strategy_is_refused(self):
        self.request.write_text(json.dumps(dict(format='npv-maker-worker-request', schema_version=1, action='build',
                                                project_id=self.identity, body_strategy='mariko_fix')))
        with patch.object(worker, 'companion_available', return_value=True), \
             patch.object(worker, 'build') as build:
            worker.process(self.request, self.game, self.plugin)
            build.assert_not_called()
        self.assertEqual(json.loads(self.status.read_text())['stage'], 'error')

    def test_recovers_claimed_request_after_shutdown(self):
        self.queue()
        claimed = self.request.with_suffix('.working')
        self.request.rename(claimed)
        with patch.object(worker, 'companion_available', return_value=True), \
             patch.object(worker, 'build', side_effect=self.fake_build), \
             patch.object(worker, 'install', return_value={'record_id': 'Character.test'}):
            worker.process(claimed, self.game, self.plugin)
        self.assertFalse(claimed.exists())
        self.assertEqual(json.loads(self.status.read_text())['stage'], 'installed')

    def test_missing_companion_explained_without_starting_conversion(self):
        self.queue()
        with patch.object(worker, 'build') as build:
            worker.process(self.request, self.game, self.plugin)
            build.assert_not_called()
        self.assertIn('Ative o Companion', json.loads(self.status.read_text())['message'])


if __name__ == '__main__':
    unittest.main()
