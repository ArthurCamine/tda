"use client";

import { useEffect, useState } from "react";

const DEFAULT_URL = "/api/downloads/companion/windows";
const MANIFEST_URL = "/api/downloads/companion/windows/manifest";
const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;

export type CompanionDownloadInfo = {
	version: string;
	url: string;
};

export function parseCompanionDownloadManifest(value: unknown): CompanionDownloadInfo | null {
	if (!value || typeof value !== "object") return null;
	const manifest = value as { version?: unknown; asset?: unknown };
	if (typeof manifest.version !== "string" || !VERSION_PATTERN.test(manifest.version)) {
		return null;
	}
	if (!manifest.asset || typeof manifest.asset !== "object") return null;
	const url = (manifest.asset as { url?: unknown }).url;
	const expectedUrl = `${DEFAULT_URL}?version=${encodeURIComponent(manifest.version)}`;
	if (url !== expectedUrl) return null;
	return { version: manifest.version, url: expectedUrl };
}

export function CompanionDownload({ className }: { className?: string }) {
	const [download, setDownload] = useState<CompanionDownloadInfo | null>(null);

	useEffect(() => {
		const controller = new AbortController();
		void fetch(MANIFEST_URL, { cache: "no-store", signal: controller.signal })
			.then(async (response) => {
				if (!response.ok) return null;
				return parseCompanionDownloadManifest(await response.json());
			})
			.then((value) => {
				if (value) setDownload(value);
			})
			.catch(() => undefined);
		return () => controller.abort();
	}, []);

	const subtitle = download
		? `v${download.version} · Windows x64 · .msi`
		: "Windows x64 · .msi";
	const title = download
		? `TDA Companion v${download.version} · Windows x64`
		: "Windows x64 · versão estável mais recente";

	return (
		<a className={className} href={download?.url ?? DEFAULT_URL} title={title}>
			<span>Baixar TDA Companion</span>
			<small>{subtitle}</small>
		</a>
	);
}
