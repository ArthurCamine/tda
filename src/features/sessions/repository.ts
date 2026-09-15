import "server-only";
import { cache } from "react";
import { publishedDataClient } from "@/integrations/supabase/server";
import type { SessionArchiveItem } from "./archive";
import {
	CAMPAIGN_SLUG,
	toPublishedSession,
	type PublishedSession,
} from "./model";

const publicMediaColumns =
	"cover_image_url:metadata->>coverImageUrl,hero_image_url:metadata->>heroImageUrl";
const columns = `source_session_id,title,session_date,arc,summary_short,${publicMediaColumns},status,campaigns!inner(slug)`;

export class PublishedSessionUnavailableError extends Error {
	constructor() {
		super("Published session unavailable");
		this.name = "PublishedSessionUnavailableError";
	}
}

export async function listPublishedSessions(): Promise<
	PublishedSession[] | null
> {
	const client = publishedDataClient();
	if (!client) return null;
	const { data, error } = await client
		.from("sessions")
		.select(columns)
		.eq("status", "published")
		.eq("campaigns.slug", CAMPAIGN_SLUG)
		.order("session_date", { ascending: false, nullsFirst: false })
		.order("source_session_id", { ascending: true })
		.limit(500);
	if (error) throw new Error("Published sessions unavailable");
	return (data ?? []).flatMap((row) => {
		const item = toPublishedSession(row);
		return item ? [item] : [];
	});
}

export async function listPublishedSessionArchive(): Promise<
	SessionArchiveItem[] | null
> {
	return listPublishedSessions();
}

export const findPublishedSession = cache(async (id: string) => {
	if (!id || id.length > 220) return null;
	const client = publishedDataClient();
	if (!client) throw new PublishedSessionUnavailableError();
	const { data, error } = await client
		.from("sessions")
		.select(
			`source_session_id,title,session_date,arc,summary_short,summary_full,${publicMediaColumns},status,campaigns!inner(slug)`,
		)
		.eq("status", "published")
		.eq("campaigns.slug", CAMPAIGN_SLUG)
		.eq("source_session_id", id)
		.maybeSingle();
	if (error) throw new PublishedSessionUnavailableError();
	return data ? toPublishedSession(data, true) : null;
});
