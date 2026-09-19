"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WorldLayout } from "../constellation-layout";
import type { WorldGraphDraft, WorldLayoutProjection } from "../model";
import {
	acquireWorldGraphDraftAction,
	publishWorldEditStateAction,
	saveWorldGraphDraftAction,
} from "../world-graph-actions";
import { publishWorldEditLayoutAction } from "../world-edit-actions";
import {
	acquireWorldLayoutSessionAction,
	discardWorldLayoutSessionAction,
	releaseWorldLayoutSessionAction,
	renewWorldLayoutSessionAction,
	saveWorldLayoutSessionDraftAction,
} from "../world-layout-session-actions";
import {
	worldDraftSaveFailureMessage,
	worldEditFailureMessage,
	worldLayoutPositionsEqual,
	worldPublishFailureMessage,
} from "./world-edit-session-model";

const WORLD_EDIT_LEASE_STORAGE_KEY = "tda.world.edit.lease.yuhara-main";
const WORLD_EDIT_HEARTBEAT_MS = 20_000;
const WORLD_EDIT_DRAFT_DEBOUNCE_MS = 500;
const WORLD_EDIT_DRAFT_SAFETY_FLUSH_MS = 10_000;
const WORLD_BUSY_NOTICE_MS = 5_000;

type WorldEditState = "view" | "acquiring" | "editing" | "publishing";
type LayoutDraftResult = Awaited<ReturnType<typeof saveWorldLayoutSessionDraftAction>>;
type GraphDraftResult = Awaited<ReturnType<typeof saveWorldGraphDraftAction>>;

type UseWorldEditSessionOptions = Readonly<{
	canEditLayout: boolean;
	canEditContent: boolean;
	canStartEditing: boolean;
	publishedPositions: WorldLayout;
	buildLayoutCandidate: (
		graphDraft: WorldGraphDraft | null,
	) => WorldLayoutProjection | null | undefined;
	onApplyLayoutDraft: (positions: WorldLayout) => void;
	onReleaseLayout: () => void;
	onEditingStarted?: () => void;
	onPublished: () => void;
}>;

type UpdateLayoutDraftOptions = Readonly<{
	dirty?: boolean;
	pendingMessage?: string;
}>;

