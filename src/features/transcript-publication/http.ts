import {
	MAX_PUBLICATION_REQUEST_BYTES,
	type PublicationResult,
} from "./contract";
import {
	publishTranscriptRevision,
	readPublicationReceipt,
	type PublicationDependencies,
} from "./consumer";

type PublicationHttpDependencies = Readonly<{
	origin: () => string | null;
	identity: () => Promise<
		| { ok: true; authUserId: string }
		| { ok: false; reason: "unauthenticated" | "dependency_unavailable" }
	>;
	publication: PublicationDependencies;
}>;

function response(result: PublicationResult): Response {
	const status = result.ok
		? 200
		: (
				{
					unauthenticated: 401,
					forbidden: 403,
					publish_capability_undefined: 503,
					invalid_payload: 400,
					approved_review_required: 422,
					too_large: 413,
					not_found: 404,
					conflict: 409,
					stale_current: 409,
					dependency_unavailable: 503,
				} as const
			)[result.reason];
	return Response.json(result, {
		status,
		headers: {
			"Cache-Control": "no-store",
			"X-Content-Type-Options": "nosniff",
		},
	});
}

async function boundedBody(request: Request): Promise<string | null> {
	if (!request.body) return "";
	const reader = request.body.getReader();
	const chunks: Uint8Array[] = [];
	let size = 0;
	try {
		while (true) {
			const next = await reader.read();
			if (next.done) break;
			size += next.value.byteLength;
			if (size > MAX_PUBLICATION_REQUEST_BYTES) {
				await reader.cancel();
				return null;
			}
			chunks.push(next.value);
		}
		return new TextDecoder("utf-8", { fatal: true }).decode(
			Buffer.concat(chunks),
		);
	} finally {
		reader.releaseLock();
	}
}

export function createPublicationHandler(
	deps: PublicationHttpDependencies,
	receiptOnly = false,
) {
	return async (request: Request): Promise<Response> => {
		try {
			const origin = deps.origin();
			if (!origin)
				return response({ ok: false, reason: "dependency_unavailable" });
			if (request.method !== "POST" || request.headers.get("origin") !== origin)
				return response({ ok: false, reason: "forbidden" });
			if (
				request.headers.get("content-type")?.split(";")[0].trim() !==
				"application/json"
			)
				return response({ ok: false, reason: "invalid_payload" });

			const identity = await deps.identity();
			if (!identity.ok) return response(identity);
			const raw = await boundedBody(request);
			if (raw === null) return response({ ok: false, reason: "too_large" });

			return response(
				await (receiptOnly
					? readPublicationReceipt(raw, identity.authUserId, deps.publication)
					: publishTranscriptRevision(
							raw,
							identity.authUserId,
							deps.publication,
						)),
			);
		} catch {
			return response({ ok: false, reason: "invalid_payload" });
		}
	};
}
