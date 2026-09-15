import type { Metadata } from "next";
import { requireCapability } from "@/features/auth/server";
import { EDIT_CAPABILITIES } from "@/features/edit/access/policy";
import { CompanionDownload } from "@/features/edit/processing/companion-download";
import { ProcessingPanel } from "@/features/edit/processing/panel";
import { ProcessingSubmission } from "@/features/edit/processing/submission";
import styles from "@/features/edit/processing/processing.module.css";
import pageStyles from "./page.module.css";

export const metadata: Metadata = {
	title: "Processamento",
	description: "Fila e conexão com o serviço local de processamento.",
};

export default async function ProcessingPage() {
	await requireCapability(
		EDIT_CAPABILITIES.localProcess,
		"/edit/processamento",
	);
	return (
		<section className={styles.page}>
			<header className={`${styles.pageHeader} ${pageStyles.pageHeaderActions}`}>
				<div>
					<div className={styles.breadcrumb}>Edit / Processamento</div>
					<h1>Processamento</h1>
				</div>
				<CompanionDownload className={pageStyles.companionDownload} />
			</header>
			<ProcessingSubmission />
			<ProcessingPanel />
		</section>
	);
}
