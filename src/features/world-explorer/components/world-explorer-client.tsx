"use client";

import { useRouter } from "next/navigation";
import {
	useEffect,
	useMemo,
	useRef,
	useState,
	type CSSProperties,
} from "react";
import { useEdgesState, useNodesState, type XYPosition } from "@xyflow/react";
import { useWorldWorkspaceControls } from "../../world-shell/world-workspace-context";
import {
	applyWorldFlowSelection,
	preserveWorldFlowNodeMeasurements,
	rerouteWorldEdges,
	toReactFlowGraph,
	toReactFlowStructure,
	type WorldFlowEdge,
	type WorldFlowNode,
} from "../adapters/react-flow";
import type { WorldLayout } from "../constellation-layout";
import { captureWorldLayoutCandidate } from "../editorial-layout";
import { useWorldAuthoringUi } from "../hooks/use-world-authoring-ui";
import { useWorldEditSession } from "../hooks/use-world-edit-session";
import {
	projectionWithWorldDraft,
	useWorldExplorerView,
} from "../hooks/use-world-explorer-view";
import type {
	WorldEntityType,
	WorldGraphProjection,
	WorldLayoutProjection,
	WorldVisibility,
} from "../model";
import {
	WORLD_AUTHORING_CONNECT_FROM_NODE_EVENT,
	type WorldAuthoringConnectFromNodeDetail,
} from "../world-authoring-events";
import {
	worldCommandForShortcut,
	worldCommandIsAvailable,
	worldShortcutFromKeyboardInput,
	type WorldCommandContext,
	type WorldCommandId,
} from "../world-commands";
import { appendWorldDraftNode } from "../world-direct-create";
import {
	appendWorldDraftRelation,
	reconnectWorldDraftRelation,
} from "../world-relation-draft";
import authoring from "./world-authoring-shell.module.css";
import { WorldCanvas } from "./world-canvas";
import { WorldCommandPalette } from "./world-command-palette";
import { WorldConductorBar } from "./world-conductor-bar";
import { WorldContentEditor } from "./world-content-editor";
import { WorldDirectCreateControls } from "./world-direct-create-controls";
import { WorldFloatingChrome } from "./world-floating-chrome";
import {
	WorldAccessibleRelations,
	WorldInspectorContent,
} from "./world-inspector";
import {
	WorldRelationAuthoringControls,
	type WorldRelationCandidate,
} from "./world-relation-authoring-controls";
import styles from "./world-explorer.module.css";
import responsive from "./world-responsive.module.css";

const PALETTE_COMMAND_IDS: ReadonlySet<WorldCommandId> = new Set([
	"world.openNavigation",
	"world.search",
	"world.reorganize",
	"world.openList",
	"world.toggleInspector",
	"world.toggleFocusMode",
	"world.createEntity",
	"world.connectSelection",
	"world.publish",
	"world.finishConductor",
	"world.discard",
	"world.openProfile",
]);

function isTypingTarget(target: EventTarget | null): boolean {
	return (
		target instanceof HTMLElement &&
		Boolean(target.closest("input, textarea, select, [contenteditable='true']"))
	);
}

function publishedLayoutCandidate(projection: WorldGraphProjection): WorldLayoutProjection {
	return {
		schemaVersion: 1,
		view: "overview",
		revision: projection.layout?.revision ?? 0,
		positions: projection.layout?.positions ?? {},
	};
}

function layoutCandidateFor(
	projection: WorldGraphProjection,
	overrides: WorldLayout,
): WorldLayoutProjection | null {
	const fullGraph = toReactFlowGraph(projection, null, overrides);
	return (
		captureWorldLayoutCandidate(
			projection,
			Object.fromEntries(
				fullGraph.nodes.map((node) => [
					node.id,
					{ x: node.position.x, y: node.position.y },
				]),
			),
		) ?? null
	);
}

