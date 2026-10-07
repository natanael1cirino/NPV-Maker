"""Performance round (06/10/2026): fewer WolvenKit processes, same files.

Each WolvenKit call costs ~6-13 s of start-up whatever it does (measured on TI 38: 103 calls = 99% of an 18.7 min
conversion), so the reader batches its work. These tests count the calls a fake WolvenKit receives and check that
batching never lets a file come from an archive other than the one the game uses.
"""
import json
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import runtime_resources
from runtime_resources import Resources, path_hash

A = 'base\\a\\only_in_first.mesh'
B = 'base\\b\\only_in_second.mesh'
SHARED = 'base\\c\\in_both.mesh'


def write_archive(path: Path, resources: list[str]) -> None:
    entries = b''.join(struct.pack('<Q', int(path_hash(r))) + bytes(48) for r in resources)
    index = struct.pack('<IIQIII', 8, 20 + len(entries), 0, len(resources), 0, 0) + entries
    header = struct.pack('<4sIQIQIQ', b'RDAR', 12, 40, len(index), 0, 0, 40 + len(index))
    path.write_bytes(header + index)


class FakeWolvenKit:
    """Extracts from the fake archives what the regex names, writing the archive name into the file, as a
    real unbundle writes that archive's copy. Serialize/deserialize copy text."""

    def __init__(self, contents):
        self.contents, self.calls = contents, []

    def __call__(self, cli, *args):
        args = [str(a) for a in args]
        self.calls.append(args)
        start = 2 if args[0] == 'convert' else 1
        inputs = []
        for value in args[start:]:
            if value.startswith('--'):
                break
            inputs.append(value)
        options = dict(zip(args[start + len(inputs)::2], args[start + len(inputs) + 1::2]))
        if args[0] == 'unbundle':
            for archive in inputs:
                for resource in self.contents[Path(archive).name]:
                    if re.fullmatch(options['--regex'], resource):
                        target = Path(options['--outpath']).joinpath(*resource.split('\\'))
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(json.dumps({'from': Path(archive).name}), encoding='utf8')
        elif args[:2] == ['convert', 'serialize']:
            for source in inputs:
                Path(source + '.json').write_text(Path(source).read_text(encoding='utf8'), encoding='utf8')
        elif args[:2] == ['convert', 'deserialize']:
            for source in map(Path, inputs):
                folder = Path(options['--outpath']) if '--outpath' in options else source.parent
                (folder / source.name[:-len('.json')]).write_text(source.read_text(encoding='utf8'), encoding='utf8')
        return ''


class BatchingTests(unittest.TestCase):
    def reader(self, folder, contents):
        game = Path(folder)
        (game / 'archive/pc/content').mkdir(parents=True)
        (game / 'archive/pc/mod').mkdir(parents=True)
        for name, resources in contents.items():
            write_archive(game / 'archive/pc/mod' / name, resources)
        return Resources(game, game / 'cli.exe', game / 'cache')

    def test_files_of_different_archives_come_in_one_call(self):
        contents = {'first.archive': [A], 'second.archive': [B]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runtime_resources, 'cli_run', side_effect=FakeWolvenKit(contents)) as fake:
            reader = self.reader(folder, contents)
            reader.fetch([A, B])
            unbundles = [c for c in fake.side_effect.calls if c[0] == 'unbundle']
            self.assertEqual(len(unbundles), 1)
            self.assertEqual(json.loads(reader.path(A).read_text())['from'], 'first.archive')
            self.assertEqual(json.loads(reader.path(B).read_text())['from'], 'second.archive')

    def test_a_file_in_two_archives_never_shares_a_call_with_the_loser(self):
        # The game loads archives alphabetically and the first one wins: SHARED comes from 'a_mod'. 'b_mod' also
        # ships SHARED; were both in one call, the copy that lands last would be a guess.
        contents = {'a_mod.archive': [SHARED], 'b_mod.archive': [SHARED, B]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runtime_resources, 'cli_run', side_effect=FakeWolvenKit(contents)) as fake:
            reader = self.reader(folder, contents)
            reader.fetch([SHARED, B])
            for call in (c for c in fake.side_effect.calls if c[0] == 'unbundle'):
                archives = [Path(a).name for a in call[1:call.index('--outpath')]]
                if 'in_both' in call[call.index('--regex') + 1]:
                    self.assertNotIn('b_mod.archive', archives)
            self.assertEqual(json.loads(reader.path(SHARED).read_text())['from'], 'a_mod.archive')
            self.assertEqual(json.loads(reader.path(B).read_text())['from'], 'b_mod.archive')

    def test_generated_files_are_written_in_one_call(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runtime_resources, 'cli_run', side_effect=FakeWolvenKit({})) as fake:
            reader = self.reader(folder, {})
            out = Path(folder) / 'out'
            errors = reader.write_binaries([({'n': i}, out / ('f%d.app' % i)) for i in range(3)])
            self.assertEqual(errors, [None, None, None])
            self.assertEqual(sum(1 for c in fake.side_effect.calls if c[:2] == ['convert', 'deserialize']), 1)
            self.assertEqual(json.loads((out / 'f2.app').read_text()), {'n': 2})
            self.assertFalse(list(out.glob('*.json')))

    def test_a_file_the_batch_missed_is_written_alone_with_its_own_error(self):
        class Lossy(FakeWolvenKit):
            def __call__(self, cli, *args):
                args = [str(a) for a in args]
                if args[:2] == ['convert', 'deserialize'] and len(args) > 3 and '--outpath' not in args:
                    args = [a for a in args if not a.endswith('broken.app.json')]
                return super().__call__(cli, *args)
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runtime_resources, 'cli_run', side_effect=Lossy({})) as fake:
            reader = self.reader(folder, {})
            out = Path(folder) / 'out'
            errors = reader.write_binaries([({'n': 1}, out / 'good.app'), ({'n': 2}, out / 'broken.app')])
            self.assertEqual(errors, [None, None])
            singles = [c for c in fake.side_effect.calls if c[:2] == ['convert', 'deserialize'] and '--outpath' in c]
            self.assertEqual(len(singles), 1)
            self.assertTrue(singles[0][2].endswith('broken.app.json'))

    def test_read_after_prefetch_starts_no_wolvenkit(self):
        contents = {'first.archive': [A], 'second.archive': [B]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runtime_resources, 'cli_run', side_effect=FakeWolvenKit(contents)) as fake:
            reader = self.reader(folder, contents)
            reader.prefetch([A, B, 'base\\missing\\nowhere.mesh'])
            before = len(fake.side_effect.calls)
            self.assertEqual(reader.read(A)['from'], 'first.archive')
            self.assertEqual(reader.read(B)['from'], 'second.archive')
            self.assertEqual(len(fake.side_effect.calls), before)
            with self.assertRaises(runtime_resources.ResourceMissing):
                reader.read('base\\missing\\nowhere.mesh')


if __name__ == '__main__':
    unittest.main()
