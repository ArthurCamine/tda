"use client";

import Image from "next/image";
import { useState } from "react";
import { PublicLink } from "@/components/public-link";
import type { WorldGraphProjection, WorldNodeDTO } from "../model";
import { relationLabelFor } from "../projection";
import {
	buildWorldInspectorContext,
	type WorldInspectorConnection,
} from "../world-inspector-context";
import {
	worldEntityMediaObjectPosition,
	worldEntityMediaShouldBypassImageOptimization,
} from "../world-entity-media";
import styles from "./world-explorer.module.css";
import inspectorStyles from "./world-inspector.module.css";

type InspectorTab = "overview" | "relations" | "moments";

function nodeTypeLabel(node: WorldNodeDTO): string {
	if (node.kind === "moment") return "Momento";
	switch (node.entityType) {
		case "pc":
			return "Herói / personagem";
		case "npc":
			return "NPC";
		case "location":
			return "Lugar";
		case "faction":
		case "organization":
			return "Facção / organização";
		case "song":
			return "Música";
		default:
			return "Entidade";
	}
}

function prominenceLabel(node: WorldNodeDTO): string | null {
	switch (node.prominence) {
		case "hero":
			return "Herói no mapa";
		case "primary":
			return "Destaque no mapa";
		case "supporting":
			return "Apoio no mapa";
		case "context":
			return "Contexto no mapa";
		default:
			return null;
	}
}

