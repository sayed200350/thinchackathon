"""PDF imports read real page text and leave claim submission to the caller."""

import base64
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch
import zlib

from backend import intake_pdf
from backend.store import RequestError


SAMPLE = Path(__file__).resolve().parents[1] / 'fixtures/sample-accident-report.pdf'


def pdf_pages(*pages):
    """Make small valid text-layer PDFs with no extra test dependencies."""
    n = len(pages)
    pages_tree = ' '.join(f'{4 + i * 2} 0 R' for i in range(n))
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               f'<< /Type /Pages /Count {n} /Kids [{pages_tree}] >>'.encode(),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    for i, lines in enumerate(pages):
        stream_id = 5 + i * 2
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
                       f'/Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>'.encode())
        commands = ['BT /F1 11 Tf 15 TL 50 780 Td']
        for line in lines:
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(f'({escaped}) Tj T*')
        data = ('\n'.join(commands) + '\nET\n').encode('cp1252')
        objects.append(f'<< /Length {len(data)} >>\nstream\n'.encode() + data + b'endstream')
    return pdf_objects(objects)


def pdf_objects(objects):
    result = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        result.extend(f'{offset:010} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    return bytes(result)


def scan_pdf(pdf):
    # Render the report, then create a new PDF containing only a page-sized
    # grayscale image. No text-layer bytes survive into the scan fixture.
    result = subprocess.run([shutil.which('pdftoppm'), '-q', '-gray', '-f', '1', '-l', '1',
                             '-singlefile', '-scale-to', '1400', '-'],
                            input=pdf, capture_output=True, check=True, timeout=10)
    header = re.match(rb'P5\s+(\d+)\s+(\d+)\s+255\s', result.stdout)
    if not header:
        raise ValueError('Expected a grayscale test page.')
    width, height = map(int, header.groups())
    raw = zlib.compress(result.stdout[header.end():])
    content = b'q 595 0 0 842 0 0 cm /Im0 Do Q'
    return pdf_objects([
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>',
        f'<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceGray '
        f'/BitsPerComponent 8 /Filter /FlateDecode /Length {len(raw)} >>\nstream\n'.encode() + raw + b'\nendstream',
        f'<< /Length {len(content)} >>\nstream\n'.encode() + content + b'\nendstream',
    ])


def body(data):
    return {'name': 'report.pdf', 'content_base64': base64.b64encode(data).decode()}


@unittest.skipUnless(shutil.which('pdftotext'), 'Poppler is optional for manual intake')
class LocalPdfImportTests(unittest.TestCase):
    def test_demo_has_the_five_documented_fields_and_page_numbers(self):
        result = intake_pdf.extract_pdf(body(SAMPLE.read_bytes()))
        self.assertEqual(result['document_kind'], 'incident_report')
        self.assertEqual({item['field']: item['value'] for item in result['suggestions']}, {
            'incident_date': '2025-10-18', 'location': 'Demo car park, Westend, Munich',
            'description': 'A delivery van scraped the left rear door while my car was parked.',
            'policy_number': 'DEMO-MOT-1048', 'email': 'alex.river@example.invalid',
        })
        self.assertEqual({item['page'] for item in result['suggestions']}, {1})

    def test_german_report_preserves_conflicts_and_deduplicates_the_same_value(self):
        document = pdf_pages(
            ['Europäischer Unfallbericht', 'Unfalldatum: 03.02.2025', 'Unfallort: München',
             'Unfallhergang: Beim Ausparken wurde die linke Tür beschädigt.', 'Verletzte: keine'],
            ['Unfallbericht', 'Unfallort: Augsburg', 'Schadendatum: 03.02.2025', 'Policennummer: DEMO-22'],
        )
        result = intake_pdf.extract_pdf(body(document))
        self.assertEqual(result['document_kind'], 'incident_report')
        values = [(s['field'], s['value'], s['page']) for s in result['suggestions']]
        self.assertIn(('location', 'München', 1), values)
        self.assertIn(('location', 'Augsburg', 2), values)
        self.assertIn(('policy_number', 'DEMO-22', 2), values)
        self.assertEqual([s for s in values if s[0] == 'incident_date'], [('incident_date', '2025-02-03', 1)])
        self.assertNotIn('injury_status', [s[0] for s in values])

    def test_quote_issue_date_and_repairer_contact_never_become_claimant_answers(self):
        document = pdf_pages(['Workshop repair estimate', 'Quote date: 04.06.2025', 'Datum: 05.06.2025',
                              'Email: workshop@example.invalid', 'Location: Workshop office',
                              'Policy number: MOTOR-100', 'Date of incident: 04/06/2025'])
        result = intake_pdf.extract_pdf(body(document))
        self.assertEqual(result['document_kind'], 'itemized_quote')
        self.assertEqual(result['suggestions'], [{'field': 'policy_number', 'value': 'MOTOR-100', 'page': 1}])

    def test_image_only_or_damaged_pdf_returns_manual_fallback(self):
        for document in [pdf_pages([]), b'%PDF-unreadable']:
            with self.subTest(document_size=len(document)):
                result = intake_pdf.extract_pdf(body(document))
                self.assertEqual(result['suggestions'], [])
                self.assertIn('enter your answers', result['notice'])

    def test_page_limit_does_not_import_fields_from_later_pages(self):
        document = pdf_pages(*([['Accident report']] * intake_pdf.MAX_PAGES + [['Incident date: 1999-01-01']]))
        self.assertEqual(intake_pdf.extract_pdf(body(document))['suggestions'], [])

    @unittest.skipUnless(shutil.which('pdftoppm') and shutil.which('tesseract'), 'Optional local OCR tools')
    def test_scanned_report_nonempty_fields_come_from_local_ocr(self):
        scan = scan_pdf(SAMPLE.read_bytes())
        self.assertFalse(intake_pdf._local_text(shutil.which('pdftotext'), scan).strip())
        result = intake_pdf.extract_pdf(body(scan))
        self.assertIn('optical scan', result['notice'])
        self.assertIn({'field': 'incident_date', 'value': '2025-10-18', 'page': 1}, result['suggestions'])
        self.assertNotIn('injury_status', {s['field'] for s in result['suggestions']})


class PdfImportBoundaryTests(unittest.TestCase):
    def test_invalid_requests_rejected_before_launching_a_parser(self):
        packet = body(b'%PDF-1.4 fake')
        for invalid in [None, {}, dict(packet, name='../x.pdf'), dict(packet, name='x.png'),
                        dict(packet, content_base64='////'), dict(packet, content_base64='not base64'),
                        dict(packet, extra='field')]:
            with self.subTest(invalid=invalid), patch.object(intake_pdf, '_local_text') as read:
                with self.assertRaises(RequestError) as raised:
                    intake_pdf.extract_pdf(invalid)
                self.assertEqual(raised.exception.status, 400)
                read.assert_not_called()

    def test_missing_tool_timeout_and_busy_reader_allow_manual_completion(self):
        packet = body(b'%PDF-1.4 fake')
        with patch.object(intake_pdf.shutil, 'which', return_value=None):
            self.assertIn('unavailable', intake_pdf.extract_pdf(packet)['notice'])
        with patch.object(intake_pdf.shutil, 'which', return_value='/tmp/fixture'), \
                patch.object(intake_pdf, '_local_text', side_effect=subprocess.TimeoutExpired('pdftotext', 6)):
            self.assertEqual(intake_pdf.extract_pdf(packet)['suggestions'], [])
        with patch.object(intake_pdf.shutil, 'which', return_value='/tmp/fixture'), \
                patch.object(intake_pdf.READERS, 'acquire', return_value=False):
            self.assertIn('busy', intake_pdf.extract_pdf(packet)['notice'])


if __name__ == '__main__':
    unittest.main()
