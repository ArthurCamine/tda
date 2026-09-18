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
	type TranscriptionProfileId,
} from "./protocol";
import styles from "./submission.module.css";

const profileLabels: Record<TranscriptionProfileId, string> = {
	"whisper-turbo": "Whisper Turbo",
	"whisper-detailed": "Whisper Detalhado",
	"qwen-fast": "Qwen Fast",
	"qwen-quality": "Qwen Quality",
};

function messageFor(code: string): string {
	return {
		unauthorized: "O pareamento local expirou. Reconecte o Companion.",
		forbidden: "O Companion recusou esta origem.",
		conflict: "O Companion recusou a operação no estado atual.",
		timeout: "A operação local excedeu o tempo esperado. Confira a fila antes de repetir.",
		unreachable: "Não foi possível alcançar o Companion local.",
		invalid_response: "O Companion respondeu com um contrato inválido.",
		incompatible: "A versão do Companion não suporta este fluxo.",
		service_error: "O Companion encontrou uma falha local.",
	}[code] ?? "Falha local inesperada.";
}

type PendingSubmission = {
	key: string;
	signature: string;
};

export function ProcessingSubmission() {
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
	const request = useRef<AbortController | null>(null);
	const fileInput = useRef<HTMLInputElement>(null);
	const pending = useRef<PendingSubmission | null>(null);

	useEffect(() => {
		if (!paired) {
			request.current?.abort();
			setCapabilities(null);
			setProfile("");
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
				setProfile((current) =>
					current && value.transcription.profiles.includes(current)
						? current
						: (value.transcription.profiles[0] ?? ""),
				);
				setError(null);
			} catch (cause) {
				if (!stopped && !controller.signal.aborted) {
					setError(messageFor(cause instanceof BridgeError ? cause.code : "service_error"));
				}
			} finally {
				reading = false;
			}
		};

		void refreshCapabilities();
		const timer = window.setInterval(() => {
			if (document.visibilityState === "visible") void refreshCapabilities();
		}, 3000);
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

	const canTranscribe = useMemo(
		() =>
			Boolean(
				capabilities?.capabilities.includes("transcription.craig") &&
				capabilities.transcription.profiles.length,
			),
		[capabilities],
	);

	if (!paired) return null;

	async function submit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (busy || !file || !profile || !canTranscribe) return;
		if (!/^[A-Za-z0-9_-]{1,128}$/u.test(sessionId)) {
			setError("Use um ID de sessão com letras, números, _ ou -, até 128 caracteres.");
			return;
		}
		if (!file.name.toLowerCase().endsWith(".zip") || file.size <= 0) {
			setError("Escolha um ZIP válido exportado pelo Craig.");
			return;
		}

		const controller = new AbortController();
		request.current?.abort();
		request.current = controller;
		setBusy(true);
		setError(null);
		setStatus("Enviando o ZIP diretamente para o Companion local…");
		try {
			const staged = await bridge.craigSource(file, controller.signal);
			setSource(staged);
			setStatus(
				staged.reused
					? `Fonte local já verificada · ${staged.trackCount} tracks. Enfileirando…`
					: `ZIP verificado · ${staged.trackCount} tracks. Enfileirando…`,
			);

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
			const code = cause instanceof BridgeError ? cause.code : "service_error";
			setError(messageFor(code));
			setStatus(
				pending.current
					? "A tentativa ficou ambígua; repetir com os mesmos dados reutiliza a mesma chave idempotente."
					: null,
			);
		} finally {
			setBusy(false);
		}
	}

	return (
		<section className={styles.card} aria-labelledby="new-local-transcription">
			<div className={styles.heading}>
				<div>
					<span>Processamento real</span>
					<h2 id="new-local-transcription">Nova transcrição Craig</h2>
				</div>
				<small>ZIP → loopback → GPU local</small>
			</div>

			{!canTranscribe ? (
				<p className={styles.notice} role="status">
					Nenhum perfil ASR está pronto ainda. Se a preparação foi iniciada no Companion, acompanhe lá as etapas de runtime, modelo e validação da GPU. Esta tela verifica novamente a cada 3 segundos e libera o formulário automaticamente assim que o perfil ficar pronto.
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
							{capabilities?.transcription.profiles.map((id) => (
								<option key={id} value={id}>{profileLabels[id]}</option>
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
					<label className={styles.wide}>
						<span>Contexto opcional</span>
						<textarea
							value={context}
							onChange={(event) => setContext(event.target.value.slice(0, 1200))}
							maxLength={1200}
							disabled={busy}
							placeholder="Contexto curto da sessão/campanha para reconhecimento."
						/>
					</label>
					<label className={styles.wide}>
						<span>Glossário opcional</span>
						<textarea
							value={glossary}
							onChange={(event) => setGlossary(event.target.value.slice(0, 1200))}
							maxLength={1200}
							disabled={busy}
							placeholder="Personagens, NPCs, lugares e termos difíceis."
						/>
					</label>
					<div className={styles.actions}>
						<Button type="submit" variant="primary" disabled={busy || !file || !profile}>
							{busy ? "Preparando localmente…" : "Adicionar à fila local"}
						</Button>
						<span>O áudio não é enviado para o cloud.</span>
					</div>
				</form>
			)}

			{source ? (
				<p className={styles.source}>
					Fonte {source.sourceId.slice(0, 18)}… · {source.trackCount} tracks · {(source.sizeBytes / 1024 ** 2).toFixed(1)} MB
				</p>
			) : null}
			{status ? <p className={styles.status} role="status">{status}</p> : null}
			{error ? <p className={styles.error} role="alert">{error}</p> : null}
		</section>
	);
}
