"use server";

import { worldEntityMediaEnabled } from "./world-entity-media-server";

/**
 * Keeps the client editor fail-closed while the candidate schema/R2 contract is
 * not enabled in the current environment. This exposes only a boolean feature
 * state; storage credentials and object identity remain server-only.
 */
export async function worldEntityMediaAvailabilityAction(): Promise<boolean> {
	return worldEntityMediaEnabled();
}