export function WorldInspectorContent({
	selected,
	projection,
	focus,
	onSelect,
	editing,
}: {
	selected: WorldNodeDTO;
	projection: WorldGraphProjection;
	focus?: WorldNodeDTO;
	onSelect: (id: string) => void;
	editing: boolean;
}) {
	const [tab, setTab] = useState<InspectorTab>("overview");
	const relation =
		focus && selected.id !== focus.id
			? relationLabelFor(projection, selected.id, focus.id)
			: null;
	const context = buildWorldInspectorContext(selected, projection);
	const {
		connections,
		moments,
		characterConnections,
		contextualConnections,
		visibleRelationHighlights,
	} = context;
	const prominence = prominenceLabel(selected);
	const tabs: Array<{ id: InspectorTab; label: string; count?: number }> = [
		{ id: "overview", label: "Visão geral" },
		{ id: "relations", label: "Laços", count: connections.length },
		...(moments.length
			? [{ id: "moments" as const, label: "Momentos", count: moments.length }]
			: []),
	];

	return (
		<>
			<section className={inspectorStyles.identityCard} aria-labelledby={`world-inspector-${selected.id}`}>
				<div className={inspectorStyles.identityMedia} aria-hidden="true">
					{selected.imageUrl ? (
						<Image
							className={inspectorStyles.identityImage}
							src={selected.imageUrl}
							alt=""
							fill
							sizes="520px"
							unoptimized={worldEntityMediaShouldBypassImageOptimization(selected.imageUrl)}
							style={{ objectPosition: worldEntityMediaObjectPosition(selected.imageFocalPoint) }}
						/>
					) : (
						<span className={inspectorStyles.identityInitial}>
							{selected.label.slice(0, 1).toLocaleUpperCase("pt-BR")}
						</span>
					)}
					<span className={inspectorStyles.identityShade} />
				</div>
				<div className={inspectorStyles.identityCopy}>
					<p className={inspectorStyles.identityEyebrow}>{nodeTypeLabel(selected)}</p>
					<h2 id={`world-inspector-${selected.id}`}>{selected.label}</h2>
					{selected.subtitle ? (
						<p className={inspectorStyles.identitySubtitle}>{selected.subtitle}</p>
					) : null}
					<div className={inspectorStyles.identityBadges}>
						{selected.status ? <span>{selected.status}</span> : null}
						{prominence ? <span>{prominence}</span> : null}
						{selected.id === projection.focusId ? <span>Foco atual</span> : null}
					</div>
				</div>
			</section>

			<div
				className={inspectorStyles.tabs}
				role="tablist"
				aria-label={`Detalhes de ${selected.label}`}
			>
				{tabs.map((item) => (
					<button
						key={item.id}
						type="button"
						role="tab"
						aria-selected={tab === item.id}
						aria-controls={`world-inspector-panel-${selected.id}-${item.id}`}
						onClick={() => setTab(item.id)}
					>
						{item.label}
						{typeof item.count === "number" ? <span>{item.count}</span> : null}
					</button>
				))}
			</div>

			{tab === "overview" ? (
				<section
					className={inspectorStyles.tabPanel}
					id={`world-inspector-panel-${selected.id}-overview`}
					role="tabpanel"
					data-inspector-tab="overview"
				>
					{selected.id === projection.focusId ? (
						<p className={styles.focusNote}>Foco exploratório atual.</p>
					) : relation && focus ? (
						<p className={styles.relationSummary}>
							Relação com {focus.label}: {relation}.
						</p>
					) : null}

					<div className={inspectorStyles.summaryBlock}>
						<p className={inspectorStyles.sectionEyebrow}>Contexto público</p>
						<p className={inspectorStyles.summaryCopy}>
							{selected.summary?.trim()
								? selected.summary
								: "Este recorte não traz um resumo narrativo público. Use os laços visíveis para percorrer o contexto disponível sem alterar o foco da URL."}
						</p>
					</div>

					<dl className={inspectorStyles.summaryStats}>
						<div>
							<dt>Laços</dt>
							<dd>{connections.length}</dd>
						</div>
						<div>
							<dt>Personagens</dt>
							<dd>{characterConnections.length}</dd>
						</div>
						<div>
							<dt>Contextos</dt>
							<dd>{contextualConnections}</dd>
						</div>
					</dl>

					{visibleRelationHighlights.length ? (
						<div className={inspectorStyles.relationHighlights}>
							<div className={inspectorStyles.relationHighlightsHeader}>
								<p className={inspectorStyles.sectionEyebrow}>Relações visíveis</p>
								<span>{connections.length}</span>
							</div>
							<div className={inspectorStyles.relationChips}>
								{visibleRelationHighlights.map(({ edge, destination }) => (
									<button
										key={edge.id}
										type="button"
										data-family={edge.family}
										onClick={() => onSelect(destination.id)}
										aria-label={`Explorar relação ${edge.label} com ${destination.label}`}
										title={`${edge.label} · ${destination.label}`}
									>
										{edge.label}
									</button>
								))}
							</div>
						</div>
					) : null}

					{connections.length ? (
						<div className={inspectorStyles.overviewRelations}>
							<h3>Conexões em destaque</h3>
							<ConnectionList connections={connections.slice(0, 4)} onSelect={onSelect} />
						</div>
					) : null}
				</section>
			) : null}

			{tab === "relations" ? (
				<section
					className={inspectorStyles.tabPanel}
					id={`world-inspector-panel-${selected.id}-relations`}
					role="tabpanel"
					data-inspector-tab="relations"
				>
					<div className={inspectorStyles.connectionsHeader}>
						<div>
							<p className={inspectorStyles.sectionEyebrow}>Teia visível</p>
							<h3>Conexões de {selected.label}</h3>
						</div>
						<span>{connections.length}</span>
					</div>
					{connections.length ? (
						<ConnectionList connections={connections} onSelect={onSelect} />
					) : (
						<p className={inspectorStyles.connectionsEmpty}>
							Nenhuma conexão permanece visível com os filtros atuais.
						</p>
					)}
				</section>
			) : null}

			{tab === "moments" ? (
				<section
					className={inspectorStyles.tabPanel}
					id={`world-inspector-panel-${selected.id}-moments`}
					role="tabpanel"
					data-inspector-tab="moments"
				>
					<div className={inspectorStyles.connectionsHeader}>
						<div>
							<p className={inspectorStyles.sectionEyebrow}>Memória conectada</p>
							<h3>Momentos visíveis</h3>
						</div>
						<span>{moments.length}</span>
					</div>
					<ConnectionList connections={moments} onSelect={onSelect} />
				</section>
			) : null}

			{editing ? (
				<p className={styles.focusNote}>
					Finalize ou descarte a edição do layout antes de sair deste mapa.
				</p>
			) : (
				<div className={inspectorStyles.actions}>
					{selected.route ? (
						<PublicLink className={`${styles.profileAction} ${inspectorStyles.primaryAction}`} href={selected.route}>
							Abrir perfil de {selected.label}
						</PublicLink>
					) : null}
					{selected.slug && selected.id !== projection.focusId ? (
						<PublicLink className={styles.focusAction} href={`/mundo?foco=${encodeURIComponent(selected.slug)}`}>
							Explorar conexões de {selected.label}
						</PublicLink>
					) : projection.mode === "focus" ? (
						<PublicLink className={styles.focusAction} href="/mundo">
							Voltar à visão geral
						</PublicLink>
					) : null}
				</div>
			)}

			<section className={inspectorStyles.entityMeta} aria-label={`Entidade no mundo: ${selected.label}`}>
				<p className={inspectorStyles.sectionEyebrow}>Entidade no mundo</p>
				<dl>
					<div>
						<dt>Tipo</dt>
						<dd>{nodeTypeLabel(selected)}</dd>
					</div>
					<div>
						<dt>Perfil público</dt>
						<dd>{selected.route ? "Disponível" : "Sem rota publicada"}</dd>
					</div>
					<div>
						<dt>Conexões visíveis</dt>
						<dd>{connections.length}</dd>
					</div>
					{selected.aliases?.length ? (
						<div>
							<dt>Aliases</dt>
							<dd>{selected.aliases.join(", ")}</dd>
						</div>
					) : null}
				</dl>
			</section>
		</>
	);
}

