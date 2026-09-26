"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status";
import {
	PublicationClientError,
	readCurrentPublication,
	preflightApprovedLocalReview,
	type PublicationReceiptView,
} from "./publication-client";
import type {
	LocalReview,
	LocalReviewSegment,
	LocalReviewStatus,
	LocalRunSummary,
} from "./protocol";
import styles from "./local-review.module.css";
import { ReviewConflicts } from "./review-conflicts";
import { prepareReviewRebase, resolveReviewRebase, type ReviewRebase } from "./review-rebase";
import { ParticipantManager } from "./participant-manager";
import { applyParticipantRename } from "./participant-rename";
import { countWordsV1, isReviewStringV1 } from "../../transcript-review/text-contract";
import { localRunKey, serializeLocalRunKey } from "./local-run-key";

type Props = Readonly<{
	runs: readonly LocalRunSummary[];
	review: LocalReview | null;
	busy: boolean;
	error: string | null;
	publicationEnabled: boolean;
	onOpen: (sourceId: string, runId: string) => void | Promise<void>;
	onSave: (
		baseline: LocalReview,
		status: LocalReviewStatus,
		segments: readonly LocalReviewSegment[],
	) => void | Promise<void>;
	onLoadLatest?: () => Promise<LocalReview>;
	onRepairTarget?: () => void | Promise<void>;
	onClose: () => void;
	onPublish: (
		review: LocalReview,
		operationId: string,
		expectedCurrentRevisionId: string | null,
	) => Promise<PublicationReceiptView>;
}>;

const PAGE_SIZE = 25;

function formatDate(value: string | null): string {
	if (!value) return "data desconhecida";
	return new Date(value).toLocaleString("pt-BR", {
		day: "2-digit",
		month: "short",
		year: "numeric",
		hour: "2-digit",
		minute: "2-digit",
	});
}

function formatSeconds(value: number | null): string {
	if (value === null) return "—";
	const seconds = Math.round(value);
	const hours = Math.floor(seconds / 3600);
	const minutes = Math.floor((seconds % 3600) / 60);
	const rest = seconds % 60;
	return hours
		? `${hours}h ${String(minutes).padStart(2, "0")}m`
		: minutes
			? `${minutes}m ${String(rest).padStart(2, "0")}s`
			: `${rest}s`;
}

function formatTimestamp(value: number): string {
	const seconds = Math.max(0, Math.floor(value));
	const hours = Math.floor(seconds / 3600);
	const minutes = Math.floor((seconds % 3600) / 60);
	const rest = seconds % 60;
	return [hours, minutes, rest].map((part) => String(part).padStart(2, "0")).join(":");
}

function formatRealtime(rtf: number | null): string {
	if (rtf === null || rtf <= 0) return "—";
	const speed = 1 / rtf;
	return `${speed >= 10 ? speed.toFixed(1) : speed.toFixed(2)}×`;
}

function formatRunExecution(run: LocalRunSummary): string {
	const values = [run.device, run.computeType, run.alignment].filter(Boolean);
	return values.length ? values.join(" · ") : "execução não registrada";
}

function formatVram(value: number | null | undefined): string {
	if (value === null || value === undefined) return "—";
	return `${(value / 1024 ** 3).toFixed(1)} GiB`;
}

function formatRuntime(run: LocalRunSummary): string {
	const lineage = run.executionLineage;
	if (!lineage) return "—";
	const runtime = [lineage.runtimeFamily, lineage.runtimeVersion]
		.filter(Boolean)
		.join(" ");
	return runtime || lineage.companionVersion
		? [runtime || null, lineage.companionVersion ? `Companion ${lineage.companionVersion}` : null]
				.filter(Boolean)
				.join(" · ")
		: "—";
}

