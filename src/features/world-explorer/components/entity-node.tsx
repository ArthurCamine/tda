"use client";

import Image from "next/image";
import { Handle, NodeToolbar, Position, type NodeProps } from "@xyflow/react";
import {
	memo,
	type CSSProperties,
	type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type { WorldFlowNode } from "../adapters/react-flow";
import {
	WORLD_PORT_LANES,
	type WorldPortSide,
	worldPortHandleId,
} from "../edge-routing";
import type { WorldNodeDTO } from "../model";
import {
	WORLD_AUTHORING_CONNECT_FROM_NODE_EVENT,
	WORLD_AUTHORING_OPEN_INSPECTOR_EVENT,
	type WorldAuthoringConnectFromNodeDetail,
} from "../world-authoring-events";
import {
	worldEntityMediaObjectPosition,
	worldEntityMediaShouldBypassImageOptimization,
} from "../world-entity-media";
import authoringStyles from "./entity-node-authoring.module.css";
import nodeStyles from "./entity-node-v2.module.css";

const SIDES: Array<{ side: WorldPortSide; position: Position }> = [
	{ side: "top", position: Position.Top },
	{ side: "right", position: Position.Right },
	{ side: "bottom", position: Position.Bottom },
	{ side: "left", position: Position.Left },
];

type VisualKind =
	| "hero"
	| "character"
	| "location"
	| "faction"
	| "song"
	| "moment"
	| "context";

function laneStyle(side: WorldPortSide, lane: number): CSSProperties {
	const placement = `${50 + lane * 14}%`;
	return side === "top" || side === "bottom"
		? { left: placement }
		: { top: placement };
}

function initials(label: string): string {
	return label
		.split(/\s+/)
		.slice(0, 2)
		.map((part) => part.charAt(0))
		.join("")
		.toLocaleUpperCase("pt-BR");
}

function visualKind(item: WorldNodeDTO, isHero: boolean): VisualKind {
	if (isHero) return "hero";
	if (item.kind === "moment") return "moment";
	if (item.entityType === "pc" || item.entityType === "npc") return "character";
	if (item.entityType === "location") return "location";
	if (item.entityType === "faction" || item.entityType === "organization") return "faction";
	if (item.entityType === "song") return "song";
	return "context";
}

function visualMark(kind: VisualKind): string {
	switch (kind) {
		case "hero":
			return "✦";
		case "character":
			return "N";
		case "location":
			return "⌖";
		case "faction":
			return "◇";
		case "song":
			return "♪";
		case "moment":
			return "◆";
		default:
			return "·";
	}
}

function stateLabel(isFocus: boolean, selected: boolean): string | null {
	if (isFocus && selected) return "Foco · selecionado";
	if (selected) return "Selecionado";
	if (isFocus) return "Foco";
	return null;
}

function openAuthoringInspector() {
	window.dispatchEvent(new Event(WORLD_AUTHORING_OPEN_INSPECTOR_EVENT));
}

function beginAuthoringConnection(nodeId: string) {
	window.dispatchEvent(
		new CustomEvent<WorldAuthoringConnectFromNodeDetail>(WORLD_AUTHORING_CONNECT_FROM_NODE_EVENT, {
			detail: { nodeId },
		}),
	);
}

function moveToolbarFocus(event: ReactKeyboardEvent<HTMLDivElement>) {
	if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
	const buttons = Array.from(
		event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"),
	).filter((button) => button.offsetParent !== null);
	if (!buttons.length) return;
	const current = Math.max(buttons.indexOf(document.activeElement as HTMLButtonElement), 0);
	let next = current;
	if (event.key === "ArrowRight") next = (current + 1) % buttons.length;
	if (event.key === "ArrowLeft") next = (current - 1 + buttons.length) % buttons.length;
	if (event.key === "Home") next = 0;
	if (event.key === "End") next = buttons.length - 1;
	event.preventDefault();
	event.stopPropagation();
	buttons[next]?.focus();
}

function WorldEntityNodeComponent({ data, selected }: NodeProps<WorldFlowNode>) {
	const { item, isFocus, isHero, prominence, isDimmed, authoringConnectable } = data;
	const kind = visualKind(item, isHero);
	const state = stateLabel(isFocus, selected);
	return (
		<div
			className={`${nodeStyles.entityNode} ${isHero ? nodeStyles.entityNodeHero : ""} ${isFocus ? nodeStyles.entityNodeFocus : ""} ${selected ? nodeStyles.entityNodeSelected : ""} ${isDimmed ? nodeStyles.entityNodeDimmed : ""}`}
			data-world-node={item.id}
			data-prominence={prominence}
			data-node-kind={kind}
		>
			<NodeToolbar isVisible={selected} position={Position.Top} offset={18} align="center">
				<div
					className={authoringStyles.toolbar}
					role="toolbar"
					aria-label={`Ações de ${item.label}`}
					data-world-node-toolbar
					onKeyDown={moveToolbarFocus}
				>
					<button
						className={`${authoringStyles.action} nodrag nopan`}
						type="button"
						tabIndex={0}
						onClick={openAuthoringInspector}
					>
						Editar
					</button>
					<button
						className={`${authoringStyles.action} ${authoringStyles.connectAction} nodrag nopan`}
						type="button"
						tabIndex={-1}
						onClick={() => beginAuthoringConnection(item.id)}
						aria-pressed={authoringConnectable}
					>
						Conectar
					</button>
				</div>
			</NodeToolbar>
			{SIDES.flatMap(({ side, position }) =>
				WORLD_PORT_LANES.flatMap((lane) => {
					const sourceId = worldPortHandleId("source", side, lane);
					const targetId = worldPortHandleId("target", side, lane);
					const style = laneStyle(side, lane);
					const sourceConnectable = authoringConnectable && lane === -1;
					const targetConnectable = authoringConnectable && lane === 1;
					return [
						<Handle
							key={sourceId}
							id={sourceId}
							type="source"
							position={position}
							style={style}
							className={`${nodeStyles.hiddenHandle} ${sourceConnectable ? authoringStyles.sourceHandle : ""}`}
							isConnectable={sourceConnectable}
						/>,
						<Handle
							key={targetId}
							id={targetId}
							type="target"
							position={position}
							style={style}
							className={`${nodeStyles.hiddenHandle} ${targetConnectable ? authoringStyles.targetHandle : ""}`}
							isConnectable={targetConnectable}
						/>,
					];
				}),
			)}
			{state ? (
				<span className={nodeStyles.nodeState} data-node-state aria-hidden="true">
					{state}
				</span>
			) : null}
			<div className={nodeStyles.nodePortrait} aria-hidden="true">
				{item.imageUrl ? (
					<Image
						className={nodeStyles.nodeImage}
						src={item.imageUrl}
						alt=""
						fill
						sizes={isHero ? "116px" : "90px"}
						unoptimized={worldEntityMediaShouldBypassImageOptimization(item.imageUrl)}
						style={{ objectPosition: worldEntityMediaObjectPosition(item.imageFocalPoint) }}
					/>
				) : (
					<span className={nodeStyles.nodeInitials}>{initials(item.label)}</span>
				)}
				<span className={nodeStyles.nodeKindMark}>{visualMark(kind)}</span>
				{isHero ? <i className={nodeStyles.heroOrbit} /> : null}
			</div>
			<div className={nodeStyles.nodeLabel} data-node-label>
				{item.label}
			</div>
			{item.subtitle ? <div className={nodeStyles.nodeSubtitle}>{item.subtitle}</div> : null}
		</div>
	);
}

export const WorldEntityNode = memo(WorldEntityNodeComponent);
