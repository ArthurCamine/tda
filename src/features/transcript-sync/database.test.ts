import {
	spawn,
	spawnSync,
	type ChildProcessWithoutNullStreams,
} from "node:child_process";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import fixture from "./fixtures/python-import.json";
import { syncTranscript } from "./client";
import { consumeTranscript, type ImportDependencies } from "./consumer";
import { createImportHandler } from "./http";
import type { ImportResult, PreparedImport } from "./contract";
import { prepareImport, sha256 } from "./validate";

const enabled = process.env.TDA_SYNTHETIC_POSTGRES === "1";
const windows = process.platform === "win32";
let cluster: ChildProcessWithoutNullStreams;
let socket = "";
const actor = {
	authUserId: "44444444-4444-4444-8444-444444444444",
	profileId: "33333333-3333-4333-8333-333333333333",
};
const parsed = prepareImport(JSON.stringify(fixture));
if (!parsed.ok) throw new Error(parsed.reason);
const input: PreparedImport = parsed.value;
function divergentInput(): PreparedImport {
	const transcriptJson = input.transcriptJson.replace(
		"A porta está fechada.",
		"A porta foi aberta.",
	);
	const transcriptSha256 = sha256(transcriptJson);
	const manifestSha256 = "c".repeat(64);
	const publicationPayloadJson = input.publicationPayloadJson
		.replace(input.transcriptSha256, transcriptSha256)
		.replace(input.manifestSha256, manifestSha256);
	return {
		...input,
		publicationId: sha256(publicationPayloadJson),
		transcriptSha256,
		manifestSha256,
		publicationPayloadJson,
		transcriptJson,
		segments: input.segments.map((segment, index) =>
			index === 1 ? { ...segment, text: "A porta foi aberta." } : segment,
		),
	};
}
const divergent = divergentInput();
const quote = (text: string) => `'${text.replaceAll("'", "''")}'`;
function command(binary: string, args: string[]) {
	return windows
		? { cmd: "wsl.exe", args: ["-d", "Ubuntu-24.04", "--", binary, ...args] }
		: { cmd: binary, args };
}
function sqlCommand() {
	if (!/^\/tmp\/tda-sync-[A-Za-z0-9_-]+\/socket$/u.test(socket))
		throw new Error("Only isolated synthetic socket is allowed");
	return command("/usr/lib/postgresql/16/bin/psql", [
		"-X",
		"-h",
		socket,
		"-U",
		"postgres",
		"-d",
		"postgres",
		"-v",
		"ON_ERROR_STOP=1",
		"-Atq",
	]);
}
const cleanEnv: NodeJS.ProcessEnv = {
	...Object.fromEntries(
		Object.entries(process.env).filter(([key]) => !key.startsWith("PG")),
	),
	NODE_ENV: process.env.NODE_ENV,
};
function sql(text: string) {
	const cmd = sqlCommand();
	const result = spawnSync(cmd.cmd, cmd.args, {
		input: text,
		encoding: "utf8",
		timeout: 20000,
		env: cleanEnv,
	});
	if (result.status !== 0)
		throw new Error(result.stderr || "Synthetic SQL process failed");
	return result.stdout.trim();
}
function call(value: unknown = input, lookup = false, auth = actor.authUserId) {
	return `select public.import_transcript_bundle_atomic('${auth}','${actor.profileId}',${quote(JSON.stringify(value))}::jsonb,${lookup});`;
}
const deps: ImportDependencies = {
	authorize: async (authUserId) => ({
		ok: true,
		actor: { ...actor, authUserId },
	}),
	commit: async (_actor, value) =>
		JSON.parse(sql(`set role service_role; ${call(value)}`)) as ImportResult,
	lookup: async (_actor, value) =>
		JSON.parse(
			sql(`set role service_role; ${call(value, true)}`),
		) as ImportResult,
};

