import { selectLatestCompanionRcRelease } from "@/features/edit/processing/companion-rc-release";
import { selectLatestCompanionStableRelease } from "@/features/edit/processing/companion-stable-release";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const RELEASES_URL = "https://api.github.com/repos/Faysk/tda/releases";
const RELEASES_PER_PAGE = 100;
const MAX_RELEASE_PAGES = 5;
const RELEASE_LOOKUP_REVALIDATE_SECONDS = 60;
const GITHUB_HEADERS = {
	Accept: "application/vnd.github+json",
	"X-GitHub-Api-Version": "2022-11-28",
};
const NO_STORE_HEADERS = {
	"Cache-Control": "no-store, max-age=0",
	Pragma: "no-cache",
	"X-Content-Type-Options": "nosniff",
};

type CompanionManifestChannel = "stable" | "rc";

function requestedChannel(request: Request): CompanionManifestChannel | null {
	const url = new URL(request.url);
	const channels = url.searchParams.getAll("channel");
	const unexpected = Array.from(url.searchParams.keys()).some((key) => key !== "channel");
	if (unexpected || channels.length > 1) return null;
	const channel = channels[0] ?? "stable";
	return channel === "stable" || channel === "rc" ? channel : null;
}

async function fetchReleaseCatalog(): Promise<unknown[]> {
	const releases: unknown[] = [];
	for (let page = 1; page <= MAX_RELEASE_PAGES; page += 1) {
		const response = await fetch(
			`${RELEASES_URL}?per_page=${RELEASES_PER_PAGE}&page=${page}`,
			{
				headers: GITHUB_HEADERS,
				next: { revalidate: RELEASE_LOOKUP_REVALIDATE_SECONDS },
			},
		);
		if (!response.ok) throw new Error("COMPANION_RELEASE_LOOKUP_FAILED");
		const value = await response.json();
		if (!Array.isArray(value)) throw new Error("COMPANION_RELEASE_LOOKUP_INVALID");
		releases.push(...value);
		if (value.length < RELEASES_PER_PAGE) break;
	}
	return releases;
}

export async function GET(request: Request) {
	const channel = requestedChannel(request);
	if (!channel) {
		return Response.json(
			{ error: "COMPANION_RELEASE_REQUEST_INVALID" },
			{ status: 400, headers: NO_STORE_HEADERS },
		);
	}

	try {
		const releases = await fetchReleaseCatalog();
		const asset =
			channel === "rc"
				? selectLatestCompanionRcRelease(releases)
				: selectLatestCompanionStableRelease(releases);
		if (!asset) {
			return Response.json(
				{ error: "COMPANION_RELEASE_NOT_FOUND" },
				{ status: 404, headers: NO_STORE_HEADERS },
			);
		}

		return Response.json(
			{
				channel,
				version: asset.version,
				tag: asset.tag,
				minimum_api: "1",
				asset: {
					url: `/api/downloads/companion/windows?tag=${encodeURIComponent(asset.tag)}`,
					sha256: asset.sha256,
					size: asset.size,
				},
			},
			{ headers: NO_STORE_HEADERS },
		);
	} catch {
		return Response.json(
			{ error: "COMPANION_RELEASE_LOOKUP_FAILED" },
			{ status: 503, headers: NO_STORE_HEADERS },
		);
	}
}
