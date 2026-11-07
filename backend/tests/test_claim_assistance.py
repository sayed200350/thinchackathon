import base64
from pathlib import Path
import shutil
import tempfile
import zipfile
import hashlib
import struct
import unittest
from unittest.mock import patch

from backend import claim_assistance as assist
from backend.intake_pdf import _local_text, _suggestions
from backend.store import RequestError


def dated_photo(day='2025:10:19 09:11:12', *, png=False, big_endian=False):
    order = '>' if big_endian else '<'
    packed = lambda fmt, *v: struct.pack(order + fmt, *v)
    date_bytes = day.encode() + b'\0'
    tiff = ((b'MM' if big_endian else b'II') + packed('HI', 42, 8) +
            packed('H', 1) + packed('HHII', 0x8769, 4, 1, 26) + packed('I', 0) +
            packed('H', 1) + packed('HHII', 0x9003, 2, len(date_bytes), 44) +
            packed('I', 0) + date_bytes)
    if png:
        return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', len(tiff)) + b'eXIf' + tiff + b'\0'*4
    body = b'Exif\0\0' + tiff
    return b'\xff\xd8\xff\xe1' + struct.pack('>H', 2+len(body)) + body + b'\xff\xd9'


def doc(kind, data, note, name='demo.jpg'):
    return dict(kind=kind, name=name, content_base64=base64.b64encode(data).decode(), assistance=note)


class ClaimAssistanceTests(unittest.TestCase):
    def test_camera_date_comes_from_original_not_claimant_or_file_modification_time(self):
        for png, big in [(False, False), (False, True), (True, False)]:
            data = dated_photo(png=png, big_endian=big)
            packet = doc('damage_photo', data + bytes(3 * 1024**2),
                         {'exif_date':'1900-01-01', 'explanation':'The photo was taken next morning.',
                          'view':'wide', 'manual_date':''}, 'demo.png' if png else 'demo.jpg')
            self.assertEqual(assist.clean_assistance(packet)['exif_date'], '2025-10-19')
            self.assertEqual(base64.b64decode(packet['content_base64']), data + bytes(3 * 1024**2))
        for raw in [b'', b'\xff\xd8\xff\xe1\x00', dated_photo(day='2025:02:31 09:00:00'),
                    dated_photo().replace(b'\x03\x90', b'\x32\x01')]:
            self.assertIsNone(assist.capture_date(raw))

    def test_no_camera_metadata_allows_a_manual_date_or_an_unknown_date(self):
        original = b'\xff\xd8\xff\xd9'
        for supplied in ('', '2025-10-19'):
            note = assist.clean_assistance(doc('damage_photo', original,
                    {'manual_date':supplied, 'exif_date':'2025-01-01', 'explanation':'', 'view':'close_up'}))
            self.assertIsNone(note['exif_date'])
            self.assertEqual(note['manual_date'], supplied)
        for note in [{'view':'other'}, {'manual_date':'2025-02-30'}, {'explanation':'x'*1001}]:
            with self.assertRaises(RequestError):
                assist.clean_assistance(doc('damage_photo', original, note))

    def test_exact_german_narrative_and_page_survive_a_translation_and_edit(self):
        text = ('Beiblatt\fUnfallbericht\nUnfallhergang: Ein Lieferwagen streifte die linke hintere Tür.\n'
                'Mein Fahrzeug war geparkt.\nUnfallort: München\n')
        with patch.object(assist, '_translate_local', return_value='A delivery van scraped the left rear door. My vehicle was parked.'):
            result = assist.report_translation(text, _suggestions(text)[1], 'incident_report')
        self.assertEqual(result['original'], 'Ein Lieferwagen streifte die linke hintere Tür. Mein Fahrzeug war geparkt.')
        self.assertEqual(result['page'], 2)
        self.assertEqual(result['source'], 'local_model')
        self.assertFalse(result['confirmed'])
        corrected = dict(result, english='A van grazed the rear left door of my parked car.', source='manual', confirmed=True)
        self.assertEqual(assist.clean_assistance(doc('incident_report', b'%PDF-1.4', {'translation':corrected}, 'report.pdf'))['translation'], corrected)

    def test_standard_german_remarks_field_on_a_report(self):
        source = 'Europäischer Unfallbericht\nBemerkungen: Mein Fahrzeug war geparkt.\nKennzeichen: M-DEMO'
        result = assist.report_translation(source, [], 'incident_report')
        self.assertEqual(result['original'], 'Mein Fahrzeug war geparkt.')
        self.assertEqual(result['english'], 'My vehicle was parked.')
        self.assertFalse(result['confirmed'])

    def test_uncertain_language_never_gets_an_invented_translation(self):
        german = 'Unfallbericht\nUnfallhergang: Ein Lastwagen verschob die Absperrung.\n'
        with patch.object(assist, '_translate_local', return_value=None):
            t = assist.report_translation(german, _suggestions(german)[1], 'incident_report')
        self.assertEqual(t['english'], '')
        self.assertEqual(t['source'], 'manual')
        self.assertFalse(t['confirmed'])
        with self.assertRaises(RequestError):
            assist.clean_assistance(doc('incident_report', b'%PDF-1.4', {'translation':dict(t,confirmed=True)}, 'r.pdf'))
        self.assertIsNone(assist.report_translation('Incident report\nWhat happened: My car was parked.', [], 'incident_report'))
        self.assertIsNone(assist.report_translation(german, [], 'itemized_quote'))

    def test_model_install_verifies_checksum_and_extracts_only_translation_assets(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                for name in ('model/model.bin', 'model/config.json', 'model/shared_vocabulary.json',
                             'sentencepiece.model', 'README.md', 'metadata.json', '../outside'):
                    bundle.writestr('translate-de_en-1_3/' + name, b'mock')
            with self.assertRaises(ValueError):
                assist.unpack_model(archive, root, '0' * 64)
            self.assertFalse((root / 'translate-de_en-1_3').exists())
            assist.unpack_model(archive, root, hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertTrue((root / 'translate-de_en-1_3/model/model.bin').is_file())
            self.assertFalse((root / 'outside').exists())

    @unittest.skipUnless(shutil.which('pdftotext'), 'Poppler is optional')
    def test_bilingual_sample_and_real_guide_photos_are_available(self):
        directory = Path(__file__).resolve().parents[1] / 'fixtures' / 'photo-guide'
        text = _local_text(shutil.which('pdftotext'), (directory / 'accident-report-de.pdf').read_bytes())
        kind, suggestions = _suggestions(text)
        with patch.object(assist, '_translate_local', return_value=None):
            result = assist.report_translation(text, suggestions, kind)
        self.assertEqual(result['source'], 'phrasebook')
        self.assertIn('rear door', result['english'])
        self.assertEqual(result['page'], 1)
        for name in ('wide.jpg','close-up.jpg'):
            data = (directory / name).read_bytes()
            self.assertTrue(data.startswith(b'\xff\xd8\xff'))
            self.assertGreater(len(data), 5000)
