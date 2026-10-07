import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import runtime_body
import runtime_npc


def option(name, app, selected, body_part="Body"):
    return dict(name=name, body_part=body_part, kind="appearance", resource_path=app, selected_name=selected,
                active=True, editable=True, selected_index=0, choice_count=1)


CENSORED = "base\\characters\\common\\player_base_bodies\\appearances\\t0_000_base__censored_items.app"
SKIN = option("body_color", "base\\characters\\common\\player_base_bodies\\appearances\\t0_000_base__full.app",
              "t0_000_pwa_base__01_ca_pale")


class DefaultUnderwearTest(unittest.TestCase):
    def test_female_full_gets_bra_and_panties_items(self):
        result = runtime_npc.default_underwear([SKIN, option("underpants", CENSORED, "female_001")], "female", "full")
        self.assertEqual(result[0], SKIN)
        self.assertEqual([(o["name"], o["resource_path"].rsplit("\\", 1)[1], o["selected_name"]) for o in result[1:]],
                         [("underpants:t1", "t1_underwear_01.app", "basic_01_w"),
                          ("underpants:l1", "l1_underwear_01.app", "basic_01_w")])
        self.assertFalse(any(o["resource_path"] == CENSORED for o in result))

    def test_male_gets_boxers_only(self):
        result = runtime_npc.default_underwear([option("underpants", CENSORED, "male_001")], "male")
        self.assertEqual([(o["name"], o["selected_name"]) for o in result], [("underpants:l1", "basic_01_m")])

    def test_default_is_bottom_only(self):
        # Author's print 01/10/2026: the bra t1_057 does not cover a modded body; the panties sit.
        result = runtime_npc.default_underwear([SKIN, option("underpants", CENSORED, "female_001")], "female")
        self.assertEqual([(o["name"], o["selected_name"]) for o in result[1:]], [("underpants:l1", "basic_01_w")])

    def test_none_drops_the_censorship_piece_too(self):
        result = runtime_npc.default_underwear([SKIN, option("underpants", CENSORED, "female_001")], "female", "none")
        self.assertEqual(result, [SKIN])
        with self.assertRaises(ValueError):
            runtime_npc.default_underwear([SKIN], "female", "bikini")

    def test_package_keeps_the_choice(self):
        import npv_package
        self.assertEqual([npv_package.underwear_field(v) for v in (None, "", "full", "none")],
                         ["bottom", "bottom", "full", "none"])
        with self.assertRaises(npv_package.PackageError):
            npv_package.underwear_field("bikini")
        self.assertEqual(tuple(npv_package.UNDERWEAR_MODES), tuple(runtime_npc.UNDERWEAR_MODES))
        entry = Path(runtime_npc.__file__).with_name("runtime_entry.py").read_text(encoding="utf8")
        self.assertIn('"underwear": underwear}', entry)

    def test_without_underpants_nothing_is_added(self):
        self.assertEqual(runtime_npc.default_underwear([SKIN], "female"), [SKIN])

    def test_items_stay_off_the_runtime_body_slice(self):
        result = runtime_npc.default_underwear([SKIN, option("underpants", CENSORED, "female_001")], "female", "full")
        body, rest = runtime_body.slice_options(result)
        self.assertEqual([o["name"] for o in body], ["body_color"])
        self.assertEqual([o["name"] for o in rest], ["underpants:t1", "underpants:l1"])

    def test_build_uses_the_items(self):
        # The build replaces the option before reading the .app files (no censorship file is requested).
        source = Path(runtime_npc.__file__).read_text(encoding="utf8")
        self.assertIn("default_underwear(selected_appearances(", source)


if __name__ == "__main__":
    unittest.main()
