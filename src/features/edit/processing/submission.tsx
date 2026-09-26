"use client";

import { FormEvent, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import {
	LocalBridge,
	localBridgePaired,
	subscribeLocalBridgePairing,
} from "./bridge";
import {
	BridgeError,
	type Capabilities,
	type CraigSource,
	type PreparationStatus,
	type TranscriptionProfileId,
} from "./protocol";
import { PROCESSING_REFRESH_POLICY } from "./refresh-policy";
import {
	craigTranscriptionRequestByteLength,
	LOCAL_JSON_BODY_MAX_BYTES,
	TRANSCRIPTION_TEXT_MAX_CHARS,
	truncateUnicodeScalars,
} from "./request-budget";
import styles from "./submission.module.css";

const profileLabels: Record<TranscriptionProfileId, string> = {
	"whisper-turbo": "Whisper Turbo",
	"whisper-detailed": "Whisper Detalhado",
	"qwen-fast": "Qwen Fast",
	"qwen-quality": "Qwen Quality",
};
const QWEN_RUNTIME_UPGRADE_REASON = "QWEN_RUNTIME_ALIGNMENT_UPGRADE_REQUIRED";
const QWEN_RUNTIME_UPGRADE_MESSAGE =
	"O Qwen local precisa do runtime 1.0.12 ou mais recente para recuperar com segurança extrapolações de alinhamento. Atualize o runtime/Companion antes de iniciar esta transcrição.";

function messageFor(code: string): string {
	return {
		unauthorized: "A sessão local expirou. O TDA tentará reconectar ao Companion.",
		forbidden: "O Companion recusou esta origem.",
		conflict: "O Companion recusou a operação no estado atual.",
		timeout: "A operação local excedeu o tempo esperado. Confira a fila antes de repetir.",
		unreachable: "Não foi possível alcançar o Companion local.",
		invalid_response: "O Companion respondeu com um contrato inválido.",
		payload_too_large:
			"Contexto e glossário excedem o orçamento UTF-8 aceito pelo Companion. Reduza o texto antes de enviar.",
		api_incompatible: "A API do Companion não suporta este fluxo. Atualize o aplicativo local.",
		version_incompatible: "A versão do Companion é antiga demais para este fluxo. Atualize o aplicativo local.",
		session_incompatible: "O Companion não oferece a sessão automática exigida por este fluxo. Atualize o aplicativo local.",
		incompatible: "O Companion não suporta este fluxo. Atualize o aplicativo local.",
		service_error: "O Companion encontrou uma falha local.",
	}[code] ?? "Falha local inesperada.";
}

function localOperationMessage(code: string | null): string {
	if (!code) return "A operação local não foi concluída.";
	return {
		TRANSCRIPTION_PREPARATION_ALREADY_RUNNING:
			"Já existe outra preparação em andamento neste computador.",
		TRANSCRIPTION_PREPARATION_CANCELLED:
			"A preparação local foi cancelada antes de terminar.",
		TRANSCRIPTION_PREPARATION_STALE_OPERATION:
			"A preparação mudou desde a última leitura. Atualizei o estado sem cancelar a operação mais nova.",
		TRANSCRIPTION_PREPARATION_OPERATION_INVALID:
			"O Companion recusou a identidade da preparação.",
		TRANSCRIPTION_PREPARATION_TIMEOUT:
			"A preparação local atingiu o limite de 2 horas e foi encerrada.",
		TRANSCRIPTION_PREPARATION_BLOCKED_BY_ACTIVE_JOB:
			"Já existe um trabalho local na fila ou em execução. Aguarde antes de preparar outro perfil.",
		TRANSCRIPTION_PREPARATION_BLOCKED_BY_RUNNING_JOB:
			"Espere o trabalho atual terminar antes de preparar outro perfil.",
		TRANSCRIPTION_WORK_ALREADY_ACTIVE:
			"Já existe uma transcrição equivalente na fila ou em execução.",
		CRAIG_STAGING_REPAIR_BLOCKED_BY_RUNNING_JOB:
			"Essa fonte está em uso pelo processamento ou pela preparação local. Aguarde terminar antes de reimportar o ZIP.",
		CRAIG_STAGING_REPAIR_FAILED:
			"O Companion tentou reparar a cópia local da sessão, mas não conseguiu concluir a troca segura.",
		CRAIG_STAGING_EXISTING_INVALID:
			"A cópia local dessa sessão está inconsistente. Reenvie o ZIP original quando a fonte não estiver em uso.",
		CRAIG_MANIFEST_TRACK_HASH_MISMATCH:
			"Uma faixa da cópia local foi alterada. Reenvie o ZIP original para reparar a sessão.",
		CRAIG_MANIFEST_TRACK_SIZE_MISMATCH:
			"Uma faixa da cópia local mudou de tamanho. Reenvie o ZIP original para reparar a sessão.",
		CRAIG_UPLOAD_STORAGE_FAILED:
			"O Companion não conseguiu gravar o ZIP no armazenamento local.",
		CRAIG_UPLOAD_SIZE_LIMIT:
			"O ZIP ultrapassa o limite aceito pelo Companion.",
		CRAIG_ZIP_REQUIRED:
			"Escolha um arquivo ZIP exportado pelo Craig.",
		QWEN_PHYSICAL_ACCEPTANCE_REQUIRED:
			"O Qwen precisa ser preparado e validado novamente nesta GPU antes de entrar na fila.",
		WHISPER_MODEL_PREPARATION_REQUIRED:
			"O modelo Whisper precisa ser preparado novamente antes de entrar na fila.",
		QWEN_CUDA_UNAVAILABLE:
			"O Qwen não encontrou CUDA disponível nesta máquina.",
		QWEN_CUDA_DRIVER_INCOMPATIBLE:
			"O driver NVIDIA não consegue executar o runtime CUDA exigido pelo Qwen.",
		QWEN_CUDA_EXECUTION_FAILED:
			"A GPU foi encontrada, mas uma operação CUDA real falhou.",
		QWEN_ASR_GPU_MEMORY_EXHAUSTED:
			"O Qwen ficou sem VRAM durante a validação local.",
		QWEN_ACCEPTANCE_AUDIO_TOO_SHORT:
			"Nenhuma faixa do ZIP possui áudio útil suficiente para validar o Qwen.",
		QWEN_ACCEPTANCE_NO_SPEECH_RECOGNIZED:
			"A amostra local escolhida não teve fala suficiente para validar o Qwen.",
		QWEN_MODEL_DOWNLOAD_FAILED:
			"Não foi possível baixar o modelo Qwen.",
		QWEN_RUNTIME_UNAVAILABLE:
			"O runtime Qwen compatível ainda não está disponível.",
		WHISPER_RUNTIME_UNAVAILABLE:
			"O runtime Whisper compatível ainda não está disponível.",
		WHISPER_MODEL_DOWNLOAD_FAILED:
			"Não foi possível baixar o modelo Whisper.",
		WHISPER_MODEL_PREPARATION_TIMEOUT:
			"A preparação do modelo Whisper excedeu o limite de tempo.",
		BODY_TOO_LARGE:
			"Contexto e glossário excedem o orçamento UTF-8 aceito pelo Companion. Reduza o texto antes de enviar.",
	}[code] ?? `Operação local não concluída · ${code}`;
}

type PendingSubmission = {
	key: string;
	signature: string;
};

function sourceMustBeRestaged(code: string | null): boolean {
	if (!code) return false;
	return (
		code.startsWith("CRAIG_MANIFEST_") ||
		code === "CRAIG_STAGING_EXISTING_INVALID" ||
		code === "CRAIG_STAGING_REPAIR_FAILED"
	);
}

export function ProcessingSubmission({
	className,
	compact = false,
}: Readonly<{ className?: string; compact?: boolean }> = {}) {
	const paired = useSyncExternalStore(
		subscribeLocalBridgePairing,
		localBridgePaired,
		() => false,
	);
	const [bridge] = useState(() => new LocalBridge());
	const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
	const [profile, setProfile] = useState<TranscriptionProfileId | "">("");
	const [sessionId, setSessionId] = useState("");
	const [context, setContext] = useState("");
	const [glossary, setGlossary] = useState("");
	const [file, setFile] = useState<File | null>(null);
	const [source, setSource] = useState<CraigSource | null>(null);
	const [busy, setBusy] = useState(false);
	const [status, setStatus] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [capabilityError, setCapabilityError] = useState<string | null>(null);
	const [preparation, setPreparation] = useState<PreparationStatus | null>(null);
	const [preparationCancelling, setPreparationCancelling] = useState(false);
	const request = useRef<AbortController | null>(null);
	const fileInput = useRef<HTMLInputElement>(null);
	const pending = useRef<PendingSubmission | null>(null);

	useEffect(() => {
		return () => request.current?.abort();
	}, []);

	useEffect(() => {
		if (!paired) {
			request.current?.abort();
			setCapabilities(null);
			setProfile("");
			setCapabilityError(null);
			return;
		}

		const controller = new AbortController();
		let reading = false;
		let stopped = false;
		const refreshCapabilities = async () => {
			if (reading || stopped || controller.signal.aborted) return;
			reading = true;
			try {
				const value = await bridge.capabilities(controller.signal);
				if (stopped || controller.signal.aborted) return;
				setCapabilities(value);
				const choices = value.transcription.catalog.length
					? value.transcription.catalog.map((item) => item.id)
					: value.transcription.profiles;
				setProfile((current) =>
					current && choices.includes(current)
						? current
						: choices.includes("qwen-quality")
							? "qwen-quality"
							: (choices[0] ?? ""),
				);
				setCapabilityError(null);
			} catch (cause) {
				if (!stopped && !controller.signal.aborted) {
					setCapabilityError(messageFor(cause instanceof BridgeError ? cause.code : "service_error"));
				}
			} finally {
				reading = false;
			}
		};

		void refreshCapabilities();
		const timer = window.setInterval(() => {
			if (document.visibilityState === "visible") void refreshCapabilities();
		}, PROCESSING_REFRESH_POLICY.capabilitiesPollMs);
		const visible = () => {
			if (document.visibilityState === "visible") void refreshCapabilities();
		};
		document.addEventListener("visibilitychange", visible);
		return () => {
			stopped = true;
			window.clearInterval(timer);
			document.removeEventListener("visibilitychange", visible);
			controller.abort();
		};
	}, [bridge, paired]);

	useEffect(() => {
		if (!paired) {
			setPreparation(null);
			return;
		}
		const controller = new AbortController();
		let stopped = false;
		let reading = false;
		const refreshPreparation = async () => {
			if (stopped || reading || controller.signal.aborted) return;
			reading = true;
			try {
				const next = await bridge.preparation(controller.signal);
				if (!stopped && !controller.signal.aborted) setPreparation(next);
			} catch {
				// Capabilities/connection owns the global error surface. Losing one
				// preparation poll must not erase the last authoritative snapshot.
			} finally {
				reading = false;
			}
		};
		void refreshPreparation();
		const timer = window.setInterval(() => {
			if (document.visibilityState === "visible") void refreshPreparation();
		}, 1500);
		const visible = () => {
			if (document.visibilityState === "visible") void refreshPreparation();
		};
		document.addEventListener("visibilitychange", visible);
		return () => {
			stopped = true;
			window.clearInterval(timer);
			document.removeEventListener("visibilitychange", visible);
			controller.abort();
		};
	}, [bridge, paired]);

	const availableProfiles = useMemo(
		() =>
			capabilities?.transcription.catalog.length
				? capabilities.transcription.catalog
				: (capabilities?.transcription.profiles ?? []).map((id) => ({
						id,
						engine: id.startsWith("qwen-")
							? ("qwen3" as const)
							: ("whisper" as const),
						ready: true,
						preparationRequired: false,
						reason: null,
					})),
		[capabilities],
	);

	const selectedProfileState = useMemo(
		() => availableProfiles.find((item) => item.id === profile) ?? null,
		[availableProfiles, profile],
	);
	const qwenRuntimeUpgradeRequired =
		selectedProfileState?.reason === QWEN_RUNTIME_UPGRADE_REASON;

	const canSubmit = useMemo(
		() =>
			Boolean(
				capabilities &&
					availableProfiles.length > 0 &&
					(capabilities.capabilities.includes("transcription.craig") ||
						capabilities.capabilities.includes("transcription.prepare")),
			),
		[availableProfiles, capabilities],
	);
	const requestBytes = useMemo(() => {
		if (!profile || !/^[A-Za-z0-9_-]{1,128}$/u.test(sessionId)) return null;
		return craigTranscriptionRequestByteLength({
			campaignId: CAMPAIGN_SLUG,
			sessionId,
			sourceId: source?.sourceId ?? `craig-${"0".repeat(64)}`,
			profileId: profile,
			glossary,
			context,
		});
	}, [context, glossary, profile, sessionId, source]);
	const requestTooLarge =
		requestBytes !== null && requestBytes > LOCAL_JSON_BODY_MAX_BYTES;

	if (!paired) return null;

	async function submit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (busy || !file || !profile || !canSubmit) return;
		if (qwenRuntimeUpgradeRequired) {
			setError(QWEN_RUNTIME_UPGRADE_MESSAGE);
			return;
		}
		if (!/^[A-Za-z0-9_-]{1,128}$/u.test(sessionId)) {
			setError("Use um ID de sessão com letras, números, _ ou -, até 128 caracteres.");
			return;
		}
		if (!file.name.toLowerCase().endsWith(".zip") || file.size <= 0) {
			setError("Escolha um ZIP válido exportado pelo Craig.");
			return;
		}
		if (requestTooLarge) {
			setError(
				`Contexto e glossário excedem o orçamento local: ${requestBytes} / ${LOCAL_JSON_BODY_MAX_BYTES} bytes UTF-8. Reduza o texto antes de enviar.`,
			);
			return;
		}

		const controller = new AbortController();
		request.current?.abort();
		request.current = controller;
		setBusy(true);
		setError(null);
		setStatus(
			source
				? "Reutilizando a fonte já verificada neste Companion…"
				: "Enviando o ZIP diretamente para o Companion local…",
		);
		try {
			const staged = source ?? (await bridge.craigSource(file, controller.signal));
			if (!source) setSource(staged);
			setStatus(
				staged.reused || source
					? `Fonte local já verificada · ${staged.trackCount} tracks.`
					: `ZIP verificado · ${staged.trackCount} tracks.`,
			);

			// Uploads grandes can take long enough for runtime/model readiness to
			// change. Decide preparation from a fresh Agent snapshot, not from the
			// render that existed when the user clicked submit.
			const currentCapabilities = await bridge.capabilities(controller.signal);
			setCapabilities(currentCapabilities);
			const currentProfiles = currentCapabilities.transcription.catalog.length
				? currentCapabilities.transcription.catalog
				: currentCapabilities.transcription.profiles.map((id) => ({
						id,
						engine: id.startsWith("qwen-")
							? ("qwen3" as const)
							: ("whisper" as const),
						ready: true,
						preparationRequired: false,
						reason: null,
					}));
			const selectedProfile = currentProfiles.find((item) => item.id === profile);
			if (!selectedProfile) {
				setError("O perfil selecionado não está disponível neste Companion.");
				return;
			}
			if (selectedProfile.reason === QWEN_RUNTIME_UPGRADE_REASON) {
				setError(QWEN_RUNTIME_UPGRADE_MESSAGE);
				return;
			}
			if (!selectedProfile.ready) {
				setStatus("Preparando o perfil no Agent local…");
				let observed = preparation;
				if (observed?.active) {
					if (
						observed.sourceId !== staged.sourceId ||
						observed.profileId !== profile
					) {
						setError(
							"Já existe outra preparação em andamento. Acompanhe ou cancele a operação atual antes de iniciar outra.",
						);
						return;
					}
				} else {
					observed = await bridge.prepareProfile(
						staged.sourceId,
						profile,
						controller.signal,
					);
					setPreparation(observed);
				}
				const operationId = observed.operationId;
				if (!operationId) {
					setError("O Agent não retornou a identidade da preparação.");
					return;
				}
				while (observed.state === "running") {
					setStatus(
						`${observed.title} ${observed.detail} · ${Math.round(observed.elapsedSeconds)} s`,
					);
					await new Promise((resolve) => window.setTimeout(resolve, 1500));
					if (controller.signal.aborted) return;
					const next = await bridge.preparation(controller.signal);
					setPreparation(next);
					if (next.operationId !== operationId) {
						setError(
							"A preparação observada terminou ou foi substituída. O estado foi atualizado sem agir sobre a operação nova.",
						);
						return;
					}
					observed = next;
				}
				if (observed.state !== "completed") {
					setError(localOperationMessage(observed.errorCode));
					return;
				}
				setStatus("Perfil preparado e validado. Confirmando capacidade do Agent…");
				const refreshed = await bridge.capabilities(controller.signal);
				setCapabilities(refreshed);
				const refreshedProfile = refreshed.transcription.catalog.find(
					(item) => item.id === profile,
				);
				if (refreshedProfile?.reason === QWEN_RUNTIME_UPGRADE_REASON) {
					setError(QWEN_RUNTIME_UPGRADE_MESSAGE);
					return;
				}
				if (!refreshed.transcription.profiles.includes(profile)) {
					setError("O Agent concluiu a preparação, mas ainda não anunciou o perfil como pronto.");
					return;
				}
			}

			const signature = JSON.stringify([
				CAMPAIGN_SLUG,
				sessionId,
				staged.sourceId,
				profile,
				glossary,
				context,
			]);
			if (!pending.current || pending.current.signature !== signature) {
				pending.current = { key: crypto.randomUUID(), signature };
			}

			const job = await bridge.transcription(
				{
					campaignId: CAMPAIGN_SLUG,
					sessionId,
					sourceId: staged.sourceId,
					profileId: profile,
					glossary,
					context,
				},
				pending.current.key,
				controller.signal,
			);
			pending.current = null;
			setStatus(`Trabalho ${job.id.slice(0, 8)}… entrou na fila local.`);
			setFile(null);
			if (fileInput.current) fileInput.current.value = "";
		} catch (cause) {
			if (cause instanceof BridgeError) {
				if (sourceMustBeRestaged(cause.serverCode)) setSource(null);
				setError(
					cause.serverCode
						? localOperationMessage(cause.serverCode)
						: messageFor(cause.code),
				);
			} else {
				setError(messageFor("service_error"));
			}
			setStatus(
				pending.current
					? "A tentativa ficou ambígua; repetir com os mesmos dados reutiliza a mesma chave idempotente."
					: null,
			);
		} finally {
			setBusy(false);
		}
	}

	async function cancelActivePreparation() {
		const operationId = preparation?.operationId;
		if (
			!operationId ||
			!preparation.active ||
			preparationCancelling ||
			!capabilities?.capabilities.includes("transcription.prepare.cancel")
		)
			return;
		const controller = new AbortController();
		setPreparationCancelling(true);
		setError(null);
		try {
			const next = await bridge.cancelPreparation(operationId, controller.signal);
			setPreparation(next);
			setStatus("Cancelamento solicitado ao Agent local.");
		} catch (cause) {
			if (cause instanceof BridgeError) {
				setError(
					cause.serverCode
						? localOperationMessage(cause.serverCode)
						: messageFor(cause.code),
				);
				try {
					setPreparation(await bridge.preparation(controller.signal));
				} catch {
					// Keep the last snapshot; the normal observer will retry.
				}
			} else {
				setError(messageFor("service_error"));
			}
		} finally {
			setPreparationCancelling(false);
		}
	}

	return (
		<section
			className={className ? `${styles.card} ${className}` : styles.card}
			data-layout={compact ? "compact" : "default"}
			aria-labelledby="new-local-transcription"
		>
			<div className={styles.heading}>
				<div>
					<span>Processamento real</span>
					<h2 id="new-local-transcription">Nova transcrição Craig</h2>
				</div>
				<small>ZIP → loopback → GPU local</small>
			</div>

			{!capabilities ? (
				<p className={styles.notice} role="status">
					Lendo os perfis disponíveis no Companion…
				</p>
			) : !canSubmit ? (
				<p className={styles.notice} role="status">
					Este Companion não anunciou um fluxo de transcrição/preparação compatível. Atualize o aplicativo local.
				</p>
			) : (
				<form className={styles.form} onSubmit={submit}>
					<label>
						<span>ID da sessão</span>
						<input
							value={sessionId}
							onChange={(event) => setSessionId(event.target.value.trim())}
							pattern="[A-Za-z0-9_-]{1,128}"
							maxLength={128}
							required
							disabled={busy}
							placeholder="sessao-42"
						/>
					</label>
					<label>
						<span>Perfil</span>
						<select
							value={profile}
							onChange={(event) => setProfile(event.target.value as TranscriptionProfileId)}
							disabled={busy}
							required
						>
							{availableProfiles.map((item) => (
								<option key={item.id} value={item.id}>
									{profileLabels[item.id]}{item.ready
										? ""
										: item.reason === QWEN_RUNTIME_UPGRADE_REASON
											? " · atualizar runtime"
											: " · preparar no primeiro uso"}
								</option>
							))}
						</select>
					</label>
					<label className={styles.fileField}>
						<span>Export do Craig</span>
						<input
							ref={fileInput}
							type="file"
							accept=".zip,application/zip"
							required
							disabled={busy}
							onChange={(event) => {
								setFile(event.target.files?.[0] ?? null);
								setSource(null);
								setStatus(null);
								setError(null);
							}}
						/>
					</label>
					<div className={styles.actions}>
						<Button
							type="submit"
							variant="primary"
							disabled={
								busy ||
								!file ||
								!profile ||
								requestTooLarge ||
								qwenRuntimeUpgradeRequired
							}
						>
							{busy ? "Preparando localmente…" : "Adicionar à fila local"}
						</Button>
						<span>O áudio não é enviado para o cloud.</span>
					</div>
					<details className={styles.advanced}>
						<summary>
							<span>Opções avançadas</span>
							<small>Contexto e glossário</small>
						</summary>
						<div className={styles.advancedGrid}>
							<label>
								<span>Contexto opcional</span>
								<textarea
									value={context}
									onChange={(event) =>
										setContext(
											truncateUnicodeScalars(
												event.target.value,
												TRANSCRIPTION_TEXT_MAX_CHARS,
											),
										)
									}
									disabled={busy}
									placeholder="Contexto curto da sessão/campanha para reconhecimento."
								/>
							</label>
							<label>
								<span>Glossário opcional</span>
								<textarea
									value={glossary}
									onChange={(event) =>
										setGlossary(
											truncateUnicodeScalars(
												event.target.value,
												TRANSCRIPTION_TEXT_MAX_CHARS,
											),
										)
									}
									disabled={busy}
									placeholder="Personagens, NPCs, lugares e termos difíceis."
								/>
							</label>
						</div>
					</details>
					{requestTooLarge ? (
						<p className={styles.error} role="alert">
							Contexto e glossário usam {requestBytes} / {LOCAL_JSON_BODY_MAX_BYTES} bytes UTF-8 no request local. Reduza o texto antes de enviar.
						</p>
					) : null}
					{qwenRuntimeUpgradeRequired ? (
						<p className={styles.error} role="alert">
							{QWEN_RUNTIME_UPGRADE_MESSAGE}
						</p>
					) : profile && !selectedProfileState?.ready ? (
						<p className={styles.notice} role="status">
							Primeiro uso: runtime, modelo e validação local da GPU serão preparados automaticamente antes de criar o job.
						</p>
					) : null}
				</form>
			)}

			{preparation?.active ? (
				<div className={styles.notice} role="status">
					<strong>{preparation.title}</strong>{" "}
					{preparation.detail} · {Math.round(preparation.elapsedSeconds)} s · op{" "}
					{preparation.operationId?.slice(0, 8)}…
					{capabilities?.capabilities.includes("transcription.prepare.cancel") &&
					preparation.operationId ? (
						<Button
							type="button"
							variant="secondary"
							disabled={preparationCancelling}
							onClick={() => void cancelActivePreparation()}
						>
							{preparationCancelling ? "Cancelando…" : "Cancelar preparação"}
						</Button>
					) : null}
				</div>
			) : null}

			{source ? (
				<p className={styles.source}>
					Fonte {source.sourceId.slice(0, 18)}… · {source.trackCount} tracks · {(source.sizeBytes / 1024 ** 2).toFixed(1)} MB
				</p>
			) : null}
			{status ? <p className={styles.status} role="status">{status}</p> : null}
			{capabilityError ? <p className={styles.error} role="alert">{capabilityError}</p> : null}
			{error ? <p className={styles.error} role="alert">{error}</p> : null}
		</section>
	);
}
