import re
import sys
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'src/redscript'
CLASS = re.compile(r'^\s*(?:public\s+|private\s+)?(?:abstract\s+|final\s+)*class\s+(\w+)', re.M)
ANNOTATION = re.compile(r'^\s*@(addField|addMethod|wrapMethod|replaceMethod)\((\w+)\)', re.M)


def own_class_annotations(folder):
    texts = {path.name: path.read_text(encoding='utf8') for path in sorted(Path(folder).glob('*.reds'))}
    classes = {name for text in texts.values() for name in CLASS.findall(text)}
    return [(file, kind, target) for file, text in texts.items()
            for kind, target in ANNOTATION.findall(text) if target in classes]


class OwnClassAnnotationsTest(unittest.TestCase):
    """Runtime 06/10/2026: @addField(NPVMakerSession) in NPVMakerManager.reds. With some mod lists scc 0.5.31 wrote
    the field before the NPVMakerSession class in final.redscripts.modded; the game loaded a field with no owner and
    crashed at startup (EXCEPTION_ACCESS_VIOLATION reading 0x8, Cyberpunk2077.exe+0x5C5C10). Without NPV Maker the game
    opened. Members of NPV classes are declared in the class body; annotations only target game classes."""

    def test_no_annotation_targets_a_class_of_this_mod(self):
        self.assertEqual(own_class_annotations(SOURCE), [])

    def test_manager_operation_lives_in_the_session_body(self):
        text = (SOURCE / 'NPVMaker.reds').read_text(encoding='utf8')
        body = text[text.index('public class NPVMakerSession extends ScriptableService {'):]
        body = body[:body.index('\n}\n')]
        self.assertIn('public let managerOperation: ref<NPVManagerOperation>;', body)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        print(own_class_annotations(sys.argv[1]))
    else:
        unittest.main()
