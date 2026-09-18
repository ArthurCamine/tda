import type { Metadata } from "next";
import Image from "next/image";
import {
	GlobalFormLoadingBridge,
	GlobalLoadingProvider,
} from "@/components/global-loading";
import { LegacyRouteBridge } from "@/components/legacy-route-bridge";
import { PublicLink as Link } from "@/components/public-link";
import { ThemeBootstrap } from "@/components/theme-bootstrap";
import { ThemeToggle } from "@/components/theme-toggle";
import { SITE_NAME } from "@/config/public-metadata";
import { CANONICAL_SITE_ORIGIN } from "@/config/site";
import "@xyflow/react/dist/base.css";
import "./globals.css";
import "./design-tokens.css";
import "./design-system.css";
import "./public-shell.css";
import "./story.css";
import "./theme.css";

export const metadata: Metadata = {
	metadataBase: new URL(CANONICAL_SITE_ORIGIN),
	title: { default: SITE_NAME, template: "%s · TDA" },
	icons: {
		icon: "/brand/favicon.svg",
	},
};

export default function Layout({ children }: { children: React.ReactNode }) {
	return (
		<html lang="pt-BR" suppressHydrationWarning>
			<body>
				<ThemeBootstrap />
				<GlobalLoadingProvider>
					<GlobalFormLoadingBridge />
					<LegacyRouteBridge />
					<a href="#conteudo" className="skip-link">
						Pular para o conteúdo
					</a>
					<header className="site-header">
						<Link
							href="/"
							className="brand"
							aria-label="TDA — Tem Dado Aqui — início"
						>
							<span className="brand-symbol" aria-hidden="true">
								<Image
									className="brand-symbol-image brand-symbol-image--dark"
									src="/brand/tda-mark-white.svg"
									width={50}
									height={50}
									alt=""
								/>
								<Image
									className="brand-symbol-image brand-symbol-image--light"
									src="/brand/tda-mark-black.svg"
									width={50}
									height={50}
									alt=""
								/>
							</span>
							<span className="brand-copy">
								<span className="brand-name">TDA</span>
								<small>Tem Dado Aqui</small>
							</span>
						</Link>
						<div className="header-actions">
							<nav aria-label="Navegação principal">
								<Link href="/sessoes">Sessões</Link>
								<Link className="lore-nav-link" href="/lore">
									Lores
								</Link>
								<Link className="world-nav-link" href="/mundo">
									Mundo
								</Link>
								<Link href="/conta">Minha conta</Link>
							</nav>
							<ThemeToggle />
						</div>
					</header>
					<main id="conteudo">{children}</main>
					<footer className="site-footer">
						Tem Dado Aqui <span>Histórias que ficam com a gente.</span>
					</footer>
				</GlobalLoadingProvider>
			</body>
		</html>
	);
}
