import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ingame_companion_worker as status_module
import runtime_entry as worker
import runtime_import

# MEDIDO EM 29/09/2026 (item 35): the CET panel reads status files with io.open, which on Windows opens them
# without FILE_SHARE_DELETE; os.replace over the file during that read fails with PermissionError WinError 5.
DENIED = PermissionError(13, 'Acesso negado', None, 5)


def failing_replace(failures):
    """os.replace that is denied `failures` times (None: always), then works."""
    real = status_module.os.replace
    calls = {'n': 0}

    def replace(source, target):
        calls['n'] += 1
        if failures is None or calls['n'] <= failures:
            raise DENIED
        return real(source, target)
    return replace, calls



def ready_wolvenkit(test):
    """The WolvenKit setup is not what these tests exercise: pretend it is READY."""
    patcher = patch.object(worker, 'require_wolvenkit', return_value=Path('WolvenKit.CLI.exe'))
    patcher.start()
    test.addCleanup(patcher.stop)

class StatusWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.status = Path(self.temp.name) / 'exports' / 'npv-x.json'
        status_module.status_write(self.status, stage='building', message='old')
        self.failures = []
        delay = status_module.REPLACE_DELAY
        status_module.REPLACE_DELAY = 0.002
        self.addCleanup(setattr, status_module, 'REPLACE_DELAY', delay)
        previous = status_module.status_failure_hook
        status_module.status_failure_hook = lambda path, error: self.failures.append((path, error))
        self.addCleanup(setattr, status_module, 'status_failure_hook', previous)

    def read(self):
        return json.loads(self.status.read_text(encoding='utf8'))

    def test_file_held_by_a_reader_is_written_once_the_reader_lets_go(self):
        status_module.REPLACE_DELAY = 0.025  # the real retry budget: 20 x 25 ms
        handle = open(self.status, 'rb')
        timer = threading.Timer(0.1, handle.close)
        timer.start()
        written = status_module.status_write(self.status, stage='building', message='new')
        timer.join()
        self.assertTrue(written)
        self.assertEqual(self.read()['message'], 'new')

    def test_first_attempt_denied_then_the_retry_writes(self):
        replace, calls = failing_replace(1)
        with patch('os.replace', side_effect=replace):
            written = status_module.status_write(self.status, stage='building', message='new')
        self.assertTrue(written)
        self.assertEqual(calls['n'], 2)
        self.assertEqual(self.read()['message'], 'new')

    def test_every_attempt_denied_returns_false_keeps_the_old_file_and_reports(self):
        replace, calls = failing_replace(None)
        with patch('os.replace', side_effect=replace):
            written = status_module.status_write(self.status, stage='building', message='new')
        self.assertFalse(written)
        self.assertGreater(calls['n'], 1)
        self.assertEqual(self.read()['message'], 'old')
        self.assertFalse(self.status.with_suffix('.json.tmp').exists())
        self.assertEqual(len(self.failures), 1)

    def test_imported_list_never_raises_when_it_cannot_be_replaced(self):
        plugin = Path(self.temp.name) / 'plugin'
        (plugin / 'data/imports').mkdir(parents=True)
        replace, _ = failing_replace(None)
        with patch('os.replace', side_effect=replace):
            runtime_import.publish_index(plugin, self.status.parent.parent)

    def test_panel_polling_while_the_converter_writes_never_sees_a_partial_file(self):
        stop, reads, broken = threading.Event(), [0], []

        def panel():
            while not stop.is_set():
                try:
                    with open(self.status, 'rb') as file:
                        raw = file.read()
                except OSError:
                    continue
                reads[0] += 1
                try:
                    json.loads(raw)
                except ValueError:
                    broken.append(raw)
                time.sleep(0.001)
        thread = threading.Thread(target=panel)
        thread.start()
        try:
            results = [status_module.status_write(self.status, stage='building', message='n%d' % i) for i in range(150)]
        finally:
            stop.set()
            thread.join()
        self.assertGreater(reads[0], 0)
        self.assertEqual(broken, [])
        self.assertTrue(results[-1])
        self.assertEqual(self.read()['message'], 'n149')
        self.assertFalse(self.status.with_suffix('.json.tmp').exists())


class ImportKeepsGoingTests(unittest.TestCase):
    def setUp(self):
        ready_wolvenkit(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / 'game'
        self.plugin = self.game / 'red4ext/plugins/NPVMaker'
        self.folder = self.game / 'bin/x64/plugins/cyber_engine_tweaks/mods/NPVMaker/projects'
        self.folder.mkdir(parents=True)
        self.identity = 'npv-20260929T000000Z-0001'
        self.request = self.folder / (self.identity + '.build.request.json')
        project = dict(format='npv-maker-project', schema_version=1, name='Teste', body='female', voice='female',
            options=[dict(name='body_color', body_part='Body', kind='appearance', selected_name='default',
                          selected_index=0, choice_count=1, active=True, editable=False, censored=False)],
            dependencies=[], dependency_status='unresolved', npc_status='not_generated')
        raw = json.dumps(project).encode()
        self.digest = hashlib.sha256(raw).hexdigest()
        (self.folder / (self.identity + '.npv.json')).write_bytes(raw)
        self.request.write_text(json.dumps(dict(format='npv-maker-worker-request', schema_version=1,
                                                action='build', project_id=self.identity)))
        previous = status_module.status_failure_hook
        self.addCleanup(setattr, status_module, 'status_failure_hook', previous)
        delay = status_module.REPLACE_DELAY
        status_module.REPLACE_DELAY = 0.002
        self.addCleanup(setattr, status_module, 'REPLACE_DELAY', delay)

    def fake_build(self, snapshot, game, cli, output, progress):
        progress('Lendo aparencias e corpo dos arquivos instalados...')
        output.mkdir(parents=True)
        manifest = dict(format='npv-maker-runtime-npc', project_sha256=self.digest)
        (output / 'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_import_finishes_even_if_no_status_can_be_written(self):
        replace, _ = failing_replace(None)
        real = status_module.os.replace

        def only_status(source, target):
            # Status files (read by the panel) are denied; plugin data (receipt, ready marker) is not.
            if str(target).endswith('.json') and 'projects' in str(target):
                return replace(source, target)
            return real(source, target)
        with patch.object(worker, 'companion_available', return_value=True), \
             patch.object(worker, 'build', side_effect=self.fake_build), \
             patch.object(worker, 'install', return_value={'record_id': 'Character.test'}) as install, \
             patch('os.replace', side_effect=only_status):
            worker.process(self.request, self.game, self.plugin)
        install.assert_called_once()
        self.assertTrue((self.plugin / 'data/imports' / (self.digest + '.json')).is_file())
        self.assertFalse(self.request.exists())
        log = (self.plugin / 'data/diagnostics.log').read_text(encoding='utf8')
        self.assertIn('NPVM-STATUS-001', log)

    def test_one_request_that_crashes_does_not_stop_the_converter_loop(self):
        with patch.object(worker, 'process', side_effect=RuntimeError('boom')):
            worker.run_request(self.request, self.game, self.plugin)
        log = (self.plugin / 'data/diagnostics.log').read_text(encoding='utf8')
        self.assertIn('NPVM-INTERNAL-001', log)


if __name__ == '__main__':
    unittest.main()
