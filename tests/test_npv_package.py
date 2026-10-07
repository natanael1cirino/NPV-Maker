import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import npv_package as pkg
import runtime_entry as worker
from runtime_resources import path_hash

try:
    from lupa.luajit21 import LuaRuntime
except ImportError:
    sys.path.insert(0, str(Path(os.environ.get('NPV_LUA_DEPS', str(ROOT / 'tools/deps')))))
    try:
        from lupa.luajit21 import LuaRuntime
    except ImportError:  # pragma: no cover
        LuaRuntime = None

EKT_MESH = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa_c__basehead\\h0_000_pwa_c__basehead.mesh'
EKT_MORPH = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa__morphs.morphtarget'
HAIR = 'peachu_hairs\\peachu_y2kponytail\\meshes\\peachu_y2kponytail_pt1.mesh'
GALAXY_PATCH = 'protossvoid\\dreamgalaxyeyesccxl\\meshes\\patch.mesh'
EYE_APP = 'archive_xl\\characters\\head\\player_base_heads\\appearances\\head\\he_000_pwa__basehead.app'
BODY = 'base\\characters\\common\\player_base_bodies\\player_female_average\\t0_000_pwa_base__full.mesh'
# Folder names measured in vortex.deployment.json on 30/09/2026.
EKT_FOLDER = 'VTK body user - Vanilla eyes compatible-16930-1-06-1737836074'
HAIR_FOLDER = 'Y2K Ponytail - CCXL-20175-2-1748346794'
GALAXY_FOLDER = 'DreamGalaxyEyesCCXL By Protossvoid 34080 1 2026-09-18T23-31Z rxs7xRsWV'


def key(resource):
    return pkg.resource_key(resource)


class FakeLocator:
    """Measured shape of the seila build: head served by EKT over the vanilla path, hair and the
    Dream Galaxy patch only in their mods, eye .app from the ArchiveXL bundle, body vanilla."""

    def __init__(self, mods=None, base=None, frameworks=None):
        self.mods = mods if mods is not None else {
            '003_EKT_CC_AsianVersion_VTK_Vanilla_eyes_V4.archive': {key(EKT_MESH), key(EKT_MORPH)},
            'vtk_VanillaHD_Head_xBaebsae.archive': {key(EKT_MESH)},
            'peachu_y2kponytail_CCXL.archive': {key(HAIR)},
            'DreamGalaxyEyesCCXL.archive': {key(GALAXY_PATCH)}}
        self.base = base if base is not None else {key(EKT_MESH), key(EKT_MORPH), key(BODY)}
        self.frameworks = frameworks if frameworks is not None else {'ArchiveXL.archive': {key(EYE_APP)}}

    def mod_owners(self, k):
        return [name for name, hashes in sorted(self.mods.items(), key=lambda i: i[0].lower()) if k in hashes]

    def framework_owner(self, k):
        return next((name for name, hashes in self.frameworks.items() if k in hashes), None)

    def in_base(self, k):
        return k in self.base

    def relative(self, archive):
        if archive in self.frameworks:
            return 'red4ext\\plugins\\ArchiveXL\\Bundle\\' + archive
        return 'archive\\pc\\mod\\' + archive


SOURCES = {'archive\\pc\\mod\\003_ekt_cc_asianversion_vtk_vanilla_eyes_v4.archive': EKT_FOLDER,
           'archive\\pc\\mod\\peachu_y2kponytail_ccxl.archive': HAIR_FOLDER,
           'archive\\pc\\mod\\dreamgalaxyeyesccxl.archive': GALAXY_FOLDER,
           'red4ext\\plugins\\archivexl\\bundle\\archivexl.archive': 'ArchiveXL-4198-1-26-1777298982'}

SEILA_ENTRIES = [
    {'resource': EKT_MESH, 'archive': '003_EKT_CC_AsianVersion_VTK_Vanilla_eyes_V4.archive', 'via': 'read'},
    {'resource': EKT_MORPH, 'archive': '003_EKT_CC_AsianVersion_VTK_Vanilla_eyes_V4.archive', 'via': 'read'},
    {'resource': HAIR, 'archive': None, 'via': 'reference'},
    {'resource': GALAXY_PATCH, 'archive': None, 'via': 'xl_patch'},
    {'resource': EYE_APP, 'archive': 'ArchiveXL.archive', 'via': 'read'},
    {'resource': BODY, 'archive': None, 'via': 'reference'},
    {'resource': 'npvmaker\\generated\\0e790e8bcc899ae5\\meshes\\eyes.mesh', 'archive': None, 'via': 'reference'},
    {'resource': 'ghost\\nowhere.mesh', 'archive': None, 'via': 'puppet'},
]


class IdentityTests(unittest.TestCase):
    def test_character_id_format_and_slug(self):
        cid = pkg.new_character_id('Seila')
        self.assertRegex(cid, r'^npv_seila_[0-9a-f]{8}$')
        self.assertTrue(pkg.CHARACTER_ID.fullmatch(cid))
        self.assertEqual(pkg.slug('Sína Virelli!!'), 'sina_virelli')
        self.assertEqual(pkg.slug('***'), 'npv')
        self.assertRegex(pkg.new_character_id('x' * 80), r'^npv_x{24}_[0-9a-f]{8}$')

    def test_package_identity_depends_only_on_character_id(self):
        first = pkg.package_identity('npv_seila_7c42a91f')
        self.assertEqual(first, pkg.package_identity('npv_seila_7c42a91f'))
        self.assertRegex(first, r'^[0-9a-f]{64}$')
        self.assertNotEqual(first, pkg.package_identity('npv_seila_7c42a920'))
        with self.assertRaises(pkg.PackageError):
            pkg.package_identity('../etc')

    def test_meta_sidecar_is_not_a_project_and_keeps_the_project_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'npv-20260930T020150Z-0001.npv.json'
            project.write_bytes(b'{"format": "npv-maker-project"}')
            before = hashlib.sha256(project.read_bytes()).hexdigest()
            pkg.write_meta(project, {'format': 'npv-maker-project-meta', 'schema_version': 1,
                                     'character_id': 'npv_seila_7c42a91f'})
            self.assertEqual(pkg.meta_path(project).name, 'npv-20260930T020150Z-0001.npv.meta.json')
            self.assertFalse(pkg.PROJECT_NAME.fullmatch(pkg.meta_path(project).name))
            self.assertEqual(hashlib.sha256(project.read_bytes()).hexdigest(), before)
            self.assertEqual(pkg.read_meta(project)['character_id'], 'npv_seila_7c42a91f')


class VortexTests(unittest.TestCase):
    def test_measured_folder_names(self):
        self.assertEqual(pkg.parse_vortex_folder(EKT_FOLDER), ('VTK body user - Vanilla eyes compatible', 16930))
        self.assertEqual(pkg.parse_vortex_folder(HAIR_FOLDER), ('Y2K Ponytail - CCXL', 20175))
        self.assertEqual(pkg.parse_vortex_folder(GALAXY_FOLDER), ('DreamGalaxyEyesCCXL By Protossvoid', 34080))
        self.assertEqual(pkg.parse_vortex_folder('NATURAL - B02 - CCXL-15176-1-0-1763141066'),
                         ('NATURAL - B02 - CCXL', 15176))

    def test_other_names_get_no_invented_id(self):
        for folder in ('Companion Expansion 1.0', 'NCA_Traducao_PTBR_1.0.0', 'NPV-maker-0.4.21-cilios-autonomous-test'):
            self.assertEqual(pkg.parse_vortex_folder(folder), (folder, None))


