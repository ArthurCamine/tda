import { createHash } from "node:crypto";
import {
	selectLatestQwenRuntimeTag,
	selectQwenRuntimeBundleManifestAssetInfo,
	selectQwenRuntimePartAssetInfo,
} from "@/features/edit/processing/companion-release";
import { parseQwenRuntimeBundle } from "@/features/edit/processing/qwen-runtime-bundle";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const TAGS_URL =
	"https://api.github.com/repos/Faysk/tda/git/matching-refs/tags/companion-qwen-runtime-v";
const RELEASE_BY_TAG_URL = "https://api.github.com/repos/Faysk/tda/releases/tags/";
const GITHUB_HEADERS = {
	Accept: "application/vnd.github+json",
	"X-GitHub-Api-Version": "2022-11-28",
};
const MAX_MANIFEST_BYTES = 256 * 1024;
const NO_STORE_HEADERS = {
	"Cache-Control": "no-store, max-age=0",
	Pragma: "no-cache",
	"X-Content-Type-Options": "nosniff",
};

function sha256(value: Uint8Array): string {
	return createHash("sha256").update(value).digest("hex");
}

export async function GET() {
	try {
		const tagsResponse = await fetch(TAGS_URL, {
			headers: GITHUB_HEADERS,
			cache: "no-store",
		});
		if (!tagsResponse.ok) {
			return Response.json(
				{ error: "QWEN_RUNTIME_RELEASE_LOOKUP_FAILED" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}
		const tag = selectLatestQwenRuntimeTag(await tagsResponse.json());
		if (!tag) {
			return Response.json(
				{ error: "QWEN_RUNTIME_RELEASE_NOT_FOUND" },
				{ status: 404, headers: NO_STORE_HEADERS },
			);
		}

		const releaseResponse = await fetch(`${RELEASE_BY_TAG_URL}${encodeURIComponent(tag)}`, {
			headers: GITHUB_HEADERS,
			cache: "no-store",
		});
		if (!releaseResponse.ok) {
			return Response.json(
				{ error: "QWEN_RUNTIME_RELEASE_LOOKUP_FAILED" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}
		const release = await releaseResponse.json();
		const manifestAsset = selectQwenRuntimeBundleManifestAssetInfo(release, tag);
		if (!manifestAsset || manifestAsset.size > MAX_MANIFEST_BYTES) {
			return Response.json(
				{ error: "QWEN_RUNTIME_RELEASE_INVALID" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}

		const assetResponse = await fetch(manifestAsset.url, {
			headers: { Accept: "application/json" },
			cache: "no-store",
			redirect: "follow",
		});
		if (!assetResponse.ok) {
			return Response.json(
				{ error: "QWEN_RUNTIME_BUNDLE_LOOKUP_FAILED" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}
		const body = new Uint8Array(await assetResponse.arrayBuffer());
		if (
			body.byteLength !== manifestAsset.size ||
			body.byteLength > MAX_MANIFEST_BYTES ||
			sha256(body) !== manifestAsset.sha256
		) {
			return Response.json(
				{ error: "QWEN_RUNTIME_BUNDLE_INVALID" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}
		let raw: unknown;
		try {
			raw = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
		} catch {
			return Response.json(
				{ error: "QWEN_RUNTIME_BUNDLE_INVALID" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}
		const bundle = parseQwenRuntimeBundle(raw, manifestAsset.version);
		if (!bundle) {
			return Response.json(
				{ error: "QWEN_RUNTIME_BUNDLE_INVALID" },
				{ status: 503, headers: NO_STORE_HEADERS },
			);
		}
		for (const part of bundle.parts) {
			const asset = selectQwenRuntimePartAssetInfo(release, tag, part.name);
			if (!asset || asset.size !== part.size || asset.sha256 !== part.sha256) {
				return Response.json(
					{ error: "QWEN_RUNTIME_RELEASE_PART_MISMATCH" },
					{ status: 503, headers: NO_STORE_HEADERS },
				);
			}
		}

		return Response.json(
			{
				channel: "stable",
				runtime_id: "qwen3-transformers",
				version: manifestAsset.version,
				tag,
				bundle,
			},
			{ headers: NO_STORE_HEADERS },
		);
	} catch {
		return Response.json(
			{ error: "QWEN_RUNTIME_RELEASE_LOOKUP_FAILED" },
			{ status: 503, headers: NO_STORE_HEADERS },
		);
	}
}