export function useWorldEditSession({
	canEditLayout,
	canEditContent,
	canStartEditing,
	publishedPositions,
	buildLayoutCandidate,
	onApplyLayoutDraft,
	onReleaseLayout,
	onEditingStarted,
	onPublished,
}: UseWorldEditSessionOptions) {
	const [state, setState] = useState<WorldEditState>("view");
	const [leaseToken, setLeaseToken] = useState<string | null>(null);
	const [layoutDirty, setLayoutDirty] = useState(false);
	const [graphDraft, setGraphDraft] = useState<WorldGraphDraft | null>(null);
	const graphDraftRef = useRef<WorldGraphDraft | null>(null);
	const [graphDirty, setGraphDirty] = useState(false);
	const [feedback, setFeedback] = useState<string | null>(null);
	const [busyNotice, setBusyNotice] = useState<string | null>(null);
	const layoutDraftTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
	const graphDraftTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
	const draftSafetyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
	const busyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
	const draftSequence = useRef(0);
	const saveQueue = useRef<Promise<void>>(Promise.resolve());

	const editing = state === "editing" || state === "publishing";
	const busy = state === "acquiring" || state === "publishing";
	const hasChanges = layoutDirty || graphDirty;

	useEffect(() => {
		graphDraftRef.current = graphDraft;
	}, [graphDraft]);

	useEffect(() => {
		if (state !== "editing" || !hasChanges) return;
		const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
			event.preventDefault();
			event.returnValue = "";
		};
		window.addEventListener("beforeunload", warnBeforeLeaving);
		return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
	}, [hasChanges, state]);

	const markLeaseLost = useCallback((reason: string) => {
		draftSequence.current += 1;
		if (layoutDraftTimer.current) clearTimeout(layoutDraftTimer.current);
		if (graphDraftTimer.current) clearTimeout(graphDraftTimer.current);
		if (draftSafetyTimer.current) clearTimeout(draftSafetyTimer.current);
		layoutDraftTimer.current = null;
		graphDraftTimer.current = null;
		draftSafetyTimer.current = null;
		setState("view");
		setLeaseToken(null);
		window.sessionStorage.removeItem(WORLD_EDIT_LEASE_STORAGE_KEY);
		setFeedback(worldEditFailureMessage(reason));
	}, []);

	useEffect(() => {
		if (state !== "editing" || !leaseToken) return;
		let cancelled = false;
		const heartbeat = window.setInterval(() => {
			void renewWorldLayoutSessionAction(leaseToken).then((result) => {
				if (cancelled || result.ok) return;
				if (result.reason === "lease_lost" || result.reason === "forbidden") {
					markLeaseLost(result.reason);
					return;
				}
				setFeedback(worldEditFailureMessage(result.reason));
			});
		}, WORLD_EDIT_HEARTBEAT_MS);
		return () => {
			cancelled = true;
			window.clearInterval(heartbeat);
		};
	}, [state, leaseToken, markLeaseLost]);

	useEffect(
		() => () => {
			if (layoutDraftTimer.current) clearTimeout(layoutDraftTimer.current);
			if (graphDraftTimer.current) clearTimeout(graphDraftTimer.current);
			if (draftSafetyTimer.current) clearTimeout(draftSafetyTimer.current);
			if (busyTimer.current) clearTimeout(busyTimer.current);
		},
		[],
	);

	function showBusyNotice(message: string) {
		setBusyNotice(message);
		if (busyTimer.current) clearTimeout(busyTimer.current);
		busyTimer.current = setTimeout(() => setBusyNotice(null), WORLD_BUSY_NOTICE_MS);
	}

	function enqueueSave<T>(operation: () => Promise<T>): Promise<T> {
		const request = saveQueue.current.then(operation);
		saveQueue.current = request.then(
			() => undefined,
			() => undefined,
		);
		return request;
	}

	function queueLayoutDraftRequest(
		token: string,
		candidate: WorldLayoutProjection,
	): Promise<LayoutDraftResult> {
		return enqueueSave(async () => {
			try {
				return await saveWorldLayoutSessionDraftAction(token, candidate);
			} catch {
				return { ok: false, reason: "dependency_unavailable" } as const;
			}
		});
	}

	function queueGraphDraftRequest(
		token: string,
		draft: WorldGraphDraft,
	): Promise<GraphDraftResult> {
		return enqueueSave(async () => {
			try {
				return await saveWorldGraphDraftAction(token, draft);
			} catch {
				return { ok: false, reason: "dependency_unavailable" } as const;
			}
		});
	}

	function scheduleSafetyDraftFlush() {
		if (state !== "editing" || !leaseToken || draftSafetyTimer.current) return;
		draftSafetyTimer.current = setTimeout(() => {
			draftSafetyTimer.current = null;
			if (state !== "editing") return;
			const latestGraph = graphDraftRef.current;
			const layoutCandidate = buildLayoutCandidate(latestGraph);
			if (!layoutCandidate) {
				setFeedback(worldDraftSaveFailureMessage("invalid_payload"));
				return;
			}
			const sequence = ++draftSequence.current;
			void queueLayoutDraftRequest(leaseToken, layoutCandidate).then(async (layoutResult) => {
				if (sequence !== draftSequence.current) return;
				if (!layoutResult.ok) {
					if (layoutResult.reason === "lease_lost" || layoutResult.reason === "forbidden") {
						markLeaseLost(layoutResult.reason);
					} else {
						setFeedback(worldDraftSaveFailureMessage(layoutResult.reason));
					}
					return;
				}

				if (canEditContent && latestGraph) {
					const graphResult = await queueGraphDraftRequest(leaseToken, latestGraph);
					if (sequence !== draftSequence.current) return;
					if (!graphResult.ok) {
						if (graphResult.reason === "lease_lost" || graphResult.reason === "forbidden") {
							markLeaseLost(graphResult.reason);
						} else {
							setFeedback(worldDraftSaveFailureMessage(graphResult.reason));
						}
						return;
					}
				}
				setFeedback("Checkpoint de segurança confirmado. Seu rascunho está preservado.");
			});
		}, WORLD_EDIT_DRAFT_SAFETY_FLUSH_MS);
	}

	function scheduleLayoutDraftSave(
		candidate: WorldLayoutProjection,
		pendingMessage = "Alterações locais — salvando rascunho…",
	) {
		if (state !== "editing" || !leaseToken) return;
		if (layoutDraftTimer.current) clearTimeout(layoutDraftTimer.current);
		const sequence = ++draftSequence.current;
		setFeedback(pendingMessage);
		scheduleSafetyDraftFlush();
		layoutDraftTimer.current = setTimeout(() => {
			layoutDraftTimer.current = null;
			void queueLayoutDraftRequest(leaseToken, candidate).then((result) => {
				if (sequence !== draftSequence.current) return;
				if (result.ok) {
					setFeedback(
						canEditContent
							? "Rascunho salvo. Só você vê estas alterações até publicar."
							: "Rascunho salvo. Só você vê estas posições até publicar.",
					);
					return;
				}
				if (result.reason === "lease_lost" || result.reason === "forbidden") {
					markLeaseLost(result.reason);
					return;
				}
				setFeedback(worldDraftSaveFailureMessage(result.reason));
			});
		}, WORLD_EDIT_DRAFT_DEBOUNCE_MS);
	}

	function scheduleGraphDraftSave(
		draft: WorldGraphDraft,
		pendingMessage = "Alterações no Mundo — salvando rascunho…",
	) {
		if (!canEditContent || state !== "editing" || !leaseToken) return;
		if (graphDraftTimer.current) clearTimeout(graphDraftTimer.current);
		const sequence = ++draftSequence.current;
		setFeedback(pendingMessage);
		scheduleSafetyDraftFlush();
		graphDraftTimer.current = setTimeout(() => {
			graphDraftTimer.current = null;
			void queueGraphDraftRequest(leaseToken, draft).then((result) => {
				if (sequence !== draftSequence.current) return;
				if (result.ok) {
					setFeedback("Rascunho salvo. Só você vê estas alterações até publicar.");
					return;
				}
				if (result.reason === "lease_lost" || result.reason === "forbidden") {
					markLeaseLost(result.reason);
					return;
				}
				setFeedback(worldDraftSaveFailureMessage(result.reason));
			});
		}, WORLD_EDIT_DRAFT_DEBOUNCE_MS);
	}

	function updateLayoutDraft(
		candidate: WorldLayoutProjection,
		{ dirty = true, pendingMessage }: UpdateLayoutDraftOptions = {},
	) {
		if (state !== "editing") return;
		setLayoutDirty(dirty);
		scheduleLayoutDraftSave(candidate, pendingMessage);
	}

	function updateGraphDraft(next: WorldGraphDraft, message?: string) {
		graphDraftRef.current = next;
		setGraphDraft(next);
		setGraphDirty(true);
		scheduleGraphDraftSave(next, message ? `${message} Salvando rascunho…` : undefined);
	}

	async function start() {
		if (!canEditLayout || !canStartEditing || state !== "view") return;
		setBusyNotice(null);
		setState("acquiring");
		setFeedback("Obtendo sessão exclusiva de edição…");
		let token = window.sessionStorage.getItem(WORLD_EDIT_LEASE_STORAGE_KEY);
		if (!token) {
			token = crypto.randomUUID();
			window.sessionStorage.setItem(WORLD_EDIT_LEASE_STORAGE_KEY, token);
		}

		const result = await acquireWorldLayoutSessionAction(token);
		if (!result.ok) {
			setState("view");
			if (result.reason === "busy") {
				showBusyNotice(
					result.sameActor
						? "Você já está editando o Mundo em outra aba. Finalize aquela sessão ou aguarde a expiração para recuperar o rascunho."
						: `${result.holderLabel} está editando o Mundo neste momento.`,
				);
				setFeedback(null);
				return;
			}
			window.sessionStorage.removeItem(WORLD_EDIT_LEASE_STORAGE_KEY);
			setFeedback(worldEditFailureMessage(result.reason));
			return;
		}

		let acquiredGraph: WorldGraphDraft | null = null;
		if (canEditContent) {
			const graphResult = await acquireWorldGraphDraftAction(token);
			if (!graphResult.ok) {
				await releaseWorldLayoutSessionAction(token);
				window.sessionStorage.removeItem(WORLD_EDIT_LEASE_STORAGE_KEY);
				setState("view");
				setFeedback(worldEditFailureMessage(graphResult.reason));
				return;
			}
			acquiredGraph = graphResult.draft;
		}

		setLeaseToken(token);
		onApplyLayoutDraft(result.draft.positions);
		setLayoutDirty(!worldLayoutPositionsEqual(result.draft.positions, publishedPositions));
		graphDraftRef.current = acquiredGraph;
		setGraphDraft(acquiredGraph);
		setGraphDirty(Boolean(acquiredGraph && result.status !== "acquired"));
		onEditingStarted?.();
		setState("editing");
		setFeedback(
			result.previousPublishConfirmed
				? result.previousPublishedGraphRevision !== undefined
					? `A publicação anterior foi confirmada pelo servidor · revisão ${result.previousPublishedGraphRevision}. Esta sessão começou do estado publicado.`
					: `A publicação anterior foi confirmada pelo servidor · revisão de layout ${result.previousPublishedLayoutRevision ?? result.draft.revision}. Esta sessão começou do estado publicado.`
				: result.staleRecovery
					? result.status === "recovered"
						? "Rascunho anterior recuperado, mas o Mundo publicado mudou desde a base dele. O trabalho foi preservado para revisão; a publicação continuará bloqueada por conflito até essa diferença ser reconciliada."
						: "Existe um rascunho anterior preservado, mas o Mundo publicado mudou desde então. Ele não foi aplicado automaticamente; esta sessão começou do estado publicado atual."
					: result.status === "acquired"
						? canEditContent
							? "Edição exclusiva ativa. Crie, conecte, organize e revise o Mundo; cada alteração confirmada fica preservada até publicar."
							: "Edição exclusiva ativa. Cada alteração de posição confirmada fica preservada até publicar."
						: result.recoverySource === "durable"
							? "Rascunho durável recuperado de uma sessão anterior. Revise antes de publicar."
							: "Rascunho de edição recuperado. Revise antes de publicar.",
		);
	}

	function cancelPendingDraftSaves() {
		if (layoutDraftTimer.current) {
			clearTimeout(layoutDraftTimer.current);
			layoutDraftTimer.current = null;
		}
		if (graphDraftTimer.current) {
			clearTimeout(graphDraftTimer.current);
			graphDraftTimer.current = null;
		}
		if (draftSafetyTimer.current) {
			clearTimeout(draftSafetyTimer.current);
			draftSafetyTimer.current = null;
		}
	}

	function completePublishedEdit(message: string) {
		window.sessionStorage.removeItem(WORLD_EDIT_LEASE_STORAGE_KEY);
		setLeaseToken(null);
		setLayoutDirty(false);
		setGraphDirty(false);
		graphDraftRef.current = null;
		setGraphDraft(null);
		setState("view");
		setFeedback(message);
		onPublished();
	}

	async function publish() {
		if (state !== "editing" || !leaseToken || !hasChanges) return;
		cancelPendingDraftSaves();
		const sequence = ++draftSequence.current;
		setState("publishing");
		setFeedback("Validando o rascunho mais recente…");

		const layoutCandidate = buildLayoutCandidate(graphDraftRef.current);
		if (!layoutCandidate) {
			setState("editing");
			setFeedback(worldPublishFailureMessage("invalid_payload"));
			return;
		}
		const layoutResult = await queueLayoutDraftRequest(leaseToken, layoutCandidate);
		if (sequence !== draftSequence.current) return;
		if (!layoutResult.ok) {
			if (layoutResult.reason === "lease_lost" || layoutResult.reason === "forbidden") {
				markLeaseLost(layoutResult.reason);
			} else {
				setState("editing");
				setFeedback(worldPublishFailureMessage(layoutResult.reason));
			}
			return;
		}

		if (canEditContent) {
			const latestGraph = graphDraftRef.current;
			if (!latestGraph) {
				setState("editing");
				setFeedback("O rascunho factual não está disponível. Reabra a edição antes de publicar.");
				return;
			}
			const graphResult = await queueGraphDraftRequest(leaseToken, latestGraph);
			if (sequence !== draftSequence.current) return;
			if (!graphResult.ok) {
				if (graphResult.reason === "lease_lost" || graphResult.reason === "forbidden") {
					markLeaseLost(graphResult.reason);
				} else {
					setState("editing");
					setFeedback(worldPublishFailureMessage(graphResult.reason));
				}
				return;
			}

			setFeedback("Publicando o Mundo com as visibilidades configuradas…");
			const publishResult = await publishWorldEditStateAction(leaseToken);
			if (sequence !== draftSequence.current) return;
			if (!publishResult.ok) {
				if (publishResult.reason === "lease_lost" || publishResult.reason === "forbidden") {
					markLeaseLost(publishResult.reason);
				} else {
					setState("editing");
					setFeedback(worldPublishFailureMessage(publishResult.reason));
				}
				return;
			}
			completePublishedEdit(
				publishResult.status === "unchanged"
					? `Publicação confirmada. Nenhuma alteração nova era necessária · revisão ${publishResult.graphRevision}.`
					: `Mundo publicado com sucesso · revisão ${publishResult.graphRevision}. Cada pessoa vê somente o que sua visibilidade permite.`,
			);
			return;
		}

		setFeedback("Publicando composição para todos…");
		const publishResult = await publishWorldEditLayoutAction(leaseToken);
		if (sequence !== draftSequence.current) return;
		if (!publishResult.ok) {
			if (publishResult.reason === "lease_lost" || publishResult.reason === "forbidden") {
				markLeaseLost(publishResult.reason);
			} else {
				setState("editing");
				setFeedback(worldPublishFailureMessage(publishResult.reason));
			}
			return;
		}
		completePublishedEdit(
			publishResult.status === "unchanged"
				? `Publicação confirmada. Nenhuma mudança de layout era necessária · revisão ${publishResult.revision}.`
				: `Composição publicada com sucesso · revisão ${publishResult.revision}.`,
		);
	}

	async function release(message: string) {
		if (!leaseToken || state !== "editing") return;
		cancelPendingDraftSaves();
		const sequence = ++draftSequence.current;

		if (hasChanges) {
			setFeedback("Salvando um checkpoint final antes de encerrar a edição…");
			const layoutCandidate = buildLayoutCandidate(graphDraftRef.current);
			if (!layoutCandidate) {
				setFeedback(worldDraftSaveFailureMessage("invalid_payload"));
				return;
			}

			const layoutResult = await queueLayoutDraftRequest(leaseToken, layoutCandidate);
			if (sequence !== draftSequence.current) return;
			if (!layoutResult.ok) {
				if (layoutResult.reason === "lease_lost" || layoutResult.reason === "forbidden") {
					markLeaseLost(layoutResult.reason);
				} else {
					setFeedback(worldDraftSaveFailureMessage(layoutResult.reason));
				}
				return;
			}

			if (canEditContent && graphDraftRef.current) {
				const graphResult = await queueGraphDraftRequest(leaseToken, graphDraftRef.current);
				if (sequence !== draftSequence.current) return;
				if (!graphResult.ok) {
					if (graphResult.reason === "lease_lost" || graphResult.reason === "forbidden") {
						markLeaseLost(graphResult.reason);
					} else {
						setFeedback(worldDraftSaveFailureMessage(graphResult.reason));
					}
					return;
				}
			}
		}

		await saveQueue.current;
		if (sequence !== draftSequence.current) return;
		setFeedback("Encerrando a sessão de edição…");
		const result = await releaseWorldLayoutSessionAction(leaseToken);
		if (!result.ok) {
			setFeedback(worldEditFailureMessage(result.reason));
			return;
		}
		window.sessionStorage.removeItem(WORLD_EDIT_LEASE_STORAGE_KEY);
		setLeaseToken(null);
		setLayoutDirty(false);
		setGraphDirty(false);
		graphDraftRef.current = null;
		setGraphDraft(null);
		setState("view");
		onReleaseLayout();
		setFeedback(message);
	}

	async function finish() {
		await release("Edição encerrada sem publicar. O rascunho confirmado foi preservado.");
	}

	async function discard() {
		if (!leaseToken || state !== "editing") return;
		const confirmed = window.confirm(
			"Descartar este rascunho? O Mundo publicado será mantido. Uma cópia de recuperação ficará registrada para auditoria, mas esta sessão será encerrada.",
		);
		if (!confirmed) return;

		cancelPendingDraftSaves();
		const sequence = ++draftSequence.current;
		setFeedback("Preservando uma cópia final antes de descartar o rascunho…");

		const layoutCandidate = buildLayoutCandidate(graphDraftRef.current);
		if (!layoutCandidate) {
			setFeedback(worldDraftSaveFailureMessage("invalid_payload"));
			return;
		}
		const layoutResult = await queueLayoutDraftRequest(leaseToken, layoutCandidate);
		if (sequence !== draftSequence.current) return;
		if (!layoutResult.ok) {
			if (layoutResult.reason === "lease_lost" || layoutResult.reason === "forbidden") {
				markLeaseLost(layoutResult.reason);
			} else {
				setFeedback(worldDraftSaveFailureMessage(layoutResult.reason));
			}
			return;
		}

		if (canEditContent && graphDraftRef.current) {
			const graphResult = await queueGraphDraftRequest(leaseToken, graphDraftRef.current);
			if (sequence !== draftSequence.current) return;
			if (!graphResult.ok) {
				if (graphResult.reason === "lease_lost" || graphResult.reason === "forbidden") {
					markLeaseLost(graphResult.reason);
				} else {
					setFeedback(worldDraftSaveFailureMessage(graphResult.reason));
				}
				return;
			}
		}

		await saveQueue.current;
		const result = await discardWorldLayoutSessionAction(leaseToken);
		if (!result.ok) {
			setFeedback(worldEditFailureMessage(result.reason));
			return;
		}
		window.sessionStorage.removeItem(WORLD_EDIT_LEASE_STORAGE_KEY);
		setLeaseToken(null);
		setLayoutDirty(false);
		setGraphDirty(false);
		graphDraftRef.current = null;
		setGraphDraft(null);
		setState("view");
		onReleaseLayout();
		setFeedback("Rascunho descartado. O Mundo publicado foi mantido e uma cópia de recuperação foi preservada.");
	}

	return {
		state,
		editing,
		busy,
		hasChanges,
		graphDraft,
		feedback,
		busyNotice,
		start,
		publish,
		finish,
		discard,
		updateLayoutDraft,
		updateGraphDraft,
		reportFailure: (reason: string) => setFeedback(worldEditFailureMessage(reason)),
	} as const;
}
