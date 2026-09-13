"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import { worldEntityMediaAvailabilityAction } from "../world-entity-media-availability-action";
import {
	finalizeWorldEntityPortraitUploadAction,
	requestWorldEntityPortraitUploadAction,
	type WorldEntityPortraitUploadIntent,
} from "../world-entity-media-actions";
import {
	WORLD_ENTITY_MEDIA_MAX_BYTES,
	type WorldEntityMediaMime,
	worldEntityMediaPreviewUrl,
} from "../world-entity-media";
import type { WorldGraphDraftNode, WorldMediaFocalPoint } from "../model";
import styles from "./world-entity-media-editor.module.css";

const WORLD_EDIT_LEASE_STORAGE_KEY = "tda.world.edit.lease.yuhara-main";

function initials(name: string): string {
	return name
		.trim()
		.split(/\s+/u)
		.slice(0, 2)
		.map((part) => part.slice(0, 1).toLocaleUpperCase("pt-BR"))
		.join("") || "?";
}

function hex(bytes: ArrayBuffer): string {
	return [...new Uint8Array(bytes)]
		.map((value) => value.toString(16).padStart(2, "0"))
		.join("");
}

function mediaMime(file: File): WorldEntityMediaMime | null {
	if (file.type === "image/png" || file.type === "image/webp") return file.type;
	return null;
}

function failureMessage(reason: string): string {
	switch (reason) {
		case "media_unavailable":
			return "Mídia ainda não está habilitada neste ambiente.";
		case "lease_lost":
			return "A sessão de edição expirou. Reabra Conduzir antes de enviar a imagem.";
		case "forbidden":
		case "profile_unresolved":
		case "unauthenticated":
			return "Sua sessão não tem autorização para alterar a imagem deste elemento.";
		case "invalid_payload":
			return "O arquivo não atende ao contrato de imagem do Mundo.";
		default:
			return "Não foi possível concluir o upload. Tente novamente sem sair da edição.";
	}
}

