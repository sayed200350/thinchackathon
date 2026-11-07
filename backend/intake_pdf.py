"""Read labelled motor claim fields using local Poppler and optional Tesseract OCR."""

import base64
from datetime import date, datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
from threading import BoundedSemaphore
from time import monotonic
import unicodedata
from zoneinfo import ZoneInfo

from .intake import _validate_document
from .store import RequestError


MAX_PAGES = 12
MAX_TEXT_BYTES = 256 * 1024
MAX_SCAN_PAGES = 2
MAX_SCAN_EDGE = 1400
MAX_SCAN_BYTES = 6 * 1024 * 1024
MAX_SUGGESTIONS = 32
READERS = BoundedSemaphore(2)

# Limit the child before exec. preexec_fn is unsafe in a threaded HTTP server.
LIMITED_EXEC = """
import os, resource, sys
def limit(which, maximum):
    _, hard = resource.getrlimit(which)
    new = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
    resource.setrlimit(which, (new, new))
limit(resource.RLIMIT_CPU, 4)
limit(resource.RLIMIT_FSIZE, int(sys.argv[1]))
if sys.platform.startswith('linux'):
    limit(resource.RLIMIT_AS, 512 * 1024 * 1024)
os.execv(sys.argv[2], sys.argv[2:])
"""

LABELS = {
    'incident_date': (
        'incident date', 'date of incident', 'date of the incident', 'accident date',
        'date of accident', 'date of the accident', 'date of loss',
        'unfalldatum', 'unfalltag', 'schadendatum', 'schadensdatum', 'datum des unfalls',
    ),
    'location': (
        'incident location', 'accident location', 'location of accident', 'location of incident',
        'place of loss', 'accident site', 'place of accident', 'unfallort', 'schadenort', 'schadensort',
        'location', 'ort',
    ),
    'description': (
        'what happened', 'incident description', 'description of incident', 'accident description',
        'description of accident', 'description of the accident', 'circumstances of accident',
        'unfallhergang', 'schadenhergang', 'schadenshergang', 'schadenschilderung',
        'beschreibung des unfalls', 'beschreibung des unfallhergangs',
    ),
    'policy_number': (
        'policy number', 'policy no.', 'policy no', 'policy #', 'insurance policy number',
        'versicherungsnummer', 'versicherungsscheinnummer', 'versicherungsschein-nr.',
        'versicherungsschein-nr', 'policennummer', 'vertragsnummer',
    ),
    'email': (
        'claimant email', 'claimant email address', 'policyholder email', 'policyholder email address',
        'e-mail des versicherungsnehmers', 'e-mail des anspruchstellers',
        'email address', 'contact email', 'e-mail-adresse', 'e-mail', 'email',
    ),
}
FIELD_FOR_LABEL = {label: field for field, labels in LABELS.items() for label in labels}
LABEL_PATTERN = '|'.join(re.escape(key) for key in sorted(FIELD_FOR_LABEL, key=len, reverse=True))
FIELD_LINE = re.compile(r'^(' + LABEL_PATTERN + r')(?:(?:\s*[:：]\s*|\s+[-–]\s+|\s{2,})(.*))?$', re.I)
OTHER_LABEL = re.compile(r'^[^:]{1,55}:(?:\s|$)')
CLAIMANT_EMAIL_LABELS = frozenset(LABELS['email'][:6])
REPORT_TITLE = re.compile(r'\b(?:accident (?:report|statement)|incident report|police report|'
                          r'unfallbericht|unfallanzeige|schadens?meldung)\b', re.I)
QUOTE_TITLE = re.compile(r'\b(?:(?:workshop|repair|itemi[sz]ed) (?:estimate|quote|quotation)|'
                         r'kostenvoranschlag|reparaturkalkulation|reparaturangebot)\b', re.I)
MONTHS = {word: index for index, words in enumerate((
    (), ('january', 'januar', 'jan'), ('february', 'februar', 'feb'), ('march', 'märz', 'mar'),
    ('april', 'apr'), ('may', 'mai'), ('june', 'juni', 'jun'), ('july', 'juli', 'jul'),
    ('august', 'aug'), ('september', 'sep', 'sept'), ('october', 'oktober', 'oct', 'okt'),
    ('november', 'nov'), ('december', 'dezember', 'dec', 'dez'),
)) for word in words}


