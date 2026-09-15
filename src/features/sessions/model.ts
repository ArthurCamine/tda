export const CAMPAIGN_SLUG = "yuhara-main";

export type PublishedSession = Readonly<{
	id: string;
	title: string;
	date: string;
	arc: string;
	summary: string;
	coverImage?: string;
	heroImage?: string;
	fullSummary?: string;
}>;

type Row = {
	source_session_id: unknown;
	title: unknown;
	session_date: unknown;
	arc: unknown;
	summary_short: unknown;
	summary_full?: unknown;
	cover_image_url?: unknown;
	hero_image_url?: unknown;
	status: unknown;
	campaigns: unknown;
};

const publicImageSources = [
	{
		hostname: "media.dnd.faysk.dev",
		pathname: "/campaigns/yuhara-main/sessions/",
	},
	{
		hostname: "dmrqnbdvbkfqzctcerbx.supabase.co",
		pathname: "/storage/v1/object/public/session-images/",
	},
	{ hostname: "dnd.faysk.dev", pathname: "/assets/sessions/" },
] as const;

function text(value: unknown, limit: number) {
	return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

function publicImageUrl(value: unknown) {
	if (typeof value !== "string" || value.length > 2000) return "";
	try {
		const url = new URL(value);
		if (url.protocol !== "https:") return "";
		if (
			url.hostname === "media.dnd.faysk.dev" &&
			(url.port || url.search || url.hash || url.username || url.password)
		)
			return "";
		const allowed = publicImageSources.some(
			(source) =>
				url.hostname === source.hostname &&
				url.pathname.startsWith(source.pathname),
		);
		return allowed ? url.toString() : "";
	} catch {
		return "";
	}
}

export function formatSessionDate(value: string) {
	if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
	const [year, month, day] = value.split("-").map(Number);
	if (!year || !month || !day) return "";
	const date = new Date(Date.UTC(year, month - 1, day));
	if (
		date.getUTCFullYear() !== year ||
		date.getUTCMonth() !== month - 1 ||
		date.getUTCDate() !== day
	) {
		return "";
	}
	return new Intl.DateTimeFormat("pt-BR", {
		day: "2-digit",
		month: "long",
		year: "numeric",
		timeZone: "UTC",
	}).format(date);
}

export function toPublishedSession(
	row: Row,
	detail = false,
): PublishedSession | null {
	const campaign = row.campaigns as { slug?: unknown } | null;
	if (row.status !== "published" || campaign?.slug !== CAMPAIGN_SLUG)
		return null;
	const id = text(row.source_session_id, 220);
	if (!id) return null;
	const coverImage = publicImageUrl(row.cover_image_url);
	const heroImage = publicImageUrl(row.hero_image_url);
	return {
		id,
		title: text(row.title, 500) || "Sessão sem título",
		date: text(row.session_date, 10),
		arc: text(row.arc, 300),
		summary: text(row.summary_short, 4000),
		...(coverImage ? { coverImage } : {}),
		...(heroImage ? { heroImage } : {}),
		...(detail ? { fullSummary: text(row.summary_full, 200000) } : {}),
	};
}
