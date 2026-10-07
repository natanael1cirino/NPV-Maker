import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'src/redscript/NPVMakerManager.reds'
MARGIN = 12.0  # line.SetChildMargin right margin between the row's widgets


class RequirementRowTest(unittest.TestCase):
    """EXPORTAR > REQUISITOS rows (pacote 22 print, 04/10/2026).

    BUGS 74: EDITAR followed the end of the text, so it moved with the length of each name. The name now has
    a fixed box, sized so EDITAR lands on the same column in detected and hand-added rows.
    BUGS 67: a detected requirement has no INCLUIR and no REMOVER."""

    def setUp(self):
        text = SOURCE.read_text(encoding='utf8')
        start = text.index('let i = this.depPage * 3;')
        self.row = text[start:text.index('let pager = new inkHorizontalPanel();', start)]

    def test_name_has_a_fixed_box(self):
        self.assertIn('text.SetFitToContent(false);', self.row)
        self.assertIn('text.SetSize(width, 64.0);', self.row)
        self.assertIn('text.SetWrapping(true, width);', self.row)
        self.assertNotIn('SetWrapping(true, dep.detected < 0 ? 560.0 : 860.0)', self.row)

    def test_editar_lands_on_the_same_column(self):
        manual, detected = map(float, re.search(r'let width = dep\.detected < 0 \? ([\d.]+) : ([\d.]+);', self.row).groups())
        include = float(re.search(r'"\[ \] INCLUIR"\), StringToName\("npvm_dinc_" \+ ToString\(i\)\), ([\d.]+)\)', self.row).group(1))
        required = float(re.search(r'StringToName\("npvm_dreq_" \+ ToString\(i\)\), ([\d.]+)\)', self.row).group(1))
        manual_editar = include + MARGIN + required + MARGIN + manual + MARGIN
        detected_editar = required + MARGIN + detected + MARGIN
        self.assertEqual(manual_editar, detected_editar)

    def test_detected_row_still_has_no_include_or_remove(self):
        self.assertRegex(self.row, r'if dep\.detected < 0 \{\s*this\.Button\(line, NPVText\.T\(dep\.include')
        self.assertRegex(self.row, r'if dep\.detected < 0 \{\s*this\.Button\(line, NPVText\.T\("REMOVER"\)')


if __name__ == '__main__':
    unittest.main()
