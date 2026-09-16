import type { Metadata } from "next";
import Image from "next/image";
import { PublicLink as Link } from "@/components/public-link";
import { Eyebrow, SectionTitle } from "@/components/ui";
import { buildPublicMetadata, SITE_NAME } from "@/config/public-metadata";
import { LoreHomeEntry } from "@/features/lore/components/lore-home-entry";
import { sessionPublicMetadataImage } from "@/features/sessions/metadata";
import {
	formatSessionDate,
	type PublishedSession,
} from "@/features/sessions/model";
import { listPublishedSessions } from "@/features/sessions/repository";
import styles from "./home.module.css";

export const dynamic = "force-dynamic";

const homeDescription =
	"Um arquivo vivo das sessões, decisões e memórias que construímos juntos ao redor da mesa.";

export async function generateMetadata(): Promise<Metadata> {
	let latest: PublishedSession | undefined;
	try {
		latest = (await listPublishedSessions())?.[0];
	} catch {
		latest = undefined;
	}
	const image = latest ? sessionPublicMetadataImage(latest) : undefined;

	return buildPublicMetadata({
		title: SITE_NAME,
		description: homeDescription,
		pathname: "/",
		absoluteTitle: true,
		...(image ? { image } : {}),
	});
}

function SessionArtwork({
	session,
	preload = false,
	sizes,
}: {
	session: PublishedSession;
	preload?: boolean;
	sizes?: string;
}) {
	const artwork = session.heroImage || session.coverImage;
	if (!artwork) {
		return (
			<div className={styles.artworkPlaceholder} aria-hidden="true">
				<span>TDA</span>
			</div>
		);
	}

	return (
		<Image
			className={styles.sessionArtwork}
			src={artwork}
			alt=""
			fill
			preload={preload}
			sizes={
				sizes ??
				(preload
					? "100vw"
					: "(max-width: 700px) calc(100vw - 40px), (max-width: 1200px) 45vw, 460px")
			}
		/>
	);
}

function ArchivePreview({ unavailable = false }: { unavailable?: boolean }) {
	return (
		<div className={styles.archivePreview} role={unavailable ? "status" : undefined}>
			<div className={styles.archiveMark} aria-hidden="true">
				TDA
			</div>
			<div>
				<Eyebrow>{unavailable ? "Arquivo indisponível" : "Arquivo da campanha"}</Eyebrow>
				<h1 id="home-title">
					{unavailable
						? "Não conseguimos abrir a última memória agora."
						: "A próxima memória começa aqui."}
				</h1>
				<p>
					{unavailable
						? "As histórias continuam guardadas. Tente novamente em instantes para carregar a sessão mais recente."
						: "Assim que uma sessão for publicada, sua arte e sua história passam a ocupar este espaço."}
				</p>
			</div>
		</div>
	);
}

export default async function Home() {
	let sessions: Awaited<ReturnType<typeof listPublishedSessions>> | undefined;
	try {
		sessions = await listPublishedSessions();
	} catch {
		sessions = undefined;
	}

	const latest = sessions?.[0];
	const recent = sessions?.slice(latest ? 1 : 0, latest ? 5 : 4) ?? [];
	const latestDate = latest ? formatSessionDate(latest.date) : "";

	return (
		<div className={styles.home}>
			<section className={styles.hero} aria-labelledby="home-title">
				{latest ? (
					<div className={styles.heroBackdrop} aria-hidden="true">
						<SessionArtwork session={latest} preload sizes="100vw" />
						<div className={styles.heroBackdropShade} />
					</div>
				) : null}

				{latest ? (
					<article className={styles.heroLatest}>
						<span className={styles.latestBadge}>Última sessão</span>
						<div className={styles.latestMeta}>
							<span>{latest.arc || "Memória da campanha"}</span>
							{latestDate ? (
								<time className={styles.latestDate} dateTime={latest.date}>
									{latestDate}
								</time>
							) : null}
						</div>
						<h1 className={styles.latestTitle} id="home-title">
							<Link href={`/sessoes/${encodeURIComponent(latest.id)}`}>
								{latest.title}
							</Link>
						</h1>
						<p className={styles.latestSummary}>
							{latest.summary ||
								"Uma nova memória da campanha já está pronta para ser revisitada."}
						</p>
						<Link
							className={styles.latestLink}
							href={`/sessoes/${encodeURIComponent(latest.id)}`}
						>
							Abrir sessão <span aria-hidden="true">→</span>
						</Link>
					</article>
				) : (
					<div className={styles.heroFallback}>
						<ArchivePreview unavailable={sessions === undefined} />
					</div>
				)}
			</section>

			<LoreHomeEntry />

			<section className={styles.memories} aria-labelledby="memories-title">
				<div className={styles.sectionHeading}>
					<div>
						<Eyebrow>O que vivemos juntos</Eyebrow>
						<SectionTitle className={styles.sectionTitle} id="memories-title">
							Memórias recentes
						</SectionTitle>
					</div>
					<Link className={styles.sectionLink} href="/sessoes">
						Ver todas as sessões <span aria-hidden="true">→</span>
					</Link>
				</div>

				{sessions === undefined ? (
					<p className={styles.state} role="status">
						Não foi possível carregar as memórias. Tente novamente em instantes.
					</p>
				) : sessions === null ? (
					<p className={styles.state}>
						Estamos preparando o arquivo de histórias da campanha.
					</p>
				) : recent.length ? (
					<div className={styles.memoryGrid}>
						{recent.map((session) => {
							const href = `/sessoes/${encodeURIComponent(session.id)}`;
							const date = formatSessionDate(session.date);
							return (
								<article className={styles.memoryCard} key={session.id}>
									<Link className={styles.memoryCardLink} href={href}>
										<div className={styles.memoryMedia}>
											<SessionArtwork session={session} />
											<div className={styles.memoryShade} aria-hidden="true" />
										</div>
										<div className={styles.memoryBody}>
											<div className={styles.memoryMeta}>
												<span>{session.arc || "Memória da campanha"}</span>
												{date ? <time dateTime={session.date}>{date}</time> : null}
											</div>
											<h3>{session.title}</h3>
											<p>
												{session.summary ||
													"O resumo desta sessão ainda não está disponível."}
											</p>
											<span className={styles.memoryRead}>
												Revisitar memória <span aria-hidden="true">→</span>
											</span>
										</div>
									</Link>
								</article>
							);
						})}
					</div>
				) : latest ? (
					<p className={styles.state}>
						A primeira memória já está em destaque. As próximas aparecem aqui.
					</p>
				) : (
					<p className={styles.state}>Nenhuma sessão publicada ainda.</p>
				)}
			</section>
		</div>
	);
}
