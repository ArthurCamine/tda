"use client";

import { useEffect } from "react";
import {
	worldCommand,
	worldCommandIsAvailable,
	type WorldCommandContext,
} from "../world-commands";
import { WORLD_AUTHORING_OPEN_INSPECTOR_EVENT } from "../world-authoring-events";
import { WorldCommandPaletteTrigger } from "./world-command-palette-trigger";
import styles from "./world-conductor-bar.module.css";

type WorldConductorAction = () => void | Promise<void>;

type WorldConductorBarProps = Readonly<{
	context: WorldCommandContext;
	canEditContent: boolean;
	busy: boolean;
	busyNotice: string | null;
	feedback: string | null;
	focusMode: boolean;
	inspectorOpen: boolean;
	onEnter: WorldConductorAction;
	onPublish: WorldConductorAction;
	onFinish: WorldConductorAction;
	onDiscard: WorldConductorAction;
	onToggleFocusMode: () => void;
	onToggleInspector: () => void;
	onOpenNavigation: () => void;
	onOpenCommandPalette: () => void;
}>;

function run(action: WorldConductorAction) {
	void action();
}

function conductorStatus(
	context: WorldCommandContext,
	canEditContent: boolean,
): { title: string; detail: string } {
	switch (context.editState) {
		case "acquiring":
			return {
				title: "Abrindo condução",
				detail: "Obtendo a sessão exclusiva antes de liberar qualquer alteração.",
			};
		case "editing":
			return {
				title: "Conduzindo",
				detail: context.hasChanges
					? "Há alterações no rascunho que ainda não foram publicadas."
					: canEditContent
						? "Crie, conecte ou organize o Mundo. Nada muda para visitantes até publicar."
						: "Organize o mapa. As posições permanecem privadas até publicar.",
			};
		case "publishing":
			return {
				title: "Publicando",
				detail: "Validando o rascunho e aplicando somente o que sua permissão autoriza.",
			};
		default:
			return {
				title: "Modo de condução",
				detail: canEditContent
					? "Abra uma sessão exclusiva para editar conteúdo e composição do Mundo."
					: "Abra uma sessão exclusiva para ajustar a composição do mapa.",
			};
	}
}

