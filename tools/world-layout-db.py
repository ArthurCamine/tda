"""Run World layout/editor migrations in a disposable PostgreSQL cluster.

Synthetic only: Unix socket, no TCP, no inherited PG credentials, no production
seed and no Supabase connection. Exits non-zero on any fixture/migration/assertion
failure and always removes the temporary cluster afterwards.
"""

import os
import pathlib
import shutil
import subprocess
import tempfile
import time

repo = pathlib.Path(__file__).resolve().parents[1]
binary = pathlib.Path("/usr/lib/postgresql/16/bin")
root = pathlib.Path(tempfile.mkdtemp(prefix="tda-world-layout-"))
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


def run_psql(sql):
    return run(psql_args, input=sql, text=True)


def run_sql_file(path):
    try:
        return run_psql(path.read_text(encoding="utf-8"))
    except subprocess.CalledProcessError as error:
        relative = path.relative_to(repo)
        raise RuntimeError(
            f"PostgreSQL contract failed in {relative}\n"
            f"stdout={error.stdout}\nstderr={error.stderr}"
        ) from error


def scalar(sql):
    return run_psql(sql).stdout.strip()


def wait_for(sql, *, attempts=80, delay=0.05):
    for _ in range(attempts):
        if scalar(sql) == "t":
            return
        time.sleep(delay)
    raise RuntimeError(f"timed out waiting for PostgreSQL state: {sql}")


