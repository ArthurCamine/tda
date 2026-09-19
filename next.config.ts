import type { NextConfig } from "next";
import diaries from "./src/features/diary/catalog.json";
import standaloneLores from "./src/features/lore/standalone-catalog.json";

const standaloneNoindexLores = ["d", "yllith"] as const;
const canonicalSupabaseOrigin = "https://dmrqnbdvbkfqzctcerbx.supabase.co";
const canonicalSupabaseWebsocketOrigin =
	"wss://dmrqnbdvbkfqzctcerbx.supabase.co";
const canonicalMediaOrigin = "https://media.dnd.faysk.dev";

const contentSecurityPolicyReportOnly = [
	"default-src 'self'",
	"base-uri 'self'",
	"object-src 'none'",
	"frame-ancestors 'none'",
	"form-action 'self'",
	"script-src 'self' 'unsafe-inline'",
	"style-src 'self' 'unsafe-inline'",
	`img-src 'self' data: blob: ${canonicalMediaOrigin} ${canonicalSupabaseOrigin}`,
	"font-src 'self' data:",
	`connect-src 'self' ${canonicalSupabaseOrigin} ${canonicalSupabaseWebsocketOrigin} ${canonicalMediaOrigin}`,
	`media-src 'self' blob: ${canonicalMediaOrigin}`,
	"worker-src 'self' blob:",
	"manifest-src 'self'",
].join("; ");

const config: NextConfig = {
	poweredByHeader: false,
	images: {
		remotePatterns: [
			{
				protocol: "https",
				hostname: "media.dnd.faysk.dev",
				port: "",
				pathname: "/campaigns/yuhara-main/sessions/**",
				search: "",
			},
			{
				protocol: "https",
				hostname: "media.dnd.faysk.dev",
				port: "",
				pathname: "/campaigns/*/entities/**",
				search: "",
			},
			{
				protocol: "https",
				hostname: "media.dnd.faysk.dev",
				port: "",
				pathname: "/lore/pipipi/**",
				search: "",
			},
			{
				protocol: "https",
				hostname: "dmrqnbdvbkfqzctcerbx.supabase.co",
				pathname: "/storage/v1/object/public/session-images/**",
			},
			{
				protocol: "https",
				hostname: "dnd.faysk.dev",
				pathname: "/assets/sessions/**",
			},
		],
	},
	async rewrites() {
		return [
			...[
				...standaloneNoindexLores,
				...standaloneLores.map(({ slug }) => slug),
			].map((slug) => ({
				source: `/lore/${slug}`,
				destination: `/lore/${slug}/index.html`,
			})),
			...diaries.map(({ slug }) => ({
				source: `/diario/${slug}`,
				destination: `/diario/${slug}/index.html`,
			})),
		];
	},
	async headers() {
		return [
			{
				source: "/:path*",
				headers: [
					{ key: "X-Content-Type-Options", value: "nosniff" },
					{ key: "X-Frame-Options", value: "DENY" },
					{ key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
					{
						key: "Permissions-Policy",
						value: "camera=(), microphone=(), geolocation=()",
					},
					{
						key: "Content-Security-Policy-Report-Only",
						value: contentSecurityPolicyReportOnly,
					},
				],
			},
			{
				source: "/auth/:path*",
				headers: [{ key: "Referrer-Policy", value: "no-referrer" }],
			},
			...standaloneNoindexLores.flatMap((slug) => [
				{
					source: `/lore/${slug}`,
					headers: [
						{
							key: "X-Robots-Tag",
							value: "noindex, nofollow, noarchive, noimageindex",
						},
					],
				},
				{
					source: `/lore/${slug}/:path*`,
					headers: [
						{
							key: "X-Robots-Tag",
							value: "noindex, nofollow, noarchive, noimageindex",
						},
					],
				},
			]),
		];
	},
};

export default config;
