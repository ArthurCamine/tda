export const WORLD_ENTITY_TYPES = [
	"pc",
	"npc",
	"location",
	"faction",
	"organization",
	"song",
	"quest",
	"concept",
	"item",
	"arc",
	"other",
] as const;

export type WorldEntityType = (typeof WORLD_ENTITY_TYPES)[number];

export const WORLD_VISIBILITIES = [
	"private_master",
	"private_players",
	"review_only",
	"public_campaign",
	"public_web",
] as const;
export type WorldVisibility = (typeof WORLD_VISIBILITIES)[number];

export type WorldNodeKind = "entity" | "moment";
export type WorldGraphMode = "overview" | "focus";
export type WorldNodeProminence = "hero" | "primary" | "supporting" | "context";
export type WorldRelationDirection = "directed" | "symmetric";

export type WorldRelationFamily =
	| "affinity"
	| "family"
	| "conflict"
	| "authority"
	| "faction"
	| "origin"
	| "mystic"
	| "creative"
	| "context";

export type WorldLineStyle = "solid" | "dashed" | "dotted";

export type WorldPositionHint = Readonly<{
	x: number;
	y: number;
}>;

export type WorldMediaFocalPoint = Readonly<{
	x: number;
	y: number;
}>;

/**
 * Audience-filtered presentation data for the campaign overview.
 *
 * It is deliberately separate from entities/relations/canon and contains only
 * world-space coordinates that the current projection is already authorized to
 * expose. Camera/zoom state is intentionally not part of the contract.
 */
export type WorldLayoutProjection = {
	schemaVersion: 1;
	view: "overview";
	revision: number;
	positions: Record<string, WorldPositionHint>;
};

export type WorldRelationStyleDTO = Readonly<{
	color: string;
	lineStyle: WorldLineStyle;
	lineWidth: number;
}>;

export type WorldRelationTypeDTO = Readonly<{
	slug: string;
	label: string;
	direction: WorldRelationDirection;
	family: WorldRelationFamily;
	description: string;
	isActive: boolean;
	style: WorldRelationStyleDTO;
}>;

export type WorldNodeDTO = {
	id: string;
	slug: string | null;
	kind: WorldNodeKind;
	entityType?: WorldEntityType;
	label: string;
	subtitle?: string;
	imageUrl?: string;
	imageFocalPoint?: WorldMediaFocalPoint;
	status?: string;
	visibility?: WorldVisibility;
	summary?: string;
	aliases?: string[];
	route?: string;
	/** Presentation-only weight. It never changes narrative authority. */
	prominence?: WorldNodeProminence;
	/** Optional curated seed used only by the canvas layout. */
	layoutHint?: WorldPositionHint;
};

export type WorldEdgeDTO = {
	id: string;
	source: string;
	target: string;
	relationType: string;
	label: string;
	direction: WorldRelationDirection;
	family: WorldRelationFamily;
	status?: string;
	visibility?: WorldVisibility;
	style?: WorldRelationStyleDTO;
};

export type WorldGraphProjection = {
	demo: boolean;
	mode: WorldGraphMode;
	focusId: string | null;
	heroIds: string[];
	nodes: WorldNodeDTO[];
	edges: WorldEdgeDTO[];
	relationTypes: WorldRelationTypeDTO[];
	/** Optional server-filtered editorial placement for overview mode only. */
	layout?: WorldLayoutProjection;
};

export type WorldDemoDataset = {
	demo?: boolean;
	nodes: WorldNodeDTO[];
	edges: WorldEdgeDTO[];
	relationTypes?: WorldRelationTypeDTO[];
	heroIds?: string[];
	layout?: WorldLayoutProjection;
};

export type WorldGraphDraftNode = Readonly<{
	id: string;
	name: string;
	slug: string | null;
	entityType: WorldEntityType;
	status: string;
	visibility: WorldVisibility;
	summary: string;
	aliases: string[];
	/** Stable media identity. Undefined means untouched; null means remove on publish. */
	primaryMediaAssetId?: string | null;
	primaryMediaFocalPoint?: WorldMediaFocalPoint;
}>;

export type WorldGraphDraftRelationType = Readonly<{
	slug: string;
	label: string;
	direction: WorldRelationDirection;
	family: WorldRelationFamily;
	description: string;
	isActive: boolean;
	color: string;
	lineStyle: WorldLineStyle;
	lineWidth: number;
}>;

export type WorldGraphDraftEdge = Readonly<{
	id: string;
	source: string;
	target: string;
	relationType: string;
	labelOverride: string | null;
	status: "active" | "ended" | "superseded" | "retcon_pending" | "archived";
	visibility: WorldVisibility;
	colorOverride: string | null;
	lineStyleOverride: WorldLineStyle | null;
	lineWidthOverride: number | null;
}>;

export type WorldGraphDraft = Readonly<{
	schemaVersion: 1;
	revision: number;
	nodes: WorldGraphDraftNode[];
	edges: WorldGraphDraftEdge[];
	relationTypes: WorldGraphDraftRelationType[];
}>;

export const WORLD_FILTERS = [
	"all",
	"characters",
	"npcs",
	"locations",
	"factions",
	"songs",
	"moments",
] as const;

export type WorldFilter = (typeof WORLD_FILTERS)[number];

export function isWorldFilter(value: string): value is WorldFilter {
	return WORLD_FILTERS.includes(value as WorldFilter);
}

export const WORLD_RELATION_FILTERS = [
	"all",
	"affinity",
	"family",
	"conflict",
	"authority",
	"faction",
	"origin",
	"mystic",
	"creative",
	"context",
] as const;

export type WorldRelationFilter = (typeof WORLD_RELATION_FILTERS)[number];