function ConnectionList({
	connections,
	onSelect,
}: {
	connections: WorldInspectorConnection[];
	onSelect: (id: string) => void;
}) {
	return (
		<ul className={inspectorStyles.connectionList}>
			{connections.map(({ edge, destination }) => (
				<li key={edge.id}>
					<button
						type="button"
						data-family={edge.family}
						onClick={() => onSelect(destination.id)}
						aria-label={`Selecionar ${destination.label}; relação ${edge.label}`}
					>
						<span className={inspectorStyles.connectionCopy}>
							<strong>{destination.label}</strong>
							<small>{nodeTypeLabel(destination)}</small>
						</span>
						<span className={inspectorStyles.relationBadge} data-family={edge.family}>
							{edge.label}
						</span>
						<span className={inspectorStyles.connectionArrow} aria-hidden="true">
							›
						</span>
					</button>
				</li>
			))}
		</ul>
	);
}

export function WorldAccessibleRelations({
	projection,
	selectedId,
	onSelect,
	compact,
}: {
	projection: WorldGraphProjection;
	selectedId: string | null;
	onSelect: (id: string) => void;
	compact: boolean;
}) {
	const nodeById = new Map(projection.nodes.map((node) => [node.id, node]));
	const relations = selectedId
		? projection.edges.filter(
				(edge) => edge.source === selectedId || edge.target === selectedId,
			)
		: projection.edges;
	return (
		<section
			className={`${styles.relationList} ${compact ? styles.relationListCompact : ""}`}
			aria-labelledby="world-relations-title"
		>
			<h2 id="world-relations-title">Relações em lista</h2>
			<p>
				{selectedId
					? "Laços visíveis da seleção atual."
					: "Alternativa textual ao canvas completo."}
			</p>
			{relations.length > 0 ? (
				<ul>
					{relations.map((edge) => {
						const source = nodeById.get(edge.source);
						const target = nodeById.get(edge.target);
						const destination = selectedId === edge.source ? target : source;
						return (
							<li key={edge.id}>
								<button
									type="button"
									onClick={() => destination && onSelect(destination.id)}
								>
									<strong>
										{source?.label ?? edge.source} ↔ {target?.label ?? edge.target}
									</strong>
									<span className={styles.relationLabelText}>{edge.label}</span>
								</button>
							</li>
						);
					})}
				</ul>
			) : (
				<p>Nenhuma relação visível para os filtros atuais.</p>
			)}
		</section>
	);
}
