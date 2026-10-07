import copy
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime_npc import read_selection
from runtime_resources import archive_xl_resources, Resources


def write_archive(path: Path, hashes) -> None:
    """Minimal RDAR file listing these path hashes, as every game archive does."""
    entries = b''.join(struct.pack('<Q', int(h)) + bytes(48) for h in hashes)
    index = struct.pack('<IIQIII', 8, 20 + len(entries), 0, len(hashes), 0, 0) + entries
    header = struct.pack('<4sIQIQIQ', b'RDAR', 12, 40, len(index), 0, 0, 40 + len(index))
    path.write_bytes(header + index)


def cname(name):
    return {'$type': 'CName', '$storage': 'string', '$value': name}


def part(name, mesh, appearance, kind='entSkinnedMeshComponent'):
    return {'$type': kind, 'name': cname(name), 'mesh': {'DepotPath': {'$value': mesh}},
            'meshAppearance': cname(appearance)}


def app(template, *parts):
    return {'Data': {'RootChunk': {'appearances': [{'Data': {'name': cname(template), 'components': list(parts)}}]}}}


def mesh(*names, materials=()):
    return {'Data': {'RootChunk': {'appearances': [{'Data': {'name': cname(n)}} for n in names],
                                   'materialEntries': [{'name': cname(m)} for m in materials]}}}


class Reader:
    def __init__(self, resources, patches=None):
        self.resources, self.patches, self.hashes = resources, patches or {}, {}

    def read(self, path):
        return copy.deepcopy(self.resources[path])

    def register(self, value, suffix):
        self.hashes[value] = suffix
        return value

    def source(self, path):
        return path


def choose(reader, option, selected):
    return read_selection(reader, dict(name=option, resource_path='a.app', selected_name=selected), {})[1]


class CcxlColorTests(unittest.TestCase):
    def test_option_without_hair_in_its_name_is_recolored(self):
        # Raven: option sb_raven_pma, one template appearance 01_blonde_platinum.
        reader = Reader({'a.app': app('01_blonde_platinum', part('sb_raven_pma', 'r.mesh', 'blonde_platinum')),
                         'r.mesh': mesh('blonde_platinum', 'brown_liquorice')})
        chosen = choose(reader, 'sb_raven_pma', '05_brown_liquorice')
        self.assertEqual(chosen['components'][0]['meshAppearance']['$value'], 'brown_liquorice')

    def test_dynamic_context_material_accepts_any_color(self):
        # Hair Collection 3: one mesh appearance plus @context/@long/@cap.
        reader = Reader({'a.app': app('01_blonde_platinum', part('hair_part_01', 'h.mesh', 'blonde_platinum')),
                         'h.mesh': mesh('blonde_platinum', materials=('@context', '@long', '@cap'))})
        chosen = choose(reader, 'acacia_hair_part_01', '02_red_merlot')
        self.assertEqual(chosen['components'][0]['meshAppearance']['$value'], 'red_merlot')

    def test_clip_without_hair_colors_keeps_standard(self):
        # Sub Hair Pack: *_hair_prop uses appearance "standard".
        reader = Reader({'a.app': app('01_blonde_platinum', part('sub_fuze_hair', 'f.mesh', 'blonde_platinum'),
                                      part('sub_fuze_hair_prop', 'p.mesh', 'standard')),
                         'f.mesh': mesh('blonde_platinum', 'brown_liquorice'), 'p.mesh': mesh('standard')})
        chosen = choose(reader, 'sub_fuze_hair', '05_brown_liquorice')
        self.assertEqual([c['meshAppearance']['$value'] for c in chosen['components']],
                         ['brown_liquorice', 'standard'])
        self.assertEqual(chosen['_npv_kept'], ['sub_fuze_hair_prop=standard'])

    def test_piece_whose_mesh_the_mod_does_not_ship_is_kept(self):
        # Hair Collection 3 lists raenef\<style>\meshes\hair_shadow.mesh, absent.
        from runtime_resources import ResourceMissing

        class Missing(Reader):
            def read(self, path):
                if path not in self.resources:
                    raise ResourceMissing('Recurso nao encontrado nos mods instalados: ' + path)
                return super().read(path)
        reader = Missing({'a.app': app('01_blonde_platinum', part('hair_part_01', 'h.mesh', 'blonde_platinum'),
                                       part('hair_shadow', 'raenef\\acacia\\meshes\\hair_shadow.mesh', 'default')),
                          'h.mesh': mesh('blonde_platinum', materials=('@context',))})
        chosen = choose(reader, 'acacia_hair_part_01', '02_red_merlot')
        self.assertEqual([c['meshAppearance']['$value'] for c in chosen['components']], ['red_merlot', 'default'])
        self.assertEqual(chosen['_npv_kept'], ['hair_shadow=default'])

    def test_mesh_referenced_by_hash(self):
        reader = Reader({'a.app': app('01_blonde_platinum', part('sub_stealth_hair', '2499028487530490373', 'blonde_platinum')),
                         '2499028487530490373': mesh('blonde_platinum', 'red_merlot')})
        choose(reader, 'sub_stealth_hair', '02_red_merlot')
        self.assertEqual(reader.hashes, {'2499028487530490373': '.mesh'})

    def test_list_patch_adds_appearances_to_target_mesh(self):
        reader = Reader({'a.app': app('01_blonde_platinum', part('brows', 'base\\brows.mesh', 'blonde_platinum')),
                         'base\\brows.mesh': mesh('blonde_platinum'), 'mod\\extra.mesh': mesh('teal_ash')},
                        patches={'base\\brows.mesh': ['mod\\extra.mesh']})
        chosen = choose(reader, 'brows', '33_teal_ash')
        self.assertEqual(chosen['components'][0]['meshAppearance']['$value'], 'teal_ash')

    def test_morph_target_component_reads_its_base_mesh(self):
        brow = {'$type': 'entMorphTargetSkinnedMeshComponent', 'name': cname('heb'),
                'morphResource': {'DepotPath': {'$value': 'b.morphtarget'}}, 'meshAppearance': cname('black_carbon')}
        reader = Reader({'a.app': app('black_carbon', brow),
                         'b.morphtarget': {'Data': {'RootChunk': {'baseMesh': {'DepotPath': {'$value': 'b.mesh'}}}}},
                         'b.mesh': mesh('black_carbon', 'brown_liquorice')})
        chosen = choose(reader, 'ark_eyebrows_02_ccxl_01', '05_brown_liquorice')
        self.assertEqual(chosen['components'][0]['meshAppearance']['$value'], 'brown_liquorice')