class DetectionTests(unittest.TestCase):
    def test_seila_requirements_by_real_origin(self):
        found = pkg.detect_dependencies(Path('.'), SEILA_ENTRIES, FakeLocator(), SOURCES)
        by_name = {d['name']: d for d in found['dependencies']}
        self.assertEqual(sorted(by_name), ['ArchiveXL', 'DreamGalaxyEyesCCXL By Protossvoid', 'VTK body user - Vanilla eyes compatible',
                                           'Y2K Ponytail - CCXL'])
        ekt = by_name['VTK body user - Vanilla eyes compatible']
        # The recorded archive wins over the other mod that ships the same path.
        self.assertEqual(ekt['archives'], ['003_EKT_CC_AsianVersion_VTK_Vanilla_eyes_V4.archive'])
        self.assertEqual({r['kind'] for r in ekt['resources']}, {'override'})
        self.assertEqual((ekt['nexus_mod_id'], ekt['url']), (16930, 'https://www.nexusmods.com/cyberpunk2077/mods/16930'))
        self.assertTrue(ekt['required_for_rebuild'])
        self.assertEqual(by_name['Y2K Ponytail - CCXL']['resources'][0]['kind'], 'own_path')
        galaxy = by_name['DreamGalaxyEyesCCXL By Protossvoid']
        self.assertFalse(galaxy['required_for_rebuild'])
        self.assertIn('patch', galaxy['reason'])
        self.assertEqual(found['counts'], {'VANILLA': 1, 'MOD DE TERCEIRO': 5, 'GERADO PELO NPV MAKER': 1,
                                           'ORIGEM DESCONHECIDA': 1})
        self.assertEqual(found['unknown'], ['ghost\\nowhere.mesh'])

    def test_archive_without_vortex_keeps_its_name_and_no_id(self):
        found = pkg.detect_dependencies(Path('.'), SEILA_ENTRIES[2:3], FakeLocator(), {})
        self.assertEqual(found['dependencies'][0]['name'], 'peachu_y2kponytail_CCXL')
        self.assertIsNone(found['dependencies'][0]['nexus_mod_id'])
        self.assertEqual(found['dependencies'][0]['detected_from'], 'archive')

    def test_build_resources_reads_stamps_references_patches_and_puppet(self):
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            installed = job / 'npc/installed-resources'
            (installed / 'base/characters').mkdir(parents=True)
            (installed / 'base/characters/x.mesh.npvsrc').write_text(
                'EKT.archive|10|20\nprops|arkhe\\donor.mesh|renderResourceBlob\ndonor|Arkhe.archive|1|2', encoding='utf8')
            (installed / 'hashes').mkdir()
            (installed / 'hashes/8931201215813019710.morphtarget.npvsrc').write_text('Mod.archive|1|2', encoding='utf8')
            manifest = {'components': [{'mesh': HAIR}, {'mesh': 'npvmaker\\generated\\a\\m.mesh'}, {'mesh': None}],
                        'diagnostics': [{'external_dependency': {'type': 'archivexl_patch', 'patch': GALAXY_PATCH}}]}
            recipe = {'runtime_manifest': {'components': [{'state': 'LOADED', 'hash': '8931201215813019710'},
                                                          {'state': 'UNOBSERVED', 'path': 'x\\y.mesh'}]}}
            entries = pkg.build_resources(job, manifest, recipe)
        resources = {e['resource']: e for e in entries}
        self.assertEqual(resources['base\\characters\\x.mesh']['archive'], 'EKT.archive')
        self.assertIn('arkhe\\donor.mesh', resources)
        self.assertEqual(resources['8931201215813019710']['archive'], 'Mod.archive')
        self.assertEqual(resources[GALAXY_PATCH]['via'], 'xl_patch')
        self.assertIn(HAIR, resources)
        self.assertNotIn('x\\y.mesh', resources)
        self.assertEqual(len(entries), len(resources))


def seila_recipe():
    return {'format': 'npv-maker-project', 'schema_version': 1, 'name': 'seila', 'body': 'female', 'voice': 'female',
            'options': [dict(name='body_color', body_part='Body', kind='appearance', selected_name='default',
                             selected_index=0, choice_count=1, active=True, editable=False, censored=False)],
            'dependencies': [], 'dependency_status': 'unresolved', 'npc_status': 'not_generated',
            'runtime_manifest': {'components': []}}


class Fixture:
    """A game tree with one imported, tested NPV (receipt, ready build, job, saved project)."""

    def __init__(self, temp: Path, recipe: dict | None = None):
        self.game = temp / 'game'
        self.plugin = self.game / 'red4ext/plugins/NPVMaker'
        self.projects = self.game / 'bin/x64/plugins/cyber_engine_tweaks/mods/NPVMaker/projects'
        (self.projects / 'exports').mkdir(parents=True)
        self.recipe_bytes = json.dumps(recipe or seila_recipe()).encode('utf8')
        self.source = hashlib.sha256(self.recipe_bytes).hexdigest()
        self.digest = hashlib.sha256((self.source + ':selected_tpp').encode()).hexdigest()
        self.token = self.digest[:16]
        self.project = self.projects / 'npv-20260930T020150Z-0001.npv.json'
        self.project.write_bytes(self.recipe_bytes)
        job = self.plugin / 'data/jobs' / (self.token + '-abcd1234')
        (job / 'npc/installed-resources/base/characters').mkdir(parents=True)
        (job / 'project.npv.json').write_bytes(self.recipe_bytes)
        self.archive = job / 'npc/packed/archive_source.archive'
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(b'RDAR npv de teste')
        self.entity = 'npvmaker\\generated\\' + self.token + '\\character.ent'
        manifest = {'format': 'npv-maker-runtime-npc', 'project_sha256': self.digest, 'body_strategy': 'selected_tpp',
                    'components': [{'mesh': HAIR}], 'diagnostics': [], 'local_use_only': True,
                    'record_id': 'Character.NPVMaker_' + self.token, 'entity_path': self.entity,
                    'base_record': 'Character.bella', 'appearance_name': 'default', 'archive': str(self.archive),
                    'name': 'seila', 'body': 'female', 'name_key': 'NPVMaker-' + self.token + '-name',
                    'photomode': None, 'archive_xl': '', 'underwear': 'bottom', 'embedded_copies': [],
                    'kept_morphtargets': ['base\\characters\\head\\h0_000_pwa__morphs.morphtarget'],
                    'runtime_morphs': [['h012', 'nose'], ['h134', 'jaw']]}
        self.manifest_path = job / 'npc/manifest.json'
        (job / 'npc/manifest.json').write_text(json.dumps(manifest), encoding='utf8')
        (self.plugin / 'data/imports').mkdir(parents=True)
        (self.plugin / 'data/imports' / (self.digest + '.json')).write_text(json.dumps(
            {'record_id': 'Character.NPVMaker_' + self.token, 'name': 'seila [SELECTED_TPP]',
             'project_sha256': self.digest, 'manifest': str(job / 'npc/manifest.json')}), encoding='utf8')
        self.exports = temp / 'Documents/NPVMaker/exports'

    def draft(self):
        return pkg.draft(self.plugin, self.projects, self.game, self.token, FakeLocator(), SOURCES)


def form(version='1.0.0', **extra):
    fields = {'display_name': 'Seila', 'author': 'Natanael', 'version': version, 'description': 'Teste',
              'source_preset': {'name': 'Mako', 'author': 'autor do preset', 'url': 'https://www.nexusmods.com/cyberpunk2077/mods/24229',
                                'nexus_mod_id': 24229, 'version': ''}}
    fields.update(extra)
    return fields


