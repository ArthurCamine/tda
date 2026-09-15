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
        repo/'supabase/migrations/20260908144711_transcript_review_default.sql',
        repo/'supabase/migrations/20260915211245_transcript_review_contract_comments.sql',
        repo/'supabase/tests/transcript_review_default.sql',
    ]
    for path in paths:
        run([str(binary/'psql'), '-X', '-h', str(socket), '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1'], input=path.read_text(), text=True)
    print(socket, flush=True)
    sys.stdin.read()
finally:
    if started:
        run([str(binary/'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'])