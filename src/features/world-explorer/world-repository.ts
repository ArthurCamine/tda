import "server-only";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import {
	editDataClient,
	publishedDataClient,
} from "@/integrations/supabase/server";
import { DANDELION_WORLD_DEMO } from "./fixtures/dandelion";
import type {
	WorldDemoDataset,
	WorldEntityType,
	WorldLineStyle,
	WorldRelationDirection,
	WorldRelationFamily,
	WorldRelationTypeDTO,
	WorldVisibility,
} from "./model";
import { loadWorldEntityPortraitPresentations } from "./world-entity-media-repository";

type WorldAudience = "public" | "editor";

type EntityRow = {
	id: string;
	name: string;
	slug: string | null;
	entity_type: string;
	status: string | null;
	visibility: string | null;
	summary: string | null;
	aliases: string[] | null;
};

type RelationTypeRow = {
	slug: string;
	label: string;
	directionality: string;
	family: string;
	description: string;
	is_active: boolean;
};

type StyleRow = {
	relation_type_slug: string;
	color: string;
	line_style: string;
	line_width: number | string;
};

type RelationRow = {
	id: string;
	source_entity_id: string;
	target_entity_id: string;
	relation_type_slug: string;
	label_override: string | null;
	status: string;
	visibility: string;
	color_override: string | null;
	line_style_override: string | null;
	line_width_override: number | string | null;
};

const EMPTY_WORLD: WorldDemoDataset = {
	demo: false,
	nodes: [],
	edges: [],
	relationTypes: [],
	heroIds: [],
};

const ENTITY_TYPES = new Set<WorldEntityType>([
	"pc",
	"npc",
	"location",
	"item",
	"organization",
	"faction",
	"arc",
	"concept",
	"song",
	"quest",
	"other",
]);
const VISIBILITIES = new Set<WorldVisibility>([
	"private_master",
	"private_players",
	"review_only",
	"public_campaign",
	"public_web",
]);
const FAMILIES = new Set<WorldRelationFamily>([
	"affinity",
	"family",
	"conflict",
	"authority",
	"faction",
	"origin",
	"mystic",
	"creative",
	"context",
]);
const DIRECTIONS = new Set<WorldRelationDirection>(["directed", "symmetric"]);
const LINE_STYLES = new Set<WorldLineStyle>(["solid", "dashed", "dotted"]);

function finiteWidth(value: number | string | null | undefined, fallback = 3): number {
	const width = typeof value === "number" ? value : Number(value);
	return Number.isFinite(width) && width >= 1 && width <= 8 ? width : fallback;
}

function relationTypeDto(row: RelationTypeRow, style?: StyleRow): WorldRelationTypeDTO | null {
	if (!DIRECTIONS.has(row.directionality as WorldRelationDirection)) return null;
	if (!FAMILIES.has(row.family as WorldRelationFamily)) return null;
	const lineStyle = LINE_STYLES.has(style?.line_style as WorldLineStyle)
		? (style?.line_style as WorldLineStyle)
		: "solid";
	const styleColor = style?.color ?? "";
	const color = /^#[0-9a-f]{6}$/iu.test(styleColor)
		? styleColor.toLowerCase()
		: "#8f9aa8";
	return {
		slug: row.slug,
		label: row.label,
		direction: row.directionality as WorldRelationDirection,
		family: row.family as WorldRelationFamily,
		description: row.description,
		isActive: row.is_active,
		style: { color, lineStyle, lineWidth: finiteWidth(style?.line_width) },
	};
}

function demoWorldDataset(): WorldDemoDataset {
	return { ...DANDELION_WORLD_DEMO, demo: true };
}

function unavailableWorldDataset(): WorldDemoDataset {
	return process.env.TDA_WORLD_DEMO_FALLBACK === "true" ? demoWorldDataset() : EMPTY_WORLD;
}