SKIN = 'base\\characters\\common\\skin\\character_mat_instance\\'
PALE_MI = SKIN + 'female\\body\\female_01_ca_pale.mi'
PALE_BASE_MI = SKIN + '01_ca_pale.mi'
TAN_MI = SKIN + 'female\\body\\female_03_ca_senna.mi'
HEAD_D01 = 'base\\characters\\head\\player_base_heads\\player_female_average\\h0_000_pwa_c__basehead\\textures\\h0_000_pwa_c__basehead_d01.xbm'
SKIN_MT = 'base\\materials\\skin.mt'


def depot(path):
    return {'DepotPath': {'$type': 'ResourcePath', '$storage': 'string', '$value': path}, 'Flags': 'Default'}


def cname(value):
    return {'$type': 'CName', '$storage': 'string', '$value': value}


def mesh_doc():
    """Shape of t0_000_pwa_base__full.mesh as WolvenKit 8.19 writes it: one appearance per skin tone, local
    instances for the tones, measured 04/10/2026."""
    return {'Data': {'RootChunk': {
        'appearances': [{'HandleId': '0', 'Data': {'name': cname('01_ca_pale'), 'chunkMaterials': [cname('01_ca_pale')] * 3}},
                        {'HandleId': '1', 'Data': {'name': cname('03_ca_senna'), 'chunkMaterials': [cname('03_ca_senna')]}},
                        {'HandleId': '2', 'Data': {'name': cname('dyn'), 'chunkMaterials': [cname('ginger@long')]}}],
        'materialEntries': [{'index': 0, 'isLocalInstance': 1, 'name': cname('01_ca_pale')},
                            {'index': 0, 'isLocalInstance': 0, 'name': cname('03_ca_senna')}],
        'localMaterialBuffer': {'materials': [{'$type': 'CMaterialInstance', 'baseMaterial': depot(PALE_MI), 'values': []}]},
        'externalMaterials': [depot(TAN_MI)]}}}


def mi_doc(base, *textures):
    return {'Data': {'RootChunk': {'$type': 'CMaterialInstance', 'baseMaterial': depot(base),
                                   'values': [{'$type': 'rRef:CBitmapTexture', 'Value': depot(t)} for t in textures]}}}


class FakeReader:
    """Files as the game serves them; the mod .mi of the pale tone points at the head texture."""

    def __init__(self, docs=None):
        self.docs = docs if docs is not None else {
            BODY: mesh_doc(), PALE_MI: mi_doc(PALE_BASE_MI, HEAD_D01), PALE_BASE_MI: mi_doc(SKIN_MT),
            TAN_MI: mi_doc(SKIN_MT)}

    def read(self, path):
        if path not in self.docs:
            raise pkg.material_chain.READ_ERRORS[0]('Recurso nao encontrado: ' + path)
        return self.docs[path]

    def mesh(self, path):
        return self.read(path)

    def references(self, path):
        return pkg.material_chain.depot_paths(self.read(path).get('Data'), [])


def material_locator():
    # APreem wins the pale .mi over ZSkin by load order; Shader wins skin.mt; Senna only changes another tone.
    return FakeLocator(mods={'APreem.archive': {key(PALE_MI), key(PALE_BASE_MI), key(SKIN_MT)},
                             'ZSkin.archive': {key(PALE_MI)},
                             'Head UST.archive': {key(HEAD_D01)},
                             'Senna.archive': {key(TAN_MI)},
                             '0Shader.archive': {key(SKIN_MT)}},
                       base={key(p) for p in (BODY, PALE_MI, PALE_BASE_MI, TAN_MI, HEAD_D01, SKIN_MT)}, frameworks={})


class MaterialChainTests(unittest.TestCase):
    """BUGS 68, author rule 04/10/2026: a mod that replaces a game material or texture the NPV really uses is a
    detected requirement (OBRIGATORIO by default); unused appearances are ignored; shared shaders are only
    information; only the load order winner is credited; dynamic ArchiveXL material names are reported."""

    def chain(self, component):
        return pkg.material_chain.npv_material_files(FakeReader(), {'components': [component]})

    def detect(self, files):
        entries = [{'resource': f, 'archive': None, 'via': 'material'} for f in files]
        return pkg.detect_dependencies(Path('.'), entries, material_locator(), {})

    def test_only_the_chosen_appearance_is_followed(self):
        found = self.chain({'name': 'body', 'mesh': BODY, 'material': '01_ca_pale'})
        self.assertEqual(found['files'], [PALE_MI, PALE_BASE_MI, HEAD_D01, SKIN_MT])
        self.assertNotIn(TAN_MI, found['files'])
        self.assertEqual((found['unresolved'], found['unread']), ([], []))

    def test_used_override_is_a_required_requirement_and_others_are_not(self):
        found = self.detect(self.chain({'name': 'body', 'mesh': BODY, 'material': '01_ca_pale'})['files'])
        by_name = {d['name']: d for d in found['dependencies']}
        self.assertEqual(sorted(by_name), ['APreem', 'Head UST'])
        self.assertTrue(all(d['required_for_rebuild'] for d in by_name.values()))
        self.assertEqual({r['kind'] for r in by_name['APreem']['resources']}, {'material_override'})
        self.assertIn('material', by_name['Head UST']['reason'])
        self.assertEqual([s['name'] for s in found['shared_overrides']], ['0Shader'])

    def test_shader_alone_is_information_not_requirement(self):
        found = self.detect([SKIN_MT])
        self.assertEqual(found['dependencies'], [])
        self.assertEqual([s['name'] for s in found['shared_overrides']], ['0Shader'])

    def test_unused_tone_and_dynamic_names(self):
        senna = self.detect(self.chain({'name': 'body', 'mesh': BODY, 'material': '03_ca_senna'})['files'])
        self.assertEqual([d['name'] for d in senna['dependencies']], ['Senna'])
        dynamic = self.chain({'name': 'hair', 'mesh': BODY, 'material': 'dyn'})
        self.assertEqual((dynamic['files'], dynamic['unresolved']), ([], ['hair']))
        missing = pkg.material_chain.npv_material_files(FakeReader({BODY: mesh_doc()}),
                                                         {'components': [{'name': 'b', 'mesh': BODY, 'material': '01_ca_pale'}]})
        self.assertEqual(missing['unread'], [PALE_MI])

    def test_generated_copy_uses_its_source_mesh(self):
        copy = 'npvmaker\\generated\\abc\\meshes\\92456719280e7c95.mesh'
        found = pkg.material_chain.npv_material_files(FakeReader(), {
            'embedded_copies': [{'resource': copy, 'source': BODY, 'from_mod': False}],
            'components': [{'name': 'head', 'mesh': copy, 'material': '01_ca_pale'}]})
        self.assertIn(PALE_MI, found['files'])

    def test_draft_credits_material_mods_and_says_when_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(Path(temp))
            manifest = json.loads(fx.manifest_path.read_text(encoding='utf8'))
            manifest['components'].append({'name': 'body', 'mesh': BODY, 'material': '01_ca_pale'})
            fx.manifest_path.write_text(json.dumps(manifest), encoding='utf8')
            locator = material_locator()
            locator.mods.update(FakeLocator().mods)
            draft = pkg.draft(fx.plugin, fx.projects, fx.game, fx.token, locator, SOURCES, reader=FakeReader())
            names = [d['name'] for d in draft['dependencies']]
            self.assertIn('APreem', names)
            self.assertIn('Head UST', names)
            self.assertNotIn('ZSkin', names)
            self.assertEqual(draft['material_check']['files'], 4)
            self.assertEqual([s['name'] for s in draft['shared_overrides']], ['0Shader'])
            skipped = pkg.draft(fx.plugin, fx.projects, fx.game, fx.token, locator, SOURCES)
            self.assertEqual(skipped['material_check']['skipped'], 'WolvenKit nao configurado')
            self.assertNotIn('APreem', [d['name'] for d in skipped['dependencies']])


