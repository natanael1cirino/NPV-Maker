import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import diagnostics
import i18n
import npv_package
import storage_bridge


def record(code, **extra):
    return diagnostics.make(code, character="seila", **extra)


class LanguageTest(unittest.TestCase):
    def test_game_codes(self):
        self.assertEqual([i18n.normalize(c) for c in ("pt-br", "en-us", "es-es", "es-mx", "fr-fr", "", None)],
                         ["pt", "en", "es", "es", "en", "pt", "pt"])

    def test_language_file(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = Path(folder)
            self.assertEqual(i18n.read_language(storage), "pt")
            (storage / "language.txt").write_text("lang\ten\nend\t1\n", encoding="utf8")
            self.assertEqual(i18n.read_language(storage), "en")


class CoverageTest(unittest.TestCase):
    def test_every_code_and_hint_is_translated(self):
        self.assertEqual(set(diagnostics.CODES) - set(i18n.CODES), set())
        self.assertEqual(set(diagnostics.HINTS) - set(i18n.HINTS), set())
        self.assertEqual(set(diagnostics.ACTIONS) - set(i18n.ACTIONS), set())

    def test_every_source_text_exists_in_the_converter(self):
        # A text changed in the converter but not here would silently stay in Portuguese.
        source = "".join(p.read_text(encoding="utf8") for p in (ROOT / "tools").glob("*.py") if p.name != "i18n.py")
        source = source.replace('"\n', "").replace("\n", " ")
        for key in i18n.TEXTS:
            for piece in re.split(r"\{\w+(?:!t)?\}", key):
                for word in [w for w in re.split(r"[\"' +]+", piece) if len(w) > 3]:
                    self.assertIn(word, source, key)

    def test_no_text_mentions_cet(self):
        for pair in list(i18n.HINTS.values()) + list(i18n.TEXTS.values()):
            self.assertFalse(any("CET" in t for t in pair))
        self.assertFalse(any("CET" in h for h in diagnostics.HINTS.values()))


class TranslationTest(unittest.TestCase):
    def test_portuguese_stays_identical(self):
        records = [record("NPVM-RUNTIME-001", action="reported")]
        self.assertEqual(diagnostics.headline("seila", records, "installed"),
                         "seila importado com 1 aviso(s). Reinicie o jogo.")
        self.assertEqual(i18n.text("Criando o pacote...", "pt"), "Criando o pacote...")

    def test_success_does_not_send_everyone_to_companion(self):
        # Author's print 01/10/2026: Companion unchecked and the message still said to open it.
        self.assertEqual(diagnostics.headline("Thai", [], "installed"), "Thai importado! Reinicie o jogo.")
        self.assertEqual(diagnostics.headline("Thai", [], "installed", "en"), "Thai imported! Restart the game.")

    def test_default_body_has_no_tag_in_the_name(self):
        import runtime_npc
        self.assertNotIn("selected_tpp", runtime_npc.DEV_SUFFIX)

    def test_headline_and_lines_in_english(self):
        records = [record("NPVM-RUNTIME-001", action="reported", option="hair_color", selection="liliac")]
        self.assertEqual(diagnostics.headline("seila", records, "installed", "en"),
                         "seila imported with 1 warning(s). Restart the game.")
        self.assertEqual(diagnostics.line(records[0], "es"), "- Cabello (liliac): indicado en el informe [NPVM-RUNTIME-001]")

    def test_failure_in_spanish(self):
        records = [record("NPVM-RESOURCE-002", action="stopped", option="body_color")]
        self.assertEqual(diagnostics.headline("seila", records, "error", "es"),
                         "La importación falló (NPVM-RESOURCE-002). Cuerpo: Falta un archivo obligatorio del cuerpo "
                         "o de la cabeza. Activa los mods de cuerpo y cabeza usados en V y vuelve a intentarlo.")

    def test_templates(self):
        self.assertEqual(i18n.text("Importando seila [SELECTED_TPP]...", "en"), "Importing seila [SELECTED_TPP]...")
        self.assertEqual(i18n.text("4 requisito(s) detectado(s). Revise e clique CRIAR PACOTE.", "es"),
                         "4 requisito(s) detectado(s). Revísalos y haz clic en CREAR PAQUETE.")
        self.assertEqual(i18n.text("algo que ninguem traduziu", "en"), "algo que ninguem traduziu")

    def test_requirement_pieces(self):
        self.assertEqual(i18n.text("v  Arkhe B02 (opcional)", "en"), "v  Arkhe B02 (optional)")
        self.assertEqual(i18n.reason_text("patch do ArchiveXL herdado; a aparencia escolhida pode nao usar", "en"),
                         "inherited ArchiveXL patch; the chosen look may not use it")


class BridgeTest(unittest.TestCase):
    def status(self, folder, records, message, stage="installed"):
        exports = folder / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        lines = [diagnostics.line(d) for d in records if d["severity"] != "INFO"]
        (exports / "npv-1.json").write_text(json.dumps({
            "format": "npv-maker-companion-job", "stage": stage, "message": message, "lines": lines,
            "diagnostics": records}), encoding="utf8")

    def test_rendered_in_the_game_language_and_again_when_it_changes(self):
        with tempfile.TemporaryDirectory() as root:
            folder, storage, seen = Path(root) / "data", Path(root) / "storage", {}
            records = [record("NPVM-RUNTIME-001", action="reported")]
            self.status(folder, records, diagnostics.headline("seila", records, "installed"))
            storage_bridge.outbound(folder, storage, seen)
            self.assertIn("seila importado com 1 aviso(s)", (storage / "npv-1.txt").read_text(encoding="utf8"))
            (storage / "language.txt").write_text("lang\ten\nend\t1\n", encoding="utf8")
            self.assertEqual(storage_bridge.outbound(folder, storage, seen), 1)
            text = (storage / "npv-1.txt").read_text(encoding="utf8")
            self.assertIn("message\tseila imported with 1 warning(s). Restart the game.", text)
            self.assertIn("line\t- Piece: noted in the report [NPVM-RUNTIME-001]", text)

    def test_setup_failure_by_code(self):
        data = {"format": "npv-maker-setup", "state": "MISSING", "failed": True, "code": "NPVM-SETUP-003",
                "message": diagnostics.CODES["NPVM-SETUP-003"][2], "hint": diagnostics.HINTS["NPVM-SETUP-003"],
                "step": "verificando"}
        rows = dict((r[0], r[1]) for r in storage_bridge.render(data, "en"))
        self.assertEqual(rows["message"], "The downloaded file does not match the official one and was discarded.")
        self.assertEqual(rows["hint"], "Try downloading again.")
        self.assertEqual(rows["step"], "checking")


class PackageTextTest(unittest.TestCase):
    def test_requirements_file_has_three_languages_and_no_cet(self):
        manifest = {"display_name": "Seila", "version": "1.0.0", "character_id": "npv_seila_0123abcd",
                    "source_preset": {}, "dependencies": [
                        {"name": "Arkhe B02", "author": "", "url": "", "required_for_rebuild": False}]}
        text = npv_package.requirements_text(manifest)
        for marker in ("== English ==", "== Portugues ==", "== Espanol ==", "NEXT: MANAGE > PACKAGES > INSTALL",
                       "PROXIMO: GERENCIAR > PACOTES > INSTALAR", "Arkhe B02 (optional)", "Arkhe B02 (opcional)"):
            self.assertIn(marker, text)
        self.assertNotIn("CET", text)


if __name__ == "__main__":
    unittest.main()
