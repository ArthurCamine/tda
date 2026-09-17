"use client";

import { useEffect, useState } from "react";

const DEFAULT_URL = "/api/downloads/companion/windows";
const MANIFEST_URL = "/api/downloads/companion/windows/manifest";
const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;
const STABLE_TAG_PATTERN = /^companion-v(\d+\.\d+\.\d+)$/;
const RC_TAG_PATTERN = /^companion-rc-v(\d+\.\d+\.\d+)-[a-f0-9]{12}$/;

export type CompanionDownloadChannel = "stable" | "rc";

export type CompanionDownloadInfo = {
	version: string;
	channel: CompanionDownloadChannel;
	tag: string;
	url: string;
};

export function companionManifestUrl(channel: CompanionDownloadChannel): string {
	return channel === "rc" ? `${MANIFEST_URL}?channel=rc` : MANIFEST_URL;
}

export function parseCompanionDownloadManifest(value: unknown): CompanionDownloadInfo | null {
	if (!value || typeof value !== "object") return null;
	const manifest = value as {
		version?: unknown;
		channel?: unknown;
		tag?: unknown;
		asset?: unknown;
	};
	if (typeof manifest.version !== "string" || !VERSION_PATTERN.test(manifest.version)) {
		return null;
	}
	if (manifest.channel !== "stable" && manifest.channel !== "rc") return null;
	if (typeof manifest.tag !== "string") return null;

	const tagMatch =
		manifest.channel === "stable"
			? STABLE_TAG_PATTERN.exec(manifest.tag)
			: RC_TAG_PATTERN.exec(manifest.tag);
	if (!tagMatch || tagMatch[1] !== manifest.version) return null;

	if (!manifest.asset || typeof manifest.asset !== "object") return null;
	const url = (manifest.asset as { url?: unknown }).url;
	const expectedUrl = `${DEFAULT_URL}?tag=${encodeURIComponent(manifest.tag)}`;
	if (url !== expectedUrl) return null;
	return {
		version: manifest.version,
		channel: manifest.channel,
		tag: manifest.tag,
		url: expectedUrl,
	};
}

export function CompanionDownload({
	className,
	channel = "stable",
}: {
	className?: string;
	channel?: CompanionDownloadChannel;
}) {
	const [download, setDownload] = useState<CompanionDownloadInfo | null>(null);

	useEffect(() => {
		const controller = new AbortController();
		setDownload(null);
		void fetch(companionManifestUrl(channel), {
			cache: "no-store",
			signal: controller.signal,
		})
			.then(async (response) => {
				if (!response.ok) return null;
				const value = parseCompanionDownloadManifest(await response.json());
				return value?.channel === channel ? value : null;
			})
			.then((value) => {
				if (value) setDownload(value);
			})
			.catch(() => undefined);
		return () => controller.abort();
	}, [channel]);

	// RC is never a fallback/default download. It only appears after the explicit
	// RC manifest resolves to a pinned prerelease tag.
	if (channel === "rc" && !download) return null;

	const channelLabel = download?.channel === "rc" ? "RC" : "Stable";
	const subtitle = download
		? `v${download.version} ${channelLabel} · Windows x64 · .msi`
		: "Windows x64 · .msi";
	const title = download
		? `TDA Companion v${download.version} ${channelLabel} · Windows x64`
		: "Windows x64 · versão stable mais recente disponível";
	const label = channel === "rc" ? "Testar TDA Companion RC" : "Baixar TDA Companion";

	return (
		<a
			className={className}
			href={download?.url ?? DEFAULT_URL}
			title={title}
		>
			<span>{label}</span>
			<small>{subtitle}</small>
		</a>
	);
}
