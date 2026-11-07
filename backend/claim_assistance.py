"""Read photo capture dates and prepare private, claimant-confirmed report translations."""
import base64
import binascii
from datetime import date, datetime
import hashlib
import os
from pathlib import Path
import re
import struct
import shutil
import tempfile
import subprocess
import sys
import zipfile
from threading import BoundedSemaphore


def _tiff_date(data):
    order = {b'II': '<', b'MM': '>'}.get(bytes(data[:2]))
    if not order or len(data) < 8:
        return None

    def number(fmt, offset):
        return struct.unpack_from(order + fmt, data, offset)[0]

    try:
        if number('H', 2) != 42:
            return None
        pending = [number('I', 4)]
        visited = set()
        while pending and len(visited) < 4:
            offset = pending.pop()
            if offset in visited or offset < 8:
                continue
            visited.add(offset)
            entries = number('H', offset)
            if offset + 2 + entries * 12 > len(data):
                return None
            for i in range(entries):
                pos = offset + 2 + i * 12
                tag, kind, count, pointer = struct.unpack_from(order + 'HHII', data, pos)
                if tag == 0x8769 and kind == 4 and count == 1:
                    pending.append(pointer)
                if tag == 0x9003 and kind == 2 and count in (19, 20):
                    text = bytes(data[pointer:pointer + 19]).decode('ascii')
                    if re.fullmatch(r'\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}', text):
                        return datetime.strptime(text, '%Y:%m:%d %H:%M:%S').date().isoformat()
    except (struct.error, ValueError):
        pass
    return None


def capture_date(raw):
    """Read DateTimeOriginal; filesystem timestamps and GPS never enter the record."""
    data = memoryview(raw)
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        pos = 8
        while pos + 12 <= len(data):
            size = int.from_bytes(data[pos:pos + 4], 'big')
            end = pos + 8 + size
            if end + 4 > len(data):
                break
            if data[pos + 4:pos + 8] == b'eXIf':
                return _tiff_date(data[pos + 8:end])
            pos = end + 4
    elif data[:2] == b'\xff\xd8':
        pos = 2
        while pos + 3 <= len(data) and data[pos] == 0xff:
            pos += 1
            while pos < len(data) and data[pos] == 0xff:
                pos += 1
            if pos + 3 > len(data) or data[pos] in (0xda, 0xd9):
                break
            marker = data[pos]
            length = int.from_bytes(data[pos + 1:pos + 3], 'big')
            end = pos + 1 + length
            if length < 2 or end > len(data):
                break
            if marker == 0xe1 and data[pos + 3:pos + 9] == b'Exif\0\0':
                stamp = _tiff_date(data[pos + 9:end])
                if stamp:
                    return stamp
            pos = end
    return None


# A known phrase can be served on installations without neural model weights. Only
# complete sentences match: partial matches could lose a negation or change a fact.
PHRASES = {
    'ein lieferwagen streifte die linke hintere tür meines geparkten autos.':
        'A delivery van scraped the left rear door of my parked car.',
    'die fahrertür blieb unbeschädigt.': 'The driver’s door was undamaged.',
    'mein fahrzeug war geparkt.': 'My vehicle was parked.',
}
TRANSLATORS = BoundedSemaphore(2)
GERMAN_NARRATIVE = re.compile(r'^(?:unfallhergang|schaden[s]?hergang|schadenschilderung|'
                              r'beschreibung des unfalls|beschreibung des unfallhergangs|sachverhalt|bemerkungen)\s*'
                              r'(?:[:：]\s*|\s[-–]\s*|\s{2,}|$)(.*)$', re.I)


def _run_model(model_dir):
    """Child process entry point in an optional isolated local translation runtime."""
    import ctranslate2
    import sentencepiece
    tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(model_dir / 'sentencepiece.model'))
    translator = ctranslate2.Translator(str(model_dir / 'model'), device='cpu',
                                        compute_type='int8', intra_threads=2)
    sentences = re.split(r'(?<=[.!?])\s+', sys.stdin.buffer.read(12000).decode().strip())
    tokens = [tokenizer.encode(sentence, out_type=str) for sentence in sentences]
    if any(len(sentence) > 512 for sentence in tokens):
        return
    outputs = translator.translate_batch(tokens, beam_size=3, max_input_length=0, max_decoding_length=1024)
    print(' '.join(tokenizer.decode(output.hypotheses[0]) for output in outputs))


def _translate_local(original):
    root = Path.home() / '.local/share/policy-replay'
    model = Path(os.environ.get('CLAIM_TRANSLATION_MODEL', root / 'translate-de_en-1_3'))
    runtime = os.environ.get('CLAIM_TRANSLATION_PYTHON', str(root / 'translation-runtime/bin/python'))
    if not (model / 'model/model.bin').is_file() or not Path(runtime).is_file():
        return None
    if not TRANSLATORS.acquire(blocking=False):
        return None
    try:
        result = subprocess.run([runtime, '-I', __file__, '--translate', str(model)],
                                input=original.encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=14, check=False)
        english = result.stdout.decode().strip()
        if result.returncode == 0 and 0 < len(english) <= 4000 and english != original:
            return english
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        pass
    finally:
        TRANSLATORS.release()
    return None


