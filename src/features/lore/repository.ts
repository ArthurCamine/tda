import "server-only";
import { loadWorldEntityPortraitPresentations } from "@/features/world-explorer/world-entity-media-repository";
import { publishedDataClient } from "@/integrations/supabase/server";
import type { LoreProfileDTO, LoreRouteKind } from "./model";
import {
	buildPublishedLoreProfile,
	toPublicLoreIndexItem,
	type LoreIndexItem,
} from "./public-projection";
import { withPublishedLorePortraitFallback } from "./public-portrait";
import {
	loreEntityTypesForRoute,
	routeAcceptsLoreEntity,
} from "./routes";

const CAMPAIGN_SLUG = "yuhara-main";
const entityColumns =
	"id,name,slug,entity_type,status,visibility,summary,aliases";
const canonColumns = "title,content,entry_type,visibility,status";
const sessionColumns =
	"source_session_id,title,session_date,arc,summary_short,status,campaigns!inner(slug)";

type PublishedClient = NonNullable<ReturnType<typeof publishedDataClient>>;

async function resolveCampaignId(client: PublishedClient) {
	const { data, error } = await client
		.from("campaigns")
		.select("id")
		.eq("slug", CAMPAIGN_SLUG)
		.maybeSingle();
	if (error) throw new Error("Published lore campaign unavailable");
	return typeof data?.id === "string" ? data.id : null;
}

async function findPublishedSessionsForEntity(
	client: PublishedClient,
	entityId: string,
) {
	const { data: participants, error: participantError } = await client
		.from("participants")
		.select("session_id")
		.eq("character_entity_id", entityId)
		.limit(500);
	if (participantError) throw new Error("Published lore session links unavailable");

	const sessionIds = [
		...new Set(
			(participants ?? []).flatMap((row) =>
				typeof row.session_id === "string" ? [row.session_id] : [],
			),
		),
	];
	if (!sessionIds.length) return [];

	const { data, error } = await client
		.from("sessions")
		.select(sessionColumns)
		.in("id", sessionIds)
		.eq("status", "published")
		.eq("campaigns.slug", CAMPAIGN_SLUG)
		.order("session_date", { ascending: false, nullsFirst: false })
		.order("source_session_id", { ascending: true })
		.limit(500);
	if (error) throw new Error("Published lore sessions unavailable");
	return data ?? [];
}

async function withPublishedEntityPortrait(
	client: PublishedClient,
	campaignId: string,
	entityId: string,
	profile: LoreProfileDTO,
): Promise<LoreProfileDTO> {
	const portraits = await loadWorldEntityPortraitPresentations(
		client,
		campaignId,
		CAMPAIGN_SLUG,
		[entityId],
	);
	return withPublishedLorePortraitFallback(profile, portraits.get(entityId));
}

/**
 * Public lore projection boundary.
 *
 * Only entities explicitly marked `public_web` are eligible. Private player/master
 * entities are filtered server-side before a DTO can reach the browser.
 */
export async function listPublishedLoreIndex(
	routeKind: LoreRouteKind,
): Promise<LoreIndexItem[] | null> {
	const client = publishedDataClient();
	if (!client) return null;
	const campaignId = await resolveCampaignId(client);
	if (!campaignId) return [];

	const { data, error } = await client
		.from("entities")
		.select(entityColumns)
		.eq("campaign_id", campaignId)
		.eq("visibility", "public_web")
		.in("entity_type", [...loreEntityTypesForRoute(routeKind)])
		.order("name", { ascending: true })
		.limit(500);
	if (error) throw new Error("Published lore index unavailable");

	return (data ?? []).flatMap((row) => {
		const item = toPublicLoreIndexItem(row);
		return item ? [item] : [];
	});
}

export async function findPublishedLoreProfile(
	routeKind: LoreRouteKind,
	slug: string,
): Promise<LoreProfileDTO | null> {
	if (!slug || slug.length > 180) return null;
	const client = publishedDataClient();
	if (!client) return null;
	const campaignId = await resolveCampaignId(client);
	if (!campaignId) return null;

	const { data: entity, error: entityError } = await client
		.from("entities")
		.select(entityColumns)
		.eq("campaign_id", campaignId)
		.eq("slug", slug)
		.eq("visibility", "public_web")
		.in("entity_type", [...loreEntityTypesForRoute(routeKind)])
		.maybeSingle();
	if (entityError) throw new Error("Published lore profile unavailable");
	if (!entity || typeof entity.id !== "string") return null;

	const [{ data: canon, error: canonError }, sessions] = await Promise.all([
		client
			.from("canon_entries")
			.select(canonColumns)
			.eq("campaign_id", campaignId)
			.eq("entity_id", entity.id)
			.eq("visibility", "public_web")
			.eq("status", "active")
			.order("created_at", { ascending: true })
			.limit(200),
		findPublishedSessionsForEntity(client, entity.id),
	]);
	if (canonError) throw new Error("Published lore canon unavailable");

	const profile = buildPublishedLoreProfile(entity, canon ?? [], sessions);
	if (!profile || !routeAcceptsLoreEntity(routeKind, profile.identity.entityType)) {
		return null;
	}
	return withPublishedEntityPortrait(client, campaignId, entity.id, profile);
}
