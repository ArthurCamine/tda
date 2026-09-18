import { describe, expect, it, vi } from "vitest";
import { LocalBridge } from "./bridge";
import { LOCAL_API, parseJob, parseJobs, parseResultSummary } from "./protocol";
const signal = () => new AbortController().signal;
const token = "synthetic_test_token_12345678901234567890";
const job = {
	id: "test-job",
	kind: "synthetic.fixture",
	status: "running",
	stage: "fixture",
	progress: { completed: 1, total: 3, unit: "items" },
	error: null,
	result_available: false,
	updated_at: "2026-09-07T12:00:00Z",
};
describe("loopback bridge", () => {
	it("keeps credentials off health and only sends bearer to fixed loopback", async () => {
		const request = vi
			.fn<typeof fetch>()
			.mockImplementation(async (url) =>
				Response.json(
					String(url).endsWith("/health")
						? { api_version: "1", service_version: "0.1.0", lifecycle: "ready" }
						: job,
				),
			);
		const bridge = new LocalBridge(request);
		bridge.pair(token);
		await bridge.health(signal());
		await bridge.synthetic("safe-key", signal());
		expect(request.mock.calls[0][1]?.headers).not.toHaveProperty(
			"Authorization",
		);
		const [url, options] = request.mock.calls[1];
		expect(url).toBe(`${LOCAL_API}/jobs`);
		expect(options).toMatchObject({
			method: "POST",
			credentials: "omit",
			redirect: "error",
			referrerPolicy: "no-referrer",
			cache: "no-store",
			mode: "cors",
			headers: {
				Authorization: `Bearer ${token}`,
				"Idempotency-Key": "safe-key",
				"Content-Type": "application/json",
			},
		});
		expect(JSON.parse(String(options?.body))).toEqual({
			kind: "synthetic.fixture",
			campaign_id: "synthetic-campaign",
			session_id: "synthetic-session",
			source_id: "synthetic-source",
			units: 3,
		});
		bridge.disconnect();
		await expect(bridge.jobs(signal())).rejects.toMatchObject({
			code: "unauthorized",
		});
		expect(request).toHaveBeenCalledTimes(2);
	});
	it("deletes a terminal job through the authenticated local action endpoint", async () => {
		const request = vi.fn<typeof fetch>().mockResolvedValue(
			Response.json({ deleted: true, id: "test-job" }),
		);
		const bridge = new LocalBridge(request);
		bridge.pair(token);

		await bridge.deleteJob("test-job", signal());

		expect(request).toHaveBeenCalledTimes(1);
		const [url, options] = request.mock.calls[0];
		expect(url).toBe(`${LOCAL_API}/jobs/test-job/delete`);
		expect(options).toMatchObject({
			method: "POST",
			credentials: "omit",
			redirect: "error",
			referrerPolicy: "no-referrer",
			cache: "no-store",
			mode: "cors",
			headers: {
				Accept: "application/json",
				Authorization: `Bearer ${token}`,
				"Content-Type": "application/json",
			},
			body: "{}",
		});
		bridge.disconnect();
	});

	it("rejects path injection without a request", async () => {
		const request = vi.fn<typeof fetch>();
		const bridge = new LocalBridge(request);
		bridge.pair(token);
		for (const id of [
			"../health",
			"http://evil.test",
			"job?secret=1",
			"%2fhealth",
		])
			await expect(bridge.job(id, signal())).rejects.toMatchObject({
				code: "invalid_response",
			});
		expect(request).not.toHaveBeenCalled();
	});
	it.each([
		[401, "unauthorized"],
		[403, "forbidden"],
		[409, "conflict"],
		[500, "service_error"],
	])("maps HTTP %s without exposing content", async (status, code) => {
		const bridge = new LocalBridge(
			vi
				.fn<typeof fetch>()
				.mockResolvedValue(
					new Response("private diagnostic", { status: Number(status) }),
				),
		);
		await expect(bridge.health(signal())).rejects.toMatchObject({
			code,
			message: code,
		});
	});
	it("does not guess network failures are an offline PC", async () => {
		const bridge = new LocalBridge(
			vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch")),
		);
		await expect(bridge.health(signal())).rejects.toMatchObject({
			code: "unreachable",
		});
	});
	it.each([
		new Response("<html>error</html>"),
		Response.json({ api_version: "2" }),
		new Response("{broken", {
			headers: { "content-type": "application/json" },
		}),
	])("rejects malformed or incompatible services", async (response) => {
		const bridge = new LocalBridge(
			vi.fn<typeof fetch>().mockResolvedValue(response),
		);
		await expect(bridge.health(signal())).rejects.toThrow();
	});
	it("bounds chunked responses", async () => {
		const bridge = new LocalBridge(
			vi.fn<typeof fetch>().mockResolvedValue(
				new Response(" ".repeat(1024 * 1024 + 1), {
					headers: { "content-type": "application/json" },
				}),
			),
		);
		await expect(bridge.health(signal())).rejects.toMatchObject({
			code: "invalid_response",
		});
	});
});
describe("wire validation", () => {
	it.each([
		{ completed: 4, total: 3, unit: "items" },
		{ completed: -1, total: 3, unit: "items" },
		{ completed: 0, total: 0, unit: "items" },
		{ completed: 0, total: Infinity, unit: "items" },
	])("rejects impossible progress", (progress) => {
		expect(() => parseJob({ ...job, progress })).toThrow();
	});
	it("accepts unknown progress and rejects duplicate identities", () => {
		expect(parseJob({ ...job, progress: null }).progress).toBeNull();
		expect(() => parseJobs({ jobs: [job, job] })).toThrow();
	});
	it("retains only result identity bound to the requested job", () => {
		const value = {
			schema_version: "tda_local_result_v1",
			campaign_id: "synthetic-campaign",
			session_id: "synthetic-session",
			source_id: "synthetic-source",
			job_id: "test-job",
			publication_bundle: {
				schema_version: "publication_bundle_v1",
				publication_id: "a".repeat(64),
				recap: "synthetic recap",
			},
			sync: { status: "not_configured" },
		};
		expect(parseResultSummary(value, "test-job")).toEqual({
			campaignId: "synthetic-campaign",
			sessionId: "synthetic-session",
			sourceId: "synthetic-source",
			jobId: "test-job",
			publicationId: "a".repeat(64),
		});
		expect(() => parseResultSummary(value, "other-job")).toThrow();
		expect(() =>
			parseResultSummary(
				{ ...value, sync: { status: "confirmed" } },
				"test-job",
			),
		).toThrow();
	});
});
