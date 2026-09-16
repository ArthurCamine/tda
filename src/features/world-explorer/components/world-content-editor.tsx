"use client";

import { useMemo, useRef, useState } from "react";
import { relationHasActiveCanonProvenance } from "../relation-provenance-contract";
import type { WorldGraphDraft, WorldVisibility } from "../model";
import { loadWorldRelationProvenanceAction } from "../world-relation-provenance-actions";
import { WorldContentEditor as BaseWorldContentEditor } from "./world-content-editor-base";
import styles from "./world-content-editor.module.css";
import { WorldRelationProvenanceEditor } from "./world-relation-provenance-editor";

function isPublicVisibility(visibility: WorldVisibility | undefined): boolean {
	return visibility === "public_campaign" || visibility === "public_web";
}

function relationLabel(draft: WorldGraphDraft, relationId: string): string {
	const edge = draft.edges.find((item) => item.id === relationId);
	if (!edge) return "Ligação";
	const source = draft.nodes.find((node) => node.id === edge.source)?.name ?? "?";
	const target = draft.nodes.find((node) => node.id === edge.target)?.name ?? "?";
	const type = draft.relationTypes.find((item) => item.slug === edge.relationType);
	return `${source} ${type?.direction === "directed" ? "→" : "↔"} ${target} · ${edge.labelOverride ?? type?.label ?? edge.relationType}`;
}

export function WorldContentEditor({
	draft,
	selectedId,
	onDraftChange,
	onSelect,
}: {
	draft: WorldGraphDraft;
	selectedId: string | null;
	onDraftChange: (draft: WorldGraphDraft, message?: string) => void;
	onSelect: (id: string | null) => void;
}) {
	const draftRef = useRef(draft);
	draftRef.current = draft;
	const [provenanceRelationId, setProvenanceRelationId] = useState<string | null>(null);
	const [gateMessage, setGateMessage] = useState<string | null>(null);
	const activeRelations = useMemo(
		() => draft.edges.filter((edge) => edge.status !== "archived"),
		[draft.edges],
	);
	const selectedProvenanceRelation = provenanceRelationId
		? activeRelations.find((edge) => edge.id === provenanceRelationId) ?? null
		: null;

	function handleDraftChange(nextDraft: WorldGraphDraft, message?: string) {
		const visibilityChange = nextDraft.edges.find((nextEdge) => {
			if (!isPublicVisibility(nextEdge.visibility)) return false;
			const previous = draft.edges.find((edge) => edge.id === nextEdge.id);
			return previous?.visibility !== nextEdge.visibility;
		});
		if (!visibilityChange) {
			setGateMessage(null);
			onDraftChange(nextDraft, message);
			return;
		}

		const previous = draft.edges.find((edge) => edge.id === visibilityChange.id);
		if (!previous) {
			setGateMessage(
				"Ligação nova não pode nascer pública. Crie-a como privada ou em revisão, publique o rascunho, anexe uma decisão canônica ativa e depois promova a visibilidade.",
			);
			return;
		}

		setGateMessage("Validando proveniência canônica salva…");
		void loadWorldRelationProvenanceAction(visibilityChange.id).then((result) => {
			if (!result.ok) {
				setGateMessage(
					"Não foi possível confirmar a proveniência canônica. A promoção pública foi bloqueada.",
				);
				return;
			}
			const eligible = relationHasActiveCanonProvenance(
				result.persisted,
				result.selectedCanonEntryIds,
				result.options.map((option) => option.id),
			);
			if (!eligible) {
				setGateMessage(
					"Visibilidade pública bloqueada: esta ligação precisa de ao menos uma decisão canônica ativa salva como proveniência.",
				);
				return;
			}

			const latestDraft = draftRef.current;
			const stillExists = latestDraft.edges.some((edge) => edge.id === visibilityChange.id);
			if (!stillExists) {
				setGateMessage("A ligação mudou enquanto a proveniência era validada. Tente novamente.");
				return;
			}
			setGateMessage(null);
			onDraftChange(
				{
					...latestDraft,
					edges: latestDraft.edges.map((edge) =>
						edge.id === visibilityChange.id
							? { ...edge, visibility: visibilityChange.visibility }
							: edge,
					),
				},
				message,
			);
		});
	}

	return (
		<>
			<BaseWorldContentEditor
				draft={draft}
				selectedId={selectedId}
				onDraftChange={handleDraftChange}
				onSelect={onSelect}
			/>

			{gateMessage ? <div className={styles.emptyCallout}>{gateMessage}</div> : null}

			{activeRelations.length ? (
				<section className={styles.editor} aria-label="Proveniência das ligações do Mundo">
					<div className={styles.formHeading}>
						<div>
							<span>Revisão canônica</span>
							<h3>Proveniência das ligações</h3>
						</div>
					</div>
					<p className={styles.editorHint}>
						Escolha uma ligação persistida, anexe decisões canônicas ativas e salve. Só depois a
						promoção para público será aceita pelo editor e pelo guard transacional do banco.
					</p>
					<div className={styles.listBlock}>
						<ul>
							{activeRelations.map((edge) => (
								<li key={edge.id}>
									<button
										type="button"
										onClick={() => setProvenanceRelationId(edge.id)}
										aria-pressed={provenanceRelationId === edge.id}
									>
										<strong>{relationLabel(draft, edge.id)}</strong>
										<span>{edge.visibility}</span>
									</button>
								</li>
							))}
						</ul>
					</div>
					{selectedProvenanceRelation ? (
						<WorldRelationProvenanceEditor
							key={selectedProvenanceRelation.id}
							relationId={selectedProvenanceRelation.id}
							onPublicationEligibilityChange={() => undefined}
						/>
					) : (
						<div className={styles.emptyCallout}>
							Selecione uma ligação acima para consultar e editar suas referências canônicas.
						</div>
					)}
				</section>
			) : null}
		</>
	);
}
