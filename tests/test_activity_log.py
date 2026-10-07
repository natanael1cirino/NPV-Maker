import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import i18n  # noqa: E402
import ingame_companion_worker as worker  # noqa: E402
import storage_bridge  # noqa: E402

MANAGER = ROOT / 'src/redscript/NPVMakerManager.reds'


class ActivityLogTests(unittest.TestCase):
    """Author request 05/10/2026: the converter activity panel shows the steps of the task like a terminal."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.status = Path(temp.name) / 'tok.json'

    def log(self):
        return [e['text'] for e in json.loads(self.status.read_text(encoding='utf8'))['log']]

    def test_each_new_step_is_kept_with_its_time(self):
        worker.status_write(self.status, stage='building', message='Lendo aparencias e corpo do personagem do editor...')
        worker.status_write(self.status, stage='building', message='Lendo aparencias e corpo do personagem do editor...')
        worker.status_write(self.status, stage='building', message='Convertendo formas: peca 1 de 3...')
        worker.status_write(self.status, stage='installed', message='RED importado! Reinicie o jogo.')
        self.assertEqual(self.log(), ['Lendo aparencias e corpo do personagem do editor...',
                                      'Convertendo formas: peca 1 de 3...', 'RED importado! Reinicie o jogo.'])
        entry = json.loads(self.status.read_text(encoding='utf8'))['log'][0]
        self.assertRegex(entry['time'], r'^\d\d:\d\d:\d\d$')

    def test_a_new_task_starts_a_new_log_and_it_stays_short(self):
        worker.status_write(self.status, stage='installed', message='RED importado! Reinicie o jogo.')
        worker.status_write(self.status, stage='building', message='Preparando HETERO para Companion...')
        self.assertEqual(self.log(), ['Preparando HETERO para Companion...'])
        for i in range(20):
            worker.status_write(self.status, stage='building', message='Convertendo formas: peca %d de 20...' % (i + 1))
        self.assertEqual(len(self.log()), worker.LOG_LINES)
        self.assertEqual(self.log()[-1], 'Convertendo formas: peca 20 de 20...')

    def test_bridge_gives_the_log_to_the_game_translated(self):
        worker.status_write(self.status, stage='building', message='Gerando arquivos do personagem...')
        worker.status_write(self.status, stage='building', message='Convertendo formas: peca 2 de 7...')
        data = json.loads(self.status.read_text(encoding='utf8'))
        rows = [r for r in storage_bridge.render(data, 'en') if r[0] == 'log']
        self.assertEqual([r[2] for r in rows], ['Creating the character files...', 'Converting shapes: piece 2 of 7...'])
        self.assertTrue(all(len(r) == 3 for r in rows))
        self.assertEqual(i18n.text('Convertendo formas: peca 2 de 7...', 'es'), 'Convirtiendo formas: pieza 2 de 7...')

    def test_detail_goes_to_the_log_and_keeps_the_message(self):
        worker.status_write(self.status, stage='building', message='Lendo aparencias e corpo do personagem do editor...')
        worker.status_write(self.status, stage='building', message='Lendo aparencias e corpo do personagem do editor...',
                            detail='hairstyle: UI-Customization-peachu_y2kponytail')
        worker.status_write(self.status, stage='building', message='Lendo aparencias e corpo do personagem do editor...',
                            detail='extraindo 14 arquivo(s) de basegame_4_appearance.archive')
        data = json.loads(self.status.read_text(encoding='utf8'))
        self.assertEqual(data['message'], 'Lendo aparencias e corpo do personagem do editor...')
        self.assertEqual(self.log()[1:], ['hairstyle: UI-Customization-peachu_y2kponytail',
                                          'extraindo 14 arquivo(s) de basegame_4_appearance.archive'])

    def test_detail_lines_are_translated(self):
        cases = {'extraindo 14 arquivo(s) de basegame_4_appearance.archive':
                 'extracting 14 file(s) from basegame_4_appearance.archive',
                 'convertendo 30 arquivo(s) para leitura': 'converting 30 file(s) for reading',
                 'corpo: 7 pecas do editor': 'body: 7 pieces from the editor',
                 'cilios: componente proprio (brown_liquorice)': 'eyelashes: own component (brown_liquorice)',
                 'montando archive: 31 arquivos': 'packing archive: 31 files',
                 'Convertendo formas: peca 3 de 12 (hx_000_pwa__morphs_makeup_eyes_01)...':
                 'Converting shapes: piece 3 of 12 (hx_000_pwa__morphs_makeup_eyes_01)...'}
        for source, english in cases.items():
            self.assertEqual(i18n.text(source, 'en'), english)

    def test_choices_are_told_one_by_one(self):
        import runtime_npc
        from test_runtime_eyelash_chunks import EYE_APP, LASH_APP, Reader, app, morph_part, option
        eye = morph_part('MorphTargetSkinnedMesh3637', '1', '18446744073709551614', 'gradient_grey')
        lash = morph_part('MorphTargetSkinnedMesh3637', '1', '18446744073709551609', 'eyelashes__black_carbon')
        reader = Reader({EYE_APP: app(('he_000_pwa__basehead__14_gradient_grey', [eye])),
                         LASH_APP: app(('female__06_black_carbon', [lash]))})
        told = []
        runtime_npc.collect_components(reader, [option('eyes_color', EYE_APP, 'he_000_pwa__basehead__14_gradient_grey'),
                                                option('eyelash_color', LASH_APP, 'female__06_black_carbon')], {},
                                       step=told.append)
        self.assertEqual(told, ['eyes_color: he_000_pwa__basehead__14_gradient_grey', 'eyelash_color: female__06_black_carbon'])
        runtime_npc.tell(lambda message: None, 'sem detalhe')  # a one-argument progress is left alone

    def test_panel_shows_the_last_lines_under_the_message(self):
        text = MANAGER.read_text(encoding='utf8')
        self.assertIn('this.logText.SetText(this.ActivityLog(tracked ? this.job.raw : raw));', text)
        self.assertIn('if Equals(row.Cell(0), "log") { ArrayPush(lines, "> " + row.Cell(1) + "  " + row.Cell(2)); };', text)
        self.assertIn('ArraySize(lines) > 10 ? ArraySize(lines) - 10 : 0', text)


if __name__ == '__main__':
    unittest.main()
