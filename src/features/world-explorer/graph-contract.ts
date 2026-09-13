import {
	WORLD_ENTITY_TYPES,
	WORLD_VISIBILITIES,
	type WorldDemoDataset,
	type WorldEntityType,
	type WorldGraphDraft,
	type WorldGraphDraftEdge,
	type WorldGraphDraftNode,
	type WorldGraphDraftRelationType,
	type WorldLineStyle,
	type WorldMediaFocalPoint,
	type WorldRelationDirection,
	type WorldRelationFamily,
	type WorldVisibility,
} from "./model";
import {
	isWorldEntityMediaAssetId,
	worldEntityMediaPreviewUrl,
} from "./world-entity-media";

const UUID_PATTERN =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,95}$/u;
const TYPE_SLUG_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/u;
const HEX_PATTERN = /^#[0-9a-f]{6}$/iu;
const DIRECTIONS = new Set<WorldRelationDirection>(["directed", "symmetric"]);
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
const LINE_STYLES = new Set<WorldLineStyle>(["solid", "dashed", "dotted"]);
const RELATION_STATUSES = new Set([
	"active",
	"ended",
	"superseded",
	"retcon_pending",
	"archived",
]);
const ENTITY_TYPES = new Set<WorldEntityType>(WORLD_ENTITY_TYPES);
const VISIBILITIES = new Set<WorldVisibility>(WORLD_VISIBILITIES);

