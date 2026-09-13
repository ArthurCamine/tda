import type { WorldGraphDraft } from "./model";

/**
 * Distinguishes an untouched graph from a graph that explicitly changes media.
 * `null` still counts as intent because it means remove the current portrait.
 */
export function worldEntityMediaDraftHasIntent(draft: WorldGraphDraft): boolean {
	return draft.nodes.some((node) => node.primaryMediaAssetId !== undefined);
}