def report_translation(text, suggestions, kind):
    """Retain the original German narrative and the physical page that contains it."""
    if kind != 'incident_report':
        return None
    for page, content in enumerate(text.split('\f')[:12], 1):
        lines = [line.strip() for line in content.splitlines()]
        for i, line in enumerate(lines):
            heading = GERMAN_NARRATIVE.match(line)
            if not heading:
                continue
            section = [heading.group(1).strip()] if heading.group(1).strip() else []
            for rest in lines[i + 1:]:
                if not rest and not section:
                    continue
                if not rest or re.match(r'^[^:]{1,55}:', rest):
                    break
                section.append(rest)
            original = ' '.join(section)
            if not 1 <= len(original) <= 2000:
                continue
            pieces = re.split(r'(?<=[.!?])\s+', original)
            if all(piece.casefold() in PHRASES for piece in pieces):
                english = ' '.join(PHRASES[piece.casefold()] for piece in pieces)
                source = 'phrasebook'
            else:
                english = _translate_local(original) or ''
                source = 'local_model' if english else 'manual'
            return {'original': original, 'english': english, 'source': source, 'page': page,
                    'confirmed': False, 'use_original': False}
    return None


def clean_assistance(doc):
    """Normalize only the supported per-file evidence note before private storage."""
    from .store import RequestError

    def text_value(value, maximum):
        if not isinstance(value, str) or len(value) > maximum or re.search(r'[\x00\ud800-\udfff]', value):
            raise RequestError(400, 'Invalid evidence note.')
        return value.strip()

    note = doc.get('assistance', {})
    if not isinstance(note, dict):
        raise RequestError(400, 'Invalid evidence note.')
    if doc.get('kind') == 'damage_photo':
        if set(note) - {'view', 'manual_date', 'exif_date', 'explanation'}:
            raise RequestError(400, 'Invalid photo note.')
        try:
            stamp = capture_date(base64.b64decode(doc['content_base64'], validate=True))
        except (KeyError, ValueError, TypeError, binascii.Error):
            raise RequestError(400, 'Invalid photo contents.') from None
        view = note.get('view', '')
        if view not in ('', 'wide', 'close_up'):
            raise RequestError(400, 'Choose wide shot or close-up.')
        manual = text_value(note.get('manual_date', ''), 10)
        if manual:
            try:
                if date.fromisoformat(manual).isoformat() != manual:
                    raise ValueError()
            except ValueError:
                raise RequestError(400, 'Enter a valid date for the photo.') from None
        if not note and not stamp:
            return {}
        return {'view': view, 'exif_date': stamp, 'manual_date': manual,
                'explanation': text_value(note.get('explanation', ''), 1000)}
    if not note:
        return {}
    if doc.get('kind') != 'incident_report' or set(note) != {'translation'}:
        raise RequestError(400, 'Invalid note for this attachment.')
    item = note['translation']
    keys = {'original', 'english', 'page', 'source', 'confirmed', 'use_original'}
    if not isinstance(item, dict) or set(item) - keys:
        raise RequestError(400, 'Invalid translation.')
    page, source = item.get('page'), item.get('source')
    confirmed, use_original = item.get('confirmed'), item.get('use_original', False)
    original = text_value(item.get('original'), 2000)
    english = text_value(item.get('english'), 4000)
    if (not original or type(page) is not int or not 1 <= page <= 12
            or source not in ('local_model', 'phrasebook', 'manual')
            or type(confirmed) is not bool or type(use_original) is not bool
            or (confirmed and (not english or use_original))):
        raise RequestError(400, 'Check the original text, English translation and confirmation.')
    return {'translation': {'original': original, 'english': english, 'page': page, 'source': source,
                            'confirmed': confirmed, 'use_original': use_original}}


def unpack_model(archive, root, checksum):
    """Install the pinned Argos resources after verifying the entire download."""
    digest = hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != checksum:
        raise ValueError('The downloaded German–English model checksum does not match.')
    package = 'translate-de_en-1_3'
    names = ('model/model.bin', 'model/config.json', 'model/shared_vocabulary.json',
             'sentencepiece.model', 'README.md', 'metadata.json')
    with tempfile.TemporaryDirectory(dir=root) as tmp, zipfile.ZipFile(archive) as bundle:
        directory = Path(tmp) / package
        (directory / 'model').mkdir(parents=True)
        for name in names:
            with bundle.open(package + '/' + name) as src, (directory / name).open('wb') as dst:
                shutil.copyfileobj(src, dst)
        directory.rename(root / package)


def install_translation():
    """Explicit one-time setup. Handling a claim never initiates a network download."""
    import urllib.request
    import venv
    root = Path.home() / '.local/share/policy-replay'
    root.mkdir(parents=True, exist_ok=True)
    runtime = root / 'translation-runtime'
    if not (runtime / 'bin/python').is_file():
        venv.EnvBuilder(with_pip=True).create(runtime)
    subprocess.run([str(runtime / 'bin/python'), '-m', 'pip', 'install',
                    'ctranslate2==4.8.5', 'sentencepiece==0.2.3'], check=True)
    if not (root / 'translate-de_en-1_3').exists():
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            archive = Path(tmp) / 'model.zip'
            with urllib.request.urlopen('https://argos-net.com/v1/translate-de_en-1_3.argosmodel',
                                        timeout=60) as src, archive.open('wb') as dst:
                shutil.copyfileobj(src, dst)
            unpack_model(archive, root, 'becc2b0011f8249fcb89be9ecb75ba0d876b1fab93c28ee6ff0420936897d637')
    if not _translate_local('Mein Auto ist blau.'):
        raise SystemExit('The installed local translator did not respond. Check the runtime and model files.')
    print('Local German–English translation is ready.')


if __name__ == '__main__':
    if sys.argv[1:] == ['--install-translation']:
        install_translation()
    elif len(sys.argv) == 3 and sys.argv[1] == '--translate':
        _run_model(Path(sys.argv[2]))
    else:
        raise SystemExit('Usage: python3 -m backend.claim_assistance --install-translation')