def cr2w(paths):
    """Smallest CR2W the import reader needs: header, table 0 (strings) and table 2 (imports)."""
    import struct
    strings = b'\0'
    offsets = []
    for path in paths:
        offsets.append(len(strings))
        strings += path.encode('utf8') + b'\0'
    head = 40 + 120
    tables = [(head, len(strings), 0), (0, 0, 0), (head + len(strings), len(paths), 0)] + [(0, 0, 0)] * 7
    blob = b'CR2W' + b'\0' * 36 + b''.join(struct.pack('<III', *t) for t in tables) + strings
    return blob + b''.join(struct.pack('<IHH', o, 0, 0) for o in offsets)


def rdar(folder, files):
    """An uncompressed RDAR archive with the given {depot path: bytes}."""
    import struct
    body, entries, segments = b'', b'', b''
    for i, (path, data) in enumerate(files.items()):
        segments += struct.pack('<QII', 40 + len(body), len(data), len(data))
        entries += struct.pack('<QQIIIII', key(path), 0, 1, i, i + 1, 0, 0) + b'\0' * 20
        body += data
    index = 40 + len(body)
    archive = folder / 'Mod.archive'
    archive.write_bytes(struct.pack('<4sIQI', b'RDAR', 12, index, 0) + b'\0' * 20 + body
                        + struct.pack('<IIQIII', 0, 0, 0, len(files), len(files), 0) + entries + segments)
    return archive


