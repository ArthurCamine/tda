import type {
	PublicationDependencies,
	AuthorizedPublicationActor,
} from "./consumer";
import { UUID, type PublicationFailure } from "./canonical";

export type CurrentPublication = Readonly<{
	actorProfileId: string;
	revisionId: string | null;
}>;
type CurrentResult =
	| { ok: true; current: CurrentPublication }
	| { ok: false; reason: PublicationFailure };
export function createCurrentPublicationHandler(deps: {
	origin: () => string | null;
	identity: () => Promise<
		| { ok: true; authUserId: string }
		| { ok: false; reason: "unauthenticated" | "dependency_unavailable" }
	>;
	publication: PublicationDependencies;
	read: (actor: AuthorizedPublicationActor) => Promise<CurrentResult>;
}) {
	return async (request: Request): Promise<Response> => {
		const respond = (result: CurrentResult) =>
			Response.json(result, {
				status: result.ok
					? 200
					: result.reason === "unauthenticated"
						? 401
						: result.reason === "forbidden"
							? 403
							: result.reason === "invalid_payload"
								? 400
								: result.reason === "not_found"
									? 404
									: 503,
				headers: {
					"Cache-Control": "no-store",
					"X-Content-Type-Options": "nosniff",
				},
			});
		try {
			const origin = deps.origin();
			if (!origin)
				return respond({ ok: false, reason: "dependency_unavailable" });
			if (request.method !== "POST" || request.headers.get("origin") !== origin)
				return respond({ ok: false, reason: "forbidden" });
			if (
				request.headers.get("content-type")?.split(";")[0].trim() !==
				"application/json"
			)
				return respond({ ok: false, reason: "invalid_payload" });
			const identity = await deps.identity();
			if (!identity.ok) return respond(identity);
			// Bound the streamed metadata request, including clients without Content-Length.
			const reader = request.body?.getReader();
			if (!reader) return respond({ ok: false, reason: "invalid_payload" });
			const chunks: Uint8Array[] = [];
			let size = 0;
			try {
				while (true) {
					const chunk = await reader.read();
					if (chunk.done) break;
					size += chunk.value.byteLength;
					if (size > 1024) {
						await reader.cancel();
						return respond({ ok: false, reason: "invalid_payload" });
					}
					chunks.push(chunk.value);
				}
			} finally {
				reader.releaseLock();
			}
			let target: unknown;
			try {
				target = JSON.parse(
					new TextDecoder("utf-8", { fatal: true }).decode(
						Buffer.concat(chunks),
					),
				);
			} catch {
				return respond({ ok: false, reason: "invalid_payload" });
			}
			if (!target || typeof target !== "object" || Array.isArray(target))
				return respond({ ok: false, reason: "invalid_payload" });
			const value = target as Record<string, unknown>;
			if (
				Object.keys(value).length !== 2 ||
				typeof value.campaignSlug !== "string" ||
				!/^[A-Za-z0-9_-]{1,128}$/u.test(value.campaignSlug) ||
				typeof value.sourceSessionId !== "string" ||
				!/^[A-Za-z0-9_-]{1,160}$/u.test(value.sourceSessionId)
			)
				return respond({ ok: false, reason: "invalid_payload" });
			const access = await deps.publication.authorize(identity.authUserId, {
				campaignSlug: value.campaignSlug,
				sourceSessionId: value.sourceSessionId,
			});
			if (!access.ok) return respond(access);
			if (access.actor.authUserId !== identity.authUserId)
				return respond({ ok: false, reason: "forbidden" });
			const result = await deps.read(access.actor);
			if (
				result.ok &&
				(result.current.actorProfileId !== access.actor.profileId ||
					(result.current.revisionId !== null &&
						!UUID.test(result.current.revisionId)))
			)
				return respond({ ok: false, reason: "dependency_unavailable" });
			return respond(result);
		} catch {
			return respond({ ok: false, reason: "dependency_unavailable" });
		}
	};
}