export function WorldConductorBar({
	context,
	canEditContent,
	busy,
	busyNotice,
	feedback,
	focusMode,
	inspectorOpen,
	onEnter,
	onPublish,
	onFinish,
	onDiscard,
	onToggleFocusMode,
	onToggleInspector,
	onOpenNavigation,
	onOpenCommandPalette,
}: WorldConductorBarProps) {
	const status = conductorStatus(context, canEditContent);
	const enter = worldCommand("world.enterConductor");
	const publish = worldCommand("world.publish");
	const finish = worldCommand("world.finishConductor");
	const discard = worldCommand("world.discard");
	const canEnter = worldCommandIsAvailable(enter.id, context);
	const canPublish = worldCommandIsAvailable(publish.id, context);
	const canFinish = worldCommandIsAvailable(finish.id, context);
	const canDiscard = worldCommandIsAvailable(discard.id, context);
	const active = context.editState === "editing" || context.editState === "publishing";

	useEffect(() => {
		if (!active) return;
		function openInspectorFromSelection() {
			if (!inspectorOpen) onToggleInspector();
		}
		window.addEventListener(WORLD_AUTHORING_OPEN_INSPECTOR_EVENT, openInspectorFromSelection);
		return () => {
			window.removeEventListener(
				WORLD_AUTHORING_OPEN_INSPECTOR_EVENT,
				openInspectorFromSelection,
			);
		};
	}, [active, inspectorOpen, onToggleInspector]);

	if (active && focusMode) {
		return (
			<section
				className={`${styles.root} ${styles.focusRoot}`}
				data-testid="world-conductor"
				data-world-conductor-state={context.editState}
				aria-label="Condução do Mundo"
			>
				<button
					type="button"
					className={styles.focusExit}
					onClick={onToggleFocusMode}
					aria-label="Mostrar interface de condução"
				>
					<span aria-hidden="true">⌘</span>
					Mostrar interface
				</button>
				<span className={styles.focusStatus} role="status">
					<span aria-hidden="true">●</span>
					{context.hasChanges ? "Rascunho alterado" : "Rascunho salvo"}
				</span>
			</section>
		);
	}

	return (
		<section
			className={`${styles.root} ${active ? styles.rootActive : ""}`}
			data-testid="world-conductor"
			data-world-conductor-state={context.editState}
			aria-label="Condução do Mundo"
		>
			<div
				className={`${styles.surface} ${active ? styles.surfaceActive : ""}`}
				data-world-conductor-surface
			>
				<div className={styles.status} data-world-conductor-status>
					<span className={styles.statusDot} aria-hidden="true" />
					<span className={styles.statusCopy}>
						<strong>{status.title}</strong>
						{!active ? <small>{status.detail}</small> : null}
					</span>
					{context.editState === "editing" ? (
						<span className={styles.draftBadge} data-dirty={context.hasChanges ? "true" : "false"}>
							{context.hasChanges ? "Rascunho alterado" : "Rascunho salvo"}
						</span>
					) : null}
				</div>

				<div className={styles.actions} data-world-conductor-actions>
					{context.editState === "view" || context.editState === "acquiring" ? (
						<button
							type="button"
							className={styles.primaryAction}
							disabled={!canEnter || busy}
							onClick={() => run(onEnter)}
							aria-label={canEditContent ? "Conduzir e editar o Mundo" : "Conduzir o layout do Mundo"}
						>
							<span aria-hidden="true">{context.editState === "acquiring" ? "…" : "✦"}</span>
							{context.editState === "acquiring" ? "Abrindo…" : enter.label}
						</button>
					) : context.editState === "publishing" ? (
						<button type="button" className={styles.primaryAction} disabled>
							<span aria-hidden="true">…</span>
							Publicando…
						</button>
					) : (
						<>
							<button type="button" className={styles.chromeAction} onClick={onOpenNavigation}>
								<span aria-hidden="true">☰</span>
								Menu
							</button>
							<button
								type="button"
								className={styles.chromeAction}
								onClick={onToggleInspector}
								aria-pressed={inspectorOpen}
							>
								<span aria-hidden="true">▤</span>
								Detalhes
							</button>
							<WorldCommandPaletteTrigger
								enabled={worldCommandIsAvailable("world.openCommandPalette", context)}
								onOpen={onOpenCommandPalette}
							/>
							<button type="button" className={styles.chromeAction} onClick={onToggleFocusMode}>
								<span aria-hidden="true">⌗</span>
								Foco
							</button>
							<button
								type="button"
								className={styles.primaryAction}
								disabled={busy || (!canPublish && !canFinish)}
								onClick={() => run(canPublish ? onPublish : onFinish)}
								aria-label={
									canPublish
										? canEditContent
											? "Publicar alterações do Mundo"
											: "Publicar alterações do layout"
										: "Concluir edição sem alterações"
								}
							>
								<span aria-hidden="true">{canPublish ? "↑" : "✓"}</span>
								{canPublish ? publish.label : finish.label}
							</button>
							<button
								type="button"
								className={styles.secondaryAction}
								disabled={busy || !canDiscard}
								onClick={() => run(onDiscard)}
							>
								{discard.label}
							</button>
						</>
					)}
				</div>
			</div>

			{busyNotice ? (
				<p className={styles.notice} role="status" data-world-conductor-notice>
					{busyNotice}
				</p>
			) : null}
			{feedback && !active ? (
				<p className={styles.feedback} role="status" aria-live="polite" data-world-conductor-notice>
					<span aria-hidden="true">{active ? "●" : "·"}</span>
					{feedback}
				</p>
			) : null}
		</section>
	);
}
