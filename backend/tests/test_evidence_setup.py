from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from backend import __main__ as cli


class EvidenceSetupTests(unittest.TestCase):
    def test_empty_optional_setting_uses_persisted_service_key(self):
        with ExitStack() as cleanup:
            folder = Path(cleanup.enter_context(tempfile.TemporaryDirectory()))
            cleanup.enter_context(patch.dict(os.environ, {'CLAIM_EVIDENCE_SERVICE_KEY': ''}))
            env_file = folder / '.env'
            server = MagicMock()

            def verify():
                saved = (folder / 'backend/.local/claim_evidence_service_key').read_text()
                self.assertTrue(bool(saved) and os.environ['CLAIM_EVIDENCE_SERVICE_KEY'] == saved)

            server.__enter__.return_value.serve_forever.side_effect = verify
            cleanup.enter_context(patch('sys.argv', ['backend', '--store', 'supabase', '--env-file', str(env_file)]))
            cleanup.enter_context(patch.object(cli, 'open_store_factory', return_value=('Supabase', None)))
            cleanup.enter_context(patch.object(cli, 'ThreadingHTTPServer', return_value=server))
            cleanup.enter_context(redirect_stdout(StringIO()))
            cleanup.enter_context(redirect_stderr(StringIO()))
            cli.main()
