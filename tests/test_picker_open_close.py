import re
import sys
import unittest
from pathlib import Path


STUDIO = Path(__file__).resolve().parents[1] / 'src/redscript/NPVMakerStudio.reds'


def between(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


class PickerOpenCloseTest(unittest.TestCase):
    """Runtime 06/10/2026 (author, editor of the NPV): the hair color choice "opens and closes" and the list comes back
    at the top after a choice. Gamelog: hair_color_cyberware_01 opened 81 times; every other option once. OpenChoice
    accepted options that Tick closes on the next frame (isActive / isCensored / name), and the native list was shown
    again without going back to the row."""

    def setUp(self):
        self.text = STUDIO.read_text(encoding='utf8')

    def test_open_uses_the_conditions_that_keep_the_picker_open(self):
        can_open = between(self.text, 'public func CanOpen(', '\n  }\n')
        self.assertIn('option.isActive', can_open)
        self.assertIn('!option.isCensored', can_open)
        self.assertIn('!ArrayContains(this.nativeOnly, option.info.name)', can_open)
        tick = between(self.text, 'public func Tick() -> Void {', '\n  }\n')
        self.assertIn('!fresh.isActive', tick)
        self.assertIn('fresh.isCensored', tick)
        open_choice = between(self.text, 'public func OpenChoice(', '\n  }\n')
        self.assertIn('if !this.CanOpen(row) { return false; };', open_choice)

    def test_color_the_picker_cannot_keep_goes_to_the_game_picker(self):
        hook = between(self.text, 'protected cb func OnColorPickerTriggered(', '\n}\n')
        fallback = hook.index('if !this.npvStudio.CanOpen(row) { return wrappedMethod(widget); };')
        self.assertLess(fallback, hook.index('row.NPVResetThumbnailTrigger();'))

    def test_closing_by_itself_right_after_opening_is_logged_and_remembered(self):
        close = between(self.text, 'public func ClosePicker(opt reason: String)', '\n  }\n')
        self.assertIn('ModLog(n"NPVMaker", "picker closed by itself: "', close)
        self.assertIn('ArrayPush(this.nativeOnly, this.optionName);', close)
        self.assertIn('this.ClosePicker("list rebuilt");', self.text)
        self.assertIsNone(re.search(r'this\.ClosePicker\(\);\s*return;', between(self.text, 'public func Tick()', '\n  }\n')))

    def test_list_returns_to_the_row_after_the_picker(self):
        self.assertIn('this.RememberRow(row, option.info.name);', self.text)
        self.assertIn('this.returnTicks = 3;', between(self.text, 'public func ClosePicker(', '\n  }\n'))
        self.assertIn('this.menu.NPVStudioEnsureVisible(target);', self.text)
        self.assertIn('this.m_scrollController.EnsureVisible(widget);', self.text)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        STUDIO = Path(sys.argv.pop())
    unittest.main()