describe.skipIf(!enabled)(
	"persistent PostgreSQL consumer and client integration (synthetic only)",
	() => {
		beforeAll(async () => {
			let path = fileURLToPath(
				new URL("../../../tools/transcript-sync-db.py", import.meta.url),
			);

			if (windows)
				path = `/mnt/${path[0].toLowerCase()}${path.slice(2).replaceAll("\\", "/")}`;
			const cmd = command("python3", [path]);
			cluster = spawn(cmd.cmd, cmd.args, { stdio: "pipe", env: cleanEnv });
			await new Promise<void>((resolve, reject) => {
				let output = "",
					errors = "";
				cluster.stdout.on("data", (data) => {
					output += data.toString();
					if (output.includes("\n")) {
						socket = output.trim().split("\n")[0];
						resolve();
					}
				});
				cluster.stderr.on("data", (data) => {
					errors += data.toString();
				});
				cluster.on("error", reject);
				cluster.on("exit", (code) => {
					if (!socket) reject(new Error(`Cluster failed ${code}: ${errors}`));
				});
			});
		}, 30000);
		afterAll(async () => {
			if (!cluster || cluster.exitCode !== null) return;
			await new Promise<void>((resolve) => {
				cluster.on("exit", () => resolve());
				cluster.stdin.end();
			});
		}, 15000);
		it("requires physical explicit capability and bound identity in SQL", () => {
			expect(JSON.parse(sql(`set role service_role; ${call()}`))).toEqual({
				ok: false,
				reason: "forbidden",
			});
			sql(
				`insert into role_permissions values ('55555555-5555-4555-8555-555555555555','campaign.transcript.import'); insert into role_assignments(profile_id,role_id,scope_type,scope_id,status,starts_at) values ('${actor.profileId}','55555555-5555-4555-8555-555555555555','campaign','synthetic-campaign','active',now());`,
			);
			expect(
				JSON.parse(
					sql(
						`set role service_role; ${call(input, false, "66666666-6666-4666-8666-666666666666")}`,
					),
				),
			).toEqual({ ok: false, reason: "forbidden" });
			expect(
				JSON.parse(
					sql(
						`set role service_role; ${call({ ...input, campaignId: "66666666-6666-4666-8666-666666666666" })}`,
					),
				),
			).toEqual({ ok: false, reason: "forbidden" });
			expect(
				JSON.parse(
					sql(
						`set role service_role; ${call({ ...input, sessionId: "66666666-6666-4666-8666-666666666666" })}`,
					),
				),
			).toEqual({ ok: false, reason: "not_found" });
			for (const patch of [
				{ sourceSessionId: "other" },
				{ sourceSystem: "craig" },
				{ sessionId: "not-a-uuid" },
			])
				expect(
					JSON.parse(
						sql(`set role service_role; ${call({ ...input, ...patch })}`),
					),
				).toEqual({ ok: false, reason: "invalid_payload" });
		});
		it("denies direct SQL clients and rolls back segments if receipt fails", () => {
			for (const role of ["anon", "authenticated"])
				expect(() => sql(`set role ${role}; ${call()}`)).toThrow(
					/permission denied/u,
				);
			sql(
				"create function fail_receipt() returns trigger language plpgsql as $$ begin raise exception 'synthetic receipt failure'; end $$; create trigger fail_receipt before insert on transcript_import_receipts for each row execute function fail_receipt();",
			);
			expect(() => sql(`set role service_role; ${call()}`)).toThrow(
				/synthetic receipt failure/u,
			);
			expect(
				sql(
					"select (select count(*) from transcript_segments),(select count(*) from transcript_import_receipts),(select count(*) from audit_log);",
				),
			).toBe("0|0|0");
			sql(
				"drop trigger fail_receipt on transcript_import_receipts; drop function fail_receipt();",
			);
		});
		it("SQL rejects malformed projection, altered canonical bytes and audit failure rolls back the complete import", () => {
			for (const value of [
				{ ...input, segments: [] },
				{
					...input,
					segments: [{ ...input.segments[0], text: "" }],
				},
				{
					...input,
					segments: [{ ...input.segments[0], endMs: 0 }],
				},
				{ ...input, segments: [input.segments[0], input.segments[0]] },
				{ ...input, publicationId: "a".repeat(64) },
				{ ...input, transcriptSha256: "b".repeat(64) },
				{
					...input,
					transcriptJson: input.transcriptJson.replace("Olá", "Ola"),
				},
			]) {
				expect(
					JSON.parse(sql(`set role service_role; ${call(value)}`)),
				).toEqual({ ok: false, reason: "invalid_payload" });
			}
			sql(
				"create function fail_audit() returns trigger language plpgsql as $$ begin raise exception 'synthetic audit failure'; end $$; create trigger fail_audit before insert on audit_log for each row execute function fail_audit();",
			);
			expect(() => sql(`set role service_role; ${call()}`)).toThrow(
				/synthetic audit failure/u,
			);
			expect(
				sql(
					"select (select count(*) from transcript_segments),(select count(*) from transcript_import_receipts),(select count(*) from audit_log);",
				),
			).toBe("0|0|0");
			sql("drop trigger fail_audit on audit_log; drop function fail_audit();");
		});
		it("client -> authenticated HTTP -> consumer -> SQL persists once across lost response/retry/readback", async () => {
			const dependencies = {
				origin: () => "https://tda.invalid",
				identity: async () => ({
					ok: true as const,
					authUserId: actor.authUserId,
				}),
				consumer: deps,
			};
			const importing = createImportHandler(dependencies),
				lookup = createImportHandler(dependencies, true);
			let loseResponse = true;
			const transport = async (path: string, init: RequestInit) => {
				const request = new Request(`https://tda.invalid${path}`, {
					...init,
					headers: { ...init.headers, Origin: "https://tda.invalid" },
				});
				const result = await (path.endsWith("/receipt")
					? lookup(request)
					: importing(request));
				if (loseResponse && result.ok) {
					loseResponse = false;
					throw new Error("lost response after COMMIT");
				}
				return result;
			};
			const request = {
				result: fixture.result,
				expected: input,
				segmentCount: 2,
			};
			expect((await syncTranscript(request, undefined, transport)).status).toBe(
				"pending",
			);
			const saved = await syncTranscript(request, undefined, transport);
			expect(saved.status).toBe("synchronized");
			expect(await syncTranscript(request, undefined, transport)).toEqual(
				saved,
			);
			expect(
				sql(
					"select (select count(*) from transcript_segments),(select count(*) from transcript_import_receipts),(select count(*) from audit_log);",
				),
			).toBe("2|1|1");
			expect(
				sql(
					"select bool_and(needs_review and review_status='pending' and revision=0 and not is_empty) from transcript_segments;",
				),
			).toBe("t");
			expect(
				JSON.parse(
					sql(
						"select json_agg(text order by source_sequence) from transcript_segments;",
					),
				),
			).toEqual(input.segments.map((row) => row.text));
		});
		it("coherent divergent hashes conflict without overwriting existing evidence or receipt", async () => {
			const original = sql(
				"select row_to_json(r) from transcript_import_receipts r;",
			);
			expect(
				JSON.parse(sql(`set role service_role; ${call(divergent)}`)),
			).toEqual({ ok: false, reason: "conflict" });
			expect(
				sql("select row_to_json(r) from transcript_import_receipts r;"),
			).toBe(original);
			expect(
				(
					await consumeTranscript(
						JSON.stringify(fixture),
						actor.authUserId,
						deps,
					)
				).ok,
			).toBe(true);
		});
		it("revocation and foreign scope deny receipt retry in SQL", () => {
			for (const change of [
				"status='revoked'",
				"status='eligible'",
				"ends_at=now()-interval '1 minute'",
				"scope_id='other'",
			]) {
				sql(`update role_assignments set ${change};`);
				expect(
					JSON.parse(sql(`set role service_role; ${call(input, true)}`)),
				).toEqual({ ok: false, reason: "forbidden" });
				sql(
					"update role_assignments set status='active',ends_at=null,scope_id='synthetic-campaign';",
				);
			}
		});
		it("transaction interruption and concurrent same/different payloads remain atomic", async () => {
			sql("truncate audit_log,transcript_segments,transcript_import_receipts;");
			sql(`set role service_role; begin; ${call()} rollback;`);
			expect(
				sql(
					"select (select count(*) from transcript_segments),(select count(*) from transcript_import_receipts);",
				),
			).toBe("0|0");
			const launch = (query: string) => {
				const cmd = sqlCommand();
				const child = spawn(cmd.cmd, cmd.args, {
					stdio: "pipe",
					env: cleanEnv,
				});
				const result = new Promise<string>((resolve, reject) => {
					let output = "",
						error = "";
					child.stdout.on("data", (data) => {
						output += data.toString();
					});
					child.stderr.on("data", (data) => {
						error += data.toString();
					});
					child.on("error", reject);
					child.on("exit", (code) =>
						code === 0 ? resolve(output.trim()) : reject(new Error(error)),
					);
				});
				child.stdin.end(query);
				return result;
			};
			const waitForFirst = async (name: string, deadline: number) => {
				while (
					sql(
						`select count(*) from pg_stat_activity where application_name='${name}' and wait_event='PgSleep';`,
					) !== "1"
				) {
					if (Date.now() > deadline)
						throw new Error("First connection did not reach commit hold");
					await new Promise((resolve) => setTimeout(resolve, 50));
				}
			};
			const observeBlocked = async (
				firstName: string,
				secondName: string,
				deadline: number,
			) => {
				while (Date.now() < deadline) {
					if (
						sql(
							`select exists(select 1 from pg_stat_activity b cross join pg_stat_activity a where b.application_name='${secondName}' and a.application_name='${firstName}' and a.pid=any(pg_blocking_pids(b.pid)));`,
						) === "t"
					)
						return true;
					await new Promise((resolve) => setTimeout(resolve, 50));
				}
				return false;
			};

			const first = launch(
				`set application_name='tda_sync_a'; set role service_role; begin; ${call()} select pg_sleep(4); commit;`,
			);
			let deadline = Date.now() + 6000;
			await waitForFirst("tda_sync_a", deadline);
			const second = launch(
				`set application_name='tda_sync_b'; set role service_role; ${call()}`,
			);
			const blockedSame = await observeBlocked(
				"tda_sync_a",
				"tda_sync_b",
				deadline,
			);
			const [a, b] = await Promise.all([first, second]);
			expect(blockedSame).toBe(true);
			expect(JSON.parse(a)).toEqual(JSON.parse(b));
			expect(
				sql(
					"select (select count(*) from transcript_segments),(select count(*) from transcript_import_receipts),(select count(*) from audit_log);",
				),
			).toBe("2|1|1");

			sql("truncate audit_log,transcript_segments,transcript_import_receipts;");
			const winning = launch(
				`set application_name='tda_sync_c'; set role service_role; begin; ${call()} select pg_sleep(4); commit;`,
			);
			deadline = Date.now() + 6000;
			await waitForFirst("tda_sync_c", deadline);
			const losing = launch(
				`set application_name='tda_sync_d'; set role service_role; ${call(divergent)}`,
			);
			const blockedDifferent = await observeBlocked(
				"tda_sync_c",
				"tda_sync_d",
				deadline,
			);
			const [winner, loser] = await Promise.all([winning, losing]);
			expect(blockedDifferent).toBe(true);
			expect(JSON.parse(winner).ok).toBe(true);
			expect(JSON.parse(loser)).toEqual({ ok: false, reason: "conflict" });
			expect(
				sql(
					"select (select count(*) from transcript_segments),(select count(*) from transcript_import_receipts),(select count(*) from audit_log);",
				),
			).toBe("2|1|1");
			expect(
				JSON.parse(
					sql(
						"select json_agg(text order by source_sequence) from transcript_segments;",
					),
				),
			).toEqual(input.segments.map((row) => row.text));
		}, 30000);

        it("serializes competing publications and rejects the stale writer without evidence", async () => {
            sql(`insert into role_permissions values ('55555555-5555-4555-8555-555555555555','campaign.transcript.publish');`);
            const make = (id: string) => JSON.parse(sql(`select synthetic_publication_input('${id}', 'run-cas', 'Synthetic concurrency probe');`));
            const a = make('91000000-0000-4000-8000-000000000001');
            const b = make('91000000-0000-4000-8000-000000000002');
            const publish = (value: unknown) => `select publish_transcript_revision_atomic('${actor.authUserId}','${actor.profileId}',${quote(JSON.stringify(value))}::jsonb,false);`;
            const launch = (statement: string) => new Promise<string>((resolve, reject) => {
                const cmd = sqlCommand(); const child = spawn(cmd.cmd, cmd.args, { env: cleanEnv }); let out = '', err = '';
                child.stdout.on('data', data => { out += data.toString(); }); child.stderr.on('data', data => { err += data.toString(); }); child.on('error', reject); child.on('exit', code => code === 0 ? resolve(out.trim()) : reject(new Error(err))); child.stdin.end(statement);
            });
            const before = sql('select count(*) from audit_log;');
            const first = launch(`set application_name='tda_pub_cas_a'; set role service_role; begin; ${publish(a)} select pg_sleep(3); commit;`);
            const deadline = Date.now() + 6000;
            while (sql("select count(*) from pg_stat_activity where application_name='tda_pub_cas_a' and wait_event='PgSleep';") !== '1') {
                if (Date.now() > deadline) throw new Error('Publication writer failed to lock session');
                await new Promise(resolve => setTimeout(resolve, 50));
            }
            const second = launch(`set application_name='tda_pub_cas_b'; set role service_role; ${publish(b)}`);
            let blocked = false;
            while (Date.now() < deadline) {
                if (sql("select exists(select 1 from pg_stat_activity b cross join pg_stat_activity a where b.application_name='tda_pub_cas_b' and a.application_name='tda_pub_cas_a' and a.pid=any(pg_blocking_pids(b.pid)));") === 't') { blocked = true; break; }
                await new Promise(resolve => setTimeout(resolve, 50));
            }
            const [winner, loser] = await Promise.all([first, second]);
            expect(blocked).toBe(true);
            expect(JSON.parse(winner).ok).toBe(true);
            expect(JSON.parse(loser)).toEqual({ ok: false, reason: 'stale_current' });
            expect(sql('select (select count(*) from transcript_revisions),(select count(*) from transcript_publication_receipts),(select count(*) from transcript_publication_events);')).toBe('1|1|1');
            expect(Number(sql('select count(*) from audit_log;'))).toBe(Number(before) + 1);
            expect(JSON.parse(sql(`set role service_role; ${publish(a)}`))).toEqual(JSON.parse(winner));
        }, 20000);
	},
);
