import type { Metadata } from "next";
import Image from "next/image";
import { SessionList } from "@/components/session-list";
import { Eyebrow } from "@/components/ui";
import { buildPublicMetadata } from "@/config/public-metadata";
import {
	formatArchiveDate,
	formatArchiveNumber,
	summarizeSessionArchive,
} from "@/features/sessions/archive";
import { sessionPublicMetadataImage } from "@/features/sessions/metadata";
import { listPublishedSessionArchive } from "@/features/sessions/repository";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

const sessionsDescription =
	"Arquivo público das sessões, histórias e memórias da campanha no TDA — Tem Dado Aqui.";

export async function generateMetadata(): Promise<Metadata> {
	let image: ReturnType<typeof sessionPublicMetadataImage>;
	try {
		const latest = (await listPublishedSessionArchive())?.[0];
		image = latest ? sessionPublicMetadataImage(latest) : undefined;
	} catch {
		image = undefined;
	}

	return buildPublicMetadata({
		title: "Sessões",
		description: sessionsDescription,
		pathname: "/sessoes",
		...(image ? { image } : {}),
	});
}

function ArchiveStat({ value, label }: { value: string; label: string }) {
	return (
		<div className={styles.stat}>
			<dt>{label}</dt>
			<dd>{value}</dd>
		</div>
	);
}

export default async function Sessions() {
	let sessions: Awaited<ReturnType<typeof listPublishedSessionArchive>> | undefined;
	try {
		sessions = await listPublishedSessionArchive();
	} catch {
		sessions = undefined;
	}

	const latest = sessions?.[0];
	const artwork = latest?.heroImage || latest?.coverImage;
	const summary = sessions?.length ? summarizeSessionArchive(sessions) : null;

	return (
		<div className={styles.page}>
			<section className={styles.hero} aria-labelledby="archive-title">
				{artwork ? (
					<div className={styles.backdrop} aria-hidden="true">
						<Image
							className={styles.backdropImage}
							src={artwork}
							alt=""
							fill
							preload
							sizes="100vw"
						/>
					</div>
				) : null}
				<div className={styles.backdropShade} aria-hidden="true" />
				<div className={styles.heroInner}>
					<header className={styles.heroCopy}>
						<Eyebrow className={styles.eyebrow}>Arquivo da campanha</Eyebrow>
						<h1 className={styles.title} id="archive-title">
							As histórias até aqui
						</h1>
						<p>
							Todas as sessões, decisões e memórias da nossa jornada reunidas em
							um só lugar.
						</p>
					</header>

					{summary ? (
						<dl className={styles.stats} aria-label="Resumo público do arquivo">
							<ArchiveStat
								value={formatArchiveNumber(summary.sessions)}
								label="memórias publicadas"
							/>
							<ArchiveStat
								value={formatArchiveNumber(summary.arcs)}
								label="arcos registrados"
							/>
							<ArchiveStat
								value={formatArchiveDate(summary.firstDate)}
								label="primeira memória"
							/>
							<ArchiveStat
								value={formatArchiveDate(summary.latestDate)}
								label="última memória"
							/>
						</dl>
					) : null}
				</div>
			</section>

			<section className={styles.archive} aria-label="Sessões publicadas">
				{sessions === undefined ? (
					<p className={styles.state} role="status">
						Não foi possível carregar as sessões. Tente novamente em instantes.
					</p>
				) : sessions === null ? (
					<p className={styles.state}>
						Estamos preparando o arquivo da campanha.
					</p>
				) : sessions.length ? (
					<SessionList sessions={sessions} />
				) : (
					<p className={styles.state}>Nenhuma sessão publicada ainda.</p>
				)}
			</section>
		</div>
	);
}