function reviewError(code: string | null): string | null {
	if (!code) return null;
	return {
		PUBLICATION_TARGET_PROVENANCE_UNAVAILABLE: "A origem original não está disponível. Restaure um backup completo; nenhum destino foi inferido.",
		PUBLICATION_TARGET_PROVENANCE_MISMATCH: "A origem e o run divergem. O reparo foi bloqueado e seus arquivos foram preservados.",
		PUBLICATION_TARGET_CONFLICT: "Existe um vínculo divergente. O reparo não troca a sessão de destino.",
		LOCAL_REVIEW_DRAFT_CONFLICT:
			"Este draft mudou em outra aba ou processo. Suas alterações continuam nesta tela. Compare com a versão mais recente para continuar sem descartar seu trabalho.",
		LOCAL_REVIEW_WRITE_UNCONFIRMED:
			"A gravação pode ter ocorrido, mas não foi possível confirmar sua persistência. Preserve o texto e confira a revisão salva antes de tentar novamente.",
		LOCAL_REVIEW_SNAPSHOT_CONTRACT_REQUIRED:
			"Atualize o Companion e a página para salvar revisões com verificação de conteúdo.",
		LOCAL_REVIEW_SEGMENT_TEXT_INVALID:
			"O texto contém caracteres inválidos ou excede o limite de 100.000 caracteres. Corrija antes de salvar.",
		LOCAL_REVIEW_SEGMENT_SPEAKER_INVALID:
			"O nome do participante contém caracteres inválidos ou excede o limite de 160 caracteres. Corrija antes de salvar.",
		LOCAL_REVIEW_LEGACY_STRING_REPAIR_REQUIRED:
			"Esta revisão antiga contém caracteres incompatíveis. O arquivo foi preservado e precisa de reparo local explícito; consulte o procedimento de reparo de revisão.",
		LOCAL_REVIEW_BASE_RUN_INVALID:
			"O run bruto não passou na verificação de integridade. Ele não foi alterado.",
		LOCAL_REVIEW_APPROVAL_REQUIRES_SAVED_DRAFT:
			"Salve primeiro as alterações desta revisão. A aprovação só pode ser aplicada ao draft exato já persistido.",
		LOCAL_REVIEW_RUN_NOT_VISIBLE:
			"Este run não está mais elegível para revisão.",
		LOCAL_REVIEW_REQUEST_TOO_LARGE:
			"O request da revisão excede o limite local de 32 MiB. Seu texto nesta tela foi preservado.",
		LOCAL_REVIEW_DRAFT_TOO_LARGE:
			"O draft serializado excede o limite local de 32 MiB. Reduza o conteúdo antes de salvar novamente.",
		payload_too_large:
			"O draft excede o limite local de 32 MiB.",
		timeout:
			"O Companion demorou demais para responder. Seu draft local nesta tela foi preservado.",
		unreachable:
			"O Companion ficou indisponível. Seu draft nesta tela foi preservado.",
		invalid_response:
			"O Companion respondeu com um contrato de revisão inválido.",
	}[code] ?? `Não foi possível concluir a revisão local · ${code}`;
}

