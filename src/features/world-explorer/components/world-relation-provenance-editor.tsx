"use client";

import { useEffect, useMemo, useState } from "react";
import { relationHasActiveCanonProvenance } from "../relation-provenance-contract";
import {
	loadWorldRelationProvenanceAction,
	replaceWorldRelationProvenanceAction,
	type LoadWorldRelationProvenanceResult,
	type WorldRelationProvenanceFailure,
} from "../world-relation-provenance-actions";
import styles from "./world-content-editor.module.css";

type LoadedProvenance = Extract<LoadWorldRelationProvenanceResult, { ok: true }>;

function failureMessage(reason: WorldRelationProvenanceFailure): string {
	switch (reason) {
		case "unauthenticated":
			return "Sua sessão expirou. Entre novamente para editar a proveniência.";
		case "profile_unresolved":
			return "Não foi possível resolver o perfil ativo para esta campanha.";
		case "forbidden":
			return "É preciso ter permissão de edição de conteúdo e aprovação canônica para alterar estas referências.";
		case "invalid_payload":
			return "A referência enviada não é válida. Recarregue o editor e tente novamente.";
		case "not_persisted":
			return "A relação ainda não foi persistida. Publique-a primeiro como privada ou em revisão.";
		case "review_required":
			return "Uma relação pública ativa precisa manter ao menos uma decisão canônica ativa como fonte.";
		case "dependency_unavailable":
		default:
			return "Não foi possível consultar a proveniência agora. A publicação pública permanece bloqueada.";
	}
}

export function WorldRelationProvenanceEditor({
	relationId,
	onPublicationEligibilityChange,
}: {
	relationId: string;
	onPublicationEligibilityChange: (eligible: boolean) => void;
}) {
	const [provenance, setProvenance] = useState<LoadedProvenance | null>(null);
	const [selectedCanonEntryIds, setSelectedCanonEntryIds] = useState<string[]>([]);
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const [feedback, setFeedback] = useState<string | null>(null);
	const [loadFailure, setLoadFailure] = useState<WorldRelationProvenanceFailure | null>(null);

	useEffect(() => {
		let cancelled = false;
		setLoading(true);
		setLoadFailure(null);
		setFeedback(null);
		setProvenance(null);
		setSelectedCanonEntryIds([]);
		onPublicationEligibilityChange(false);

		void loadWorldRelationProvenanceAction(relationId).then((result) => {
			if (cancelled) return;
			setLoading(false);
			if (!result.ok) {
				setLoadFailure(result.reason);
				return;
			}
			setProvenance(result);
			setSelectedCanonEntryIds([...result.selectedCanonEntryIds]);
		});

		return () => {
			cancelled = true;
		};
	}, [relationId, onPublicationEligibilityChange]);

	const activeCanonEntryIds = useMemo(
		() => provenance?.options.map((option) => option.id) ?? [],
		[provenance],
	);
	const activeCanonEntrySet = useMemo(() => new Set(activeCanonEntryIds), [activeCanonEntryIds]);
	const publicEligible = relationHasActiveCanonProvenance(
		provenance?.persisted === true,
		selectedCanonEntryIds,
		activeCanonEntryIds,
	);
	const staleSourceCount = selectedCanonEntryIds.filter(
		(id) => !activeCanonEntrySet.has(id),
	).length;

	useEffect(() => {
		onPublicationEligibilityChange(publicEligible);
	}, [onPublicationEligibilityChange, publicEligible]);

	async function saveProvenance() {
		if (!provenance?.persisted || saving) return;
		setSaving(true);
		setFeedback(null);
		const replaceResult = await replaceWorldRelationProvenanceAction(
			relationId,
			selectedCanonEntryIds,
		);
		if (!replaceResult.ok) {
			setSaving(false);
			setFeedback(failureMessage(replaceResult.reason));
			return;
		}

		const refreshed = await loadWorldRelationProvenanceAction(relationId);
		setSaving(false);
		if (!refreshed.ok) {
			setProvenance(null);
			setSelectedCanonEntryIds([]);
			setLoadFailure(refreshed.reason);
			setFeedback("As referências foram salvas, mas não foi possível confirmar o estado atualizado. A publicação pública permanece bloqueada.");
			return;
		}
		setLoadFailure(null);
		setProvenance(refreshed);
		setSelectedCanonEntryIds([...refreshed.selectedCanonEntryIds]);
		setFeedback(
			replaceResult.status === "unchanged"
				? "As referências canônicas já estavam atualizadas."
				: `Referências canônicas atualizadas (${replaceResult.sourceCount}).`,
		);
	}

	function toggleCanonEntry(id: string, checked: boolean) {
		setSelectedCanonEntryIds((current) =>
			checked ? [...new Set([...current, id])] : current.filter((item) => item !== id),
		);
		setFeedback(null);
	}

	return (
		<div className={styles.referencePanel} aria-label="Proveniência canônica da ligação">
			<div className={styles.formHeading}>
				<div>
					<span>Proveniência</span>
					<h3>Decisões canônicas</h3>
				</div>
			</div>

			{loading ? <p className={styles.editorHint}>Carregando proveniência…</p> : null}
			{loadFailure ? <div className={styles.emptyCallout}>{failureMessage(loadFailure)}</div> : null}

			{provenance && !provenance.persisted ? (
				<div className={styles.emptyCallout}>
					Esta ligação ainda existe apenas no rascunho. Publique-a primeiro como privada ou em
					revisão; depois anexe uma decisão canônica ativa e só então promova a visibilidade.
				</div>
			) : null}

			{provenance?.persisted && provenance.options.length === 0 ? (
				<div className={styles.emptyCallout}>
					Nenhuma decisão canônica ativa está disponível nesta campanha. A ligação pode continuar
					privada ou em revisão, mas não pode ser promovida ao público.
				</div>
			) : null}

			{provenance?.persisted && provenance.options.length > 0 ? (
				<div className={styles.stack}>
					{provenance.options.map((option) => (
						<label className={styles.checkbox} key={option.id}>
							<input
								type="checkbox"
								checked={selectedCanonEntryIds.includes(option.id)}
								onChange={(event) => toggleCanonEntry(option.id, event.target.checked)}
								disabled={saving}
							/>
							<span>
								<strong>{option.title}</strong>
								<br />
								<small>
									{option.entryType} · {option.visibility}
								</small>
							</span>
						</label>
					))}
					{staleSourceCount > 0 ? (
						<p className={styles.editorHint}>
							{staleSourceCount} referência(s) antiga(s) não contam para publicação e serão removidas
							ao salvar.
						</p>
					) : null}
					<button
						className={styles.primaryButton}
						type="button"
						onClick={() => void saveProvenance()}
						disabled={saving}
					>
						{saving ? "Salvando referências…" : "Salvar referências canônicas"}
					</button>
				</div>
			) : null}

			{feedback ? <p className={styles.editorHint}>{feedback}</p> : null}
			{provenance?.persisted ? (
				<p className={styles.editorHint}>
					{publicEligible
						? "Há proveniência canônica ativa; a visibilidade pública pode ser selecionada no rascunho."
						: "Sem proveniência canônica ativa, a visibilidade pública permanece bloqueada."}
				</p>
			) : null}
		</div>
	);
}