class FastReaderTests(unittest.TestCase):
    """Performance round 04/10/2026: references from the archive imports, cached for every NPV; WolvenKit
    only for a file the fast path cannot read."""

    def setUp(self):
        import archive_imports
        self.mod = archive_imports
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'bin/x64').mkdir(parents=True)
        (self.root / 'bin/x64/oo2ext_7_win64.dll').write_bytes(b'')
        self.archive = rdar(self.root, {PALE_MI: cr2w([PALE_BASE_MI, HEAD_D01])})
        archive = self.archive

        class Served:
            def source(self, path):
                return path

            def owners(self, path):
                return [archive] if key(path) == key(PALE_MI) else []

            def base_owner(self, path):
                return None

            def key(self, path):
                return key(path)
        self.served = Served()

    def test_imports_come_from_the_serving_archive_and_are_cached(self):
        cache = self.root / 'cache/references.json'
        refs = self.mod.References(self.root, self.served, cache)
        self.assertEqual(refs.references(PALE_MI), [PALE_BASE_MI, HEAD_D01])
        refs.save()
        doc = json.loads(cache.read_text(encoding='utf8'))
        stamp = next(iter(doc['references']))
        doc['references'][stamp] = ['cached']
        cache.write_text(json.dumps(doc), encoding='utf8')
        self.assertEqual(self.mod.References(self.root, self.served, cache).references(PALE_MI), ['cached'])
        os.utime(self.archive, ns=(1, 1))
        self.assertEqual(self.mod.References(self.root, self.served, cache).references(PALE_MI), [PALE_BASE_MI, HEAD_D01])
        with self.assertRaises(ValueError):
            refs.references(TAN_MI)

    def test_fast_reader_uses_the_job_and_falls_back_per_file(self):
        refs = self.mod.References(self.root, self.served)
        job = self.root / 'job'
        serial = job / 'npc/installed-resources/base/characters/common/player_base_bodies/player_female_average'
        serial.mkdir(parents=True)
        (serial / 't0_000_pwa_base__full.mesh.json').write_text(json.dumps(mesh_doc()), encoding='utf8')
        slow = FakeReader()
        reader = pkg.material_chain.FastReader(pkg.installed_serial(job), refs, slow)
        found = pkg.material_chain.npv_material_files(reader, {'components': [
            {'name': 'body', 'mesh': BODY, 'material': '01_ca_pale'}]})
        self.assertEqual(found['files'], [PALE_MI, PALE_BASE_MI, HEAD_D01, SKIN_MT])
        self.assertEqual(reader.fallbacks, [PALE_BASE_MI])

    def test_missing_game_oodle_disables_the_fast_path(self):
        (self.root / 'bin/x64/oo2ext_7_win64.dll').unlink()
        with self.assertRaises(OSError):
            self.mod.References(self.root, self.served)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fx = Fixture(Path(self.temp.name))

    def export(self, version='1.0.0', dependencies=None, draft=None):
        draft = draft or self.fx.draft()
        deps = dependencies if dependencies is not None else [
            {'name': d['name'], 'author': '', 'url': d['url'], 'nexus_mod_id': d['nexus_mod_id'],
             'required_for_rebuild': d['required_for_rebuild'], 'include': True, 'reason': d['reason'], 'detected': i}
            for i, d in enumerate(draft['dependencies'])]
        return pkg.export(self.fx.plugin, self.fx.projects, self.fx.token,
                          {'fields': form(version), 'dependencies': deps}, draft, self.fx.exports)

    def test_zip_is_the_npv_itself_not_a_recipe(self):
        # Author decision 03/10/2026 (BUGS 67b/67c): the export is the NPV the author tested, its game files.
        done = self.export()
        info = 'red4ext/plugins/NPVMaker/npvs/' + done['character_id'] + '/'
        token = self.fx.token
        with zipfile.ZipFile(done['zip']) as bundle:
            names = bundle.namelist()
            self.assertIn('archive/pc/mod/npvmaker_' + token + '.archive', names)
            self.assertEqual(bundle.read('archive/pc/mod/npvmaker_' + token + '.archive'), self.fx.archive.read_bytes())
            self.assertIn('r6/tweaks/NPVMaker/generated_' + token + '.yaml', names)
            self.assertIn(info + 'npv-package.json', names)
            self.assertIn(info + 'REQUIREMENTS.txt', names)
            self.assertFalse(any('recipe/' in n or n.startswith('red4ext/plugins/NPVMaker/packages/') for n in names))
            manifest = json.loads(bundle.read(info + 'npv-package.json'))
            for relative, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256(bundle.read(relative)).hexdigest(), digest)
        self.assertEqual((manifest['package_type'], manifest['requires_npvmaker'], manifest['embedded']),
                         ('npvmaker_npv_files', True, []))
        self.assertEqual(manifest['recipe'], {'project_sha256': self.fx.source, 'body_strategy': 'selected_tpp'})
        self.assertEqual(manifest['runtime_morphs'], [['h012', 'nose'], ['h134', 'jaw']])
        self.assertEqual(manifest['source_preset']['nexus_mod_id'], 24229)
        self.assertFalse(manifest['source_preset']['required_for_rebuild'])
        self.assertNotIn('Mako', [d['name'] for d in manifest['dependencies']])
        texts = sorted(done['files'])
        self.assertEqual(texts, sorted([done['zip'].name, 'Seila-NEXUS.txt', 'Seila-REQUIREMENTS.txt']))
        nexus = (done['folder'] / 'Seila-NEXUS.txt').read_text(encoding='utf8')
        self.assertIn('Created with [b]NPV Maker[/b]', nexus)
        self.assertIn('NPV Maker (required: it applies the face and body shapes in game)', nexus)
        self.assertNotIn('PACKAGES > INSTALL', nexus)
        self.assertLess(nexus.index('NPV Maker (required'), nexus.index('Y2K Ponytail - CCXL'))
        self.assertIn('[url=https://www.nexusmods.com/cyberpunk2077/mods/24229]Mako[/url]', nexus)
        # BUGS 68: the page is in English, the notice too.
        self.assertIn(pkg.i18n.text(pkg.NOTICE, 'en'), nexus)
        self.assertNotIn(pkg.NOTICE, nexus)

    def test_yaml_carries_the_shapes_applied_in_game(self):
        done = self.export()
        with zipfile.ZipFile(done['zip']) as bundle:
            yaml = bundle.read('r6/tweaks/NPVMaker/generated_' + self.fx.token + '.yaml').decode('utf8')
        self.assertIn('NPVMaker.morphs_' + path_hash(self.fx.entity) + ': [ n"h012", n"nose", n"h134", n"jaw" ]', yaml)

    def rewrite_manifest(self, **changes):
        manifest = json.loads(self.fx.manifest_path.read_text(encoding='utf8'))
        manifest.update(changes)
        for key_name in [k for k, v in changes.items() if v is None]:
            manifest.pop(key_name)
        self.fx.manifest_path.write_text(json.dumps(manifest), encoding='utf8')

    def test_npv_built_before_the_rule_is_refused(self):
        self.rewrite_manifest(embedded_copies=None)
        with self.assertRaisesRegex(pkg.PackageError, 'crie o NPV de novo'):
            self.export()
        self.assertFalse(self.fx.exports.exists() and any(self.fx.exports.iterdir()))

    def test_copy_of_a_mod_piece_is_refused(self):
        self.rewrite_manifest(embedded_copies=[
            {'resource': 'npvmaker\\generated\\x\\meshes\\eyes.mesh', 'source': 'mod\\eye.mesh', 'from_mod': True}])
        with self.assertRaisesRegex(pkg.PackageError, 'copia de peca de mod'):
            self.export()

    def test_copy_of_a_game_piece_is_exported(self):
        self.rewrite_manifest(embedded_copies=[
            {'resource': 'npvmaker\\generated\\x\\meshes\\a.mesh', 'source': 'base\\a.mesh', 'from_mod': False}])
        self.assertTrue(self.export()['zip'].is_file())

    def test_character_id_is_created_once_and_kept_across_versions(self):
        first = self.export('1.0.0')
        meta = pkg.read_meta(self.fx.project)
        self.assertEqual(meta['character_id'], first['character_id'])
        self.assertEqual(self.fx.project.read_bytes(), self.fx.recipe_bytes)
        second = self.export('1.1.0')
        self.assertEqual(second['character_id'], first['character_id'])
        self.assertEqual([e['version'] for e in pkg.read_meta(self.fx.project)['exports']], ['1.0.0', '1.1.0'])
        self.assertEqual(self.fx.draft()['character_id'], first['character_id'])
        with self.assertRaisesRegex(pkg.PackageError, 'aumente a versao'):
            self.export('1.1.0')

    def detected_entries(self, draft):
        return [{'name': d['name'], 'author': '', 'url': d['url'], 'nexus_mod_id': d['nexus_mod_id'],
                 'required_for_rebuild': d['required_for_rebuild'], 'include': True, 'reason': d['reason'],
                 'detected': i} for i, d in enumerate(draft['dependencies'])]

    def test_author_edits_the_detected_list(self):
        draft = self.fx.draft()
        names = [d['name'] for d in draft['dependencies']]
        hair = names.index('Y2K Ponytail - CCXL')
        deps = self.detected_entries(draft)
        deps[hair].update({'name': 'Y2K Ponytail', 'author': 'Peachu', 'url': '', 'nexus_mod_id': 20175,
                           'required_for_rebuild': False})
        deps += [{'name': 'Arkhe skin', 'author': 'Arkhe', 'url': 'https://www.nexusmods.com/cyberpunk2077/mods/1',
                  'required_for_rebuild': False, 'include': True, 'detected': None},
                 {'name': 'manual removido', 'include': False, 'detected': None}]
        manifest = self.export(dependencies=deps, draft=draft)['manifest']
        out = {d['name']: d for d in manifest['dependencies']}
        self.assertEqual(sorted(out), sorted([n for n in names if n != 'Y2K Ponytail - CCXL'] + ['Y2K Ponytail', 'Arkhe skin']))
        self.assertEqual(out['Y2K Ponytail']['resources'], draft['dependencies'][hair]['resources'])
        self.assertEqual(out['Y2K Ponytail']['url'], 'https://www.nexusmods.com/cyberpunk2077/mods/20175')
        self.assertFalse(out['Y2K Ponytail']['required_for_rebuild'])
        self.assertEqual((out['Arkhe skin']['detected_from'], out['Arkhe skin']['resources']), ('author', []))

    def test_detected_requirement_cannot_be_dropped(self):
        # BUGS 67 (author, 04/10/2026): a detected requirement is always credited, even if the window is bypassed.
        draft = self.fx.draft()
        self.assertTrue(draft['dependencies'])
        excluded = self.detected_entries(draft)
        excluded[0]['include'] = False
        with self.assertRaisesRegex(pkg.PackageError, 'nao pode ser removido'):
            self.export(dependencies=excluded, draft=draft)
        manual_only = [{'name': 'Arkhe skin', 'include': True, 'detected': None}]
        with self.assertRaisesRegex(pkg.PackageError, 'nao pode ser removido'):
            self.export(dependencies=manual_only, draft=draft)
        with self.assertRaisesRegex(pkg.PackageError, 'nao pode ser removido'):
            self.export(dependencies=[], draft=draft)
        twice = self.detected_entries(draft) + self.detected_entries(draft)
        with self.assertRaisesRegex(pkg.PackageError, 'repetido'):
            self.export(dependencies=twice, draft=draft)
        self.assertFalse(self.fx.exports.exists() and any(self.fx.exports.iterdir()))

    def test_detected_patch_is_optional_by_default(self):
        found = {'by_archive': {'a.archive': [{'path': 'a\\x.mesh', 'kind': 'own_path'}],
                                'b.archive': [{'path': 'b\\y.mesh', 'kind': 'xl_patch'}],
                                'c.archive': [{'path': 'c\\z.mesh', 'kind': 'override'},
                                              {'path': 'c\\w.mesh', 'kind': 'xl_patch'}]},
                 'counts': {}, 'unknown': []}

        class Loc:
            def relative(self, archive):
                return archive
        with patch.object(pkg, 'classify', return_value=found):
            deps = {d['name']: d['required_for_rebuild'] for d in
                    pkg.detect_dependencies(Path('.'), [], Loc(), {})['dependencies']}
        self.assertEqual(deps, {'a': True, 'b': False, 'c': True})

    def test_failed_write_leaves_no_half_version_folder(self):
        with patch.object(pkg, 'nexus_text', side_effect=OSError('disco cheio')):
            with self.assertRaises(OSError):
                self.export('1.0.0')
        self.assertEqual(list(self.fx.exports.iterdir()), [])
        self.assertTrue(self.export('1.0.0')['zip'].is_file())

    def test_empty_list_from_cet_is_accepted(self):
        self.assertEqual(pkg.merge_dependencies({}, []), [])

    def test_export_is_never_blocked_by_a_third_party_mod(self):
        draft = self.fx.draft()
        self.assertTrue(any(d['required_for_rebuild'] for d in draft['dependencies']))
        self.assertTrue(self.export()['zip'].is_file())
        self.assertEqual(draft['notice'], pkg.NOTICE)

    def test_private_path_in_recipe_is_refused(self):
        recipe = seila_recipe()
        recipe['source'] = 'C:\\Users\\alguem\\Documents\\x'
        other = Fixture(Path(self.temp.name) / 'b', recipe)
        with self.assertRaisesRegex(pkg.PackageError, 'caminho pessoal'):
            other.draft()

    def test_bad_form_is_refused(self):
        draft = self.fx.draft()
        for fields in (form(display_name=''), form('1.0'), form(source_preset={'url': 'javascript:x'})):
            with self.assertRaises(pkg.PackageError):
                pkg.export(self.fx.plugin, self.fx.projects, self.fx.token, {'fields': fields, 'dependencies': []},
                           draft, self.fx.exports)
        with self.assertRaises(pkg.PackageError):
            pkg.export(self.fx.plugin, self.fx.projects, self.fx.token,
                       {'fields': form(), 'dependencies': [{'name': 'x', 'detected': 99}]}, draft, self.fx.exports)


