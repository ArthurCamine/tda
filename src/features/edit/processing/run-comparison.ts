import type { LocalReviewSegment, LocalRunSummary } from "./protocol";
import { localRunKey, sameLocalRun, type LocalRunKey } from "./local-run-key";

export type RunComparisonKind = "equal" | "changed" | "left_only" | "right_only";

export type RunComparisonRegion = Readonly<{
	id: string;
	trackNumber: number;
	start: number;
	end: number;
	kind: RunComparisonKind;
	left: readonly LocalReviewSegment[];
	right: readonly LocalReviewSegment[];
	leftText: string;
	rightText: string;
	speakerChanged: boolean;
}>;

export type RunComparisonSummary = Readonly<{
	totalRegions: number;
	equalRegions: number;
	changedRegions: number;
	leftOnlyRegions: number;
	rightOnlyRegions: number;
	speakerChangedRegions: number;
	differentRegions: number;
}>;

const DEFAULT_TIME_TOLERANCE_SECONDS = 0.35;
const MAX_COMPARISON_SEGMENTS = 500_000;
const TIME_EPSILON = 1e-9;

function compareCanonicalText(left: string, right: string): number {
	return left < right ? -1 : left > right ? 1 : 0;
}

function normalizedText(value: string): string {
	return value.normalize("NFC").replace(/\s+/gu, " ").trim();
}

function speakerSequence(values: readonly LocalReviewSegment[]): string {
	const sequence: string[] = [];
	for (const item of values) {
		const speaker = item.speaker.trim();
		if (sequence.at(-1) !== speaker) sequence.push(speaker);
	}
	return JSON.stringify(sequence);
}

function ordered(values: readonly LocalReviewSegment[]): LocalReviewSegment[] {
	return [...values].sort(
		(left, right) =>
			left.trackNumber - right.trackNumber ||
			left.start - right.start ||
			left.end - right.end ||
			compareCanonicalText(left.segmentId, right.segmentId),
	);
}

function comparableInTime(
	left: LocalReviewSegment,
	right: LocalReviewSegment,
	tolerance: number,
): boolean {
	const overlap =
		Math.min(left.end, right.end) - Math.max(left.start, right.start);
	if (overlap > TIME_EPSILON) return true;
	const gap =
		Math.max(left.start, right.start) - Math.min(left.end, right.end);
	return gap > TIME_EPSILON && gap <= tolerance + TIME_EPSILON;
}

function regionId(
	trackNumber: number,
	kind: RunComparisonKind,
	left: readonly LocalReviewSegment[],
	right: readonly LocalReviewSegment[],
): string {
	return JSON.stringify([
		"tda_run_comparison_region_v1",
		trackNumber,
		kind,
		left.map((item) => [item.trackNumber, item.segmentId]),
		right.map((item) => [item.trackNumber, item.segmentId]),
	]);
}

function buildRegion(
	trackNumber: number,
	leftInput: readonly LocalReviewSegment[],
	rightInput: readonly LocalReviewSegment[],
): RunComparisonRegion {
	const left = ordered(leftInput);
	const right = ordered(rightInput);
	const all = [...left, ...right];
	const start = Math.min(...all.map((item) => item.start));
	const end = Math.max(...all.map((item) => item.end));
	const leftText = left.map((item) => item.text).join(" ").trim();
	const rightText = right.map((item) => item.text).join(" ").trim();
	const kind: RunComparisonKind =
		left.length === 0
			? "right_only"
			: right.length === 0
				? "left_only"
				: normalizedText(leftText) === normalizedText(rightText)
					? "equal"
					: "changed";
	return {
		id: regionId(trackNumber, kind, left, right),
		trackNumber,
		start,
		end,
		kind,
		left,
		right,
		leftText,
		rightText,
		speakerChanged:
			left.length > 0 &&
			right.length > 0 &&
			speakerSequence(left) !== speakerSequence(right),
	};
}