class ArchiveXlResourceTests(unittest.TestCase):
    def test_copy_and_list_patch_are_read_from_installed_xl(self):
        # Shapes copied from the installed CCXL Clinic and Beautiful Eyebrows .xl.
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'a.xl').write_text(
                'customizations:\n  female: x\\f.inkcharcustomization\n'
                'resource:\n  copy: \n    bby\\app.app:\n      - bby\\app_2.app\n'
                '  patch:\n    bby\\xtra.mesh:\n      - base\\a.mesh\n      - base\\b.mesh\n'
                '    arkhe_copy\\m.morphtarget:\n      props: [ blob, targets ]\n'
                '      targets: &T\n        - arkhe\\m_01.morphtarget\n'
                'localization:\n  onscreens:\n    en-us: x.json\n', encoding='utf8')
            (Path(folder) / 'b.xl').write_text('resource:\n  copy:\n    src.mesh: [dst1.mesh, Dst2.mesh]\n', encoding='utf8')
            copies, patches = archive_xl_resources([Path(folder)])
        self.assertEqual(copies, {'bby\\app_2.app': 'bby\\app.app', 'dst1.mesh': 'src.mesh', 'dst2.mesh': 'src.mesh'})
        self.assertEqual(patches, {'base\\a.mesh': ['bby\\xtra.mesh'], 'base\\b.mesh': ['bby\\xtra.mesh']})

    def test_hash_request_extracted_under_its_name_is_found(self):
        import runtime_resources
        from unittest.mock import patch
        named = 'arkhe\\ccxl_eyebrows_02\\models\\pma\\heb_000_pma__morphs_06.morphtarget'

        def fake_cli(cli, command, root, flag, out, *rest):
            target = Path(out).joinpath(*named.split('\\'))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'morph')
            return ''
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder)
            (game / 'archive/pc/mod').mkdir(parents=True)
            write_archive(game / 'archive/pc/mod/arkhe.archive', [2625047240192513416])
            reader = Resources(game, game / 'cli.exe', game / 'cache')
            key = reader.register('2625047240192513416', '.morphtarget')
            with patch.object(runtime_resources, 'cli_run', side_effect=fake_cli):
                reader.fetch([key])
            self.assertEqual(reader.path(key).read_bytes(), b'morph')

    def test_reader_follows_copy_to_archived_source(self):
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder)
            (game / 'archive/pc/mod').mkdir(parents=True)
            (game / 'archive/pc/mod/c.xl').write_text(
                'resource:\n  copy:\n    base\\hx_000__cyberware.app:\n      - based\\zwei\\hx_000__cyberware_2.app\n',
                encoding='utf8')
            reader = Resources(game, game / 'cli.exe', game / 'cache')
            self.assertEqual(reader.source('based\\zwei\\HX_000__cyberware_2.app'), 'base\\hx_000__cyberware.app')


if __name__ == '__main__':
    unittest.main()
