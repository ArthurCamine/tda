export type CanonicalRelationIdentity = Readonly<{
	id: string;
}>;

export type CanonicalRelationSourceIdentity = Readonly<{
	relation_id: string;
	canon_entry_id: string;
}>;

/**
 * Returns only relations backed by at least one reviewed canon entry.
 *
 * `canon_entries` is the post-review publication boundary defined by ADR-0005.
 * Callers must scope `canonEntryIds` to the same campaign before invoking this
 * helper so a stale or cross-campaign source cannot authorize a public edge.
 */
export function evidenceBackedRelationIds(
	relations: readonly CanonicalRelationIdentity[],
	sources: readonly CanonicalRelationSourceIdentity[],
	canonEntryIds: readonly string[],
): Set<string> {
	const candidateRelationIds = new Set(relations.map((relation) => relation.id));
	const reviewedCanonEntryIds = new Set(canonEntryIds);
	const backedRelationIds = new Set<string>();

	for (const source of sources) {
		if (
			candidateRelationIds.has(source.relation_id) &&
			reviewedCanonEntryIds.has(source.canon_entry_id)
		) {
			backedRelationIds.add(source.relation_id);
		}
	}

	return backedRelationIds;
}
