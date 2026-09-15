import type { Metadata } from "next";
import Image from "next/image";
import { notFound } from "next/navigation";
import { PublicLink as Link } from "@/components/public-link";
import { SessionShareActions } from "@/components/session-share-actions";
import { StoryMarkdown } from "@/components/story-markdown";
import { DisplayTitle, Eyebrow } from "@/components/ui";
import { buildPublicMetadata } from "@/config/public-metadata";
import { sessionPublicMetadata } from "@/features/sessions/metadata";
import {
	formatSessionDate,
	type PublishedSession,
} from "@/features/sessions/model";
import {
	findPublishedSession,
	listPublishedSessions,
	PublishedSessionUnavailableError,
} from "@/features/sessions/repository";
import { sessionShareDescription } from "@/features/sessions/share";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

type SessionParams = { params: Promise<{ id: string }> };

type Direction = "previous" | "next";

function unavailableSessionMetadata(id: string) {
	return buildPublicMetadata({
		title: "Sessão temporariamente indisponível",
		description:
			"Não foi possível consultar esta sessão agora. Tente novamente em instantes.",
		pathname: `/sessoes/${encodeURIComponent(id)}`,
	});
}

export async function generateMetadata({ params }: SessionParams): Promise<Metadata> {
	const { id } = await params;
	let session: PublishedSession | null;
	try {
		session = await findPublishedSession(id);
	} catch (error) {
		if (error instanceof PublishedSessionUnavailableError) {
			return unavailableSessionMetadata(id);
		}
		throw error;
	}
	if (!session) notFound();
	return sessionPublicMetadata(session);
}

function SessionNavigationCard({
	session,
	direction,
}: {
	session: PublishedSession;
	direction: Direction;
}) {
	const href = `/sessoes/${encodeURIComponent(session.id)}`;
	const image = session.coverImage || session.heroImage;
	const isNext = direction === "next";

	return (
		<Link
			className={`${styles.link}${isNext ? ` ${styles.next}` : ""}`}
			href={href}
		>
			<span className={styles.linkMedia} aria-hidden="true">
				{image ? (
					<Image
						className={styles.linkImage}
						src={image}
						alt=""
						fill
						sizes="(max-width: 700px) calc(100vw - 40px), 420px"
					/>
				) : (
					<span className={styles.linkFallback}>TDA</span>
				)}
				<span className={styles.linkShade} />
			</span>
			<span className={styles.linkCopy}>
				<span className={styles.label}>
					{isNext ? "Próxima sessão →" : "← Sessão anterior"}
				</span>
				<strong className={styles.linkTitle}>{session.title}</strong>
				{session.arc ? <span className={styles.linkArc}>{session.arc}</span> : null}
			</span>
		</Link>
	);
}

export default async function Session({ params }: SessionParams) {
	const { id } = await params;
	let session: PublishedSession | null;
	try {
		session = await findPublishedSession(id);
	} catch (error) {
		if (!(error instanceof PublishedSessionUnavailableError)) throw error;
		return (
			<section className="page-section">
				<Eyebrow>Arquivo de sessões</Eyebrow>
				<DisplayTitle>Esta sessão está temporariamente indisponível.</DisplayTitle>
				<p>Não conseguimos consultar o arquivo agora. Tente novamente em instantes.</p>
				<p>
					<Link
						className="ds-action ds-action--primary ds-action--md"
						href={`/sessoes/${encodeURIComponent(id)}`}
					>
						Tentar novamente
					</Link>{" "}
					<Link className="ds-action ds-action--secondary ds-action--md" href="/sessoes">
						Voltar às sessões
					</Link>
				</p>
			</section>
		);
	}
	if (!session) notFound();

	let archive: Awaited<ReturnType<typeof listPublishedSessions>> = null;
	try {
		archive = await listPublishedSessions();
	} catch {
		archive = null;
	}
	const currentIndex = archive?.findIndex((item) => item.id === session.id) ?? -1;
	const previous =
		archive && currentIndex >= 0 ? archive[currentIndex + 1] : undefined;
	const next = archive && currentIndex > 0 ? archive[currentIndex - 1] : undefined;
	const story =
		session.fullSummary || session.summary || "Resumo ainda não disponível.";
	const image = session.heroImage || session.coverImage;
	const date = formatSessionDate(session.date);
	const shareDescription = sessionShareDescription(session.summary, session.title);

	return (
		<article className={styles.page}>
			<header className={`${styles.hero}${image ? ` ${styles.heroWithArt}` : ""}`}>
				{image ? (
					<>
						<Image
							className={styles.art}
							src={image}
							alt=""
							fill
							preload
							sizes="100vw"
						/>
						<div className={styles.overlay} aria-hidden="true" />
					</>
				) : null}
				<div className={styles.heroInner}>
					<div className={styles.content}>
						<Link className={styles.back} href="/sessoes">
							<span aria-hidden="true">←</span>
							<span>Arquivo de sessões</span>
						</Link>
						<Eyebrow className={styles.eyebrow}>
							{session.arc || "Memória da campanha"}
						</Eyebrow>
						<DisplayTitle className={styles.title}>{session.title}</DisplayTitle>
						{date ? (
							<time className={styles.date} dateTime={session.date}>
								{date}
							</time>
						) : null}
					</div>
				</div>
			</header>

			<div className={styles.body}>
				<div className={styles.readingIntro}>
					<span className={styles.chapterMark} aria-hidden="true">
						◆
					</span>
					<SessionShareActions
						title={session.title}
						description={shareDescription}
					/>
				</div>
				<StoryMarkdown source={story} title={session.title} />
				{previous || next ? (
					<nav className={styles.pagination} aria-label="Navegação entre sessões">
						{previous ? (
							<SessionNavigationCard session={previous} direction="previous" />
						) : null}
						{next ? (
							<SessionNavigationCard session={next} direction="next" />
						) : null}
					</nav>
				) : null}
			</div>
		</article>
	);
}
