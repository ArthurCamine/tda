import { MarkerType, type Edge, type Node } from "@xyflow/react";
import {
	constellationWorldLayout,
	type WorldLayout,
} from "../constellation-layout";
import { routeWorldEdgePorts } from "../edge-routing";
import { worldLayoutOverrides } from "../layout-contract";
import type {
	WorldEdgeDTO,
	WorldGraphProjection,
	WorldNodeDTO,
	WorldNodeProminence,
	WorldRelationFamily,
	WorldRelationStyleDTO,
} from "../model";

export type WorldFlowNodeData = {
	item: WorldNodeDTO;
	isFocus: boolean;
	isHero: boolean;
	prominence: WorldNodeProminence;
	isDimmed: boolean;
	authoringConnectable: boolean;
};

export type WorldFlowEdgeData = {
	item: WorldEdgeDTO;
	family: WorldRelationFamily;
	style?: WorldRelationStyleDTO;
	isHighlighted: boolean;
	isDimmed: boolean;
	routeOffset: number;
	labelOffset: { x: number; y: number };
};

export type WorldFlowNode = Node<WorldFlowNodeData, "worldEntity">;
export type WorldFlowEdge = Edge<WorldFlowEdgeData, "worldRelation">;
export type WorldFlowGraph = Readonly<{
	nodes: WorldFlowNode[];
	edges: WorldFlowEdge[];
}>;

/**
 * React Flow stores measured node dimensions in controlled node state.
 * Rebuilding the graph from domain data does not include those measurements,
 * so replacing the whole node array can temporarily make every node unmeasured.
 * With onlyRenderVisibleElements enabled that can cull the entire canvas until
 * the flow is remounted. Preserve measurements for stable node ids while still
 * accepting every domain-driven field from the freshly projected graph.
 */
export function preserveWorldFlowNodeMeasurements(
	currentNodes: readonly WorldFlowNode[],
	nextNodes: readonly WorldFlowNode[],
): WorldFlowNode[] {
	const currentById = new Map(currentNodes.map((node) => [node.id, node]));
	return nextNodes.map((node) => {
		if (node.measured) return node;
		const measured = currentById.get(node.id)?.measured;
		return measured ? { ...node, measured } : node;
	});
}

function prominenceFor(
	item: WorldNodeDTO,
	isHero: boolean,
): WorldNodeProminence {
	if (item.prominence) return item.prominence;
	if (isHero) return "hero";
	if (item.kind === "entity" && item.entityType === "npc") return "primary";
	if (item.kind === "moment") return "context";
	return "supporting";
}

function layoutWithOverrides(
	projection: WorldGraphProjection,
	positionOverrides?: Readonly<WorldLayout>,
): WorldLayout {
	const layout = constellationWorldLayout(projection);
	const visibleIds = new Set(projection.nodes.map((node) => node.id));

	for (const [id, position] of Object.entries(worldLayoutOverrides(projection))) {
		layout[id] = position;
	}

	if (!positionOverrides) return layout;
	for (const [id, position] of Object.entries(positionOverrides)) {
		if (visibleIds.has(id)) layout[id] = position;
	}
	return layout;
}

/**
 * Builds the expensive, selection-independent React Flow structure.
 * Layout and edge routing only need to run when the visible projection or
 * editorial positions change, not whenever the user clicks another node.
 */
