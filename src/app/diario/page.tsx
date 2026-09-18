import { buildPublicMetadata } from "@/config/public-metadata";
import diaries from "@/features/diary/catalog.json";
import styles from "./page.module.css";

export const metadata = buildPublicMetadata({
	title: "Diários",
	description: "Memórias escritas pelos personagens, um diário de cada vez.",
	pathname: "/diario",
});

export default function DiaryIndex() {
	return (
		<section className={styles.archive}>
			<header className={styles.heading}>
				<p className={styles.eyebrow}>Entre páginas</p>
				<h1>Diários</h1>
				<p>Memórias escritas pelos personagens, com suas próprias vozes.</p>
			</header>
			<ul className={styles.books}>
				{diaries.map((diary) => (
					<li key={diary.slug}>
						{/* Standalone documents require a full navigation outside the React shell. */}
						<a className={styles.book} href={`/diario/${diary.slug}`}>
							<div className={styles.spine} aria-hidden="true">
								{diary.author}
							</div>
							<div>
								<p className={styles.eyebrow}>{diary.author}</p>
								<h2>{diary.title}</h2>
								<p>{diary.description}</p>
								<span className={styles.action}>
									Abrir o diário <span aria-hidden="true">→</span>
								</span>
							</div>
						</a>
					</li>
				))}
			</ul>
		</section>
	);
}
