import type { Metadata } from "next";
import Image from "next/image";
import { PublicLink as Link } from "@/components/public-link";
import { buildPublicMetadata } from "@/config/public-metadata";
import standaloneLores from "@/features/lore/standalone-catalog.json";
import styles from "./page.module.css";

export const metadata: Metadata = buildPublicMetadata({
	title: "Lores",
	description:
		"Histórias especiais da campanha apresentadas como experiências editoriais e cinematográficas.",
	pathname: "/lore",
});

export default function LoreIndexRoute() {
	return (
		<div className={styles.page}>
			<header className={styles.hero}>
				<p className={styles.eyebrow}>Arquivo cinematográfico</p>
				<h1>Histórias que ganharam outro palco.</h1>
				<p>
					Lores especiais da campanha, reunidas em experiências próprias para
					quando uma história pede mais do que uma ficha ou um resumo.
				</p>
			</header>

			<section className={styles.archive} aria-label="Lores publicadas">
				{standaloneLores.map((lore) => (
					<article className={styles.card} key={lore.slug} data-lore={lore.slug}>
						<Image
							className={styles.cardBackground}
							src={lore.cover}
							alt=""
							fill
							unoptimized
							sizes="(max-width: 650px) 100vw, 1120px"
						/>
						<div className={styles.cardShade} aria-hidden="true" />
						<a className={styles.cardLink} href={`/lore/${lore.slug}`}>
							<div className={styles.cardCopy}>
								<span>{lore.name}</span>
								<h2>{lore.title}</h2>
								<p>{lore.description}</p>
								<span className={styles.action}>
									Começar a história <span aria-hidden="true">→</span>
								</span>
							</div>
						</a>
					</article>
				))}
				<article className={styles.card}>
					<Image
						className={styles.cardBackground}
						src="/lore/pipipi/stage-bg.avif"
						alt=""
						fill
						sizes="(max-width: 650px) 100vw, 1120px"
						quality={88}
					/>
					<div className={styles.cardShade} aria-hidden="true" />
					<Link className={styles.cardLink} href="/lore/pipipi">
						<div className={styles.cardCopy}>
							<span>Pipipi</span>
							<h2>A Casa Onde os Super-Heróis Visitavam</h2>
							<p>
								A história de Pipipi, da Casa onde viveu e das duas metades de
								uma mesma memória.
							</p>
							<span className={styles.action}>
								Começar a história <span aria-hidden="true">→</span>
							</span>
						</div>
					</Link>
				</article>
			</section>
		</div>
	);
}
