"use client";

import { useEffect, useRef } from "react";
import Image from "next/image";
import type { CSSProperties } from "react";
import type { LoreIdentityDTO, LorePresentation } from "../model";
import {
	resolveLoreMotionDefinition,
	resolveLoreScene,
} from "../presentation";
import styles from "./lore-cinematic-hero.module.css";

type LoreCinematicHeroProps = {
	identity: LoreIdentityDTO;
	presentation: LorePresentation;
	activeSceneId?: string | null;
};

export function LoreCinematicHero({
	identity,
	presentation,
	activeSceneId,
}: LoreCinematicHeroProps) {
	const rootRef = useRef<HTMLElement>(null);
	const scene = resolveLoreScene(presentation, activeSceneId);
	const motion = resolveLoreMotionDefinition(scene.motion);
	const layers = scene.hero.layers;
	const poster = scene.hero.poster;
	const artworkAlt = poster?.alt || `Ambientação visual de ${identity.name}`;

	useEffect(() => {
		const root = rootRef.current;
		if (!root || !scene.motion.pointerParallax) return;

		const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
		const coarsePointer = window.matchMedia("(pointer: coarse)");
		if (reducedMotion.matches || coarsePointer.matches) return;

		let frame = 0;
		let pointerX = 0;
		let pointerY = 0;

		const render = () => {
			frame = 0;
			for (const layer of root.querySelectorAll<HTMLElement>("[data-lore-depth]")) {
				const depth = Number(layer.dataset.loreDepth ?? 0);
				const x = pointerX * motion.pointerAmplitudeX * depth;
				const y = pointerY * motion.pointerAmplitudeY * depth;
				layer.style.setProperty(
					"--lore-pointer-transform",
					`translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0)`,
				);
			}
		};

		const scheduleRender = () => {
			if (!frame) frame = window.requestAnimationFrame(render);
		};

		const onPointerMove = (event: PointerEvent) => {
			const bounds = root.getBoundingClientRect();
			pointerX = ((event.clientX - bounds.left) / bounds.width - 0.5) * 2;
			pointerY = ((event.clientY - bounds.top) / bounds.height - 0.5) * 2;
			scheduleRender();
		};

		const onPointerLeave = () => {
			pointerX = 0;
			pointerY = 0;
			scheduleRender();
		};

		root.addEventListener("pointermove", onPointerMove, { passive: true });
		root.addEventListener("pointerleave", onPointerLeave, { passive: true });

		return () => {
			root.removeEventListener("pointermove", onPointerMove);
			root.removeEventListener("pointerleave", onPointerLeave);
			if (frame) window.cancelAnimationFrame(frame);
		};
	}, [
		motion.pointerAmplitudeX,
		motion.pointerAmplitudeY,
		scene.motion.pointerParallax,
	]);

	return (
		<header
			ref={rootRef}
			className={styles.hero}
			data-height={scene.hero.height}
			data-overlay={scene.hero.overlay}
			data-motion={scene.motion.preset}
			data-scene={activeSceneId ?? "base"}
			style={
				presentation.accent
					? ({ "--lore-accent": presentation.accent } as CSSProperties)
					: undefined
			}
		>
			<div className={styles.artwork} role="img" aria-label={artworkAlt}>
				{poster && layers.length === 0 ? (
					<div className={styles.poster}>
						<Image
							src={poster.src}
							alt=""
							fill
							preload
							sizes="100vw"
							style={{
								objectPosition: `${scene.hero.focalPoint.x}% ${scene.hero.focalPoint.y}%`,
							}}
						/>
					</div>
				) : null}

				{layers.map((layer) => {
					const scale =
						(layer.scale ?? 1.06) + motion.layerScaleBoost * layer.depth;
					return (
						<div
							key={`${activeSceneId ?? "base"}:${layer.id}`}
							className={styles.layer}
							data-lore-depth={layer.depth}
							data-role={layer.role}
						>
							<div
								className={styles.layerAsset}
								style={{
									opacity: layer.opacity ?? 1,
									filter: layer.blur ? `blur(${layer.blur}px)` : undefined,
									mixBlendMode: layer.blendMode,
									transform: `translate3d(${layer.offsetX ?? 0}px, ${layer.offsetY ?? 0}px, 0) scale(${scale})`,
								}}
							>
								<Image
									src={layer.src}
									alt=""
									fill
									preload={layer.role === "background" || layer.role === "subject"}
									sizes="100vw"
									style={{
										objectPosition: `${layer.objectPosition?.x ?? scene.hero.focalPoint.x}% ${layer.objectPosition?.y ?? scene.hero.focalPoint.y}%`,
									}}
								/>
							</div>
						</div>
					);
				})}

				{scene.atmosphere.effects.includes("fog") ? (
					<div className={styles.fog} aria-hidden="true" />
				) : null}
				{scene.atmosphere.effects.includes("dust") ? (
					<div className={styles.dust} aria-hidden="true" />
				) : null}
				<div className={styles.overlay} aria-hidden="true" />
				<div className={styles.vignette} aria-hidden="true" />
			</div>

			<div className={styles.content}>
				{identity.eyebrow ? <p className={styles.eyebrow}>{identity.eyebrow}</p> : null}
				<h1 className={styles.title}>{identity.name}</h1>
				{identity.epithet ? <p className={styles.epithet}>{identity.epithet}</p> : null}
				{identity.summary ? <p className={styles.summary}>{identity.summary}</p> : null}
				{identity.tags?.length ? (
					<ul className={styles.tags} aria-label="Características">
						{identity.tags.map((tag) => (
							<li key={tag}>{tag}</li>
						))}
					</ul>
				) : null}
			</div>
		</header>
	);
}
