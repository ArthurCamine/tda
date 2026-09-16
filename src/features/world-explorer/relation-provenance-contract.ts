export function relationHasActiveCanonProvenance(
	persisted: boolean,
	selectedCanonEntryIds: readonly string[],
	activeCanonEntryIds: readonly string[],
): boolean {
	if (!persisted || selectedCanonEntryIds.length === 0 || activeCanonEntryIds.length === 0) {
		return false;
	}
	const activeCanonEntries = new Set(activeCanonEntryIds);
	return selectedCanonEntryIds.some((id) => activeCanonEntries.has(id));
}