export function toReactFlowStructure(
	projection: WorldGraphProjection,
	positionOverrides?: Readonly<WorldLayout>,
): WorldFlowGraph {
	const layout = layoutWithOverrides(projection, positionOverrides);
	const routes = routeWorldEdgePorts(layout, projection.edges);
	const heroIds = new Set(projection.heroIds);
	const labelById = new Map(projection.nodes.map((node) => [node.id, node.label]));
	const nodes: WorldFlowNode[] = projection.nodes.map((item) => {
		const isHero = heroIds.has(item.id);
		const isFocus = item.id === projection.focusId;
		return {
			id: item.id,
			type: "worldEntity",
			position: layout[item.id] ?? { x: 0, y: 0 },
			data: {
				item,
				isFocus,
				isHero,
				prominence: prominenceFor(item, isHero),
				isDimmed: false,
				authoringConnectable: false,
			},
			draggable: true,
			connectable: false,
			deletable: false,
			selectable: true,
			selected: false,
			focusable: true,
			ariaLabel: `${item.label}${item.subtitle ? ` — ${item.subtitle}` : ""}${isFocus ? " — foco exploratório" : ""}`,
			zIndex: isHero ? 3 : isFocus ? 4 : 1,
		};
	});

	const edges: WorldFlowEdge[] = projection.edges.map((item) => {
		const route = routes[item.id];
		const sourceLabel = labelById.get(item.source) ?? item.source;
		const targetLabel = labelById.get(item.target) ?? item.target;
		return {
			id: item.id,
			type: "worldRelation",
			source: item.source,
			target: item.target,
			sourceHandle: route?.sourceHandle,
			targetHandle: route?.targetHandle,
			data: {
				item,
				family: item.family,
				style: item.style,
				isHighlighted: false,
				isDimmed: false,
				routeOffset: route?.offset ?? 28,
				labelOffset: route?.labelOffset ?? { x: 0, y: 0 },
			},
			deletable: false,
			selectable: true,
			focusable: true,
			ariaLabel: `${item.label}: ${sourceLabel} → ${targetLabel}`,
			markerEnd:
				item.direction === "directed"
					? { type: MarkerType.ArrowClosed, width: 17, height: 17 }
					: undefined,
		};
	});
	return { nodes, edges };
}

/** Applies transient selection state without recalculating layout or edge routes. */
export function applyWorldFlowSelection(
	graph: WorldFlowGraph,
	selectedId?: string | null,
): WorldFlowGraph {
	const hasSelection = Boolean(selectedId);
	const connected = new Set<string>();
	if (selectedId) {
		connected.add(selectedId);
		for (const edge of graph.edges) {
			if (edge.source === selectedId) connected.add(edge.target);
			if (edge.target === selectedId) connected.add(edge.source);
		}
	}

	const nodes = graph.nodes.map((node) => {
		const isSelected = node.id === selectedId;
		const isDimmed = hasSelection && !connected.has(node.id);
		const zIndex = isSelected
			? 5
			: node.data.isHero
				? 3
				: node.data.isFocus
					? 4
					: 1;
		if (
			node.selected === isSelected &&
			node.data.isDimmed === isDimmed &&
			node.zIndex === zIndex
		) {
			return node;
		}
		return {
			...node,
			selected: isSelected,
			zIndex,
			data: { ...node.data, isDimmed },
		};
	});

	const edges = graph.edges.map((edge) => {
		const isHighlighted = Boolean(
			selectedId && (edge.source === selectedId || edge.target === selectedId),
		);
		const isDimmed = hasSelection && !isHighlighted;
		if (
			edge.data?.isHighlighted === isHighlighted &&
			edge.data?.isDimmed === isDimmed
		) {
			return edge;
		}
		return {
			...edge,
			data: edge.data
				? { ...edge.data, isHighlighted, isDimmed }
				: edge.data,
		};
	});

	return { nodes, edges };
}

export function toReactFlowGraph(
	projection: WorldGraphProjection,
	selectedId?: string | null,
	positionOverrides?: Readonly<WorldLayout>,
): WorldFlowGraph {
	return applyWorldFlowSelection(
		toReactFlowStructure(projection, positionOverrides),
		selectedId,
	);
}

export function rerouteWorldEdges(
	nodes: readonly WorldFlowNode[],
	edges: readonly WorldFlowEdge[],
): WorldFlowEdge[] {
	const layout: WorldLayout = Object.fromEntries(
		nodes.map((node) => [node.id, node.position]),
	);
	const relationItems = edges
		.map((edge) => edge.data?.item)
		.filter((item): item is WorldEdgeDTO => Boolean(item));
	const routes = routeWorldEdgePorts(layout, relationItems);
	return edges.map((edge) => {
		const route = routes[edge.id];
		if (!route) return edge;
		return {
			...edge,
			sourceHandle: route.sourceHandle,
			targetHandle: route.targetHandle,
			data: edge.data
				? {
					...edge.data,
					routeOffset: route.offset,
					labelOffset: route.labelOffset,
				}
				: edge.data,
		};
	});
}
