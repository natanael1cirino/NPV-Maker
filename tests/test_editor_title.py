import re
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'src/redscript/NPVMaker.reds'
STUDIO = Path(__file__).resolve().parents[1] / 'src/redscript/NPVMakerStudio.reds'


def between(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


class EditorTitleTest(unittest.TestCase):
    """Runtime 02/10/2026: SetText on the stock title lost to its inkTextReplaceAnimationController.

    UI07 (04/10/2026): the NPV tools take the place of the stock "Customize Your Look" heading
    (GroupListArea/list_header), hidden only while the NPV session runs and restored when the screen closes.
    The old NPV panel built after the title is gone."""

    def setUp(self):
        self.menu = SOURCE.read_text(encoding='utf8')
        self.studio = STUDIO.read_text(encoding='utf8')
        init = between(self.menu, 'protected cb func OnInitialize() -> Bool {\n  let result = wrappedMethod();\n'
                                  '  let session = NPVMakerSession.GetInstance();', '  return result;')
        self.init = init
        self.block = between(init, 'let title = this.NPVFindChild(', 'this.npvStudio = NPVStudioView.Create(')

    def test_stock_title_is_hidden_not_rewritten(self):
        self.assertIn('if session.active {', self.init.split('let title = ')[0])
        self.assertIn('title.SetVisible(false);', self.block)
        self.assertIsNone(re.search(r'\btitle\.SetText\(', self.block))
        self.assertIn('header.SetText(NPVText.T("DEFINIR APARENCIA DO NPV"));', self.block)
        self.assertIn('header.Reparent(line);', self.block)

    def test_stock_heading_hidden_in_session_and_restored_on_close(self):
        self.assertIn('return this.NPVFindChild(this.GetRootCompoundWidget(), n"GroupListArea", n"list_header");',
                      self.studio)
        build = between(self.studio, 'private func Build() -> Void {', 'let nav = this.Row(this.root);')
        self.assertIn('this.sectionHeadingVisible = this.sectionHeading.IsVisible();', build)
        self.assertIn('this.sectionHeading.SetVisible(false);', build)
        dispose = between(self.studio, 'public func Dispose() -> Void {', '\n  }')
        self.assertIn('this.sectionHeading.SetVisible(this.sectionHeadingVisible);', dispose)
        uninit = between(self.menu, 'protected cb func OnUninitialize() -> Bool {', 'return wrappedMethod();')
        self.assertIn('this.npvStudio.Dispose();', uninit)
        self.assertNotIn('let panel = new inkVerticalPanel();', self.init)


if __name__ == '__main__':
    unittest.main()