export async function loadWorldDataset(
	audience: WorldAudience,
	campaignSlug = CAMPAIGN_SLUG,
): Promise<WorldDemoDataset> {
	// Canonical authoring can be deployed before the public projection is activated.
	// This prevents a sparse or not-yet-reviewed dataset from replacing the current
	// demonstrative World merely because the new tables already exist in production.
	if (audience === "public" && process.env.TDA_WORLD_CANONICAL_ENABLED !== "true") {
		return demoWorldDataset();
	}

	const client = audience === "editor" ? editDataClient() : publishedDataClient();
	if (!client) return unavailableWorldDataset();

	const { data: campaign, error: campaignError } = await client
		.from("campaigns")
		.select("id")
		.eq("slug", campaignSlug)
		.maybeSingle();
	if (campaignError) throw new Error(`World campaign lookup failed: ${campaignError.message}`);
	if (!campaign?.id) return EMPTY_WORLD;

	let entityQuery = client
		.from("entities")
		.select("id,name,slug,entity_type,status,visibility,summary,aliases")
		.eq("campaign_id", campaign.id);
	if (audience === "public") {
		entityQuery = entityQuery.eq("status", "active").eq("visibility", "public_web");
	}
	const { data: entityData, error: entityError } = await entityQuery.order("name");
	if (entityError) throw new Error(`World entity lookup failed: ${entityError.message}`);

	let nodes = ((entityData ?? []) as EntityRow[]).flatMap((row) => {
		if (!ENTITY_TYPES.has(row.entity_type as WorldEntityType)) return [];
		const visibility = VISIBILITIES.has(row.visibility as WorldVisibility)
			? (row.visibility as WorldVisibility)
			: "private_players";
		return [
			{
				id: row.id,
				slug: row.slug,
				kind: "entity" as const,
				entityType: row.entity_type as WorldEntityType,
				label: row.name,
				status: row.status ?? "active",
				visibility,
				summary: row.summary ?? "",
				aliases: row.aliases ?? [],
			},
		];
	});

	const portraitPresentations = await loadWorldEntityPortraitPresentations(
		client,
		campaign.id,
		campaignSlug,
		nodes.map((node) => node.id),
	);
	if (portraitPresentations.size) {
		nodes = nodes.map((node) => {
			const portrait = portraitPresentations.get(node.id);
			return portrait
				? {
						...node,
						imageUrl: portrait.imageUrl,
						imageFocalPoint: portrait.focalPoint,
					}
				: node;
		});
	}

	const visibleIds = new Set(
		nodes.filter((node) => node.status !== "archived").map((node) => node.id),
	);

	let typeQuery = client
		.from("relation_types")
		.select("slug,label,directionality,family,description,is_active")
		.eq("campaign_id", campaign.id);
	if (audience === "public") typeQuery = typeQuery.eq("is_active", true);
	const [{ data: typeData, error: typeError }, { data: styleData, error: styleError }] =
		await Promise.all([
			typeQuery.order("label"),
			client
				.from("world_relation_styles")
				.select("relation_type_slug,color,line_style,line_width")
				.eq("campaign_id", campaign.id),
		]);
	if (typeError) throw new Error(`World relation type lookup failed: ${typeError.message}`);
	if (styleError) throw new Error(`World relation style lookup failed: ${styleError.message}`);
	const styleByType = new Map(
		((styleData ?? []) as StyleRow[]).map((style) => [style.relation_type_slug, style]),
	);
	const relationTypes = ((typeData ?? []) as RelationTypeRow[])
		.map((row) => relationTypeDto(row, styleByType.get(row.slug)))
		.filter((item): item is WorldRelationTypeDTO => Boolean(item));
	const typeBySlug = new Map(relationTypes.map((item) => [item.slug, item]));

	let relationQuery = client
		.from("entity_relations")
		.select(
			"id,source_entity_id,target_entity_id,relation_type_slug,label_override,status,visibility,color_override,line_style_override,line_width_override",
		)
		.eq("campaign_id", campaign.id);
	if (audience === "public") {
		relationQuery = relationQuery.eq("status", "active").eq("visibility", "public_web");
	}
	const { data: relationData, error: relationError } = await relationQuery.order("created_at");
	if (relationError) throw new Error(`World relation lookup failed: ${relationError.message}`);

	const edges = ((relationData ?? []) as RelationRow[]).flatMap((row) => {
		const type = typeBySlug.get(row.relation_type_slug);
		if (!type || !visibleIds.has(row.source_entity_id) || !visibleIds.has(row.target_entity_id)) {
			return [];
		}
		const visibility = VISIBILITIES.has(row.visibility as WorldVisibility)
			? (row.visibility as WorldVisibility)
			: "private_players";
		const lineStyle = LINE_STYLES.has(row.line_style_override as WorldLineStyle)
			? (row.line_style_override as WorldLineStyle)
			: type.style.lineStyle;
		const relationColor = row.color_override ?? "";
		const color = /^#[0-9a-f]{6}$/iu.test(relationColor)
			? relationColor.toLowerCase()
			: type.style.color;
		return [
			{
				id: row.id,
				source: row.source_entity_id,
				target: row.target_entity_id,
				relationType: row.relation_type_slug,
				label: row.label_override ?? type.label,
				direction: type.direction,
				family: type.family,
				status: row.status,
				visibility,
				style: {
					color,
					lineStyle,
					lineWidth: finiteWidth(row.line_width_override, type.style.lineWidth),
				},
			},
		];
	});

	const activeNodes = nodes.filter((node) => node.status !== "archived");
	const activeIds = new Set(activeNodes.map((node) => node.id));
	return {
		demo: false,
		nodes: activeNodes,
		edges: edges.filter(
			(edge) =>
				edge.status !== "archived" &&
				activeIds.has(edge.source) &&
				activeIds.has(edge.target),
		),
		relationTypes,
		heroIds: activeNodes.filter((node) => node.entityType === "pc").map((node) => node.id),
	};
}
