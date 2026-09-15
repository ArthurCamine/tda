import { selectLatestCompanionInstallableRelease } from "@/features/edit/processing/companion-release";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const RELEASES_URL = "https://api.github.com/repos/Faysk/tda/releases?per_page=100";
const GITHUB_HEADERS = {
	Accept: "application/vnd.github+json",
	"X-GitHub-Api-Version": "2022-11-28",
};
const NO_STORE_HEADERS = {
	"Cache-Control": "no-store, max-age=0",
	Pragma: "no-cache",
	"X-Content-Type-Options": "nosniff",
};

export async function GET() {
	try {
		const releasesResponse = await fetch(RELEASES_URL, {
			headers: GITHUB_HEADERS,
			cache: "no-store",
		});
		if (!releasesResponse.ok) {
			return Response.json(
				{ error: "COMPANION_RELEASE_LOOKUP_FAILED" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}

		const asset = selectLatestCompanionInstallableRelease(await releasesResponse.json());
		if (!asset) {
			return Response.json(
				{ error: "COMPANION_RELEASE_NOT_FOUND" },
				{ status: 404, headers: NO_STORE_HEADERS },
			);
		}

		return Response.json(
			{
				channel: asset.channel,
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
