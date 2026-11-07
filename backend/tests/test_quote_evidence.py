"""Run actual quote documents through the same evidence reader and v1 engine."""
import base64
from pathlib import Path
import shutil
import unittest

from backend.quote_evidence import QUOTE_EXAMPLES, assess_quote, demo_replay, replay_quote
from backend.store import RequestError
from backend.tests.test_intake_pdf import pdf_pages


FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'quotes'


def attachment(content, name='garage.pdf'):
    return {'kind': 'itemized_quote', 'name': name, 'content_base64': base64.b64encode(content).decode()}


@unittest.skipUnless(shutil.which('pdftotext') and shutil.which('pdfinfo'), 'Poppler required')
class QuoteEvidenceTests(unittest.TestCase):
    def test_judges_four_documents_replay_v1_without_changing_other_facts(self):
        expected = {
            'total-only-890.pdf': (890, False, 'needs_clarification', 'request_information', 'v1.2'),
            'itemized-890.pdf': (890, True, 'verified', 'routine_processing', 'v1.3'),
            'itemized-1800.pdf': (1800, True, 'verified', 'human_review', 'v1.1'),
            'unreadable-total.pdf': (None, True, 'needs_clarification', 'request_information', 'v1.missing'),
        }
        self.assertEqual(set(QUOTE_EXAMPLES), expected.keys())
        for name, target in expected.items():
            with self.subTest(quote=name):
                result = demo_replay(attachment((FIXTURES / name).read_bytes(), name))
                evidence, decision = result['assessment'], result['decision']
                self.assertEqual((evidence['amount_eur'], evidence['itemized'], evidence['status'],
                                  decision['recommendation'], decision['matched_rule']), target)
                self.assertEqual(result['original']['matched_rule'], 'v1.2')
                self.assertEqual(evidence['name'], name)
                if evidence['amount_eur'] is not None:
                    self.assertEqual(evidence['page'], 1)
                    self.assertIn('Total', evidence['total_text'])
                if evidence['itemized']:
                    self.assertTrue(all(row['page'] == 1 for row in evidence['lines']))
                else:
                    self.assertIn('890', evidence['garage_request'])

    def test_multipage_german_quote_and_euro_cents_have_document_sources(self):
        pdf = pdf_pages(['Kostenvoranschlag', 'Arbeitslohn: 500,40 EUR'],
                        ['Lackmaterial: 389,70 EUR', 'Gesamtbetrag: 890,10 EUR'])
        assessment = assess_quote(attachment(pdf))
        self.assertEqual(assessment['status'], 'verified')
        self.assertEqual((assessment['amount_eur'], assessment['page']), (890.1, 2))
        self.assertEqual([row['page'] for row in assessment['lines']], [1, 2])

    def test_filename_tax_and_arbitrary_rows_cannot_verify_a_quote(self):
        variants = [
            ['Invoice', 'Bumper paint EUR 100.00', 'Bumper fitting EUR 50.00', 'Total EUR 150.00'],
            ['Repair quote', 'Subtotal EUR 100.00', 'VAT EUR 19.00', 'Total EUR 119.00'],
            ['Repair quote', 'Deposit EUR 80.00', 'Amount already paid EUR 20.00', 'Total EUR 100.00'],
            ['Repair quote', 'Bumper fitting EUR 100.00', 'Bumper paint EUR 80.00', 'Total EUR 200.00'],
            ['Repair quote', 'Bumper fitting EUR 100.00', 'Bumper paint EUR 80.00', 'Total EUR 180.00', 'Total EUR 200.00'],
            ['Repair quote', 'Bumper fitting USD 100.00', 'Bumper paint USD 80.00', 'Total USD 180.00'],
        ]
        for lines in variants:
            with self.subTest(lines=lines):
                result = demo_replay(attachment(pdf_pages(lines), 'itemized-890.pdf'))
                self.assertEqual(result['assessment']['status'], 'needs_clarification')
                self.assertNotEqual(result['decision']['recommendation'], 'routine_processing')

    def test_unreadable_image_or_truncated_document_never_inherits_previous_quote(self):
        for upload in [attachment(b'%PDF-garbage'), attachment(b'\x89PNG\r\n\x1a\n', 'garage.png'),
                       attachment(pdf_pages(['Repair quote','Panel repair EUR 500.00','Paint EUR 390.00',
                                             'Total EUR 890.00'], *[['Additional page']]*12))]:
            result = demo_replay(upload)
            self.assertIsNone(result['assessment']['amount_eur'])
            self.assertEqual(result['decision']['recommendation'], 'request_information')

    def test_quote_photo_is_flagged_for_manual_review_without_invented_facts(self):
        original = (FIXTURES.parent / 'photo-guide' / 'wide.jpg').read_bytes()
        evidence = assess_quote(attachment(original, 'Estimate-890-EUR.JPEG'))
        self.assertIn('manual review', evidence['reason'].lower())
        self.assertTrue(evidence['review_required'])
        self.assertEqual(evidence['status'], 'needs_clarification')
        self.assertIsNone(evidence['amount_eur'])
        self.assertIsNone(evidence['itemized'])
        self.assertIsNone(evidence['page'])
        self.assertEqual(evidence['lines'], [])
        self.assertEqual(evidence['garage_request'], '')

    def test_replay_uses_real_claim_facts_and_keeps_unknowns(self):
        evidence = assess_quote(attachment((FIXTURES / 'itemized-890.pdf').read_bytes()))
        facts = {'case_id': 'CLM-TEST', 'case_status': 'open'}
        self.assertEqual(replay_quote(evidence, facts)['recommendation'], 'request_information')
        self.assertEqual(replay_quote(evidence, dict(facts, injury_reported=True))['recommendation'], 'human_review')
        self.assertNotIn('quote_eur', facts)

    def test_validation_rejects_other_attachment_kind(self):
        doc = attachment(pdf_pages(['Repair quote']))
        with self.assertRaises(RequestError):
            assess_quote(dict(doc, kind='damage_photo'))