function compareTrack(
	trackNumber: number,
	leftInput: readonly LocalReviewSegment[],
	rightInput: readonly LocalReviewSegment[],
	tolerance: number,
): RunComparisonRegion[] {
	const left = ordered(leftInput);
	const right = ordered(rightInput);
	const regions: RunComparisonRegion[] = [];
	let leftIndex = 0;
	let rightIndex = 0;

	while (leftIndex < left.length || rightIndex < right.length) {
		const leftSegment = left[leftIndex];
		const rightSegment = right[rightIndex];

		if (!leftSegment && rightSegment) {
			regions.push(buildRegion(trackNumber, [], [rightSegment]));
			rightIndex += 1;
			continue;
		}
		if (leftSegment && !rightSegment) {
			regions.push(buildRegion(trackNumber, [leftSegment], []));
			leftIndex += 1;
			continue;
		}
		if (!leftSegment || !rightSegment) break;

		if (!comparableInTime(leftSegment, rightSegment, tolerance)) {
			if (
				leftSegment.end < rightSegment.start ||
				(leftSegment.end === rightSegment.start &&
					leftSegment.start <= rightSegment.start)
			) {
				regions.push(buildRegion(trackNumber, [leftSegment], []));
				leftIndex += 1;
			} else {
				regions.push(buildRegion(trackNumber, [], [rightSegment]));
				rightIndex += 1;
			}
			continue;
		}

		const leftValues = [leftSegment];
		const rightValues = [rightSegment];
		leftIndex += 1;
		rightIndex += 1;

		if (leftSegment.end > rightSegment.end + TIME_EPSILON) {
			while (rightIndex < right.length) {
				const candidate = right[rightIndex];
				if (
					!candidate ||
					candidate.start >= leftSegment.end - TIME_EPSILON ||
					!comparableInTime(leftSegment, candidate, tolerance)
				)
					break;
				rightValues.push(candidate);
				rightIndex += 1;
			}
		} else if (rightSegment.end > leftSegment.end + TIME_EPSILON) {
			while (leftIndex < left.length) {
				const candidate = left[leftIndex];
				if (
					!candidate ||
					candidate.start >= rightSegment.end - TIME_EPSILON ||
					!comparableInTime(candidate, rightSegment, tolerance)
				)
					break;
				leftValues.push(candidate);
				leftIndex += 1;
			}
		}

		regions.push(buildRegion(trackNumber, leftValues, rightValues));
	}

	return regions.sort(
		(leftRegion, rightRegion) =>
			leftRegion.start - rightRegion.start ||
			leftRegion.end - rightRegion.end ||
			compareCanonicalText(leftRegion.id, rightRegion.id),
	);
}

export function compareRunSegments(
	leftInput: readonly LocalReviewSegment[],
	rightInput: readonly LocalReviewSegment[],
	options: Readonly<{ timeToleranceSeconds?: number }> = {},
): RunComparisonRegion[] {
	const tolerance =
		options.timeToleranceSeconds ?? DEFAULT_TIME_TOLERANCE_SECONDS;
	if (!Number.isFinite(tolerance) || tolerance < 0 || tolerance > 5)
		throw new Error("RUN_COMPARISON_TOLERANCE_INVALID");
	if (leftInput.length + rightInput.length > MAX_COMPARISON_SEGMENTS)
		throw new Error("RUN_COMPARISON_SEGMENT_LIMIT");

	const left = ordered(leftInput);
	const right = ordered(rightInput);
	const tracks = [
		...new Set([
			...left.map((item) => item.trackNumber),
			...right.map((item) => item.trackNumber),
		]),
	].sort((a, b) => a - b);

	return tracks.flatMap((trackNumber) =>
		compareTrack(
			trackNumber,
			left.filter((item) => item.trackNumber === trackNumber),
			right.filter((item) => item.trackNumber === trackNumber),
			tolerance,
		),
	);
}

export function summarizeRunComparison(
	regions: readonly RunComparisonRegion[],
): RunComparisonSummary {
	let equalRegions = 0;
	let changedRegions = 0;
	let leftOnlyRegions = 0;
	let rightOnlyRegions = 0;
	let speakerChangedRegions = 0;
	for (const region of regions) {
		if (region.kind === "equal") equalRegions += 1;
		else if (region.kind === "changed") changedRegions += 1;
		else if (region.kind === "left_only") leftOnlyRegions += 1;
		else rightOnlyRegions += 1;
		if (region.speakerChanged) speakerChangedRegions += 1;
	}
	return {
		totalRegions: regions.length,
		equalRegions,
		changedRegions,
		leftOnlyRegions,
		rightOnlyRegions,
		speakerChangedRegions,
		differentRegions: regions.filter(
			(region) => region.kind !== "equal" || region.speakerChanged,
		).length,
	};
}

export function runsShareComparisonSource(
	left: LocalRunKey,
	right: LocalRunKey,
): boolean {
	return left.sourceId === right.sourceId && !sameLocalRun(left, right);
}

export function comparisonRunKey(
	run: Pick<LocalRunSummary, "sourceId" | "runId">,
): LocalRunKey {
	return localRunKey(run);
}
