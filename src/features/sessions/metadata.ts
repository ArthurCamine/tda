import { buildPublicMetadata } from "../../config/public-metadata";
import {
	PUBLIC_SESSION_MEDIA_MANIFEST,
	type PublicSessionMediaManifest,
	verifiedSessionMetadataImage,
} from "../../config/public-session-media";
import type { PublishedSession } from "./model";
import { sessionShareDescription } from "./share";

export function sessionPublicMetadataImage(
	session: Pick<PublishedSession, "id" | "title">,
	manifest: PublicSessionMediaManifest = PUBLIC_SESSION_MEDIA_MANIFEST,
) {
	return verifiedSessionMetadataImage({
		sessionId: session.id,
		title: session.title,
		manifest,
	});
}

export function sessionPublicMetadata(
	session: PublishedSession,
	manifest: PublicSessionMediaManifest = PUBLIC_SESSION_MEDIA_MANIFEST,
) {
	const image = sessionPublicMetadataImage(session, manifest);
	return buildPublicMetadata({
		title: session.title,
		description: sessionShareDescription(session.summary, session.title),
		pathname: `/sessoes/${encodeURIComponent(session.id)}`,
		type: "article",
		...(image ? { image } : {}),
	});
}