function RunCard({
	run,
	busy,
	onOpen,
}: Readonly<{
	run: LocalRunSummary;
	busy: boolean;
	onOpen: () => void;
}>) {
	const model = [run.engine, run.model].filter(Boolean).join(" · ") || "modelo desconhecido";
	return (
		<article className={styles.runCard}>
			<div className={styles.runHeader}>
				<div>
					<span className={styles.eyebrow}>Resultado local</span>
					<h3>{run.profileId}</h3>
				</div>
				<StatusPill tone="success">Concluído</StatusPill>
			</div>
			<p className={styles.runModel}>
				{model}
				{run.modelRevision ? ` · rev ${run.modelRevision}` : ""}
				{" · "}
				{formatRunExecution(run)}
			</p>
			<dl className={styles.runFacts}>
				<div><dt>Concluído</dt><dd>{formatDate(run.completedAt)}</dd></div>
				<div><dt>Duração da sessão</dt><dd>{formatSeconds(run.stats.sessionDurationSeconds)}</dd></div>
				<div><dt>Trabalho de áudio</dt><dd>{formatSeconds(run.stats.audioWorkSeconds)}</dd></div>
				<div><dt>Processamento</dt><dd>{formatSeconds(run.stats.processingSeconds)}</dd></div>
				<div><dt>Velocidade</dt><dd>{formatRealtime(run.stats.rtf)}</dd></div>
				<div><dt>RTF</dt><dd>{run.stats.rtf === null ? "—" : run.stats.rtf.toFixed(3)}</dd></div>
				<div><dt>Palavras</dt><dd>{run.stats.wordCount ?? "—"}</dd></div>
				<div><dt>Segmentos</dt><dd>{run.stats.segmentCount ?? "—"}</dd></div>
				<div><dt>Turnos</dt><dd>{run.stats.turnCount ?? "—"}</dd></div>
				<div><dt>Tracks</dt><dd>{run.stats.trackCount ?? "—"}</dd></div>
				<div><dt>Deduplicados</dt><dd>{run.stats.deduplicatedSegmentCount ?? "—"}</dd></div>
				<div><dt>Warnings</dt><dd>{run.stats.warningCount ?? "—"}</dd></div>
				<div><dt>GPU</dt><dd>{run.executionLineage?.gpu?.model ?? "—"}</dd></div>
				<div><dt>VRAM</dt><dd>{formatVram(run.executionLineage?.gpu?.vramTotalBytes)}</dd></div>
				<div><dt>Runtime</dt><dd>{formatRuntime(run)}</dd></div>
				<div><dt>Compute capability</dt><dd>{run.executionLineage?.gpu?.computeCapability ?? "—"}</dd></div>
			</dl>
			<div className={styles.runIdentity}>
				<span title={run.sourceId}>Fonte {run.sourceId.slice(0, 22)}…</span>
				<span title={run.transcriptSha256}>SHA {run.transcriptSha256.slice(0, 12)}…</span>
				{run.publicationTarget ? (
					<span>
						Destino {run.publicationTarget.campaignSlug} · sessão{" "}
						{run.publicationTarget.sourceSessionId}
					</span>
				) : (
					<span>Sem destino cloud vinculado</span>
				)}
			</div>
			<Button size="sm" variant="primary" disabled={busy} onClick={onOpen}>
				Revisar resultado
			</Button>
		</article>
	);
}

