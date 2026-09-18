"""Transactional queue. Single supervisor owns recovery; claims are atomic."""
import json
import re
import sqlite3
from contextlib import contextmanager
from uuid import uuid4

from .legacy.artifacts import sha256_json, utc_now
from .legacy.publication import build_publication_bundle


class Conflict(Exception):
    pass


class Store:
    def __init__(self, root):
        self.path = root / "jobs.sqlite3"
        with self.tx() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError("DATABASE_VERSION_UNSUPPORTED")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, signature TEXT NOT NULL,
                    body TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0, attempt INTEGER NOT NULL DEFAULT 0,
                    error TEXT, result TEXT, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    code TEXT NOT NULL, at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            event_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(events)").fetchall()
            }
            if "level" not in event_columns:
                db.execute("ALTER TABLE events ADD COLUMN level TEXT NOT NULL DEFAULT 'info'")
            if "data" not in event_columns:
                db.execute("ALTER TABLE events ADD COLUMN data TEXT")
            db.execute("PRAGMA user_version=2")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('device', ?)", (str(uuid4()),))
            db.execute("INSERT OR IGNORE INTO settings VALUES ('paused', 'false')")

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def setting(self, key):
        with self.tx() as db:
            return db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0]

    def pause(self, paused):
        with self.tx() as db:
            db.execute("UPDATE settings SET value=? WHERE key='paused'", (json.dumps(paused),))

    def has_running_jobs(self):
        with self.tx() as db:
            return db.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone() is not None

    def event(self, db, job_id, code, data=None, level="info"):
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data else None
        db.execute(
            "INSERT INTO events(job_id,code,at,level,data) VALUES (?,?,?,?,?)",
            (job_id, code, utc_now(), level, payload),
        )

    def record_worker_event(
        self,
        job_id,
        attempt,
        code,
        data=None,
        *,
        level="info",
    ):
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9_]{1,96}", code):
            raise Conflict("WORKER_EVENT_CODE_INVALID")
        if level not in {"info", "warning", "error"}:
            raise Conflict("WORKER_EVENT_LEVEL_INVALID")
        payload = data if isinstance(data, dict) else {}
        if len(payload) > 32:
            raise Conflict("WORKER_EVENT_DATA_INVALID")
        clean = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
                raise Conflict("WORKER_EVENT_DATA_INVALID")
            if value is None or isinstance(value, (bool, int, float)):
                clean[key] = value
            elif isinstance(value, str) and len(value) <= 256:
                clean[key] = value
            else:
                raise Conflict("WORKER_EVENT_DATA_INVALID")
        with self.tx() as db:
            row = db.execute(
                "SELECT status,attempt FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["status"] != "running" or row["attempt"] != attempt:
                return False
            self.event(db, job_id, code, clean, level=level)
            return True

    def recover(self):
        with self.tx() as db:
            for row in db.execute("SELECT id FROM jobs WHERE status='running'").fetchall():
                db.execute(
                    "UPDATE jobs SET status='interrupted',stage='interrupted',error='PROCESS_INTERRUPTED',updated=? WHERE id=?",
                    (utc_now(), row["id"]),
                )
                self.event(db, row["id"], "PROCESS_INTERRUPTED", level="warning")

    @staticmethod
    def dto(row):
        body = json.loads(row["body"])
        context = dict(
            campaign_id=body["campaign_id"],
            session_id=body["session_id"],
            source_id=body["source_id"],
        )
        if body["kind"] == "transcription.craig":
            context["profile_id"] = body["profile_id"]
            context["cpu"] = bool(body.get("cpu", False))
        return dict(
            id=row["id"],
            kind=body["kind"],
            status=row["status"],
            stage=row["stage"],
            progress=dict(
                completed=row["completed"],
                total=body["units"],
                unit="tracks" if body["kind"] == "transcription.craig" else "items",
            ),
            error=dict(code=row["error"], recoverable=True) if row["error"] else None,
            result_available=row["result"] is not None,
            updated_at=row["updated"],
            attempt=row["attempt"],
            context=context,
        )

    @staticmethod
    def _transcription_work_signature(body):
        if body.get("kind") != "transcription.craig":
            return None
        return sha256_json(
            {
                "kind": "transcription.craig",
                "source_id": body.get("source_id"),
                "profile_id": body.get("profile_id"),
                "glossary": body.get("glossary", ""),
                "context": body.get("context", ""),
                "cpu": bool(body.get("cpu", False)),
                "units": body.get("units"),
            }
        )

    def submit(self, key, body):
        signature = sha256_json(body)
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE idem=?", (key,)).fetchone()
            if row:
                if row["signature"] != signature:
                    raise Conflict("IDEMPOTENCY_CONFLICT")
                return self.dto(row)
            if body.get("kind") == "transcription.craig":
                active = db.execute(
                    """
                    SELECT * FROM jobs
                    WHERE signature=? AND status IN ('queued','running')
                    ORDER BY updated DESC
                    LIMIT 1
                    """,
                    (signature,),
                ).fetchone()
                if active:
                    self.event(
                        db,
                        active["id"],
                        "DUPLICATE_SUBMISSION_REUSED",
                        {"status": active["status"]},
                    )
                    return self.dto(active)

                requested_work = self._transcription_work_signature(body)
                for candidate in db.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status IN ('queued','running')
                    ORDER BY updated DESC
                    """
                ).fetchall():
                    candidate_body = json.loads(candidate["body"])
                    if (
                        candidate_body.get("kind") == "transcription.craig"
                        and self._transcription_work_signature(candidate_body) == requested_work
                    ):
                        raise Conflict("TRANSCRIPTION_WORK_ALREADY_ACTIVE")
            units = body.get("units")
            if isinstance(units, bool) or not isinstance(units, int) or units < 1:
                raise Conflict("JOB_UNITS_INVALID")
            job_id = str(uuid4())
            db.execute(
                "INSERT INTO jobs(id,idem,signature,body,status,stage,updated) VALUES (?,?,?,?,'queued','queued',?)",
                (job_id, key, signature, json.dumps(body), utc_now()),
            )
            self.event(db, job_id, "QUEUED", {"total": units})
            return self.dto(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def get(self, job_id):
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            return self.dto(row)

    def body(self, job_id):
        with self.tx() as db:
            row = db.execute("SELECT body FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            return json.loads(row["body"])

    def jobs(self):
        with self.tx() as db:
            return [self.dto(r) for r in db.execute("SELECT * FROM jobs ORDER BY updated DESC LIMIT 100")]

    def events(self, job_id):
        self.get(job_id)
        with self.tx() as db:
            rows = db.execute(
                "SELECT seq,code,at,level,data FROM events WHERE job_id=? ORDER BY seq DESC LIMIT 100",
                (job_id,),
            ).fetchall()
            return [
                dict(
                    seq=row["seq"],
                    code=row["code"],
                    at=row["at"],
                    level=row["level"],
                    data=json.loads(row["data"]) if row["data"] else {},
                )
                for row in rows
            ]

    def remove(self, job_id):
        with self.tx() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["status"] in ("queued", "running"):
                raise Conflict("JOB_ACTIVE")
            db.execute("DELETE FROM events WHERE job_id=?", (job_id,))
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            return {"deleted": True, "id": job_id}

    def action(self, job_id, action):
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            body = json.loads(row["body"])
            status = row["status"]
            completed = row["completed"]
            if action == "cancel":
                if status == "cancelled":
                    return self.dto(row)
                if status == "succeeded":
                    raise Conflict("JOB_TERMINAL")
                status = "cancelled"
            else:
                if status not in ("failed", "interrupted"):
                    raise Conflict("JOB_NOT_RETRYABLE")
                if body["kind"] == "transcription.craig":
                    requested_work = self._transcription_work_signature(body)
                    for candidate in db.execute(
                        """
                        SELECT body FROM jobs
                        WHERE id<>? AND status IN ('queued','running')
                        """,
                        (job_id,),
                    ).fetchall():
                        candidate_body = json.loads(candidate["body"])
                        if (
                            candidate_body.get("kind") == "transcription.craig"
                            and self._transcription_work_signature(candidate_body) == requested_work
                        ):
                            raise Conflict("TRANSCRIPTION_WORK_ALREADY_ACTIVE")
                status = "queued"
                # Real ASR checkpoint reuse is not wired yet. Reset progress instead
                # of pretending that a partial transcript can resume safely.
                if body["kind"] == "transcription.craig":
                    completed = 0
            db.execute(
                "UPDATE jobs SET status=?,stage=?,completed=?,error=NULL,updated=? WHERE id=?",
                (status, status, completed, utc_now(), job_id),
            )
            self.event(
                db,
                job_id,
                status.upper(),
                level="warning" if status == "cancelled" else "info",
            )
            return self.dto(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def claim(self):
        with self.tx() as db:
            if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == "true":
                return None
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY updated LIMIT 1").fetchone()
            if not row:
                return None
            body = json.loads(row["body"])
            next_attempt = row["attempt"] + 1
            stage = "preparing" if body["kind"] == "transcription.craig" else "fixture"
            db.execute(
                "UPDATE jobs SET status='running',stage=?,attempt=?,updated=? WHERE id=?",
                (stage, next_attempt, utc_now(), row["id"]),
            )
            self.event(db, row["id"], "RUNNING", {"attempt": next_attempt, "total": body["units"]})
            return row["id"], next_attempt

    def set_stage(self, job_id, attempt, stage):
        if not isinstance(stage, str) or not re.fullmatch(r"[a-z0-9_.-]{1,64}", stage):
            raise Conflict("JOB_STAGE_INVALID")
        with self.tx() as db:
            changed = db.execute(
                "UPDATE jobs SET stage=?,updated=? WHERE id=? AND status='running' AND attempt=?",
                (stage, utc_now(), job_id, attempt),
            ).rowcount
            if changed:
                self.event(db, job_id, "STAGE_CHANGED", {"stage": stage})
            return bool(changed)

    def progress(self, job_id, attempt, *, completed, total, stage):
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] != "running" or row["attempt"] != attempt:
                return False
            body = json.loads(row["body"])
            if total != body["units"] or completed != row["completed"] + 1:
                raise Conflict("WORKER_PROGRESS_MISMATCH")
            if not isinstance(stage, str) or not re.fullmatch(r"[a-z0-9_.-]{1,64}", stage):
                raise Conflict("JOB_STAGE_INVALID")
            db.execute(
                "UPDATE jobs SET completed=?,stage=?,updated=? WHERE id=?",
                (completed, stage, utc_now(), job_id),
            )
            self.event(
                db,
                job_id,
                "UNIT_COMMITTED",
                {"completed": completed, "total": total, "unit": "tracks"},
            )
            return True

    def complete(self, job_id, attempt, result):
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] != "running" or row["attempt"] != attempt:
                return False
            body = json.loads(row["body"])
            if row["completed"] != body["units"]:
                raise Conflict("WORKER_RESULT_INCOMPLETE")
            db.execute(
                "UPDATE jobs SET status='succeeded',stage='complete',result=?,error=NULL,updated=? WHERE id=?",
                (encoded, utc_now(), job_id),
            )
            self.event(db, job_id, "SUCCEEDED", {"total": body["units"]})
            return True

    def step(self, job_id, attempt):
        """Commit a real synthetic work unit and progress together; fence stale workers."""
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row["status"] != "running" or row["attempt"] != attempt:
                return False
            body = json.loads(row["body"])
            if body["kind"] != "synthetic.fixture":
                raise Conflict("JOB_STEP_KIND_INVALID")
            completed = row["completed"] + 1
            sha256_json({"source": body["source_id"], "unit": completed})
            done = completed == body["units"]
            result = None
            if done:
                bundle = build_publication_bundle(
                    {"recording_id": body["source_id"], "format": "synthetic.fixture"},
                    {"fixture": True, "units": body["units"], "transcript": {"sha256": sha256_json([])}},
                )
                payload = {
                    key: value
                    for key, value in bundle.items()
                    if key not in ("publication_id", "generated_at")
                }
                result = json.dumps(
                    dict(
                        schema_version="tda_local_result_v1",
                        campaign_id=body["campaign_id"],
                        session_id=body["session_id"],
                        source_id=body["source_id"],
                        job_id=job_id,
                        publication_bundle=bundle,
                        sync={"status": "not_configured"},
                        import_artifacts={
                            "publication_payload_json": json.dumps(
                                payload,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            "transcript_json": "[]",
                        },
                    )
                )
            db.execute(
                "UPDATE jobs SET completed=?,status=?,stage=?,result=?,updated=? WHERE id=?",
                (
                    completed,
                    "succeeded" if done else "running",
                    "complete" if done else "fixture",
                    result,
                    utc_now(),
                    job_id,
                ),
            )
            self.event(
                db,
                job_id,
                "SUCCEEDED" if done else "UNIT_COMMITTED",
                {"completed": completed, "total": body["units"]},
            )
            return not done

    def result(self, job_id):
        self.get(job_id)
        with self.tx() as db:
            value = db.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
            if value is None:
                raise Conflict("RESULT_NOT_READY")
            return json.loads(value)

    def fail(self, job_id, attempt, error_code="FIXTURE_EXECUTION_FAILED"):
        if not isinstance(error_code, str) or not re.fullmatch(r"[A-Z0-9_]{1,96}", error_code):
            error_code = "WORKER_EXECUTION_FAILED"
        with self.tx() as db:
            changed = db.execute(
                "UPDATE jobs SET status='failed',stage='failed',error=?,updated=? WHERE id=? AND status='running' AND attempt=?",
                (error_code, utc_now(), job_id, attempt),
            ).rowcount
            if changed:
                self.event(db, job_id, error_code, level="error")
