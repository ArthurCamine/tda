"""Validate the World entity media migration in disposable PostgreSQL.

Synthetic only: Unix socket, no TCP, no inherited PG credentials, no production
seed and no Supabase connection. Migration SQL is executed only inside the temp
cluster; this runner never mutates a remote database.
"""

import os
import pathlib
import shutil
import subprocess
import tempfile

repo = pathlib.Path(__file__).resolve().parents[1]
binary = pathlib.Path("/usr/lib/postgresql/16/bin")
root = pathlib.Path(tempfile.mkdtemp(prefix="tda-world-entity-media-"))
root.chmod(0o700)
data = root / "data"
socket = root / "socket"
socket.mkdir(mode=0o700)
env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, env=env, **kwargs)


psql_args = [
    str(binary / "psql"),
    "-X",
    "-A",
    "-t",
    "-q",
    "-h",
    str(socket),
    "-U",
    "postgres",
    "-d",
    "postgres",
    "-v",
    "ON_ERROR_STOP=1",
]


def run_sql_file(path):
    try:
        return run(psql_args, input=path.read_text(encoding="utf-8"), text=True)
    except subprocess.CalledProcessError as error:
        relative = path.relative_to(repo)
        raise RuntimeError(
            f"World entity media PostgreSQL contract failed in {relative}\n"
            f"stdout={error.stdout}\nstderr={error.stderr}"
        ) from error


started = False
try:
    run(
        [
            str(binary / "initdb"),
            "-D",
            str(data),
            "-U",
            "postgres",
            "--auth-local=trust",
            "--auth-host=reject",
            "--encoding=UTF8",
            "--no-locale",
        ]
    )
    with (data / "postgresql.conf").open("a", encoding="utf-8") as file:
        file.write(
            f"\nlisten_addresses=''\nunix_socket_directories='{socket}'\n"
            "unix_socket_permissions=0700\n"
        )
    run(
        [
            str(binary / "pg_ctl"),
            "-D",
            str(data),
            "-l",
            str(root / "postgres.log"),
            "-w",
            "start",
        ]
    )
    started = True

    migration_paths = sorted(
        [
            *(repo / "supabase/migrations").glob("*_world_layout_*.sql"),
            *(repo / "supabase/migrations").glob("*_world_edit_*.sql"),
            *(repo / "supabase/migrations").glob("*_world_graph_*.sql"),
        ]
    )
    paths = [
        repo / "supabase/tests/world_layout_fixture.sql",
        *migration_paths,
        # Reuse the same synthetic setup sequence as tools/world-layout-db.py.
        # The earlier suites create the role assignment/capability state that
        # the factual authoring contract intentionally expects.
        repo / "supabase/tests/world_layout_snapshot_atomic.sql",
        repo / "supabase/tests/world_edit_lease_atomic.sql",
        repo / "supabase/tests/world_graph_authoring_atomic.sql",
        repo / "supabase/migrations/20260912214500_world_entity_media_foundation_v2.sql",
        repo / "supabase/tests/world_entity_media_candidate.sql",
    ]
    outputs = [run_sql_file(path).stdout.strip() for path in paths]
    media_output = outputs[-1]
    if "WORLD_ENTITY_MEDIA_DATABASE_OK" not in media_output:
        raise RuntimeError(f"missing media contract receipt: {media_output!r}")

    print(
        "WORLD_ENTITY_MEDIA_DATABASE_OK synthetic=true migration=true "
        "remote_mutation=false"
    )
finally:
    if started:
        run([str(binary / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"])
    shutil.rmtree(root, ignore_errors=True)