function ReviewEditor({
	review,
	busy,
	error,
	onSave,
	onClose,
	publicationEnabled,
	onPublish,
	onRepairTarget,
	onLoadLatest,
}: Readonly<{
	review: LocalReview;
	busy: boolean;
	error: string | null;
	onSave: Props["onSave"];
	onClose: () => void;
	publicationEnabled: boolean;
	onPublish: Props["onPublish"];
	onRepairTarget: Props["onRepairTarget"];
	onLoadLatest: Props["onLoadLatest"];
}>) {
    const scrollAnchor = useRef<{ key: string; top: number } | null>(null);
    const restoreAnchor = useRef(false);
    const [baseline, setBaseline] = useState(review);
    const [comparison, setComparison] = useState<ReviewRebase | null>(null);
    const [comparing, setComparing] = useState(false);
    const [comparisonError, setComparisonError] = useState<string | null>(null);
	const [segments, setSegments] = useState<LocalReviewSegment[]>(() =>
		review.segments.map((segment) => ({ ...segment })),
	);
    useLayoutEffect(() => {
        if (!restoreAnchor.current || !scrollAnchor.current || segments.length === 0) return;
        restoreAnchor.current = false;
        const anchor = scrollAnchor.current;
        const row = Array.from(document.querySelectorAll<HTMLElement>("[data-review-segment]")).find((node) => node.dataset.reviewSegment === anchor.key);
        if (row) window.scrollBy(0, row.getBoundingClientRect().top - anchor.top);
    }, [segments]);
	const [status, setStatus] = useState<LocalReviewStatus>(review.status);
	const [dirty, setDirty] = useState(false);
	const [query, setQuery] = useState("");
	const [page, setPage] = useState(0);
	const [publicationCurrent, setPublicationCurrent] = useState<{ actorProfileId: string; revisionId: string | null } | null>(null);
	const [publishConfirmation, setPublishConfirmation] = useState(false);
	const [publishOperationId, setPublishOperationId] = useState<string | null>(null);
	const [publishing, setPublishing] = useState(false);
    const editingBlocked = busy || comparing || comparison !== null || publishing;
	const [publicationError, setPublicationError] = useState<string | null>(null);
	const [publicationReceipt, setPublicationReceipt] =
		useState<PublicationReceiptView | null>(null);
	const canSave = review.snapshotContract === "tda_local_review_cas_v1";
	const ephemeral = review.persistence === "ephemeral_base";
	const invalidStrings = segments.some((segment) => !isReviewStringV1(segment.text, "text") || !isReviewStringV1(segment.speaker, "speaker"));
	const publicationPreflight = useMemo(
		() =>
			publicationEnabled &&
			review.publicationTarget &&
			review.status === "approved_local" &&
			!dirty
				? preflightApprovedLocalReview(review)
				: null,
		[dirty, publicationEnabled, review],
	);

	useEffect(() => {
		if (!dirty) return;
		const beforeUnload = (event: BeforeUnloadEvent) => {
			event.preventDefault();
		};
		window.addEventListener("beforeunload", beforeUnload);
		return () => window.removeEventListener("beforeunload", beforeUnload);
	}, [dirty]);

	const filtered = useMemo(() => {
		const normalized = query.trim().toLocaleLowerCase("pt-BR");
		return segments
			.map((segment, index) => ({ segment, index }))
			.filter(({ segment }) =>
				!normalized
					? true
					: `${segment.speaker} ${segment.text}`
							.toLocaleLowerCase("pt-BR")
							.includes(normalized),
			);
	}, [query, segments]);
	const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
	const safePage = Math.min(page, pageCount - 1);
	const visible = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);
	const reviewed = segments.filter((segment) => segment.reviewed).length;
	const words = segments.reduce(
		(total, segment) =>
			total + countWordsV1(segment.text),
		0,
	);
	const participants = new Set(segments.map((segment) => segment.speaker)).size;

	function patch(index: number, value: Partial<LocalReviewSegment>) {
		if (status === "approved_local") setStatus("reviewed");
		setSegments((current) =>
			current.map((segment, candidate) =>
				candidate === index ? { ...segment, ...value } : segment,
			),
		);
		setDirty(true);
	}

	function attemptClose() {
		if (
			dirty &&
			!window.confirm(
				"Há alterações locais ainda não salvas. Fechar a revisão e descartá-las desta tela?",
			)
		)
			return;
		onClose();
	}
	function publicationErrorMessage(code: string): string {
		return {
			unauthenticated: "Sua sessão Web expirou. Entre novamente antes de publicar.",
			forbidden: "Seu acesso não permite publicar transcrições nesta campanha.",
			publish_capability_undefined:
				"A publicação ainda não está ativada para esta campanha.",
			approved_review_required:
				"Salve esta revisão como Aprovado localmente antes de publicar.",
			invalid_payload:
				"O servidor recusou o vínculo ou o conteúdo desta revisão.",
			too_large: "A revisão excede o limite aceito para publicação.",
			not_found:
				"A sessão vinculada não foi localizada no escopo autorizado.",
			stale_current: "A revisão publicada mudou. Consulte novamente e confirme a substituição antes de publicar.",
			conflict:
				"Esta operação conflita com uma publicação já registrada. Recarregue antes de continuar.",
			dependency_unavailable:
				"O serviço de publicação está indisponível e não confirmou nenhuma alteração.",
			unconfirmed:
				"A resposta foi perdida e o readback ainda não confirmou o commit. Repetir reutilizará a mesma operação.",
		}[code] ?? `Publicação não confirmada · ${code}`;
	}

	async function preparePublicationConfirmation() {
        setPublishing(true); setPublicationError(null);
        try {
            // Keep a lost-response retry frozen to its original expected pointer.
            if (!publishOperationId || !publicationCurrent) setPublicationCurrent(await readCurrentPublication(review));
            setPublishConfirmation(true);
        } catch (cause) { setPublicationError(publicationErrorMessage(cause instanceof PublicationClientError ? cause.code : "dependency_unavailable")); }
        finally { setPublishing(false); }
    }

	async function confirmPublication() {
		if (
			publishing || !publicationCurrent ||
			dirty ||
			review.status !== "approved_local" ||
			!review.publicationTarget ||
			publicationPreflight?.eligible !== true
		)
			return;
		const operationId = publishOperationId ?? crypto.randomUUID();
		setPublishOperationId(operationId);
		setPublishing(true);
		setPublicationError(null);
		try {
			const receipt = await onPublish(review, operationId, publicationCurrent.revisionId);
			setPublicationReceipt(receipt);
			setPublishConfirmation(false);
			setPublishOperationId(null);
		} catch (cause) {
			const code =
				cause instanceof PublicationClientError
					? cause.code
					: "dependency_unavailable";
			if (code === "stale_current") { setPublicationCurrent(null); setPublishOperationId(null); }
			setPublicationError(publicationErrorMessage(code));
			setPublishConfirmation(false);
		} finally {
			setPublishing(false);
		}
	}

	return (
		<section className={styles.editor} aria-labelledby="local-review-title">
			<div className={styles.editorHeader}>
				<div>
					<span className={styles.eyebrow}>Revisão local derivada</span>
					<h2 id="local-review-title">{review.lineage.profileId}</h2>
					<p>
						Run bruto imutável · {ephemeral ? "Sem revisão salva" : `draft r${review.draftRevision}`} · SHA{" "}
						{review.baseTranscriptSha256.slice(0, 12)}…
					</p>
				</div>
				<div className={styles.headerActions}>
					<Button size="sm" variant="tertiary" disabled={busy || publishing} onClick={attemptClose}>
						Voltar aos resultados
					</Button>
					<Button
						size="sm"
						variant="primary"
						disabled={editingBlocked || !dirty || !canSave || invalidStrings}
						onClick={() => void onSave(baseline, status, segments)}
					>
						{busy ? "Salvando…" : "Salvar revisão"}
					</Button>
					{publicationEnabled && review.publicationTarget ? (
						<Button
							size="sm"
							variant="primary"
							disabled={
								editingBlocked || error === "LOCAL_REVIEW_DRAFT_CONFLICT" ||
								publishing ||
								dirty ||
								review.status !== "approved_local" ||
								Boolean(publicationReceipt)
							}
							onClick={() => void preparePublicationConfirmation()}
						>
							{publicationReceipt
								? `Publicado · r${publicationReceipt.revisionNumber}`
								: publishing
									? "Publicando…"
									: "Publicar no TDA"}
						</Button>
					) : null}
				</div>
			</div>

			{!canSave ? <p role="status">Atualize o Companion para salvar revisões com verificação de conteúdo. A leitura continua disponível.</p> : null}
			<div className={styles.reviewNotice}>
				<strong>Nada será publicado automaticamente.</strong>
				<span>
					{review.publicationTarget
						? `Destino vinculado: ${review.publicationTarget.campaignSlug} · sessão ${review.publicationTarget.sourceSessionId}. ${publicationEnabled ? "Somente a confirmação explícita abaixo pode publicar este draft salvo." : "A publicação cloud continua desativada neste ambiente."}`
						: "O destino cloud está indisponível. A revisão continua local e só pode ser publicada com um vínculo verificado."}
				</span>
			</div>

			{publicationPreflight && !publicationPreflight.eligible ? (
				<p className={styles.error} role="status">
					{publicationPreflight.reason === "too_large"
						? `Aprovado localmente, mas a publicação está indisponível: payload canônico ${publicationPreflight.payloadBytes?.toLocaleString("pt-BR") ?? "acima do limite"} bytes / ${publicationPreflight.maxPayloadBytes.toLocaleString("pt-BR")} bytes.`
						: "Aprovado localmente, mas este snapshot não passa no contrato atual de publicação. Salve/reabra a revisão antes de tentar publicar."}
				</p>
			) : publicationPreflight?.eligible ? (
				<p className={styles.saved} role="status">
					Publicação compatível · payload canônico {publicationPreflight.payloadBytes?.toLocaleString("pt-BR")} / {publicationPreflight.maxPayloadBytes.toLocaleString("pt-BR")} bytes.
				</p>
			) : null}

            {!review.publicationTarget && onRepairTarget ? (
                <div className={styles.notice}>
                    <p>{review.publicationTargetState === "invalid" ? "O vínculo de publicação está danificado." : "O destino de publicação não está disponível."} O reparo usa somente a origem verificada. Sem essa prova, o Companion mantém a publicação bloqueada.</p>
                    <Button type="button" variant="secondary" disabled={busy || dirty || publishing} onClick={() => void onRepairTarget()}>Reparar vínculo original</Button>
                    {dirty ? <p>Salve suas alterações antes de reparar o vínculo.</p> : null}
                </div>
            ) : null}
			{publishConfirmation && review.publicationTarget ? (
				<section
					className={styles.publishConfirmation}
					role="alertdialog"
					aria-labelledby="publication-confirmation-title"
					aria-describedby="publication-confirmation-detail"
				>
					<div>
						<span className={styles.eyebrow}>Confirmação editorial</span>
						<h3 id="publication-confirmation-title">Publicar esta revisão no TDA?</h3>
						<p id="publication-confirmation-detail">
							Será publicada a revisão salva <strong>r{review.draftRevision}</strong> com{" "}
							<strong>{review.segments.length} segmentos</strong> em{" "}
							<strong>{review.publicationTarget.campaignSlug}</strong> · sessão{" "}
							<strong>{review.publicationTarget.sourceSessionId}</strong>.
							O run bruto continuará imutável.
						</p>
						<p>Revisão atualmente publicada: {publicationCurrent?.revisionId ?? "nenhuma"}. A publicação será recusada se esse estado mudar.</p>
						<small>
							Base SHA {review.baseTranscriptSha256.slice(0, 12)}… · draft SHA{" "}
							{review.draftSha256?.slice(0, 12)}…
						</small>
					</div>
					<div className={styles.publishActions}>
						<Button
							size="sm"
							variant="tertiary"
							disabled={publishing}
							onClick={() => setPublishConfirmation(false)}
						>
							Cancelar
						</Button>
						<Button
							size="sm"
							variant="primary"
							disabled={publishing}
							onClick={() => void confirmPublication()}
						>
							{publishing ? "Publicando…" : "Confirmar publicação"}
						</Button>
					</div>
				</section>
			) : null}

			{publicationError ? (
				<p className={styles.error} role="alert">{publicationError}</p>
			) : null}
			{publicationReceipt ? (
				<p className={styles.published} role="status">
					Publicação confirmada · revisão cloud {publicationReceipt.revisionNumber} · receipt{" "}
					{publicationReceipt.receiptId.slice(0, 12)}…
				</p>
			) : null}

			<div className={styles.summaryGrid}>
				<div><span>Revisão</span><strong>{reviewed} / {segments.length}</strong><small>{segments.length ? Math.round((reviewed / segments.length) * 100) : 100}%</small></div>
				<div><span>Palavras</span><strong>{words}</strong><small>{review.review.editedSegments} segmentos alterados no último save</small></div>
				<div><span>Participantes</span><strong>{participants}</strong><small>{review.stats.trackCount ?? "—"} tracks</small></div>
				<div><span>Duração</span><strong>{formatSeconds(review.stats.sessionDurationSeconds)}</strong><small>Processamento {formatSeconds(review.stats.processingSeconds)}</small></div>
				<div><span>Avisos</span><strong>{review.review.warningCount}</strong><small>{review.warningSummary ? "atalhos de atenção, não veredictos" : "total histórico não verificado"}</small></div>
				<div>
					<span>Hardware</span>
					<strong>{review.lineage.executionLineage?.gpu?.model ?? review.lineage.device ?? "—"}</strong>
					<small>
						{[
							review.lineage.executionLineage?.runtimeFamily,
							review.lineage.executionLineage?.runtimeVersion,
							review.lineage.computeType,
							review.lineage.alignment,
						]
							.filter(Boolean)
							.join(" · ") || "desconhecido"}
					</small>
				</div>
			</div>

			{review.warnings.length ? (
				<details className={styles.warnings}>
					<summary>{review.review.warningCount} avisos do pipeline · mostrando {Math.min(new Set(review.warnings).size, 50)} tipos{review.warningSummary?.truncated ? ` dos primeiros ${review.warningSummary.displayedCount} avisos` : ""}</summary>
					<ul>
						{Array.from(new Set(review.warnings)).slice(0, 50).map((warning) => (
							<li key={warning}>{warning}</li>
						))}
					</ul>
				</details>
			) : null}

            <ParticipantManager segments={segments} disabled={editingBlocked || publishing || !canSave} onApply={(intent) => {
                const next = applyParticipantRename(segments, intent);
                if (next === segments) return;
                setSegments([...next]);
                if (status === "approved_local") setStatus("reviewed");
                setDirty(true);
                setPublishConfirmation(false);
            }} />
            <div className={styles.reviewToolbar}>
				<label>
					<span>Estado do draft</span>
					<select
						value={status}
						disabled={editingBlocked || !canSave}
						onChange={(event) => {
							setStatus(event.target.value as LocalReviewStatus);
							setDirty(true);
						}}
					>
						<option value="draft">Draft</option>
						<option value="reviewed">Revisado</option>
						<option value="approved_local">Aprovado localmente</option>
					</select>
				</label>
				<label className={styles.search}>
					<span>Filtrar falas</span>
					<input
						value={query}
						onChange={(event) => {
							setQuery(event.target.value);
							setPage(0);
						}}
						placeholder="Speaker ou texto…"
					/>
				</label>
				<div className={styles.pageControls}>
					<Button
						size="sm"
						variant="tertiary"
						disabled={safePage === 0}
						onClick={() => setPage((current) => Math.max(0, current - 1))}
					>
						Anterior
					</Button>
					<span>{safePage + 1} / {pageCount}</span>
					<Button
						size="sm"
						variant="tertiary"
						disabled={safePage >= pageCount - 1}
						onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
					>
						Próxima
					</Button>
				</div>
			</div>

            {error === "LOCAL_REVIEW_DRAFT_CONFLICT" && onLoadLatest ? <Button type="button" disabled={editingBlocked || publishing} onClick={async () => {
                const anchor = Array.from(document.querySelectorAll<HTMLElement>("[data-review-segment]")).find((node) => { const rect = node.getBoundingClientRect(); return rect.bottom > 0 && rect.top < window.innerHeight; });
                scrollAnchor.current = anchor ? { key: anchor.dataset.reviewSegment ?? "", top: anchor.getBoundingClientRect().top } : null;
                setComparing(true); setComparisonError(null);
                try {
                    const latest = await onLoadLatest();
                    setComparison(prepareReviewRebase(baseline, segments, status, latest));
                } catch {
                    setComparisonError("Não foi possível comparar uma revisão compatível. Suas alterações continuam intactas.");
                } finally { setComparing(false); }
            }}>Comparar com versão mais recente</Button> : null}
            {comparisonError ? <p role="alert">{comparisonError}</p> : null}
            {comparison ? <ReviewConflicts plan={comparison} onCancel={() => setComparison(null)} onApply={(choices) => {
                if (segments !== comparison.working) { setComparisonError("O draft mudou durante a comparação. Compare novamente."); setComparison(null); return; }
                const result = resolveReviewRebase(comparison, choices);
                restoreAnchor.current = true;
                setBaseline(comparison.latest);
                setSegments(result.segments);
                setStatus(result.status);
                setDirty(true);
                setPublicationReceipt(null);
                setPublishOperationId(null);
                setPublishConfirmation(false);
                setComparison(null);
            }} /> : null}
            {baseline !== review ? <p role="status">Reconciliado sobre a revisão {baseline.draftRevision}. Alterações ainda não salvas; aprovação nova necessária após salvar.</p> : null}
			{reviewError(error) ? (
				<p className={styles.error} role="alert">{reviewError(error)}</p>
			) : null}
			{invalidStrings ? <p className={styles.error} role="alert">Corrija os campos destacados: texto com até 100.000 caracteres e participante com até 160, sem controles incompatíveis.</p> : null}
			{dirty ? (
				<p className={styles.unsaved} role="status">Alterações não salvas neste draft.</p>
			) : (
				<p className={styles.saved} role="status">{ephemeral ? "Visualização da base. Nenhuma revisão foi salva." : "Draft salvo localmente."}</p>
			)}

			<div className={styles.segmentList}>
				{visible.map(({ segment, index }) => (
					<article
						className={styles.segment}
						data-review-segment={JSON.stringify([segment.trackNumber, segment.segmentId])}
						key={`${segment.trackNumber}-${segment.segmentId}`}
					>
						<div className={styles.segmentMeta}>
							<span>Track {segment.trackNumber}</span>
							<span>{formatTimestamp(segment.start)} → {formatTimestamp(segment.end)}</span>
							<label className={styles.reviewed}>
								<input
									type="checkbox"
									checked={segment.reviewed}
									disabled={editingBlocked || !canSave}
									onChange={(event) => patch(index, { reviewed: event.target.checked })}
								/>
								Revisado
							</label>
						</div>
						<label>
							<span>Speaker</span>
							<input
								value={segment.speaker}
								maxLength={320}
								aria-invalid={!isReviewStringV1(segment.speaker, "speaker")}
								disabled={editingBlocked || !canSave}
								onChange={(event) => patch(index, { speaker: event.target.value })}
							/>
						</label>
						<label>
							<span>Texto</span>
							<textarea
								value={segment.text}
								maxLength={200_000}
								aria-invalid={!isReviewStringV1(segment.text, "text")}
								disabled={editingBlocked || !canSave}
								onChange={(event) => patch(index, { text: event.target.value })}
							/>
						</label>
					</article>
				))}
				{visible.length === 0 ? (
					<p className={styles.empty}>Nenhuma fala corresponde ao filtro.</p>
				) : null}
			</div>
		</section>
	);
}

