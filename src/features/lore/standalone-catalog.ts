import catalog from "./standalone-catalog.json";

/** Editorial links only; never changes an entity's profile route or canon. */
export function standaloneLoreForEntity(
	entityType: string | undefined,
	slug: string | null,
) {
	if (entityType !== "pc" || !slug) return null;
	return catalog.find((lore) => lore.slug === slug) ?? null;
}
