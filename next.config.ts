import type { NextConfig } from "next";

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
				hostname: "raw.githubusercontent.com",
				pathname: "/Faysk/dnd-scribe/**",
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
			{
				source: "/lore/d",
				destination: "/lore/d/index.html",
			},
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
				],
			},
			{
				source: "/auth/:path*",
				headers: [{ key: "Referrer-Policy", value: "no-referrer" }],
			},
			{
				source: "/lore/d",
				headers: [
					{
						key: "X-Robots-Tag",
						value: "noindex, nofollow, noarchive, noimageindex",
					},
				],
			},
			{
				source: "/lore/d/:path*",
				headers: [
					{
						key: "X-Robots-Tag",
						value: "noindex, nofollow, noarchive, noimageindex",
					},
				],
			},
		];
	},
};

export default config;
