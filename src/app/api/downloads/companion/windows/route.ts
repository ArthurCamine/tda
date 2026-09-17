import {
	isCompanionInstallableTag,
	selectCompanionInstallableAssetInfo,
} from "@/features/edit/processing/companion-release";
import { selectLatestCompanionStableRelease } from "@/features/edit/processing/companion-stable-release";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const RELEASES_URL = "https://api.github.com/repos/Faysk/tda/releases?per_page=100";
const RELEASE_BY_TAG_URL = "https://api.github.com/repos/Faysk/tda/releases/tags/";
const VERSION_PATTERN = /^(\d+)\.(\d+)\.(\d+)$/;
const GITHUB_HEADERS = {
	Accept: "application/vnd.github+json",
	"X-GitHub-Api-Version": "2022-11-28",
};
const NO_STORE_HEADERS = {
	"Cache-Control": "no-store, max-age=0",
	Pragma: "no-cache",
};

async function latestStable() {
	const response = await fetch(RELEASES_URL, {
		headers: GITHUB_HEADERS,
		cache: "no-store",
	});
	if (!response.ok) throw new Error("COMPANION_RELEASE_LOOKUP_FAILED");
	return selectLatestCompanionStableRelease(await response.json());
}

export async function GET(request: Request) {
	try {
		const requestUrl = new URL(request.url);
		const versions = requestUrl.searchParams.getAll("version");
		const tags = requestUrl.searchParams.getAll("tag");
		const unexpectedQuery = Array.from(requestUrl.searchParams.keys()).some(
			(key) => key !== "version" && key !== "tag",
		);
		if (
			versions.length > 1 ||
			tags.length > 1 ||
			(versions.length > 0 && tags.length > 0) ||
			unexpectedQuery
		) {
			return Response.json(
				{ error: "COMPANION_RELEASE_REQUEST_INVALID" },
				{ status: 400, headers: NO_STORE_HEADERS },
			);
		}

		const requestedVersion = versions[0] ?? null;
		const requestedTag = tags[0] ?? null;
		if (requestedVersion !== null && !VERSION_PATTERN.test(requestedVersion)) {
			return Response.json(
				{ error: "COMPANION_RELEASE_REQUEST_INVALID" },
				{ status: 400, headers: NO_STORE_HEADERS },
			);
		}
		if (requestedTag !== null && !isCompanionInstallableTag(requestedTag)) {
			return Response.json(
				{ error: "COMPANION_RELEASE_REQUEST_INVALID" },
				{ status: 400, headers: NO_STORE_HEADERS },
			);
		}

		if (!requestedVersion && !requestedTag) {
			const latest = await latestStable();
			if (!latest) {
				return Response.json(
					{ error: "COMPANION_RELEASE_NOT_FOUND" },
					{ status: 404, headers: NO_STORE_HEADERS },
				);
			}
			return new Response(null, {
				status: 307,
				headers: {
					Location: latest.url,
					...NO_STORE_HEADERS,
				},
			});
		}

		const tag = requestedTag ?? `companion-v${requestedVersion}`;
		const releaseResponse = await fetch(`${RELEASE_BY_TAG_URL}${encodeURIComponent(tag)}`, {
			headers: GITHUB_HEADERS,
			cache: "no-store",
		});
		if (releaseResponse.status === 404) {
			return Response.json(
				{ error: "COMPANION_RELEASE_NOT_FOUND" },
				{ status: 404, headers: NO_STORE_HEADERS },
			);
		}
		if (!releaseResponse.ok) {
			return Response.json(
				{ error: "COMPANION_RELEASE_LOOKUP_FAILED" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}

		const asset = selectCompanionInstallableAssetInfo(await releaseResponse.json(), tag);
		if (!asset) {
			return Response.json(
				{ error: "COMPANION_RELEASE_INVALID" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}

		return new Response(null, {
			status: 307,
			headers: {
				Location: asset.url,
				...NO_STORE_HEADERS,
			},
		});
	} catch {
		return Response.json(
			{ error: "COMPANION_RELEASE_LOOKUP_FAILED" },
			{ status: 503, headers: NO_STORE_HEADERS },
		);
	}
}
