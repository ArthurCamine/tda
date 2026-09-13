import type { LoreProfileDTO } from "./model";

export type PublishedLorePortrait = Readonly<{
	imageUrl: string;
	focalPoint: Readonly<{ x: number; y: number }>;
}>;

function unitToPercent(value: number): number {
	if (!Number.isFinite(value)) return 50;
	return Math.min(100, Math.max(0, value * 100));
}

/**
 * Reuses the verified public World portrait only when the lore profile has no
 * authored hero media of its own. Bespoke cinematic/poster art always wins.
 */
export function withPublishedLorePortraitFallback(
	profile: LoreProfileDTO,
	portrait: PublishedLorePortrait | undefined,
): LoreProfileDTO {
	if (!portrait) return profile;
	if (profile.presentation.hero.poster || profile.presentation.hero.layers.length > 0) {
		return profile;
	}

	return {
		...profile,
		presentation: {
			...profile.presentation,
			hero: {
				...profile.presentation.hero,
				poster: {
					src: portrait.imageUrl,
					alt: `Retrato de ${profile.identity.name}`,
				},
				focalPoint: {
					x: unitToPercent(portrait.focalPoint.x),
					y: unitToPercent(portrait.focalPoint.y),
				},
			},
		},
	};
}