def recipe_package(fx, version='1.0.0') -> dict:
    """A rebuild-recipe package as EXPORTAR wrote before 03/10/2026; INSTALAR still installs those."""
    draft = fx.draft()
    deps = pkg.merge_dependencies([dict(d, author='', include=True, detected=i)
                                   for i, d in enumerate(draft['dependencies'])], draft['dependencies'])
    cid = pkg.new_character_id('Seila')
    manifest = pkg.package_manifest(cid, pkg.clean_fields(form(version)), deps, json.loads(fx.recipe_bytes),
                                    fx.recipe_bytes, 'selected_tpp', draft['resource_origin'], None, 'bottom')
    written = pkg.write_package(fx.exports / (cid + '-' + version), manifest, fx.recipe_bytes)
    return dict(written, character_id=cid)


def unpack(zip_path: Path, game: Path) -> Path:
    with zipfile.ZipFile(zip_path) as bundle:
        bundle.extractall(game)
        return game / Path(bundle.namelist()[0]).parent


class PackageReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fx = Fixture(Path(self.temp.name))
        self.done = recipe_package(self.fx)
        self.consumer = Path(self.temp.name) / 'consumer'
        self.plugin = self.consumer / 'red4ext/plugins/NPVMaker'
        self.folder = unpack(self.done['zip'], self.consumer)

    def test_installed_package_reads_back(self):
        manifest, recipe = pkg.read_package(self.folder)
        self.assertEqual(recipe, self.fx.recipe_bytes)
        self.assertEqual(self.folder.parent, self.plugin / 'packages')
        self.assertEqual(pkg.scan_packages(self.plugin)[0]['state'], 'available')

    def test_tampered_or_newer_package_is_invalid(self):
        (self.folder / 'recipe/project.npv.json').write_bytes(b'{}')
        with self.assertRaisesRegex(pkg.PackageError, 'receita diferente'):
            pkg.read_package(self.folder)
        self.assertEqual(pkg.scan_packages(self.plugin)[0]['state'], 'invalid')
        (self.folder / 'recipe/project.npv.json').write_bytes(self.fx.recipe_bytes)
        manifest = json.loads((self.folder / 'npv-package.json').read_text(encoding='utf8'))
        manifest['minimum_npvmaker_version'] = '9.0.0'
        (self.folder / 'npv-package.json').write_text(json.dumps(manifest), encoding='utf8')
        with self.assertRaises(pkg.PackageError) as raised:
            pkg.read_package(self.folder)
        self.assertEqual(raised.exception.code, 'NPVM-PACKAGE-006')

    def test_states_follow_the_installed_receipt(self):
        receipts = self.plugin / 'data/imports'
        receipts.mkdir(parents=True)
        receipt = receipts / (pkg.package_identity(self.done['character_id']) + '.json')
        receipt.write_text(json.dumps({'character_id': self.done['character_id'], 'package_version': '1.0.0'}))
        self.assertEqual(pkg.scan_packages(self.plugin)[0]['state'], 'installed')
        receipt.write_text(json.dumps({'character_id': self.done['character_id'], 'package_version': '0.9.0'}))
        listed = pkg.scan_packages(self.plugin)[0]
        self.assertEqual((listed['state'], listed['installed_version']), ('other_version', '0.9.0'))


class RequirementCheckTests(unittest.TestCase):
    def manifest(self):
        found = pkg.detect_dependencies(Path('.'), SEILA_ENTRIES, FakeLocator(), SOURCES)
        return {'dependencies': found['dependencies'] + [
            {'name': 'Arkhe skin', 'required_for_rebuild': False, 'resources': [], 'archives': [], 'url': ''}]}

    def states(self, locator):
        return {r['name']: r['state'] for r in pkg.check_requirements(self.manifest(), locator)}

    def test_all_present(self):
        states = self.states(FakeLocator())
        self.assertEqual(states['VTK body user - Vanilla eyes compatible'], 'ok')
        self.assertEqual(states['Arkhe skin'], 'unchecked')

    def test_vanilla_copy_does_not_satisfy_a_head_mod(self):
        locator = FakeLocator()
        del locator.mods['003_EKT_CC_AsianVersion_VTK_Vanilla_eyes_V4.archive']
        del locator.mods['vtk_VanillaHD_Head_xBaebsae.archive']
        del locator.mods['peachu_y2kponytail_CCXL.archive']
        results = {r['name']: r for r in pkg.check_requirements(self.manifest(), locator)}
        self.assertEqual(results['VTK body user - Vanilla eyes compatible']['state'], 'missing')
        self.assertEqual(results['Y2K Ponytail - CCXL']['state'], 'missing')
        lines = pkg.requirement_report(list(results.values()))
        self.assertIn('x  VTK body user - Vanilla eyes compatible  https://www.nexusmods.com/cyberpunk2077/mods/16930', lines)
        self.assertIn('?  Arkhe skin (opcional)  (nao conferido)', lines)

    def test_other_mod_serving_the_path_is_a_warning(self):
        locator = FakeLocator()
        del locator.mods['003_EKT_CC_AsianVersion_VTK_Vanilla_eyes_V4.archive']
        locator.mods['vtk_VanillaHD_Head_xBaebsae.archive'].add(key(EKT_MORPH))
        self.assertEqual(self.states(locator)['VTK body user - Vanilla eyes compatible'], 'other_archive')