function objectValue(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function optionalString(value: unknown, maxLength: number): string | null | undefined {
	if (value === null || value === undefined || value === "") return null;
	if (typeof value !== "string" || value.length > maxLength) return undefined;
	return value;
}

function parseMediaFocalPoint(value: unknown): WorldMediaFocalPoint | null {
	const row = objectValue(value);
	if (!row || typeof row.x !== "number" || typeof row.y !== "number") return null;
	if (!Number.isFinite(row.x) || !Number.isFinite(row.y)) return null;
	if (row.x < 0 || row.x > 1 || row.y < 0 || row.y > 1) return null;
	return { x: row.x, y: row.y };
}

function parseNode(value: unknown): WorldGraphDraftNode | null {
	const row = objectValue(value);
	if (!row || typeof row.id !== "string" || !UUID_PATTERN.test(row.id)) return null;
	if (typeof row.name !== "string" || row.name.trim().length < 1 || row.name.trim().length > 160) {
		return null;
	}
	const slug = optionalString(row.slug, 96);
	if (slug === undefined || (slug && !SLUG_PATTERN.test(slug))) return null;
	if (typeof row.entityType !== "string" || !ENTITY_TYPES.has(row.entityType as WorldEntityType)) {
		return null;
	}
	if (typeof row.status !== "string" || row.status.length < 1 || row.status.length > 32) return null;
	if (typeof row.visibility !== "string" || !VISIBILITIES.has(row.visibility as WorldVisibility)) {
		return null;
	}
	if (typeof row.summary !== "string" || row.summary.length > 4000) return null;
	if (!Array.isArray(row.aliases) || row.aliases.length > 50) return null;
	const aliases = row.aliases.filter(
		(alias): alias is string => typeof alias === "string" && alias.length >= 1 && alias.length <= 160,
	);
	if (aliases.length !== row.aliases.length) return null;

	let primaryMediaAssetId: string | null | undefined;
	let primaryMediaFocalPoint: WorldMediaFocalPoint | undefined;
	if (row.primaryMediaAssetId === undefined) {
		primaryMediaAssetId = undefined;
	} else if (row.primaryMediaAssetId === null || row.primaryMediaAssetId === "") {
		primaryMediaAssetId = null;
		if (row.primaryMediaFocalPoint !== undefined && row.primaryMediaFocalPoint !== null) return null;
	} else if (isWorldEntityMediaAssetId(row.primaryMediaAssetId)) {
		primaryMediaAssetId = row.primaryMediaAssetId.toLowerCase();
		if (row.primaryMediaFocalPoint === undefined || row.primaryMediaFocalPoint === null) {
			primaryMediaFocalPoint = { x: 0.5, y: 0.5 };
		} else {
			const focal = parseMediaFocalPoint(row.primaryMediaFocalPoint);
			if (!focal) return null;
			primaryMediaFocalPoint = focal;
		}
	} else {
		return null;
	}

	return {
		id: row.id.toLowerCase(),
		name: row.name.trim(),
		slug,
		entityType: row.entityType as WorldEntityType,
		status: row.status,
		visibility: row.visibility as WorldVisibility,
		summary: row.summary,
		aliases: [...new Set(aliases.map((alias) => alias.trim()).filter(Boolean))].sort((a, b) =>
			a.localeCompare(b, "pt-BR"),
		),
		...(primaryMediaAssetId === undefined ? {} : { primaryMediaAssetId }),
		...(primaryMediaFocalPoint ? { primaryMediaFocalPoint } : {}),
	};
}

function parseRelationType(value: unknown): WorldGraphDraftRelationType | null {
	const row = objectValue(value);
	if (!row || typeof row.slug !== "string" || !TYPE_SLUG_PATTERN.test(row.slug)) return null;
	if (typeof row.label !== "string" || row.label.trim().length < 1 || row.label.trim().length > 80) {
		return null;
	}
	if (typeof row.direction !== "string" || !DIRECTIONS.has(row.direction as WorldRelationDirection)) {
		return null;
	}
	if (typeof row.family !== "string" || !FAMILIES.has(row.family as WorldRelationFamily)) return null;
	if (typeof row.description !== "string" || row.description.length > 1000) return null;
	if (typeof row.isActive !== "boolean") return null;
	if (typeof row.color !== "string" || !HEX_PATTERN.test(row.color)) return null;
	if (typeof row.lineStyle !== "string" || !LINE_STYLES.has(row.lineStyle as WorldLineStyle)) {
		return null;
	}
	if (typeof row.lineWidth !== "number" || !Number.isFinite(row.lineWidth) || row.lineWidth < 1 || row.lineWidth > 8) {
		return null;
	}
	return {
		slug: row.slug,
		label: row.label.trim(),
		direction: row.direction as WorldRelationDirection,
		family: row.family as WorldRelationFamily,
		description: row.description,
		isActive: row.isActive,
		color: row.color.toLowerCase(),
		lineStyle: row.lineStyle as WorldLineStyle,
		lineWidth: row.lineWidth,
	};
}

function parseEdge(value: unknown): WorldGraphDraftEdge | null {
	const row = objectValue(value);
	if (!row || typeof row.id !== "string" || !UUID_PATTERN.test(row.id)) return null;
	if (typeof row.source !== "string" || !UUID_PATTERN.test(row.source)) return null;
	if (typeof row.target !== "string" || !UUID_PATTERN.test(row.target) || row.source === row.target) return null;
	if (typeof row.relationType !== "string" || !TYPE_SLUG_PATTERN.test(row.relationType)) return null;
	const labelOverride = optionalString(row.labelOverride, 120);
	if (labelOverride === undefined) return null;
	if (typeof row.status !== "string" || !RELATION_STATUSES.has(row.status)) return null;
	if (typeof row.visibility !== "string" || !VISIBILITIES.has(row.visibility as WorldVisibility)) return null;
	const colorOverride = optionalString(row.colorOverride, 7);
	if (colorOverride === undefined || (colorOverride && !HEX_PATTERN.test(colorOverride))) return null;
	const lineStyleOverride = optionalString(row.lineStyleOverride, 16);
	if (
		lineStyleOverride === undefined ||
		(lineStyleOverride && !LINE_STYLES.has(lineStyleOverride as WorldLineStyle))
	) {
		return null;
	}
	if (
		row.lineWidthOverride !== null &&
		row.lineWidthOverride !== undefined &&
		(typeof row.lineWidthOverride !== "number" ||
			!Number.isFinite(row.lineWidthOverride) ||
			row.lineWidthOverride < 1 ||
			row.lineWidthOverride > 8)
	) {
		return null;
	}
	return {
		id: row.id.toLowerCase(),
		source: row.source.toLowerCase(),
		target: row.target.toLowerCase(),
		relationType: row.relationType,
		labelOverride,
		status: row.status as WorldGraphDraftEdge["status"],
		visibility: row.visibility as WorldVisibility,
		colorOverride: colorOverride?.toLowerCase() ?? null,
		lineStyleOverride: (lineStyleOverride as WorldLineStyle | null) ?? null,
		lineWidthOverride: typeof row.lineWidthOverride === "number" ? row.lineWidthOverride : null,
	};
}

export function sanitizeWorldGraphDraft(value: unknown): WorldGraphDraft | null {
	const row = objectValue(value);
	if (!row || row.schemaVersion !== 1 || !Number.isSafeInteger(row.revision) || Number(row.revision) < 0) {
		return null;
	}
	if (!Array.isArray(row.nodes) || !Array.isArray(row.edges) || !Array.isArray(row.relationTypes)) return null;
	if (row.nodes.length > 1000 || row.edges.length > 5000 || row.relationTypes.length > 200) return null;
	const nodes = row.nodes.map(parseNode);
	const edges = row.edges.map(parseEdge);
	const relationTypes = row.relationTypes.map(parseRelationType);
	if (nodes.some((item) => !item) || edges.some((item) => !item) || relationTypes.some((item) => !item)) {
		return null;
	}
	const safeNodes = nodes as WorldGraphDraftNode[];
	const safeEdges = edges as WorldGraphDraftEdge[];
	const safeTypes = relationTypes as WorldGraphDraftRelationType[];
	if (new Set(safeNodes.map((item) => item.id)).size !== safeNodes.length) return null;
	if (new Set(safeNodes.map((item) => item.name)).size !== safeNodes.length) return null;
	if (new Set(safeTypes.map((item) => item.slug)).size !== safeTypes.length) return null;
	if (new Set(safeEdges.map((item) => item.id)).size !== safeEdges.length) return null;
	const nodeIds = new Set(safeNodes.map((item) => item.id));
	const typeSlugs = new Set(safeTypes.map((item) => item.slug));
	if (safeEdges.some((edge) => !nodeIds.has(edge.source) || !nodeIds.has(edge.target) || !typeSlugs.has(edge.relationType))) {
		return null;
	}
	return {
		schemaVersion: 1,
		revision: Number(row.revision),
		nodes: safeNodes.sort((a, b) => a.id.localeCompare(b.id)),
		edges: safeEdges.sort((a, b) => a.id.localeCompare(b.id)),
		relationTypes: safeTypes.sort((a, b) => a.slug.localeCompare(b.slug)),
	};
}

export function worldDatasetFromDraft(draft: WorldGraphDraft): WorldDemoDataset {
	const activeNodes = draft.nodes.filter((node) => node.status !== "archived");
	const nodeIds = new Set(activeNodes.map((node) => node.id));
	const typeBySlug = new Map(draft.relationTypes.map((type) => [type.slug, type]));
	const relationTypes = draft.relationTypes.map((type) => ({
		slug: type.slug,
		label: type.label,
		direction: type.direction,
		family: type.family,
		description: type.description,
		isActive: type.isActive,
		style: { color: type.color, lineStyle: type.lineStyle, lineWidth: type.lineWidth },
	}));
	return {
		demo: false,
		nodes: activeNodes.map((node) => ({
			id: node.id,
			slug: node.slug,
			kind: "entity" as const,
			entityType: node.entityType,
			label: node.name,
			imageUrl: node.primaryMediaAssetId
				? worldEntityMediaPreviewUrl(node.primaryMediaAssetId)
				: undefined,
			imageFocalPoint: node.primaryMediaAssetId
				? (node.primaryMediaFocalPoint ?? { x: 0.5, y: 0.5 })
				: undefined,
			status: node.status,
			visibility: node.visibility,
			summary: node.summary,
			aliases: node.aliases,
		})),
		edges: draft.edges.flatMap((edge) => {
			if (edge.status === "archived" || !nodeIds.has(edge.source) || !nodeIds.has(edge.target)) return [];
			const type = typeBySlug.get(edge.relationType);
			if (!type) return [];
			return [
				{
					id: edge.id,
					source: edge.source,
					target: edge.target,
					relationType: edge.relationType,
					label: edge.labelOverride ?? type.label,
					direction: type.direction,
					family: type.family,
					status: edge.status,
					visibility: edge.visibility,
					style: {
						color: edge.colorOverride ?? type.color,
						lineStyle: edge.lineStyleOverride ?? type.lineStyle,
						lineWidth: edge.lineWidthOverride ?? type.lineWidth,
					},
				},
			];
		}),
		relationTypes,
		heroIds: activeNodes.filter((node) => node.entityType === "pc").map((node) => node.id),
	};
}
