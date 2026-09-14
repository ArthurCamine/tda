import {
	selectCompanionAsset,
	selectLatestCompanionTag,
} from "@/features/edit/processing/companion-release";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const TAGS_URL =
	"https://api.github.com/repos/Faysk/tda/git/matching-refs/tags/companion-v";
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

async function latestTag(): Promise<string | null> {
	const tagsResponse = await fetch(TAGS_URL, {
		headers: GITHUB_HEADERS,
		cache: "no-store",
	});
	if (!tagsResponse.ok) throw new Error("COMPANION_RELEASE_LOOKUP_FAILED");
	return selectLatestCompanionTag(await tagsResponse.json());
}

export async function GET(request: Request) {
	try {
		const requestUrl = new URL(request.url);
		const versions = requestUrl.searchParams.getAll("version");
		const unexpectedQuery = Array.from(requestUrl.searchParams.keys()).some(
			(key) => key !== "version",
		);
		if (versions.length > 1 || unexpectedQuery) {
			return Response.json(
				{ error: "COMPANION_RELEASE_REQUEST_INVALID" },
				{ status: 400, headers: NO_STORE_HEADERS },
			);
		}

		const requestedVersion = versions[0] ?? null;
		if (requestedVersion !== null && !VERSION_PATTERN.test(requestedVersion)) {
			return Response.json(
				{ error: "COMPANION_RELEASE_REQUEST_INVALID" },
				{ status: 400, headers: NO_STORE_HEADERS },
			);
		}

		const tag = requestedVersion
			? `companion-v${requestedVersion}`
			: await latestTag();
		if (!tag) {
			return Response.json(
				{ error: "COMPANION_RELEASE_NOT_FOUND" },
				{ status: 404, headers: NO_STORE_HEADERS },
			);
		}

		const releaseResponse = await fetch(`${RELEASE_BY_TAG_URL}${encodeURIComponent(tag)}`, {
			headers: GITHUB_HEADERS,
			cache: "no-store",
		});
		if (releaseResponse.status === 404 && requestedVersion) {
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

		const downloadUrl = selectCompanionAsset(await releaseResponse.json(), tag);
		if (!downloadUrl) {
			return Response.json(
				{ error: "COMPANION_RELEASE_INVALID" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}

		return new Response(null, {
			status: 307,
			headers: {
				Location: downloadUrl,
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
