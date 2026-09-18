import { describe, expect, it, vi } from "vitest";
import { LocalBridge } from "./bridge";
import { ProcessingController } from "./controller";
const token = "synthetic_test_token_12345678901234567890";
const health = {
	api_version: "1",
	service_version: "0.1.0",
	lifecycle: "ready",
};
const caps = {
	capabilities: ["synthetic.fixture"],
	sync: false,
	device: { id: "synthetic-device", label: "Test device" },
};
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
function fixture() {
	const request = vi
		.fn<typeof fetch>()
		.mockImplementation(async (url) =>
			Response.json(
				String(url).endsWith("/health")
					? health
					: String(url).endsWith("/capabilities")
						? caps
						: { jobs: [job] },
			),
		);
	return {
		request,
		controller: new ProcessingController(new LocalBridge(request)),
	};
}
describe("processing state", () => {
	it("never probes until explicitly paired and discards status on transport loss", async () => {
		const { request, controller } = fixture();
		expect(request).not.toHaveBeenCalled();
		await controller.refresh();
		expect(request).not.toHaveBeenCalled();
		await controller.connect(token);
		expect(controller.snapshot()).toMatchObject({
			connection: "connected",
			jobs: [job],
		});
		request.mockRejectedValue(new TypeError("CORS"));
		await controller.refresh();
		expect(controller.snapshot()).toMatchObject({
			connection: "error",
			error: "unreachable",
			health: null,
			capabilities: null,
			jobs: [],
			busy: false,
		});
	});
	it("does not send token to an incompatible service", async () => {
		const { request, controller } = fixture();
		request.mockResolvedValue(Response.json({ api_version: "99" }));
		await controller.connect(token);
		expect(controller.snapshot().error).toBe("incompatible");
		expect(request).toHaveBeenCalledTimes(1);
		expect(request.mock.calls[0][1]?.headers).not.toHaveProperty(
			"Authorization",
		);
	});
	it("ignores late responses after disconnect", async () => {
		const { request, controller } = fixture();
		let finish: ((value: Response) => void) | undefined;
		request.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					finish = resolve;
				}),
		);
		const pending = controller.connect(token);
		controller.disconnect();
		finish?.(Response.json(health));
		await pending;
		expect(controller.snapshot().connection).toBe("disconnected");
		expect(request).toHaveBeenCalledTimes(1);
	});
	it("serializes actions and prevents retry of an active job", async () => {
		const { request, controller } = fixture();
		await controller.connect(token);
		request.mockClear();
		await controller.jobAction(job.id, "retry");
		expect(request).not.toHaveBeenCalled();
		let finish: ((value: Response) => void) | undefined;
		request.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					finish = resolve;
				}),
		);
		const pending = controller.refresh();
		await controller.synthetic();
		expect(request).toHaveBeenCalledTimes(1);
		finish?.(Response.json(health));
		await pending;
	});
	it("deletes only terminal jobs and refreshes them out of local history", async () => {
		let jobs: Array<Record<string, unknown>> = [job];
		const deleteHealth = { ...health, service_version: "0.3.11" };
		const request = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
			const value = String(url);
			if (value.endsWith("/health")) return Response.json(deleteHealth);
			if (value.endsWith("/capabilities")) return Response.json(caps);
			if (value.endsWith("/jobs/test-job/delete") && init?.method === "POST") {
				jobs = [];
				return Response.json({ deleted: true, id: "test-job" });
			}
			return Response.json({ jobs });
		});
		const controller = new ProcessingController(new LocalBridge(request));
		await controller.connect(token);

		request.mockClear();
		await controller.deleteJob(job.id);
		expect(request).not.toHaveBeenCalled();

		jobs = [
			{
				...job,
				status: "failed",
				stage: "failed",
				error: { code: "WORKER_EXECUTION_FAILED", recoverable: true },
			},
		];
		await controller.refresh();
		request.mockClear();

		await controller.deleteJob(job.id);

		expect(
			request.mock.calls.some(
				([url, init]) =>
					String(url).endsWith("/jobs/test-job/delete") &&
					init?.method === "POST",
			),
		).toBe(true);
		expect(controller.snapshot().jobs).toEqual([]);
	});

	it("does not call the delete endpoint on Companion 0.3.10", async () => {
		const oldHealth = { ...health, service_version: "0.3.10" };
		const terminal = {
			...job,
			status: "failed",
			stage: "failed",
			error: { code: "WORKER_EXECUTION_FAILED", recoverable: true },
		};
		const request = vi.fn<typeof fetch>().mockImplementation(async (url) => {
			const value = String(url);
			if (value.endsWith("/health")) return Response.json(oldHealth);
			if (value.endsWith("/capabilities")) return Response.json(caps);
			return Response.json({ jobs: [terminal] });
		});
		const controller = new ProcessingController(new LocalBridge(request));
		await controller.connect(token);
		request.mockClear();

		await controller.deleteJob(job.id);

		expect(request).not.toHaveBeenCalled();
		expect(controller.snapshot().jobs).toEqual([terminal]);
	});

	it("reuses idempotency key after an uncertain submission", async () => {
		const { request, controller } = fixture();
		await controller.connect(token);
		request.mockImplementationOnce(async () => {
			throw new TypeError("response lost");
		});
		await controller.synthetic();
		expect(controller.snapshot().uncertainSubmission).toBe(true);
		const firstPost = request.mock.calls.find(
			([, init]) => init?.method === "POST",
		);
		await controller.connect(token);
		request.mockImplementationOnce(async () => Response.json(job));
		await controller.synthetic();
		const posts = request.mock.calls.filter(
			([, init]) => init?.method === "POST",
		);
		expect(posts).toHaveLength(2);
		expect(posts[1][1]?.headers).toEqual(firstPost?.[1]?.headers);
		expect(controller.snapshot().uncertainSubmission).toBe(false);
	});
});