export function WorldEntityMediaEditor({
	entity,
	onChange,
	onFocalPointChange,
}: {
	entity: WorldGraphDraftNode;
	onChange: (assetId: string | null) => void;
	onFocalPointChange: (focalPoint: WorldMediaFocalPoint) => void;
}) {
	const inputRef = useRef<HTMLInputElement>(null);
	const [available, setAvailable] = useState(false);
	const [busy, setBusy] = useState(false);
	const [dragging, setDragging] = useState(false);
	const [status, setStatus] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const previewUrl = entity.primaryMediaAssetId
		? worldEntityMediaPreviewUrl(entity.primaryMediaAssetId)
		: undefined;
	const focal = entity.primaryMediaFocalPoint ?? { x: 0.5, y: 0.5 };

	useEffect(() => {
		let active = true;
		void worldEntityMediaAvailabilityAction()
			.then((enabled) => {
				if (active) setAvailable(enabled);
			})
			.catch(() => {
				if (active) setAvailable(false);
			});
		return () => {
			active = false;
		};
	}, []);

	async function upload(file: File) {
		setError(null);
		setStatus(null);
		const leaseToken = window.sessionStorage.getItem(WORLD_EDIT_LEASE_STORAGE_KEY);
		if (!leaseToken) {
			setError("A sessão de edição não está ativa. Reabra Conduzir antes de enviar a imagem.");
			return;
		}
		const mimeType = mediaMime(file);
		if (!mimeType) {
			setError("Use uma imagem PNG ou WebP.");
			return;
		}
		if (file.size < 24 || file.size > WORLD_ENTITY_MEDIA_MAX_BYTES) {
			setError("A imagem precisa ter até 8 MiB e conter dados válidos.");
			return;
		}

		setBusy(true);
		try {
			setStatus("Preparando upload seguro…");
			const bytes = await file.arrayBuffer();
			const sha256 = hex(await crypto.subtle.digest("SHA-256", bytes));
			const intent: WorldEntityPortraitUploadIntent = {
				sha256,
				mimeType,
				bytes: file.size,
			};
			const requested = await requestWorldEntityPortraitUploadAction(
				leaseToken,
				entity.id,
				intent,
			);
			if (!requested.ok) {
				setError(failureMessage(requested.reason));
				setStatus(null);
				return;
			}

			setStatus("Enviando direto para o armazenamento…");
			const uploaded = await fetch(requested.uploadUrl, {
				method: requested.method,
				headers: requested.headers,
				body: bytes,
				cache: "no-store",
				credentials: "omit",
			});
			if (!uploaded.ok) {
				setError(`O armazenamento recusou o upload (${uploaded.status}).`);
				setStatus(null);
				return;
			}

			setStatus("Validando bytes e registrando o asset…");
			const finalized = await finalizeWorldEntityPortraitUploadAction(
				leaseToken,
				entity.id,
				requested.uploadId,
				intent,
			);
			if (!finalized.ok) {
				setError(failureMessage(finalized.reason));
				setStatus(null);
				return;
			}

			onChange(finalized.assetId);
			setStatus(
				`Imagem pronta no rascunho · ${finalized.width}×${finalized.height} · ${(finalized.bytes / 1024).toFixed(0)} KiB`,
			);
		} catch (uploadError) {
			console.error("World portrait browser upload failed", uploadError);
			setError("O upload foi interrompido. Tente novamente sem sair da edição.");
			setStatus(null);
		} finally {
			setBusy(false);
			if (inputRef.current) inputRef.current.value = "";
		}
	}

	function handleDrop(event: DragEvent<HTMLButtonElement>) {
		event.preventDefault();
		setDragging(false);
		if (busy) return;
		const file = event.dataTransfer.files.item(0);
		if (file) void upload(file);
	}

	if (!available) return null;

	return (
		<section className={styles.mediaEditor} aria-label="Imagem do elemento" aria-busy={busy}>
			<div className={styles.heading}>
				<strong>Imagem do elemento</strong>
				<span>PNG ou WebP · até 8 MiB</span>
			</div>
			<div className={styles.previewRow}>
				<div className={styles.preview}>
					{previewUrl ? (
						<img
							src={previewUrl}
							alt={`Retrato de ${entity.name}`}
							style={{ objectPosition: `${focal.x * 100}% ${focal.y * 100}%` }}
							draggable={false}
						/>
					) : (
						<span aria-hidden="true">{initials(entity.name)}</span>
					)}
				</div>
				<button
					className={styles.dropZone}
					type="button"
					disabled={busy}
					data-dragging={dragging ? "true" : "false"}
					onClick={() => inputRef.current?.click()}
					onDragEnter={(event) => {
						event.preventDefault();
						if (!busy) setDragging(true);
					}}
					onDragOver={(event) => event.preventDefault()}
					onDragLeave={() => setDragging(false)}
					onDrop={handleDrop}
				>
					<strong>{busy ? "Processando imagem…" : previewUrl ? "Trocar imagem" : "Adicionar imagem"}</strong>
					<span>Arraste aqui ou clique para escolher.</span>
				</button>
			</div>
			<input
				ref={inputRef}
				className={styles.input}
				type="file"
				accept="image/png,image/webp,.png,.webp"
				disabled={busy}
				onChange={(event) => {
					const file = event.target.files?.item(0);
					if (file) void upload(file);
				}}
			/>
			{previewUrl ? (
				<>
					<fieldset className={styles.focalControls}>
						<legend className={styles.input}>Enquadramento do retrato</legend>
						<div className={styles.focalHeading}>
							<strong>Enquadramento</strong>
							<span>
								{Math.round(focal.x * 100)}% · {Math.round(focal.y * 100)}%
							</span>
						</div>
						<label>
							Horizontal
							<input
								type="range"
								min={0}
								max={100}
								step={1}
								value={Math.round(focal.x * 100)}
								disabled={busy}
								onChange={(event) =>
									onFocalPointChange({ x: Number(event.target.value) / 100, y: focal.y })
								}
							/>
						</label>
						<label>
							Vertical
							<input
								type="range"
								min={0}
								max={100}
								step={1}
								value={Math.round(focal.y * 100)}
								disabled={busy}
								onChange={(event) =>
									onFocalPointChange({ x: focal.x, y: Number(event.target.value) / 100 })
								}
							/>
						</label>
						<button
							type="button"
							disabled={busy || (focal.x === 0.5 && focal.y === 0.5)}
							onClick={() => onFocalPointChange({ x: 0.5, y: 0.5 })}
						>
							Centralizar
						</button>
					</fieldset>
					<div className={styles.actions}>
						<button type="button" disabled={busy} onClick={() => inputRef.current?.click()}>
							Escolher outra
						</button>
						<button
							type="button"
							disabled={busy}
							onClick={() => {
								setError(null);
								setStatus("Imagem removida do rascunho. A publicação atual permanece intacta até publicar.");
								onChange(null);
							}}
						>
							Remover do rascunho
						</button>
					</div>
				</>
			) : null}
			{status ? (
				<p className={styles.status} role="status" aria-live="polite">
					{status}
				</p>
			) : null}
			{error ? (
				<p className={styles.error} role="alert">
					{error}
				</p>
			) : null}
		</section>
	);
}
