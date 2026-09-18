import {
	BridgeError,
	type CraigTranscriptionInput,
	identifier,
	LOCAL_API,
	parseCapabilities,
	parseCraigSource,
	parseHealth,
	parseJob,
	parseJobEvents,
	parseJobs,
	parseResultSummary,
	parseSystemSnapshot,
} from "./protocol";

let pairedToken = "";
const pairingListeners = new Set<() => void>();

function notifyPairing() {
	for (const listener of pairingListeners) listener();
}

export function localBridgePaired(): boolean {
	return pairedToken.length > 0;
}

export function subscribeLocalBridgePairing(listener: () => void) {
	pairingListeners.add(listener);
	return () => pairingListeners.delete(listener);
}

function mapStatus(status: number): BridgeError {
	return new BridgeError(
		status === 401
			? "unauthorized"
			: status === 403
				? "forbidden"
				: status === 409
					? "conflict"
					: "service_error",
	);
}

export class LocalBridge {
	constructor(
		private readonly request: typeof fetch = (input, init) =>
			fetch(input, init),
	) {}

	pair(token: string) {
		if (!/^[A-Za-z0-9_-]{32,256}$/u.test(token))
			throw new BridgeError("unauthorized");
		pairedToken = token;
		notifyPairing();
	}

	disconnect() {
		if (!pairedToken) return;
		pairedToken = "";
		notifyPairing();
	}

	private token() {
		if (!pairedToken) throw new BridgeError("unauthorized");
		return pairedToken;
	}

	private async responseJson(response: Response) {
		if (!response.ok) throw mapStatus(response.status);
		if (!response.headers.get("content-type")?.includes("application/json"))
			throw new BridgeError("invalid_response");
		const reader = response.body?.getReader();
		if (!reader) throw new BridgeError("invalid_response");
		let size = 0;
		let data = "";
		const decoder = new TextDecoder();
		try {
			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				size += value.byteLength;
				if (size > 1024 * 1024) {
					await reader.cancel();
					throw new BridgeError("invalid_response");
				}
				data += decoder.decode(value, { stream: true });
			}
		} finally {
			reader.releaseLock();
		}
		try {
			return JSON.parse(data + decoder.decode()) as unknown;
		} catch {
			throw new BridgeError("invalid_response");
		}
	}

	private async json(
		path: string,
		signal: AbortSignal,
		body?: unknown,
		key?: string,
		publicRequest = false,
	) {
		const headers: Record<string, string> = { Accept: "application/json" };
		if (!publicRequest) headers.Authorization = `Bearer ${this.token()}`;
		if (body !== undefined) headers["Content-Type"] = "application/json";
		if (key) headers["Idempotency-Key"] = identifier(key);
		const timeout = AbortSignal.timeout(8000);
		try {
			const response = await this.request(`${LOCAL_API}${path}`, {
				method: body === undefined ? "GET" : "POST",
				headers,
				body: body === undefined ? undefined : JSON.stringify(body),
				mode: "cors",
				credentials: "omit",
				redirect: "error",
				cache: "no-store",
				referrerPolicy: "no-referrer",
				signal: AbortSignal.any([signal, timeout]),
			});
			return await this.responseJson(response);
		} catch (error) {
			if (error instanceof BridgeError) throw error;
			throw new BridgeError(timeout.aborted ? "timeout" : "unreachable");
		}
	}

	async health(signal: AbortSignal) {
		return parseHealth(
			await this.json("/health", signal, undefined, undefined, true),
		);
	}
	async capabilities(signal: AbortSignal) {
		return parseCapabilities(await this.json("/capabilities", signal));
	}
	async jobs(signal: AbortSignal) {
		return parseJobs(await this.json("/jobs", signal));
	}
	async job(id: string, signal: AbortSignal) {
		return parseJob(await this.json(`/jobs/${identifier(id)}`, signal));
	}
	async events(id: string, signal: AbortSignal) {
		return parseJobEvents(
			await this.json(`/jobs/${identifier(id)}/events`, signal),
		);
	}
	async system(signal: AbortSignal) {
		return parseSystemSnapshot(await this.json("/system", signal));
	}
	async lifecycle(action: "pause" | "resume", signal: AbortSignal) {
		return parseHealth(await this.json("/lifecycle", signal, { action }));
	}
	async jobAction(id: string, action: "cancel" | "retry", signal: AbortSignal) {
		return parseJob(
			await this.json(`/jobs/${identifier(id)}/${action}`, signal, {}),
		);
	}
	async deleteJob(id: string, signal: AbortSignal) {
		await this.json(`/jobs/${identifier(id)}/delete`, signal, {});
	}
	async craigSource(file: File, signal: AbortSignal) {
		if (!(file instanceof Blob) || file.size <= 0)
			throw new BridgeError("invalid_response");
		const timeout = AbortSignal.timeout(15 * 60 * 1000);
		try {
			const response = await this.request(`${LOCAL_API}/sources/craig`, {
				method: "POST",
				headers: {
					Accept: "application/json",
					Authorization: `Bearer ${this.token()}`,
					"Content-Type": "application/zip",
				},
				body: file,
				mode: "cors",
				credentials: "omit",
				redirect: "error",
				cache: "no-store",
				referrerPolicy: "no-referrer",
				signal: AbortSignal.any([signal, timeout]),
			});
			return parseCraigSource(await this.responseJson(response));
		} catch (error) {
			if (error instanceof BridgeError) throw error;
			throw new BridgeError(timeout.aborted ? "timeout" : "unreachable");
		}
	}
	async transcription(input: CraigTranscriptionInput, key: string, signal: AbortSignal) {
		return parseJob(
			await this.json(
				"/jobs",
				signal,
				{
					kind: "transcription.craig",
					campaign_id: identifier(input.campaignId),
					session_id: identifier(input.sessionId),
					source_id: identifier(input.sourceId),
					profile_id: input.profileId,
					glossary: input.glossary.slice(0, 1200),
					context: input.context.slice(0, 1200),
					cpu: false,
				},
				key,
			),
		);
	}
	async synthetic(key: string, signal: AbortSignal) {
		return parseJob(
			await this.json(
				"/jobs",
				signal,
				{
					kind: "synthetic.fixture",
					campaign_id: "synthetic-campaign",
					session_id: "synthetic-session",
					source_id: "synthetic-source",
					units: 3,
				},
				key,
			),
		);
	}
	async result(id: string, signal: AbortSignal) {
		return parseResultSummary(
			await this.json(`/jobs/${identifier(id)}/result`, signal),
			id,
		);
	}
}
