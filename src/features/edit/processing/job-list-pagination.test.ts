import { describe, expect, it, vi } from "vitest";
import { LocalBridge } from "./bridge";
import { ProcessingController } from "./controller";
import { parseJobListPage } from "./protocol";

const token = "synthetic_test_token_12345678901234567890";
const health = {
	api_version: "1",
	service_version: "0.3.16",
	lifecycle: "ready",
};
const capabilities = {
	capabilities: ["synthetic.fixture", "job.list.cursor"],
	sync: false,
	device: { id: "synthetic-device", label: "Test device" },
};

function queued(id: string, updatedAt: string) {
	return {
		id,
		kind: "synthetic.fixture",
		status: "queued",
		stage: "queued",
		progress: { completed: 0, total: 1, unit: "items" },
		error: null,
		result_available: false,
		updated_at: updatedAt,
		attempt: 0,
		context: {
			campaign_id: "campaign",
			session_id: `session-${id}`,
			source_id: `source-${id}`,
		},
	};
}

function page(
	scope: "active" | "history",
	jobs: readonly ReturnType<typeof queued>[],
	hasMore: boolean,
	nextCursor: string | null,
	totalMatching: number,
) {
	return {
		schema_version: "tda_job_page_v1",
		scope,
		jobs,
		has_more: hasMore,
		next_cursor: nextCursor,
		total_matching: totalMatching,
		counts: { queued: 201 },
	};
}

describe("job list pagination", () => {
	it("parses bounded list metadata and rejects inconsistent cursors", () => {
		const parsed = parseJobListPage(
			page("active", [queued("a", "2026-09-26T12:00:00Z")], true, "next", 2),
		);
		expect(parsed).toMatchObject({
			scope: "active",
			hasMore: true,
			nextCursor: "next",
			totalMatching: 2,
		});
		expect(parsed.counts.queued).toBe(201);
		expect(parsed.counts.running).toBe(0);

		expect(() =>
			parseJobListPage({
				...page("active", [], true, null, 1),
			}),
		).toThrow();
	});

	it("serializes scope, cursor and bounded limit in the bridge", async () => {
		const request = vi.fn<typeof fetch>().mockResolvedValue(
			Response.json(page("active", [], false, null, 0)),
		);
		const bridge = new LocalBridge(request);
		bridge.pair(token);

		await bridge.jobPage("active", new AbortController().signal, {
			cursor: "cursor-2",
			limit: 200,
		});

		expect(request.mock.calls[0]?.[0]).toBe(
			"http://127.0.0.1:8765/api/v1/jobs?scope=active&cursor=cursor-2&limit=200",
		);
		bridge.disconnect();
	});

	it("drains active pages so the oldest runnable job cannot stay invisible", async () => {
		const first = Array.from({ length: 200 }, (_, index) =>
			queued(
				`queued-${String(index + 2).padStart(3, "0")}`,
				`2026-09-26T12:${String(59 - (index % 60)).padStart(2, "0")}:00Z`,
			),
		);
		const oldest = queued("queued-001", "2026-09-25T00:00:00Z");
		const request = vi.fn<typeof fetch>().mockImplementation(async (url) => {
			const value = String(url);
			if (value.endsWith("/health")) return Response.json(health);
			if (value.endsWith("/capabilities")) return Response.json(capabilities);
			if (value.includes("/jobs?scope=history"))
				return Response.json(page("history", [], false, null, 0));
			if (value.endsWith("/jobs?scope=active&limit=200"))
				return Response.json(
					page("active", first, true, "active-page-2", 201),
				);
			if (
				value.endsWith(
					"/jobs?scope=active&cursor=active-page-2&limit=200",
				)
			)
				return Response.json(
					page("active", [oldest], false, null, 201),
				);
			throw new Error(`unexpected request: ${value}`);
		});
		const controller = new ProcessingController(new LocalBridge(request));

		await controller.connect(token);

		expect(controller.snapshot().jobs).toHaveLength(201);
		expect(controller.snapshot().jobs.some((job) => job.id === oldest.id)).toBe(
			true,
		);
		expect(controller.snapshot().observedJobId).toBe(oldest.id);
		expect(
			request.mock.calls.some(([url]) =>
				String(url).includes("cursor=active-page-2"),
			),
		).toBe(true);
	});
});
