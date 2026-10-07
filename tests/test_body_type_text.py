import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/redscript/NPVMaker.reds'
TEXT = ROOT / 'src/redscript/NPVMakerText.reds'
KEY = ('Escolha o tipo de corpo do NPV. Ocasionalmente, a aparencia do NPV pode afetar o comportamento de outros '
       'personagens.')


def between(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


class BodyTypeTextTest(unittest.TestCase):
    """Author request 06/10/2026: the body type screen (gender_selection, LocKey#35480) says NPV, not V.

    The stock description carries the inkTextReplaceAnimationController that wrote the key back over SetText on the
    editor title (02/10/2026), so it is hidden and replaced, and only while the NPV session runs (New Game keeps the
    stock text)."""

    def setUp(self):
        self.menu = SOURCE.read_text(encoding='utf8')
        self.text = TEXT.read_text(encoding='utf8')
        self.block = between(self.menu, '@wrapMethod(CharacterCreationGenderSelectionMenu)\n'
                                        'protected cb func OnInitialize() -> Bool {', '  return result;')

    def test_only_in_npv_session(self):
        self.assertIn('if NPVMakerSession.GetInstance().active {', self.block.split('NPVFindNamedChild')[0])

    def test_stock_description_hidden_not_rewritten(self):
        self.assertIn('NPVFindNamedChild(this.GetRootCompoundWidget(), n"descHolder", n"desc") as inkText', self.block)
        self.assertIn('desc.SetVisible(false);', self.block)
        self.assertIsNone(re.search(r'\bdesc\.SetText\(', self.block))
        self.assertIn('text.SetText(NPVText.T("' + KEY + '"));', self.block)
        self.assertIn('text.Reparent(holder);', self.block)
        self.assertIn('text.SetWrapping(true, 1430.0);', self.block)

    def test_three_languages(self):
        entry = between(self.text, 'this.Add("' + KEY + '",', ');')
        self.assertIn("Select the NPV's body type.", entry)
        self.assertIn('Elige el tipo de cuerpo del NPV.', entry)
        self.assertNotIn(" V.", entry.replace('NPV.', ''))


if __name__ == '__main__':
    unittest.main()