export function WorldExplorerClient({
	projection,
	canEditLayout = false,
	canEditContent = false,
}: {
	projection: WorldGraphProjection;
	canEditLayout?: boolean;
	canEditContent?: boolean;
}) {
	const router = useRouter();
	const workspace = useWorldWorkspaceControls();
	const [positionOverrides, setPositionOverrides] = useState<WorldLayout>({});
	const positionOverridesRef = useRef<WorldLayout>({});
	const searchInputRef = useRef<HTMLInputElement>(null);
	const executeWorldCommandRef = useRef<(id: WorldCommandId) => void>(() => undefined);
	const [createType, setCreateType] = useState<WorldEntityType | null>(null);
	const [createPoint, setCreatePoint] = useState<XYPosition | null>(null);
	const [relationCandidate, setRelationCandidate] = useState<WorldRelationCandidate | null>(null);
	const authoringUi = useWorldAuthoringUi();

	const edit = useWorldEditSession({
		canEditLayout,
		canEditContent,
		canStartEditing: projection.mode === "overview",
		publishedPositions: projection.layout?.positions ?? {},
		buildLayoutCandidate: (draft) =>
			layoutCandidateFor(
				canEditContent ? projectionWithWorldDraft(projection, draft) : projection,
				positionOverridesRef.current,
			),
		onApplyLayoutDraft: (positions) => {
			positionOverridesRef.current = positions;
			setPositionOverrides(positions);
		},
		onReleaseLayout: () => {
			positionOverridesRef.current = {};
			setPositionOverrides({});
		},
		onEditingStarted: authoringUi.authoringStarted,
		onPublished: () => router.refresh(),
	});

	const {
		filter,
		setFilter,
		relationFilter,
		setRelationFilter,
		query,
		setQuery,
		selectedId,
		setSelectedId,
		view,
		setView,
		workingProjection,
		visibleProjection,
		selected,
		focus,
		activeRelationTypes,
	} = useWorldExplorerView({
		projection,
		canEditContent,
		editing: edit.editing,
		graphDraft: edit.graphDraft,
	});

	const authoringActive = edit.editing;
	const authoringPanelVisible =
		canEditContent && edit.state === "editing" && edit.graphDraft !== null;
	const directCreateEnabled =
		authoringPanelVisible && view === "canvas" && !authoringUi.focusMode;
	const relationAuthoringAvailable =
		authoringPanelVisible && view === "canvas" && !authoringUi.focusMode;
	const connectionActive =
		relationAuthoringAvailable && authoringUi.state.tool === "connect";

	const commandContext = useMemo<WorldCommandContext>(
		() => ({
			mode: workingProjection.mode,
			canEditLayout,
			canEditContent,
			editState: edit.state,
			hasChanges: edit.hasChanges,
			hasSelection: Boolean(selected),
			selectionIsFocus: Boolean(selected && selected.id === workingProjection.focusId),
			hasProfileRoute: Boolean(selected?.route),
			focusMode: authoringUi.focusMode,
		}),
		[
			workingProjection.mode,
			workingProjection.focusId,
			canEditLayout,
			canEditContent,
			edit.state,
			edit.hasChanges,
			selected,
			authoringUi.focusMode,
		],
	);

	const graphStructure = useMemo(
		() => toReactFlowStructure(visibleProjection, positionOverrides),
		[visibleProjection, positionOverrides],
	);
	const graph = useMemo(() => {
		const selectedGraph = applyWorldFlowSelection(graphStructure, selectedId);
		if (!connectionActive) return selectedGraph;
		return {
			nodes: selectedGraph.nodes.map((node) => ({
				...node,
				connectable: true,
				data: { ...node.data, authoringConnectable: true },
			})),
			edges: selectedGraph.edges.map((edge) => ({ ...edge, reconnectable: true })),
		};
	}, [connectionActive, graphStructure, selectedId]);
	const [nodes, setNodes, onNodesChange] = useNodesState<WorldFlowNode>(graph.nodes);
	const [edges, setEdges, onEdgesChange] = useEdgesState<WorldFlowEdge>(graph.edges);

	useEffect(() => {
		positionOverridesRef.current = positionOverrides;
	}, [positionOverrides]);

	useEffect(() => {
		setNodes((current) => preserveWorldFlowNodeMeasurements(current, graph.nodes));
		setEdges(graph.edges);
	}, [graph, setEdges, setNodes]);

	useEffect(() => {
		workspace.setAuthoringActive(edit.editing);
		if (!edit.editing) authoringUi.authoringStopped();
	}, [edit.editing, workspace.setAuthoringActive, authoringUi.authoringStopped]);

	useEffect(() => {
		if (edit.editing) return;
		setCreateType(null);
		setCreatePoint(null);
		setRelationCandidate(null);
	}, [edit.editing]);

	useEffect(() => {
		if (!relationAuthoringAvailable) return;
		function beginConnectionFromNode(event: Event) {
			const detail = (event as CustomEvent<WorldAuthoringConnectFromNodeDetail>).detail;
			if (!detail?.nodeId) return;
			setCreateType(null);
			setCreatePoint(null);
			setRelationCandidate(null);
			setSelectedId(detail.nodeId);
			authoringUi.setTool("connect");
		}
		window.addEventListener(WORLD_AUTHORING_CONNECT_FROM_NODE_EVENT, beginConnectionFromNode);
		return () =>
			window.removeEventListener(
				WORLD_AUTHORING_CONNECT_FROM_NODE_EVENT,
				beginConnectionFromNode,
			);
	}, [relationAuthoringAvailable, setSelectedId, authoringUi]);

	useEffect(
		() => () => {
			workspace.setAuthoringActive(false);
		},
		[workspace.setAuthoringActive],
	);

	function rememberNodePosition(node: WorldFlowNode) {
		const nextOverrides: WorldLayout = {
			...positionOverridesRef.current,
			[node.id]: { x: node.position.x, y: node.position.y },
		};
		positionOverridesRef.current = nextOverrides;
		setPositionOverrides(nextOverrides);
		const positionedNodes = nodes.map((item) =>
			item.id === node.id ? { ...item, position: node.position } : item,
		);
		setEdges((current) => rerouteWorldEdges(positionedNodes, current));
		if (edit.state === "editing") {
			const candidate = layoutCandidateFor(workingProjection, nextOverrides);
			if (!candidate) {
				edit.reportFailure("invalid_payload");
				return;
			}
			edit.updateLayoutDraft(candidate);
		}
	}

	function resetLayout() {
		positionOverridesRef.current = {};
		setPositionOverrides({});
		setSelectedId(workingProjection.focusId);
		if (edit.state === "editing") {
			edit.updateLayoutDraft(publishedLayoutCandidate(projection), {
				dirty: false,
				pendingMessage: "Restaurando as posições publicadas no rascunho…",
			});
		}
	}

	function cancelDirectCreate() {
		setCreateType(null);
		setCreatePoint(null);
		authoringUi.setTool("select");
	}

	function beginDirectCreate(type: WorldEntityType) {
		if (!directCreateEnabled) return;
		setRelationCandidate(null);
		setSelectedId(null);
		setCreateType(type);
		setCreatePoint(null);
		authoringUi.setTool("create");
	}

	function cancelRelationAuthoring() {
		setRelationCandidate(null);
		authoringUi.setTool("select");
	}

	function relationConnectionIsValid(sourceId: string, targetId: string): boolean {
		if (!connectionActive || !edit.graphDraft || sourceId === targetId) return false;
		const activeNodeIds = new Set(
			edit.graphDraft.nodes
				.filter((node) => node.status !== "archived")
				.map((node) => node.id),
		);
		return activeNodeIds.has(sourceId) && activeNodeIds.has(targetId);
	}

	function captureRelationCandidate(sourceId: string, targetId: string) {
		if (!relationConnectionIsValid(sourceId, targetId)) return;
		setRelationCandidate({ sourceId, targetId });
	}

	function confirmRelation(relationType: string, visibility: WorldVisibility) {
		if (edit.state !== "editing" || !edit.graphDraft || !relationCandidate) return;
		const nextDraft = appendWorldDraftRelation(edit.graphDraft, {
			id: crypto.randomUUID(),
			sourceId: relationCandidate.sourceId,
			targetId: relationCandidate.targetId,
			relationType,
			visibility,
		});
		if (!nextDraft) {
			edit.reportFailure("duplicate");
			return;
		}
		const sourceName = edit.graphDraft.nodes.find(
			(node) => node.id === relationCandidate.sourceId,
		)?.name;
		const targetName = edit.graphDraft.nodes.find(
			(node) => node.id === relationCandidate.targetId,
		)?.name;
		edit.updateGraphDraft(
			nextDraft,
			`Ligação ${sourceName ?? "origem"} → ${targetName ?? "destino"} criada no rascunho.`,
		);
		setFilter("all");
		setRelationFilter("all");
		setQuery("");
		setSelectedId(relationCandidate.sourceId);
		setRelationCandidate(null);
		authoringUi.setTool("select");
	}

	function reconnectRelation(edgeId: string, sourceId: string, targetId: string) {
		if (edit.state !== "editing" || !edit.graphDraft || !connectionActive) return;
		const nextDraft = reconnectWorldDraftRelation(edit.graphDraft, edgeId, sourceId, targetId);
		if (!nextDraft) {
			edit.reportFailure("duplicate");
			return;
		}
		edit.updateGraphDraft(nextDraft, "Ligação corrigida no rascunho.");
		setRelationCandidate(null);
		setSelectedId(sourceId);
		authoringUi.setTool("select");
	}

	function handleCanvasPaneClick(position: XYPosition | null) {
		if (
			directCreateEnabled &&
			authoringUi.state.tool === "create" &&
			createType &&
			position
		) {
			setCreatePoint(position);
			return;
		}
		setSelectedId(null);
	}

	function createDirectNode(name: string) {
		if (
			edit.state !== "editing" ||
			!edit.graphDraft ||
			!createType ||
			!createPoint
		) {
			return;
		}
		const result = appendWorldDraftNode(edit.graphDraft, {
			id: crypto.randomUUID(),
			name,
			entityType: createType,
		});
		if (!result) return;

		const nextOverrides: WorldLayout = {
			...positionOverridesRef.current,
			[result.node.id]: { x: createPoint.x, y: createPoint.y },
		};
		const candidate = layoutCandidateFor(
			projectionWithWorldDraft(projection, result.draft),
			nextOverrides,
		);
		if (!candidate) {
			edit.reportFailure("invalid_payload");
			return;
		}

		positionOverridesRef.current = nextOverrides;
		setPositionOverrides(nextOverrides);
		setFilter("all");
		setQuery("");
		edit.updateGraphDraft(result.draft, `${result.node.name} foi criado no rascunho.`);
		edit.updateLayoutDraft(candidate, {
			pendingMessage: "Salvando posição do novo elemento no rascunho…",
		});
		setSelectedId(result.node.id);
		setCreateType(null);
		setCreatePoint(null);
		authoringUi.setTool("select");
		authoringUi.setInspectorMode("overlay");
	}

	function openDirectCreateFromCommand() {
		if (!worldCommandIsAvailable("world.createEntity", commandContext)) return;
		setView("canvas");
		window.requestAnimationFrame(() => {
			window.requestAnimationFrame(() => {
				document
					.querySelector<HTMLButtonElement>("[data-world-direct-create] > button")
					?.click();
			});
		});
	}

	function executeWorldCommand(id: WorldCommandId) {
		if (!worldCommandIsAvailable(id, commandContext)) return;
		switch (id) {
			case "world.openNavigation":
				workspace.openNavigation();
				return;
			case "world.search":
				searchInputRef.current?.focus();
				return;
			case "world.reorganize":
				resetLayout();
				return;
			case "world.openList":
				setView("list");
				return;
			case "world.toggleInspector":
				authoringUi.toggleInspector(authoringActive ? "overlay" : "docked");
				return;
			case "world.toggleFocusMode":
				authoringUi.toggleFocusMode();
				return;
			case "world.createEntity":
				openDirectCreateFromCommand();
				return;
			case "world.connectSelection":
				if (!selectedId) return;
				window.dispatchEvent(
					new CustomEvent<WorldAuthoringConnectFromNodeDetail>(
						WORLD_AUTHORING_CONNECT_FROM_NODE_EVENT,
						{ detail: { nodeId: selectedId } },
					),
				);
				return;
			case "world.publish":
				void edit.publish();
				return;
			case "world.finishConductor":
				void edit.finish();
				return;
			case "world.discard":
				void edit.discard();
				return;
			case "world.openProfile":
				if (selected?.route) router.push(selected.route);
				return;
			default:
				return;
		}
	}
	executeWorldCommandRef.current = executeWorldCommand;

	function selectEntityFromPalette(id: string) {
		setFilter("all");
		setRelationFilter("all");
		setQuery("");
		setView("canvas");
		setSelectedId(id);
	}

	useEffect(() => {
		if (!authoringActive) return;
		function handleShortcut(event: KeyboardEvent) {
			if (event.key === "Escape" && connectionActive && !isTypingTarget(event.target)) {
				event.preventDefault();
				setRelationCandidate(null);
				authoringUi.setTool("select");
				return;
			}
			const shortcut = worldShortcutFromKeyboardInput(event);
			if (!shortcut || shortcut === "N") return;
			if (shortcut !== "Mod+K" && isTypingTarget(event.target)) return;
			const command = worldCommandForShortcut(shortcut, commandContext);
			if (!command) return;
			event.preventDefault();
			if (command.id === "world.openCommandPalette") {
				authoringUi.setCommandPaletteOpen(!authoringUi.state.commandPaletteOpen);
				return;
			}
			executeWorldCommandRef.current(command.id);
		}
		window.addEventListener("keydown", handleShortcut);
		return () => window.removeEventListener("keydown", handleShortcut);
	}, [
		authoringActive,
		connectionActive,
		commandContext,
		authoringUi.state.commandPaletteOpen,
		authoringUi.setCommandPaletteOpen,
		authoringUi.setTool,
	]);

	return (
		<div
			className={`${styles.explorer} ${responsive.layout} ${authoringActive ? authoring.active : ""} ${authoringActive && authoringUi.focusMode ? authoring.focusMode : ""} ${authoringUi.inspectorCollapsed ? styles.explorerPanelCollapsed : ""}`}
			style={
				{
					"--world-inspector-width": `${authoringUi.state.inspectorWidth}px`,
				} as CSSProperties
			}
			data-world-edit-state={edit.state}
			data-world-content-edit={canEditContent ? "enabled" : "disabled"}
			data-world-authoring-active={authoringActive ? "true" : "false"}
			data-world-authoring-tool={authoringUi.state.tool}
			data-world-focus-mode={authoringActive && authoringUi.focusMode ? "true" : "false"}
			data-world-inspector-mode={authoringUi.state.inspectorMode}
			data-world-command-palette={authoringUi.state.commandPaletteOpen ? "open" : "closed"}
			aria-busy={edit.busy}
		>
			<section
				className={`${styles.canvasColumn} ${responsive.canvasColumn} ${authoring.canvasColumn}`}
				aria-labelledby="world-explorer-title"
			>
				<header className={`${styles.explorerHeader} ${authoring.editorialHeader}`}>
					<div className={styles.titleCluster}>
						<p className={styles.eyebrow}>Mapa da campanha</p>
						<div className={styles.titleLine}>
							<h1 id="world-explorer-title">Ecos da Jornada</h1>
							{workingProjection.mode === "focus" && focus ? (
								<span className={styles.focusContext}>Conexões de {focus.label}</span>
							) : null}
						</div>
					</div>
					<div className={styles.headerActions}>
						{workingProjection.demo ? (
							<span className={styles.demoBadge}>Demo · não canônico</span>
						) : null}
					</div>
				</header>

				{canEditLayout && projection.mode === "overview" ? (
					<WorldConductorBar
						context={commandContext}
						canEditContent={canEditContent}
						busy={edit.busy}
						busyNotice={edit.busyNotice}
						feedback={edit.feedback}
						focusMode={authoringActive && authoringUi.focusMode}
						inspectorOpen={!authoringUi.inspectorCollapsed}
						onEnter={edit.start}
						onPublish={edit.publish}
						onFinish={edit.finish}
						onDiscard={edit.discard}
						onToggleFocusMode={authoringUi.toggleFocusMode}
						onToggleInspector={() => authoringUi.toggleInspector("overlay")}
						onOpenNavigation={workspace.openNavigation}
						onOpenCommandPalette={() => authoringUi.setCommandPaletteOpen(true)}
					/>
				) : null}

				<div className={authoring.publicChrome}>
					<WorldFloatingChrome
						query={query}
						onQueryChange={setQuery}
						filter={filter}
						onFilterChange={setFilter}
						relationFilter={relationFilter}
						onRelationFilterChange={setRelationFilter}
						view={view}
						onViewChange={setView}
						onReset={resetLayout}
						resetLabel={edit.editing ? "Restaurar posições" : "Reorganizar"}
						resetDisabled={edit.busy}
						demo={workingProjection.demo}
						activeRelationTypes={activeRelationTypes}
						searchInputRef={searchInputRef}
					/>
				</div>

				{view === "canvas" ? (
					<WorldCanvas
						nodes={nodes}
						edges={edges}
						onNodesChange={onNodesChange}
						onEdgesChange={onEdgesChange}
						onNodeSelect={(node) => {
							if (authoringUi.state.tool === "create") cancelDirectCreate();
							setSelectedId(node.id);
						}}
						onNodeDragStop={rememberNodePosition}
						onPaneClick={handleCanvasPaneClick}
						placementActive={
							directCreateEnabled &&
							authoringUi.state.tool === "create" &&
							Boolean(createType)
						}
						connectionActive={connectionActive}
						onConnectNodes={captureRelationCandidate}
						onReconnectEdge={reconnectRelation}
						isConnectionValid={relationConnectionIsValid}
						overlay={
							<>
								<WorldDirectCreateControls
									enabled={directCreateEnabled && !connectionActive}
									placementType={createType}
									placementPoint={createPoint}
									onSelectType={beginDirectCreate}
									onCancel={cancelDirectCreate}
									onCreate={createDirectNode}
								/>
								<WorldRelationAuthoringControls
									enabled={connectionActive}
									draft={edit.graphDraft}
									candidate={relationCandidate}
									onCancel={cancelRelationAuthoring}
									onConfirm={confirmRelation}
								/>
							</>
						}
					/>
				) : null}

				<WorldAccessibleRelations
					projection={visibleProjection}
					selectedId={selected?.id ?? null}
					onSelect={setSelectedId}
					compact={view === "canvas"}
				/>
			</section>

			<aside
				className={`${styles.inspector} ${responsive.inspector} ${authoring.inspector}`}
				aria-live="polite"
			>
				<hr
					className={`${styles.panelResizer} ${responsive.resizer}`}
					aria-label="Ajustar largura do painel"
					aria-orientation="vertical"
					aria-valuemin={authoringUi.inspectorMinWidth}
					aria-valuemax={authoringUi.inspectorMaxWidth}
					aria-valuenow={authoringUi.state.inspectorWidth}
					tabIndex={0}
					onPointerDown={authoringUi.startInspectorResize}
					onPointerMove={authoringUi.resizeInspector}
					onPointerUp={authoringUi.stopInspectorResize}
					onKeyDown={(event) => {
						if (event.key === "ArrowLeft") {
							authoringUi.adjustInspectorWidth(24);
						}
						if (event.key === "ArrowRight") {
							authoringUi.adjustInspectorWidth(-24);
						}
					}}
				/>
				<button
					className={`${styles.panelToggle} ${responsive.panelToggle}`}
					type="button"
					onClick={() => authoringUi.toggleInspector(authoringActive ? "overlay" : "docked")}
					aria-expanded={!authoringUi.inspectorCollapsed}
					aria-label={
						authoringUi.inspectorCollapsed
							? "Abrir painel de detalhes"
							: "Recolher painel de detalhes"
					}
				>
					{authoringUi.inspectorCollapsed ? "‹" : "›"}
				</button>
				{!authoringUi.inspectorCollapsed ? (
					authoringPanelVisible && edit.graphDraft ? (
						<WorldContentEditor
							draft={edit.graphDraft}
							selectedId={selectedId}
							onDraftChange={edit.updateGraphDraft}
							onSelect={setSelectedId}
						/>
				) : edit.state === "publishing" && canEditContent ? (
						<div className={styles.overviewInspector}>
							<h2>Publicando…</h2>
							<p>Validando o rascunho e registrando as alterações do Mundo.</p>
						</div>
				) : selected ? (
						<WorldInspectorContent
							key={selected.id}
							selected={selected}
							projection={visibleProjection}
							focus={focus}
							onSelect={setSelectedId}
							editing={edit.editing}
						/>
				) : (
						<div className={styles.overviewInspector}>
							<h2>Visão geral</h2>
							<p>
								{canEditContent && edit.editing
									? "Abra Detalhes quando precisar editar propriedades. O canvas continua como superfície principal de trabalho."
									: "Selecione qualquer nó para inspecionar seus laços sem reorganizar o mapa."}
							</p>
							<dl className={styles.overviewStats}>
								<div>
									<dt>Heróis visíveis</dt>
									<dd>{visibleProjection.heroIds.length}</dd>
								</div>
								<div>
									<dt>Nós</dt>
									<dd>{visibleProjection.nodes.length}</dd>
								</div>
								<div>
									<dt>Relações</dt>
									<dd>{visibleProjection.edges.length}</dd>
								</div>
							</dl>
						</div>
					)
				) : null}
			</aside>

			<WorldCommandPalette
				open={authoringActive && authoringUi.state.commandPaletteOpen}
				context={commandContext}
				entities={workingProjection.nodes}
				commandIds={PALETTE_COMMAND_IDS}
				onClose={() => authoringUi.setCommandPaletteOpen(false)}
				onCommand={executeWorldCommand}
				onSelectEntity={selectEntityFromPalette}
			/>
		</div>
	);
}