export function LocalReviewWorkspace({
	runs,
	review,
	busy,
	error,
	publicationEnabled,
	onOpen,
	onSave,
	onClose,
	onPublish,
	onRepairTarget,
	onLoadLatest,
}: Props) {
	if (review) {
		return (
			<ReviewEditor
				key={`${review.sourceId}:${review.runId}:${review.draftSha256 ?? review.baseTranscriptSha256}:${review.approvedAt ?? "unapproved"}`}
				review={review}
				busy={busy}
				error={error}
				onSave={onSave}
				onClose={onClose}
				publicationEnabled={publicationEnabled}
				onLoadLatest={onLoadLatest}
				onRepairTarget={onRepairTarget}
				onPublish={onPublish}
			/>
		);
	}

	return (
		<section
			className={`${styles.library} ${runs.length ? "" : styles.libraryCompact}`}
			aria-labelledby="local-results-title"
		>
			<div className={styles.libraryHeader}>
				<div>
					<span className={styles.eyebrow}>Biblioteca local</span>
					<h2 id="local-results-title">Resultados locais</h2>
				</div>
				<span>{runs.length} {runs.length === 1 ? "resultado" : "resultados"}</span>
			</div>
			{runs.length ? (
				<>
					<p className={styles.libraryIntro}>
						Runs concluídos ficam separados da fila operacional. O transcript só é carregado quando você abre uma revisão.
					</p>
					<div className={styles.runGrid}>
						{runs.map((run) => (
							<RunCard
								key={serializeLocalRunKey(localRunKey(run))}
								run={run}
								busy={busy}
								onOpen={() => void onOpen(run.sourceId, run.runId)}
							/>
						))}
					</div>
				</>
			) : (
				<p className={styles.emptyCompact}>
					Nenhum resultado local concluído ainda.
					<span> Runs concluídos aparecem aqui sem publicação automática.</span>
				</p>
			)}
		</section>
	);
}
