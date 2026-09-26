"""Private scratch PostgreSQL for synthetic tests, Unix socket only. Run on Linux/WSL.
Starts a fresh cluster, prints its socket, and stops it when stdin closes.
No environment credentials, TCP, existing database, production seed, or third-party packages.
"""
import os
import pathlib
import subprocess
import tempfile
import sys

repo = pathlib.Path(__file__).resolve().parents[1]
binary = pathlib.Path('/usr/lib/postgresql/16/bin')
root = pathlib.Path(tempfile.mkdtemp(prefix='tda-sync-'))
root.chmod(0o700)
data, socket = root/'data', root/'socket'
socket.mkdir(mode=0o700)
env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, env=env, **kwargs)
started = False
try:
    run([str(binary/'initdb'), '-D', str(data), '-U', 'postgres', '--auth-local=trust', '--auth-host=reject', '--encoding=UTF8', '--no-locale'])
    with (data/'postgresql.conf').open('a') as file:
        file.write(f"\nlisten_addresses=''\nunix_socket_directories='{socket}'\nunix_socket_permissions=0700\n")
    run([str(binary/'pg_ctl'), '-D', str(data), '-l', str(root/'postgres.log'), '-w', 'start'])
    started = True
    paths = [
        repo/'supabase/tests/transcript_import_fixture.sql',
        *sorted((repo/'supabase/candidates').glob('*_transcript_import_*.sql')),
        repo/'supabase/migrations/20260922133000_transcript_publication_revisions.sql',
        repo/'supabase/migrations/20260922151000_transcript_publication_hardening.sql',
        repo/'supabase/migrations/20260908144711_transcript_review_default.sql',
        repo/'supabase/migrations/20260915211245_transcript_review_contract_comments.sql',
        repo/'supabase/migrations/20260921003045_bind_transcript_edit_to_session.sql',
        repo/'supabase/migrations/20260923152000_transcript_statistics_read_model.sql',
        repo/'supabase/migrations/20260923163000_harden_transcript_statistics_grants.sql',
        repo/'supabase/tests/transcript_review_default.sql',
        repo/'supabase/tests/transcript_edit_atomic.sql',
        repo/'supabase/tests/transcript_statistics_read_model.sql',
        repo/'supabase/migrations/20260926220608_transcript_publication_current_cas.sql',
        repo/'supabase/tests/transcript_publication_revisions.sql',
    ]
    for path in paths:
        try:
            run(
                [
                    str(binary/'psql'),
                    '-X',
                    '-h',
                    str(socket),
                    '-U',
                    'postgres',
                    '-d',
                    'postgres',
                    '-v',
                    'ON_ERROR_STOP=1',
                ],
                input=path.read_text(),
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            print(
                f"SCRATCH_SQL_FAILED {path.relative_to(repo)}",
                file=sys.stderr,
                flush=True,
            )
            if exc.stdout:
                print(exc.stdout, file=sys.stderr, flush=True)
            if exc.stderr:
                print(exc.stderr, file=sys.stderr, flush=True)
            raise
    print(socket, flush=True)
    sys.stdin.read()
finally:
    if started:
        run([str(binary/'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'])