class ConverterPackageTests(unittest.TestCase):
    """runtime_entry: requirements, export and install requests."""

    def setUp(self):
        patcher = patch.object(worker, 'require_wolvenkit', return_value=Path('WolvenKit.CLI.exe'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fx = Fixture(Path(self.temp.name))
        env = patch.dict(os.environ, {'NPV_EXPORTS_ROOT': str(self.fx.exports)})
        env.start()
        self.addCleanup(env.stop)
        locator = patch.object(pkg, 'Locator', return_value=FakeLocator())
        locator.start()
        self.addCleanup(locator.stop)
        sources = patch.object(pkg, 'vortex_sources', return_value=SOURCES)
        sources.start()
        self.addCleanup(sources.stop)

    def request(self, target, action, **extra):
        path = self.fx.projects / (target + '.' + action + '.request.json')
        path.write_text(json.dumps(dict(format='npv-maker-worker-request', schema_version=1, action=action,
                                        project_id=target, **extra)), encoding='utf8')
        worker.process(path, self.fx.game, self.fx.plugin)
        self.assertFalse(path.exists())

    def exported(self):
        self.request(self.fx.token, 'requirements')
        status = json.loads((self.fx.projects / 'exports' / (self.fx.token + '.export.json')).read_text())
        self.assertEqual(status['stage'], 'requirements_ready')
        draft = json.loads((self.fx.projects / 'exports' / (self.fx.token + '.export-draft.json')).read_text())
        deps = [dict(name=d['name'], nexus_mod_id=d['nexus_mod_id'], required_for_rebuild=d['required_for_rebuild'],
                     include=True, detected=i) for i, d in enumerate(draft['dependencies'])]
        self.request(self.fx.token, 'export', fields=form(), dependencies=deps)
        status = json.loads((self.fx.projects / 'exports' / (self.fx.token + '.export.json')).read_text())
        self.assertEqual(status['stage'], 'exported', status.get('message'))
        self.assertTrue(status['folder'].startswith('Documentos\\NPVMaker\\exports\\npv_seila_'))
        return status

    def install(self, status):
        zip_path = self.fx.exports / status['folder'].split('\\')[-1] / (status['folder'].split('\\')[-1] + '.zip')
        unpack(zip_path, self.fx.game)
        return status['character_id']

    def install_recipe(self):
        done = recipe_package(self.fx)
        unpack(done['zip'], self.fx.game)
        return done['character_id']

    def test_export_request_writes_the_npv(self):
        status = self.exported()
        folder = status['folder'].split('\\')[-1]
        with zipfile.ZipFile(self.fx.exports / folder / (folder + '.zip')) as bundle:
            self.assertIn('archive/pc/mod/npvmaker_' + self.fx.token + '.archive', bundle.namelist())

    def fake_build(self, snapshot, game, cli, output, progress, body_strategy='legacy', identity=None, display_name=None,
                   underwear='bottom'):
        self.built = dict(strategy=body_strategy, identity=identity, name=display_name, recipe=snapshot.read_bytes(),
                          underwear=underwear)
        output.mkdir(parents=True)
        manifest = dict(format='npv-maker-runtime-npc', project_sha256=identity, name=display_name, diagnostics=[])
        (output / 'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_export_then_install_rebuilds_with_the_package_identity_without_companion(self):
        cid = self.install_recipe()
        with patch.object(pkg, 'Locator', return_value=FakeLocator(mods={})):
            self.request(cid, 'install')
        status = json.loads((self.fx.projects / 'exports' / (cid + '.json')).read_text())
        self.assertEqual(status['stage'], 'error')
        self.assertIn('NPVM-PACKAGE-003', status['message'])
        self.assertFalse(hasattr(self, 'built'))
        # Requirements installed now (the fake locator of the author's PC).
        with patch.object(worker, 'build', side_effect=self.fake_build), \
             patch.object(worker, 'install', return_value={'record_id': 'Character.x'}) as install, \
             patch.object(worker, 'companion_available', return_value=False):
            (self.fx.plugin / 'packages').mkdir(exist_ok=True)
            self.request(cid, 'install')
        status = json.loads((self.fx.projects / 'exports' / (cid + '.json')).read_text())
        self.assertEqual(status['stage'], 'installed', status.get('message'))
        self.assertEqual(self.built, dict(strategy='selected_tpp', identity=pkg.package_identity(cid), name='Seila',
                                          recipe=self.fx.recipe_bytes, underwear='bottom'))
        kwargs = install.call_args.kwargs
        self.assertFalse(kwargs['require_companion'])
        self.assertEqual((kwargs['extra']['character_id'], kwargs['extra']['package_version']), (cid, '1.0.0'))
        self.assertTrue(any(line.startswith('v  ') for line in status['requirements']))

    def test_missing_requirement_lists_it_and_does_not_convert(self):
        cid = self.install_recipe()
        with patch.object(pkg, 'Locator', return_value=FakeLocator(mods={})), \
             patch.object(worker, 'build') as build:
            self.request(cid, 'install')
            build.assert_not_called()
        status = json.loads((self.fx.projects / 'exports' / (cid + '.json')).read_text())
        self.assertIn('NPVM-PACKAGE-003', status['message'])
        self.assertIn('x  Y2K Ponytail - CCXL  https://www.nexusmods.com/cyberpunk2077/mods/20175', status['requirements'])

    def test_other_installed_version_is_removed_first(self):
        cid = self.install_recipe()
        receipts = self.fx.plugin / 'data/imports'
        (receipts / (pkg.package_identity(cid) + '.json')).write_text(json.dumps(
            {'character_id': cid, 'package_version': '0.9.0'}))
        with patch.object(worker, 'build') as build:
            self.request(cid, 'install')
            build.assert_not_called()
        status = json.loads((self.fx.projects / 'exports' / (cid + '.json')).read_text())
        self.assertIn('NPVM-PACKAGE-005', status['message'])

    def test_package_list_is_published_for_the_panel(self):
        cid = self.install_recipe()
        worker.packages_published = None
        worker.publish_packages(self.fx.plugin, self.fx.projects)
        listing = json.loads((self.fx.projects / 'exports/packages.json').read_text())
        self.assertEqual([(p['character_id'], p['state']) for p in listing['packages']], [(cid, 'available')])

    def test_wrong_identifier_for_an_action_is_ignored(self):
        path = self.fx.projects / (self.fx.token + '.install.request.json')
        path.write_text('{}')
        worker.process(path, self.fx.game, self.fx.plugin)
        self.assertTrue(path.exists())


def lua_json(lua):
    def to_python(value):
        if hasattr(value, 'items'):
            items = dict(value.items())
            if items and all(isinstance(k, int) for k in items):
                return [to_python(items[i]) for i in sorted(items)]
            return {k: to_python(v) for k, v in items.items()}
        return value
    return lua.table_from({'encode': lambda value: json.dumps(to_python(value)),
                           'decode': lambda raw: lua.table_from(json.loads(raw), recursive=True)})


@unittest.skipIf(LuaRuntime is None or not (ROOT / 'src/cet/init.lua').is_file(),
                 'lupa not installed or the old CET panel (src/cet) is not in this source')
class PanelPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        (self.dir / 'projects/exports').mkdir(parents=True)
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().json = lua_json(self.lua)
        self.lua.execute('''
          callbacks = {}
          registerForEvent = function(name, fn) callbacks[name] = fn end
          storage = { snapshot = function() return {} end }
          require = function(name) return storage end
          session = { pendingCopy = 0, pendingSave = false, exportAfterSave = false }
          function session:SetStatus(text) self.status = text end
          function session:SetDiagnostics(text, copyable) end
          NPVMakerSession = { GetInstance = function() return session end }
          print = function() end
          windows, buttons, clicks, typed, texts = {}, {}, {}, {}, {}
          ImGui = {
            Begin = function(name) table.insert(windows, name); return true end, End = function() end,
            Text = function(t) table.insert(texts, t) end, TextWrapped = function(t) table.insert(texts, t) end,
            SameLine = function() end, Separator = function() end,
            InputText = function(label, text, size) if typed[label] then local v = typed[label]; typed[label] = nil; return v, true end return text, false end,
            Button = function(label) table.insert(buttons, label); if clicks[label] then clicks[label] = nil; return true end; return false end,
          }
        ''')
        self.previous = Path.cwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, self.previous)
        self.lua.execute((ROOT / 'src/cet/init.lua').read_text(encoding='utf8'))
        self.cb = self.lua.globals().callbacks
        self.cb.onInit()
        self.cb.onOverlayOpen()

    def tick(self):
        for _ in range(7):
            self.cb.onUpdate(0.2)

    def draw(self):
        self.lua.execute('windows, buttons, texts = {}, {}, {}')
        self.cb.onDraw()
        return list(self.lua.globals().windows.values())

    def click(self, label):
        self.lua.globals().clicks[label] = True
        self.draw()

    def test_export_flow_writes_requirements_then_export_request(self):
        token = '0e790e8bcc899ae5'
        (self.dir / 'projects/exports/imported.json').write_text(json.dumps({'format': 'npv-maker-imported', 'characters': [
            {'token': token, 'name': 'seila [SELECTED_TPP]', 'removal_pending': [], 'package': ''},
            {'token': 'aaaaaaaaaaaaaaaa', 'name': 'Outra', 'removal_pending': [], 'package': 'npv_outra_00000000',
             'package_version': '1.0.0'}]}))
        self.tick()
        self.draw()
        buttons = list(self.lua.globals().buttons.values())
        self.assertIn('Exportar##' + token, buttons)
        self.assertNotIn('Exportar##aaaaaaaaaaaaaaaa', buttons)
        self.click('Exportar##' + token)
        request = json.loads((self.dir / 'projects' / (token + '.requirements.request.json')).read_text())
        self.assertEqual((request['action'], request['project_id']), ('requirements', token))
        (self.dir / 'projects' / (token + '.requirements.request.json')).unlink()
        (self.dir / 'projects/exports' / (token + '.export-draft.json')).write_text(json.dumps({
            'format': 'npv-maker-export-draft', 'token': token, 'character_id': None, 'notice': pkg.NOTICE,
            'fields': {'display_name': 'seila', 'author': '', 'version': '1.0.0', 'description': '',
                       'source_preset': {'name': '', 'author': '', 'url': '', 'version': ''}},
            'dependencies': [{'name': 'Y2K Ponytail - CCXL', 'author': '', 'url': 'https://x', 'nexus_mod_id': 20175,
                              'required_for_rebuild': True, 'reason': 'arquivos do proprio mod'},
                             {'name': 'DreamGalaxyEyesCCXL', 'author': '', 'url': '', 'nexus_mod_id': 34080,
                              'required_for_rebuild': False, 'reason': 'patch'}]}))
        self.tick()
        self.assertIn('NPV Maker - exportar NPV', self.draw())
        self.lua.globals().typed['Nome##npvexp'] = 'Seila'
        self.lua.globals().typed['Nome do preset##npvexp'] = 'Mako'
        self.lua.globals().typed['Nexus ID do preset##npvexp'] = '24229'
        self.draw()
        self.click('[x] incluir##npvdepinc2')
        self.click('ADICIONAR REQUISITO##npvexp')
        self.lua.globals().typed['Nome##npvdepname3'] = 'Arkhe skin'
        self.draw()
        self.click('CRIAR PACOTE##npvexp')
        request = json.loads((self.dir / 'projects' / (token + '.export.request.json')).read_text())
        self.assertEqual(request['fields']['display_name'], 'Seila')
        self.assertEqual(request['fields']['source_preset']['nexus_mod_id'], 24229)
        deps = request['dependencies']
        self.assertEqual([(d['name'], d.get('detected'), d['include']) for d in deps],
                         [('Y2K Ponytail - CCXL', 0, True), ('DreamGalaxyEyesCCXL', 1, False), ('Arkhe skin', None, True)])
        self.assertIn(pkg.NOTICE, list(self.lua.globals().texts.values()))

    def test_packages_window_lists_and_installs(self):
        cid = 'npv_seila_7c42a91f'
        self.tick()
        self.assertNotIn('NPV Maker - pacotes NPV', self.draw())
        (self.dir / 'projects/exports/packages.json').write_text(json.dumps({'format': 'npv-maker-packages', 'packages': [
            {'character_id': cid, 'display_name': 'Seila', 'version': '1.0.0', 'author': 'Natanael', 'state': 'available'}]}))
        self.tick()
        self.assertIn('NPV Maker - pacotes NPV', self.draw())
        self.click('INSTALAR##npvpkg' + cid)
        request = json.loads((self.dir / 'projects' / (cid + '.install.request.json')).read_text())
        self.assertEqual((request['action'], request['project_id']), ('install', cid))
        (self.dir / 'projects/exports' / (cid + '.json')).write_text(json.dumps({
            'format': 'npv-maker-companion-job', 'stage': 'error', 'message': 'Faltam requisitos',
            'requirements': ['x  Y2K Ponytail - CCXL  https://x']}))
        self.tick()
        self.draw()
        self.assertIn('Faltam requisitos\nx  Y2K Ponytail - CCXL  https://x', list(self.lua.globals().texts.values()))


class CreateNpvTests(ConverterPackageTests):
    """CRIAR NPV (author request 01/10/2026): the local import takes the mods and outfit chosen in the manager."""

    PROJECT = 'npv-20260930T020150Z-0001'

    def built_with(self, **extra):
        (self.fx.plugin / 'data/imports' / (self.fx.digest + '.json')).unlink()
        with patch.object(worker, 'build', side_effect=self.fake_build), \
             patch.object(worker, 'install', return_value={'record_id': 'Character.x'}) as install, \
             patch.object(worker, 'companion_available', return_value=False):
            self.request(self.PROJECT, 'build', body_strategy='selected_tpp', **extra)
        status = json.loads((self.fx.projects / 'exports' / (self.PROJECT + '.json')).read_text())
        return status, install

    def test_mods_and_outfit_reach_the_install_without_companion(self):
        status, install = self.built_with(integrations={'companion': False, 'nca': True, 'amm': True},
                                          underwear='full')
        self.assertEqual(status['stage'], 'installed', status.get('message'))
        self.assertEqual(self.built['underwear'], 'full')
        kwargs = install.call_args.kwargs
        self.assertEqual(kwargs['integrations'], {'companion': False, 'nca': True, 'amm': True, 'photomode': False, 'nca_merc': False})
        self.assertFalse(kwargs['require_companion'])
        # A local NPV is not a package: no character_id in the receipt (EXPORTAR stays available).
        self.assertNotIn('character_id', kwargs['extra'])
        self.assertTrue(kwargs['extra']['local_id'].startswith('npv_local_'))

    def test_companion_marked_still_needs_it(self):
        status, install = self.built_with(integrations={'companion': True})
        self.assertEqual(status['stage'], 'error')
        self.assertIn('NPVM-DEPENDENCY-001', status['message'])
        install.assert_not_called()

    def test_save_request_carries_the_choice(self):
        import storage_bridge
        storage = Path(self.temp.name) / 'storage'
        storage.mkdir()
        draft = storage / 'save-abc123.draft.json'
        draft.write_text(json.dumps({'format': 'npv-maker-save-request', 'schema_version': 1, 'after_save': 'build',
                                     'body_strategy': 'selected_tpp', 'project': json.loads(self.fx.recipe_bytes),
                                     'integrations': {'nca': True}, 'underwear': 'none'}), encoding='utf8')
        saved = storage_bridge.save_project(draft, self.fx.projects, storage, 1790000000.0)
        request = json.loads((self.fx.projects / (saved['id'] + '.build.request.json')).read_text(encoding='utf8'))
        self.assertEqual((request['integrations'], request['underwear']), ({'nca': True}, 'none'))


if __name__ == '__main__':
    unittest.main()
