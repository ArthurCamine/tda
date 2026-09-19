import Image from "next/image";
import { PublicLink } from "@/components/public-link";
import type {
	LoreBlockDTO,
	LoreCardDTO,
	LoreMediaDTO,
	LoreProfileDTO,
} from "../model";
import { LoreExperience } from "./lore-experience";
import { standaloneLoreForEntity } from "../standalone-catalog";
import styles from "./lore-page.module.css";

type LorePageProps = {
	profile: LoreProfileDTO;
};

function LoreCard({ card }: { card: LoreCardDTO }) {
	const content = (
		<>
			{card.image ? (
				<div className={styles.cardImage}>
					<Image
						src={card.image.src}
						alt={card.image.alt}
						fill
						sizes="(max-width: 760px) 92vw, 360px"
					/>
				</div>
			) : null}
			<div className={styles.cardBody}>
				{card.eyebrow ? <span>{card.eyebrow}</span> : null}
				<strong>{card.title}</strong>
				{card.summary ? <p>{card.summary}</p> : null}
			</div>
		</>
	);

	return card.href ? (
		<PublicLink className={styles.card} href={card.href}>
			{content}
		</PublicLink>
	) : (
		<article className={styles.card}>{content}</article>
	);
}

function LoreGalleryImage({ media }: { media: LoreMediaDTO }) {
	return (
		<figure className={styles.galleryItem}>
			<Image
				src={media.src}
				alt={media.alt}
				width={media.width ?? 1600}
				height={media.height ?? 1000}
				sizes="(max-width: 760px) 92vw, 50vw"
			/>
		</figure>
	);
}

function LoreBlock({ block }: { block: LoreBlockDTO }) {
	switch (block.kind) {
		case "prose": {
			const occurrences = new Map<string, number>();
			return (
				<div className={styles.prose}>
					{block.paragraphs.map((paragraph) => {
						const occurrence = (occurrences.get(paragraph) ?? 0) + 1;
						occurrences.set(paragraph, occurrence);
						return (
							<p key={`${block.id}:${paragraph}:${occurrence}`}>{paragraph}</p>
						);
					})}
				</div>
			);
		}
		case "quote":
			return (
				<figure className={styles.quote}>
					<blockquote>{block.text}</blockquote>
					{block.attribution ? <figcaption>— {block.attribution}</figcaption> : null}
				</figure>
			);
		case "facts":
			return (
				<dl className={styles.facts}>
					{block.items.map((item) => (
						<div key={`${item.label}:${item.value}`}>
							<dt>{item.label}</dt>
							<dd>{item.value}</dd>
						</div>
					))}
				</dl>
			);
		case "cards":
			return (
				<div className={styles.cards}>
					{block.items.map((card) => (
						<LoreCard key={card.id} card={card} />
					))}
				</div>
			);
		case "links":
			return (
				<ul className={styles.linkList}>
					{block.items.map((item) => (
						<li key={item.id}>
							<PublicLink href={item.href}>
								<strong>{item.label}</strong>
								{item.description ? <span>{item.description}</span> : null}
							</PublicLink>
						</li>
					))}
				</ul>
			);
		case "gallery":
			return (
				<div className={styles.gallery}>
					{block.items.map((media) => (
						<LoreGalleryImage key={media.src} media={media} />
					))}
				</div>
			);
	}
}

export function LorePage({ profile }: LorePageProps) {
	const standaloneLore = standaloneLoreForEntity(profile.identity.entityType, profile.identity.slug);
	return (
		<article className={styles.page}>
			<LoreExperience
				identity={profile.identity}
				presentation={profile.presentation}
				narration={profile.narration}
			/>

			<div className={styles.shell}>
				{profile.sections.length || standaloneLore ? (
					<nav className={styles.sectionNav} aria-label="Nesta história">
						{standaloneLore ? (
							<a href={`/lore/${standaloneLore.slug}`}>Ler a história: {standaloneLore.title}</a>
						) : null}
						{profile.sections.map((section) => (
							<a key={section.id} href={`#${section.id}`}>
								{section.title}
							</a>
						))}
						{profile.worldHref ? (
							<PublicLink className={styles.worldLink} href={profile.worldHref}>
								Ver nos Ecos da Jornada ↗
							</PublicLink>
						) : null}
					</nav>
				) : null}

				<div className={styles.sections}>
					{profile.identity.quote ? (
						<figure className={styles.leadQuote}>
							<blockquote>{profile.identity.quote.text}</blockquote>
							{profile.identity.quote.attribution ? (
								<figcaption>— {profile.identity.quote.attribution}</figcaption>
							) : null}
						</figure>
					) : null}

					{profile.sections.map((section) => (
						<section className={styles.section} id={section.id} key={section.id}>
							<header className={styles.sectionHeader}>
								{section.eyebrow ? <p>{section.eyebrow}</p> : null}
								<h2>{section.title}</h2>
								{section.intro ? <div>{section.intro}</div> : null}
							</header>
							<div className={styles.blocks}>
								{section.blocks.map((block) => (
									<LoreBlock key={`${section.id}:${block.id}`} block={block} />
								))}
							</div>
						</section>
					))}
				</div>
			</div>
		</article>
	);
}
