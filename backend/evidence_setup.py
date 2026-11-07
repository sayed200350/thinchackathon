"""Prepare local staff credentials and a project-specific Supabase evidence migration."""

import argparse
import hashlib
import os
from pathlib import Path
import secrets
import tempfile


def credential(folder, name):
    supplied = os.getenv(name)
    if supplied:
        if len(supplied) < 32:
            raise ValueError(f'{name} must contain at least 32 characters.')
        return supplied
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    dest = folder / name.lower()
    if not dest.exists():
        with tempfile.NamedTemporaryFile(mode='w', dir=folder, delete=False) as temporary:
            temporary.write(secrets.token_hex(32))
        try:
            try:
                os.link(temporary.name, dest)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary.name)
    return dest.read_text().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=Path(__file__).parent / '.local')
    parser.add_argument('--sql-output', type=Path, required=True)
    args = parser.parse_args()
    key = credential(args.state_dir, 'CLAIM_EVIDENCE_SERVICE_KEY')
    credential(args.state_dir, 'CLAIM_REVIEWER_KEY')
    path = Path(__file__).resolve().parents[1] / 'contract/db/claim_evidence.sql'
    args.sql_output.write_text(
        path.read_text().replace('__SERVICE_KEY_SHA256__', hashlib.sha256(key.encode()).hexdigest())
    )
    print('Private migration written to', args.sql_output)


if __name__ == '__main__':
    main()