def _page_kind(lines):
    # Use headings, never a filename or an incidental mention in a long narrative.
    headings = [line for line in lines[:10] if line and len(line) <= 75 and ':' not in line]
    report = any(REPORT_TITLE.search(line) for line in headings)
    quote = any(QUOTE_TITLE.search(line) for line in headings)
    if report != quote:
        return 'incident_report' if report else 'itemized_quote'
    return None


def _date_value(value):
    ymd = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', value)
    numeric = re.fullmatch(r'(\d{1,2})([./])(\d{1,2})\2(\d{4})', value)
    verbal = re.fullmatch(r'(\d{1,2})\.?\s+([\w]+)\.?\s+(\d{4})', value)
    month_first = re.fullmatch(r'([\w]+)\.?\s+(\d{1,2}),?\s+(\d{4})', value)
    if ymd:
        year, month, day = map(int, ymd.groups())
    elif numeric:
        day, sep, month, year = numeric.groups()
        day, month, year = int(day), int(month), int(year)
        if sep == '/':
            if day != month and day <= 12 and month <= 12:
                return None
            if month > 12:
                day, month = month, day
    elif verbal or month_first:
        if verbal:
            day, name, year = verbal.groups()
        else:
            name, day, year = month_first.groups()
        day, month, year = int(day), MONTHS.get(name.casefold(), 0), int(year)
    else:
        return None
    try:
        found = date(year, month, day)
    except ValueError:
        return None
    return found.isoformat() if found <= datetime.now(ZoneInfo('Europe/Berlin')).date() else None


def _field_value(field, label, value, kind):
    if not value or value.casefold() in {'n/a', 'unknown', 'unbekannt', 'tbd', '-', '—'}:
        return None
    if re.search(r'\s{2,}\S', value) or OTHER_LABEL.match(value):
        return None  # A table row has more than one cell or another labelled value.
    if field == 'incident_date':
        return _date_value(value)
    if field == 'email':
        if kind != 'incident_report' and label not in CLAIMANT_EMAIL_LABELS:
            return None
        return value if len(value) <= 254 and re.fullmatch(r'[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+', value) else None
    if field == 'location' and label in {'location', 'ort'} and kind != 'incident_report':
        return None
    minimum, maximum = {'location': (1, 160), 'description': (10, 2000), 'policy_number': (1, 80)}[field]
    return value if minimum <= len(value) <= maximum else None


def _field_candidates(lines, kind):
    for index, line in enumerate(lines):
        match = FIELD_LINE.fullmatch(line)
        if not match:
            continue
        label, value = match.groups()
        label = label.casefold()
        field = FIELD_FOR_LABEL[label]
        following = index + 1
        if not value:
            # Form layouts often place the answer in the next paragraph.
            while following < len(lines) and not lines[following]:
                following += 1
            if following == len(lines) or FIELD_LINE.fullmatch(lines[following]) or OTHER_LABEL.match(lines[following]):
                continue
            value = lines[following]
            following += 1
        if field == 'description':
            for continuation in lines[following:following + 5]:
                if (not continuation or FIELD_LINE.fullmatch(continuation) or OTHER_LABEL.match(continuation)
                        or re.search(r'\s{2,}', continuation) or value.endswith(('.', '!', '?'))):
                    break
                value += ' ' + continuation
        value = _field_value(field, label, value.strip(), kind)
        if value is not None:
            yield field, value


def _suggestions(text):
    pages = []
    for raw_page in text.split('\f')[:MAX_PAGES]:
        lines = [unicodedata.normalize('NFKC', line).strip() for line in raw_page.splitlines()]
        pages.append((lines, _page_kind(lines)))
    kinds = {kind for _, kind in pages if kind}
    document_kind = next(iter(kinds)) if len(kinds) == 1 else None
    seen = set()
    suggestions = []
    for page_number, (lines, kind) in enumerate(pages, 1):
        for field, value in _field_candidates(lines, kind or document_kind):
            if (field, value) in seen:
                continue
            seen.add((field, value))
            suggestions.append({'field': field, 'value': value, 'page': page_number})
            if len(suggestions) == MAX_SUGGESTIONS:
                return document_kind, suggestions
    return document_kind, suggestions


