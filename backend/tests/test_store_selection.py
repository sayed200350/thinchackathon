import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.__main__ import load_settings, open_store_factory
from backend.supabase_store import SupabaseStore


class StoreSelectionTests(unittest.TestCase):
    def test_configured_project_is_default_for_every_request(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            env_file = Path(folder) / '.env'
            env_file.write_text('SUPABASE_URL=https://example.supabase.co\nSUPABASE_ANON_KEY=sb_publishable_fixture\n')
            load_settings(env_file)
            label, open_store = open_store_factory('auto', None, None)
            self.assertEqual(label, 'Supabase')
            with open_store() as store, open_store() as another:
                self.assertIsInstance(store, SupabaseStore)
                self.assertIs(store, another)

    def test_partial_config_does_not_silently_create_an_offline_database(self):
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://example.supabase.co'}, clear=True):
            for mode in ('auto', 'supabase'):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'PUBLISHABLE_KEY'):
                    open_store_factory(mode, None, None)

    def test_existing_offline_db_option_wins_and_conflicting_explicit_modes_fail(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'SUPABASE_URL': 'https://example.supabase.co'}, clear=True):
            database = Path(folder) / 'offline.db'
            label, open_store = open_store_factory('auto', database, None)
            self.assertEqual(label, 'SQLite')
            with open_store() as sqlite:
                self.assertEqual(len(sqlite.claim_list()['claims']), 26)
            with self.assertRaisesRegex(ValueError, '--db'):
                open_store_factory('supabase', database, None)