def start_psql(sql):
    process = subprocess.Popen(
        psql_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    process.stdin.write(sql)
    process.stdin.close()
    # communicate() tries to flush a non-None stdin even when already closed.
    process.stdin = None
    return process


def collect_psql(process, *, timeout=10):
    stdout, stderr = process.communicate(timeout=timeout)
    if process.returncode != 0:
        raise RuntimeError(
            f"psql concurrency session failed rc={process.returncode}\nstdout={stdout}\nstderr={stderr}"
        )
    return stdout.strip()


def assert_saved_conflict(first, second, revision, label):
    saved = f'"status": "saved"' in first and f'"revision": {revision}' in first
    conflict = f'"reason": "conflict"' in second and f'"revision": {revision}' in second
    if not saved or not conflict:
        raise RuntimeError(
            f"{label} expected saved/{revision} + conflict/{revision}; first={first!r} second={second!r}"
        )


def assert_acquired_busy(first, second):
    acquired = '"status": "acquired"' in first and '"ok": true' in first
    busy = '"reason": "busy"' in second and '"ok": false' in second
    if not acquired or not busy:
        raise RuntimeError(
            f"lease race expected acquired + busy; first={first!r} second={second!r}"
        )


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
    run([str(binary / "pg_ctl"), "-D", str(data), "-l", str(root / "postgres.log"), "-w", "start"])
    started = True

    migration_paths = sorted(
        [
            *(repo / "supabase/migrations").glob("*_world_layout_*.sql"),
            *(repo / "supabase/migrations").glob("*_world_edit_*.sql"),
            *(repo / "supabase/migrations").glob("*_world_graph_*.sql"),
            *(repo / "supabase/migrations").glob("*_world_relation_provenance_*.sql"),
        ]
    )
    paths = [
        repo / "supabase/tests/world_layout_fixture.sql",
        *migration_paths,
        repo / "supabase/tests/world_layout_snapshot_atomic.sql",
        repo / "supabase/tests/world_edit_lease_atomic.sql",
        repo / "supabase/tests/world_graph_authoring_atomic.sql",
        repo / "supabase/tests/world_relation_provenance_atomic.sql",
    ]
    for path in paths:
        run_sql_file(path)

    # The SQL assertions above exercise grants, authorization, lease recovery,
    # private drafts, factual graph publication, stale conflict and audit rollback.
    # Reset only synthetic World state, then use real PostgreSQL sessions to prove
    # the low-level layout/lease lock behavior under concurrent transactions.
    run_psql(
        """
        delete from public.world_edit_leases;
        delete from public.world_edit_drafts;
        delete from public.audit_log where action in ('world_layout.update', 'world_graph.publish');
        delete from public.world_graph_revisions;
        delete from public.world_graph_heads;
        delete from public.entity_relations;
        delete from public.world_relation_styles;
        delete from public.relation_types;
        delete from public.world_layout_snapshots;
        """
    )

    first_insert_a = start_psql(
        """
        begin;
        set application_name = 'tda-world-layout-insert-a';
        set role service_role;
        select public.save_world_layout_snapshot_atomic(
          '44444444-4444-4444-8444-444444444444',
          '33333333-3333-4333-8333-333333333333',
          'synthetic-campaign',
          0,
          '{"node-a":{"x":100,"y":-50}}'::jsonb
        );
        select pg_sleep(3);
        commit;
        """
    )
    wait_for(
        """
        select exists (
          select 1 from pg_stat_activity
          where application_name = 'tda-world-layout-insert-a'
            and wait_event_type = 'Timeout'
            and wait_event = 'PgSleep'
        );
        """
    )

    first_insert_b = start_psql(
        """
        begin;
        set application_name = 'tda-world-layout-insert-b';
        set role service_role;
        select public.save_world_layout_snapshot_atomic(
          '44444444-4444-4444-8444-444444444444',
          '33333333-3333-4333-8333-333333333333',
          'synthetic-campaign',
          0,
          '{"node-a":{"x":200,"y":-50}}'::jsonb
        );
        commit;
        """
    )
    wait_for(
        """
        select exists (
          select 1 from pg_stat_activity
          where application_name = 'tda-world-layout-insert-b'
            and wait_event_type = 'Lock'
        );
        """
    )

    first_insert_a_out = collect_psql(first_insert_a)
    first_insert_b_out = collect_psql(first_insert_b)
    assert_saved_conflict(first_insert_a_out, first_insert_b_out, 1, "first-insert race")
    if scalar(
        """
        select revision::text || ':' ||
               (select count(*) from public.audit_log where action = 'world_layout.update')::text
        from public.world_layout_snapshots;
        """
    ) != "1:1":
        raise RuntimeError("first-insert race must leave revision=1 and exactly one audit row")

    update_a = start_psql(
        """
        begin;
        set application_name = 'tda-world-layout-update-a';
        set role service_role;
        select public.save_world_layout_snapshot_atomic(
          '44444444-4444-4444-8444-444444444444',
          '33333333-3333-4333-8333-333333333333',
          'synthetic-campaign',
          1,
          '{"node-a":{"x":300,"y":-50}}'::jsonb
        );
        select pg_sleep(3);
        commit;
        """
    )
    wait_for(
        """
        select exists (
          select 1 from pg_stat_activity
          where application_name = 'tda-world-layout-update-a'
            and wait_event_type = 'Timeout'
            and wait_event = 'PgSleep'
        );
        """
    )

    update_b = start_psql(
        """
        begin;
        set application_name = 'tda-world-layout-update-b';
        set role service_role;
        select public.save_world_layout_snapshot_atomic(
          '44444444-4444-4444-8444-444444444444',
          '33333333-3333-4333-8333-333333333333',
          'synthetic-campaign',
          1,
          '{"node-a":{"x":400,"y":-50}}'::jsonb
        );
        commit;
        """
    )
    wait_for(
        """
        select exists (
          select 1 from pg_stat_activity
          where application_name = 'tda-world-layout-update-b'
            and wait_event_type = 'Lock'
        );
        """
    )

    update_a_out = collect_psql(update_a)
    update_b_out = collect_psql(update_b)
    assert_saved_conflict(update_a_out, update_b_out, 2, "existing-row race")
    if scalar(
        """
        select revision::text || ':' || positions::text || ':' ||
               (select count(*) from public.audit_log where action = 'world_layout.update')::text
        from public.world_layout_snapshots;
        """
    ) != '2:{"node-a": {"x": 300, "y": -50}}:2':
        raise RuntimeError("existing-row race must preserve winner payload, revision=2 and two audit rows")

    # Two first-time editor sessions race while no lease row exists. The acquire
    # RPC must serialize on the campaign advisory lock: one succeeds, the other
    # waits and then receives busy instead of a primary-key/500 failure.
    run_psql("delete from public.world_edit_leases;")
    lease_a = start_psql(
        """
        begin;
        set application_name = 'tda-world-edit-lease-a';
        set role service_role;
        select public.acquire_world_edit_lease_atomic(
          '44444444-4444-4444-8444-444444444444',
          '33333333-3333-4333-8333-333333333333',
          'synthetic-campaign',
          'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        );
        select pg_sleep(3);
        commit;
        """
    )
    wait_for(
        """
        select exists (
          select 1 from pg_stat_activity
          where application_name = 'tda-world-edit-lease-a'
            and wait_event_type = 'Timeout'
            and wait_event = 'PgSleep'
        );
        """
    )

    lease_b = start_psql(
        """
        begin;
        set application_name = 'tda-world-edit-lease-b';
        set role service_role;
        select public.acquire_world_edit_lease_atomic(
          '88888888-8888-4888-8888-888888888888',
          '77777777-7777-4777-8777-777777777777',
          'synthetic-campaign',
          'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        );
        commit;
        """
    )
    wait_for(
        """
        select exists (
          select 1 from pg_stat_activity
          where application_name = 'tda-world-edit-lease-b'
            and wait_event_type = 'Lock'
            and wait_event = 'advisory'
        );
        """
    )

    lease_a_out = collect_psql(lease_a)
    lease_b_out = collect_psql(lease_b)
    assert_acquired_busy(lease_a_out, lease_b_out)
    if scalar(
        """
        select holder_profile_id::text || ':' || lease_token::text
        from public.world_edit_leases;
        """
    ) != "33333333-3333-4333-8333-333333333333:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa":
        raise RuntimeError("lease race must preserve the first editor/token only")

    print("WORLD_LAYOUT_DATABASE_OK synthetic=true layout_concurrency=real lease_concurrency=real graph_authoring=true relation_provenance=true")
finally:
    if started:
        run([str(binary / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"])
    shutil.rmtree(root, ignore_errors=True)