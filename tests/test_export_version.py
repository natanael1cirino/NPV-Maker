import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import diagnostics  # noqa: E402
import npv_package as pkg  # noqa: E402
import runtime_entry as worker  # noqa: E402
import storage_bridge  # noqa: E402
from test_npv_package import Fixture, form  # noqa: E402

MANAGER = ROOT / 'src/redscript/NPVMakerManager.reds'


class ExportedVersionTests(unittest.TestCase):
    """BUGS 75 (pacote 23, 04/10/2026): EXPORTAR refused RED 1.0.0 because its folder already existed (right),
    but the panel said "Importe este NPV de novo" (the hint of the generic NPVM-PACKAGE-001) and nothing told
    the author to change the version. Own code with its hint, and a warning before the click."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fx = Fixture(Path(temp.name))

    def export(self, version, draft):
        deps = [dict(d, author='', include=True, detected=i) for i, d in enumerate(draft['dependencies'])]
        return pkg.export(self.fx.plugin, self.fx.projects, self.fx.token,
                          {'fields': form(version), 'dependencies': deps}, draft, self.fx.exports)

    def test_same_version_has_its_own_code_and_the_panel_says_what_to_do(self):
        draft = self.fx.draft()
        self.export('1.0.0', draft)
        with self.assertRaises(pkg.PackageError) as caught:
            self.export('1.0.0', draft)
        self.assertEqual(caught.exception.code, 'NPVM-PACKAGE-007')
        record = worker.classify(caught.exception, 'export', 'RED', lambda text: text)
        shown = {lang: diagnostics.headline('RED', [record], 'error', lang) for lang in ('pt', 'en', 'es')}
        self.assertIn('ja foi exportada', shown['pt'])
        self.assertIn('1. DADOS', shown['pt'])
        self.assertNotIn('Importe este NPV', shown['pt'])
        self.assertIn('1. DETAILS', shown['en'])
        self.assertIn('1. DATOS', shown['es'])
        self.assertTrue(self.export('1.0.1', draft)['zip'].is_file())

    def test_draft_lists_versions_still_in_the_exports_folder(self):
        draft = self.fx.draft()
        cid = self.export('1.0.0', draft)['character_id']
        (self.fx.exports / (cid + '-nota')).mkdir()
        (self.fx.exports / 'npv_outro_00000000-2.0.0').mkdir()
        again = pkg.draft(self.fx.plugin, self.fx.projects, self.fx.game, self.fx.token,
                          *self.fx_args(), exports=self.fx.exports)
        self.assertEqual(again['exported_versions'], ['1.0.0'])
        (self.fx.exports / (cid + '-1.0.0')).rename(self.fx.exports / (cid + '-1.0.0-antigo'))
        moved = pkg.draft(self.fx.plugin, self.fx.projects, self.fx.game, self.fx.token,
                          *self.fx_args(), exports=self.fx.exports)
        self.assertEqual(moved['exported_versions'], [])

    def fx_args(self):
        from test_npv_package import FakeLocator, SOURCES
        return FakeLocator(), SOURCES

    def test_bridge_gives_the_versions_to_the_game(self):
        rows = storage_bridge.render({'format': 'npv-maker-export-draft', 'token': 't', 'fields': {},
                                      'dependencies': [], 'exported_versions': ['1.0.0', '1.0.1']})
        self.assertEqual([r for r in rows if r[0] == 'exported'], [('exported', '1.0.0'), ('exported', '1.0.1')])

    def test_window_warns_in_details_and_before_export(self):
        text = MANAGER.read_text(encoding='utf8')
        details = text[text.index('this.FormInput(right, NPVText.T("Versao (1.0.0)"), 2, 14);'):]
        details = details[:details.index('this.FormInput(right, NPVText.T("Descricao")')]
        self.assertIn('if this.VersionTaken()', details)
        export = text[text.index('if this.exportStep == 3 {'):]
        export = export[:export.index('n"npvm_create"')]
        self.assertIn('if this.VersionTaken()', export)
        self.assertIn('Troque a versao em 1. DADOS', export)
        self.assertIn('if Equals(row.Cell(0), "exported") { ArrayPush(this.exportedVersions, row.Cell(1)); };', text)


if __name__ == '__main__':
    unittest.main()
