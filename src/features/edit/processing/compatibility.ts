const TERMINAL_JOB_DELETE_MINIMUM = [0, 3, 11] as const;

function parseVersion(value: string | null | undefined): readonly [number, number, number] | null {
	if (!value) return null;
	const match = /^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/u.exec(value.trim());
	if (!match) return null;
	return [Number(match[1]), Number(match[2]), Number(match[3])];
}

export function supportsTerminalJobDelete(
	serviceVersion: string | null | undefined,
): boolean {
	const parsed = parseVersion(serviceVersion);
	if (!parsed) return false;
	for (let index = 0; index < TERMINAL_JOB_DELETE_MINIMUM.length; index++) {
		if (parsed[index] > TERMINAL_JOB_DELETE_MINIMUM[index]) return true;
		if (parsed[index] < TERMINAL_JOB_DELETE_MINIMUM[index]) return false;
	}
	return true;
}