def _bounded_output(command, data, maximum, timeout):
    # Never pass the user's filename to a parser. A temporary file bounds its
    # stdout size at the OS level and closes automatically, including on timeout.
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
        source.write(data)
        source.seek(0)
        result = subprocess.run(
            [sys.executable, '-I', '-c', LIMITED_EXEC, str(maximum + 1), *command],
            stdin=source, stdout=output, stderr=subprocess.DEVNULL, timeout=timeout, check=False,
            env={'PATH': os.defpath, 'OMP_THREAD_LIMIT': '1'},
        )
        if result.returncode:
            return None
        output.seek(0)
        raw = output.read(maximum + 1)
        return raw if len(raw) <= maximum else None


def _local_text(executable, pdf):
    command = [executable, '-q', '-f', '1', '-l', str(MAX_PAGES), '-layout', '-enc', 'UTF-8', '-', '-']
    raw = _bounded_output(command, pdf, MAX_TEXT_BYTES, 6)
    return raw.decode('utf-8', errors='replace') if raw is not None else None


def _scan_text(pdf, page_count):
    renderer = shutil.which('pdftoppm')
    ocr = shutil.which('tesseract')
    if not renderer or not ocr:
        return ''
    pages = []
    deadline = monotonic() + 8
    for index in range(1, min(page_count, MAX_SCAN_PAGES) + 1):
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        render = [renderer, '-q', '-f', str(index), '-l', str(index), '-singlefile', '-gray',
                  '-scale-to', str(MAX_SCAN_EDGE), '-png', '-']
        image = _bounded_output(render, pdf, MAX_SCAN_BYTES, min(remaining, 4))
        remaining = deadline - monotonic()
        if not image or remaining <= 0:
            break
        read = [ocr, 'stdin', 'stdout', '-l', 'eng', '--psm', '3', '-c', 'preserve_interword_spaces=1']
        raw = _bounded_output(read, image, MAX_TEXT_BYTES // MAX_SCAN_PAGES, min(remaining, 4))
        pages.append(raw.decode('utf-8', errors='replace') if raw else '')
    return '\f'.join(pages)


def extract_pdf(body):
    """Read a PDF for confirmation; this operation does not submit or persist a claim."""
    if not isinstance(body, dict) or set(body) != {'name', 'content_base64'}:
        raise RequestError(400, 'Provide the PDF filename and its base64 contents.')
    if not isinstance(body['name'], str) or not body['name'].lower().endswith('.pdf'):
        raise RequestError(400, 'Choose a PDF to import.')
    validated = _validate_document(dict(body, kind='incident_report'))
    result = {'document_kind': None, 'suggestions': [], 'notice': ''}
    executable = shutil.which('pdftotext')
    if not executable:
        result['notice'] = 'The PDF reader is unavailable. You can attach the document and enter your answers.'
        return result
    if not READERS.acquire(blocking=False):
        result['notice'] = 'The PDF reader is busy. Try again or enter the claim details yourself.'
        return result
    scanned = False
    try:
        pdf = base64.b64decode(validated['content_base64'])
        text = _local_text(executable, pdf)
        if text is not None and not text.strip():
            scanned = True
            text = _scan_text(pdf, max(1, text.count('\f')))
    except (OSError, subprocess.TimeoutExpired):
        text = ''
    finally:
        READERS.release()
    if not text or not text.strip():
        result['notice'] = 'No readable text was available. For a scan or protected file, attach the PDF and enter your answers.'
        return result
    kind, suggestions = _suggestions(text)
    result['document_kind'] = kind
    result['suggestions'] = suggestions
    if scanned:
        result['notice'] = ('Suggestions come from an optical scan of the first two pages. Check the spelling and numbers.'
                            if suggestions else 'No labelled details could be read on the first two scanned pages. Enter your answers.')
    else:
        result['notice'] = ('Check each suggestion against the document before continuing.' if suggestions
                            else 'No labelled claim details were found in the first 12 pages. Enter the information you know.')
    return result
