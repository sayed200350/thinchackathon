"""Page-cited checks for repair estimates and replay with the existing triage policy."""
import base64
import csv
from decimal import Decimal
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata

from engine.policy import decide
from . import intake_pdf
from .intake import _validate_document
from .store import RequestError


QUOTE_EXAMPLES = ('total-only-890.pdf', 'itemized-890.pdf', 'itemized-1800.pdf', 'unreadable-total.pdf')
DEMO_CASES = Path(__file__).resolve().parents[1] / 'data/taktile/labelled_development_cases.csv'
TOTAL_LABEL = re.compile(r'^(?:(?:grand|gross|quote|estimate)\s+total|total(?: amount| incl\.? VAT)?|'
                         r'gesamtbetrag|gesamtsumme|endbetrag|bruttobetrag|gesamt(?: brutto)?)\s*[:\-]?\s*(.*)$',
                         re.I)
# Require an explicit euro currency on the page or on each priced row. Never
# round unrecognized precision, convert currencies, or infer a total from line items.
NUMBER = r'(?:\d{1,3}(?:,\d{3})+\.\d{2}|\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,8}(?:[.,]\d{2})?)'
EURO = r'(?:€|EUR)'
MONEY = re.compile(rf'(?:{EURO}\s*({NUMBER})|({NUMBER})\s*{EURO})', re.I)
PRICED = re.compile(rf'^(.+?)(?:\s*:\s*|\s+)({EURO}\s*{NUMBER}|{NUMBER}\s*{EURO})$', re.I)
BARE_PRICED = re.compile(rf'^(.+?)(?:\s*:\s*|\s{{2,}})({NUMBER})$', re.I)
EURO_HEADING = re.compile(r'\b(?:amount|price|betrag|preis|summe|currency|währung)\s*[:(/\[]?\s*(?:EUR\b|€)', re.I)
WORK = re.compile(r'\b(?:parts?|materials?|pain[t\w]*|labou?r|repair\w*|replac\w*|refin\w*|'
                  r'align\w*|fitt?ing|bumper|door|panel|assembly|headlamp|windscreen|glass|'
                  r'arbeits\w*|lohn\w*|lack\w*|ersatzteil\w*|montage\w*|instandsetz\w*|'
                  r'stoßfänger\w*|karosserie\w*|austausch\w*)\b', re.I)
TAX = re.compile(r'^(?:VAT|MwSt\.?|Mehrwertsteuer|Umsatzsteuer|sales tax)(?:\s|$)', re.I)
NON_WORK = re.compile(r'\b(?:subtotal|netto|net|gross|brutto|tax|deposit|paid|balance|discount|'
                      r'anzahlung|zwischensumme|rabatt|summe|total)\b', re.I)


def _decimal(number):
    if ',' in number and '.' in number:
        if number.rfind(',') > number.rfind('.'):
            number = number.replace('.', '').replace(',', '.')
        else:
            number = number.replace(',', '')
    return Decimal(number.replace(',', '.'))


def _money(text, euro_header):
    match = MONEY.fullmatch(text)
    if match:
        return _decimal(match.group(1) or match.group(2))
    if euro_header and re.fullmatch(NUMBER, text):
        return _decimal(text)
    return None


def _result(name):
    return {'name': name, 'status': 'needs_clarification', 'amount_eur': None, 'itemized': None,
            'page': None, 'total_text': None, 'lines': [],
            'reason': 'I could not verify a readable repair estimate and euro total.',
            'garage_request': 'Please send a readable itemized repair estimate showing the work, its costs and the final euro total.'}


def _read_pdf_pages(content):
    reader, info = shutil.which('pdftotext'), shutil.which('pdfinfo')
    if not reader or not info or not intake_pdf.READERS.acquire(blocking=False):
        return None
    try:
        metadata = intake_pdf._bounded_output([info, '-'], content, 32768, 4)
        count = re.search(rb'^Pages:\s+(\d+)\s*$', metadata or b'', re.M)
        if not count or not 1 <= int(count[1]) <= intake_pdf.MAX_PAGES:
            return None
        text = intake_pdf._local_text(reader, content)
        if not text:
            return None
        pages = text.rstrip('\f').split('\f')
        if len(pages) != int(count[1]) or any(not page.strip() for page in pages):
            return None
        return [[unicodedata.normalize('NFKC', line).strip() for line in page.splitlines() if line.strip()]
                for page in pages]
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        intake_pdf.READERS.release()


def assess_quote(doc):
    if not isinstance(doc, dict) or doc.get('kind', 'itemized_quote') != 'itemized_quote':
        raise RequestError(400, 'Choose a repair estimate to check.')
    validated = _validate_document(dict(doc, kind='itemized_quote'))
    result = _result(validated['name'])
    if not validated['name'].lower().endswith('.pdf'):
        return result
    pages = _read_pdf_pages(base64.b64decode(validated['content_base64']))
    if not pages:
        return result
    kinds = {intake_pdf._page_kind(page) for page in pages}
    if 'itemized_quote' not in kinds or 'incident_report' in kinds:
        result['reason'] = 'I could not identify a repair estimate heading in this document.'
        return result

    totals, items, taxes = [], [], []
    for page_num, lines in enumerate(pages, 1):
        euro_header = any(EURO_HEADING.search(line) for line in lines)
        for line in lines:
            total = TOTAL_LABEL.fullmatch(line)
            if total:
                totals.append((_money(total[1], euro_header), page_num, line))
                continue
            row = PRICED.fullmatch(line) or (BARE_PRICED.fullmatch(line) if euro_header else None)
            if not row:
                continue
            desc, raw = row.groups()
            amount = _money(raw, euro_header)
            if TAX.search(desc):
                taxes.append(amount)
            elif WORK.search(desc) and not NON_WORK.search(desc):
                items.append((desc, amount, page_num))
    result['lines'] = [{'description': desc, 'amount_eur': float(value), 'page': page}
                       for desc, value, page in items]
    breakdown = len({desc.casefold() for desc, _, _ in items}) >= 2
    result['itemized'] = breakdown
    if len(totals) == 1:
        value, page, source = totals[0]
        result.update(page=page, total_text=source, amount_eur=float(value) if value is not None else None)
    else:
        value = None

    if value is None:
        result['reason'] = ('The document has more than one final total. Please confirm which estimate applies.'
                            if len(totals) > 1 else 'I could not verify a printed euro total for this estimate.')
    elif not breakdown:
        result['reason'] = f'I found the €{value:,.2f} total on page {result["page"]}, but could not verify a breakdown of the work and its costs.'
        result['garage_request'] = f'Could you send an itemized version of the €{value:,.2f} estimate showing the repair work and its costs?'
    elif sum(amount for _, amount, _ in items) + sum(taxes) != value:
        result['itemized'] = None
        result['reason'] = 'The priced work and recognized tax do not add up to the printed total. Please check the estimate.'
    else:
        result.update(status='verified', reason='The priced work and any listed tax add up to the printed euro total.',
                      garage_request='')
    return result


def replay_quote(assessment, facts):
    """Only the quote facts change; missing policy or incident facts stay unknown."""
    return decide(dict(facts, quote_eur=assessment['amount_eur'], itemized_quote_present=assessment['itemized']))


def demo_facts():
    with DEMO_CASES.open(encoding='utf-8', newline='') as source:
        return next(row for row in csv.DictReader(source) if row['case_id'] == 'DEV-003')


def demo_replay(doc):
    facts = demo_facts()
    assessment = assess_quote(doc)
    return {'assessment': assessment, 'decision': replay_quote(assessment, facts), 'original': decide(facts)}
