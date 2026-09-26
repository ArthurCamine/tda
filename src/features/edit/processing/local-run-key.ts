import type { LocalRunSummary } from "./protocol";

export type LocalRunKey = Readonly<{
	sourceId: string;
	runId: string;
}>;

export function localRunKey(
	run: Pick<LocalRunSummary, "sourceId" | "runId">,
): LocalRunKey {
	return { sourceId: run.sourceId, runId: run.runId };
}

export function sameLocalRun(
	key: LocalRunKey | null,
	run: Pick<LocalRunSummary, "sourceId" | "runId">,
): boolean {
	return (
		key !== null &&
		key.sourceId === run.sourceId &&
		key.runId === run.runId
	);
}

export function serializeLocalRunKey(key: LocalRunKey): string {
	return JSON.stringify(["tda_local_run_key_v1", key.sourceId, key.runId]);
}
