"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	WorldWorkspaceControlsContext,
	type WorldWorkspaceControls,
} from "./world-workspace-context";
import { WorldEdgeTab } from "./world-edge-tab";
import { WorldNavigation, WorldNavigationIntro } from "./world-navigation";
import styles from "./world-workspace-shell.module.css";

const MOBILE_NAVIGATION_FOCUSABLE =
	'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function WorldWorkspaceShell({ children }: { children: React.ReactNode }) {
	const pathname = usePathname() || "/mundo";
	const [navigationOpen, setNavigationOpen] = useState(true);
	const [mobileNavigation, setMobileNavigation] = useState(false);
	const [siteHeaderOpen, setSiteHeaderOpen] = useState(false);
	const [authoringActive, setAuthoringActiveState] = useState(false);
	const navigationPanelRef = useRef<HTMLElement>(null);
	const navigationCloseRef = useRef<HTMLButtonElement>(null);
	const navigationToggleRef = useRef<HTMLButtonElement>(null);

	useEffect(() => {
		const desktop = window.matchMedia("(min-width: 821px)");
		const syncNavigationToViewport = () => {
			setMobileNavigation(!desktop.matches);
			setNavigationOpen(authoringActive ? false : desktop.matches);
		};
		syncNavigationToViewport();
		desktop.addEventListener("change", syncNavigationToViewport);
		return () => desktop.removeEventListener("change", syncNavigationToViewport);
	}, [authoringActive]);

	useEffect(() => {
		if (authoringActive) setSiteHeaderOpen(false);
	}, [authoringActive]);

	const closeNavigation = useCallback(() => {
		const shouldRestoreFocus = window.matchMedia("(max-width: 820px)").matches;
		setNavigationOpen(false);
		if (shouldRestoreFocus) {
			window.requestAnimationFrame(() => navigationToggleRef.current?.focus());
		}
	}, []);

	const setAuthoringActive = useCallback((active: boolean) => {
		setAuthoringActiveState(active);
	}, []);

	const openNavigation = useCallback(() => {
		setNavigationOpen(true);
	}, []);

	const workspaceControls = useMemo<WorldWorkspaceControls>(
		() => ({ authoringActive, setAuthoringActive, openNavigation }),
		[authoringActive, openNavigation, setAuthoringActive],
	);

	useEffect(() => {
		if (!navigationOpen) return;
		const mobile = window.matchMedia("(max-width: 820px)");
		if (mobile.matches) {
			window.requestAnimationFrame(() => navigationCloseRef.current?.focus());
		}

		const manageNavigationFocus = (event: KeyboardEvent) => {
			const panel = navigationPanelRef.current;
			if (event.key === "Escape") {
				if (!mobile.matches && (!panel || !panel.contains(document.activeElement))) return;
				event.preventDefault();
				setNavigationOpen(false);
				window.requestAnimationFrame(() => navigationToggleRef.current?.focus());
				return;
			}

			if (!mobile.matches || event.key !== "Tab" || !panel) return;
			const focusable = Array.from(
				panel.querySelectorAll<HTMLElement>(MOBILE_NAVIGATION_FOCUSABLE),
			).filter((element) => element.getAttribute("aria-hidden") !== "true");
			if (focusable.length === 0) return;

			const first = focusable[0];
			const last = focusable[focusable.length - 1];
			const active = document.activeElement;
			if (event.shiftKey && (active === first || !panel.contains(active))) {
				event.preventDefault();
				last.focus();
			} else if (!event.shiftKey && (active === last || !panel.contains(active))) {
				event.preventDefault();
				first.focus();
			}
		};

		document.addEventListener("keydown", manageNavigationFocus);
		return () => document.removeEventListener("keydown", manageNavigationFocus);
	}, [navigationOpen]);

	const navigationIsModal = navigationOpen && mobileNavigation;
	const navigationContent = (
		<div className={styles.navigationInner}>
			<div className={styles.navigationHeader}>
				<WorldNavigationIntro />
				<div className={styles.navigationHeaderActions}>
					<button
						ref={navigationCloseRef}
						type="button"
						className={styles.closeNavigation}
						onClick={closeNavigation}
						aria-label="Fechar navegação do mundo"
					>
						×
					</button>
				</div>
			</div>
			<WorldNavigation pathname={pathname} />
		</div>
	);

	return (
		<WorldWorkspaceControlsContext.Provider value={workspaceControls}>
			<div
				className={`${styles.workspace}${navigationOpen ? ` ${styles.navigationOpen}` : ""}`}
				data-world-workspace-root
				data-world-navigation={navigationOpen ? "open" : "closed"}
				data-world-site-header={siteHeaderOpen ? "open" : "closed"}
				data-world-authoring={authoringActive ? "active" : "inactive"}
				data-testid="world-workspace"
			>
				{navigationIsModal ? (
					<div
						ref={(element) => {
							navigationPanelRef.current = element;
						}}
						id="world-workspace-navigation"
						className={styles.navigationPanel}
						role="dialog"
						aria-modal="true"
						aria-label="Navegação do mundo"
						data-testid="world-workspace-navigation"
					>
						{navigationContent}
					</div>
				) : (
					<aside
						ref={(element) => {
							navigationPanelRef.current = element;
						}}
						id="world-workspace-navigation"
						className={styles.navigationPanel}
						aria-label="Navegação do mundo"
						aria-hidden={!navigationOpen}
						inert={!navigationOpen}
						data-testid="world-workspace-navigation"
					>
						{navigationContent}
					</aside>
				)}

				<button
					type="button"
					className={styles.mobileBackdrop}
					onClick={closeNavigation}
					aria-label="Fechar navegação do mundo"
					aria-hidden="true"
					tabIndex={-1}
				/>

				{!authoringActive ? (
					<WorldEdgeTab
						edge="top"
						expanded={siteHeaderOpen}
						label={siteHeaderOpen ? "Ocultar menu principal" : "Mostrar menu principal"}
						onToggle={() => setSiteHeaderOpen((value) => !value)}
						icon={siteHeaderOpen ? "⌃" : "⌄"}
						className={styles.topNavigationToggle}
					/>
				) : null}

				<WorldEdgeTab
					edge="left"
					expanded={navigationOpen}
					controls="world-workspace-navigation"
					label={navigationOpen ? "Recolher navegação do mundo" : "Explorar universo"}
					onToggle={() => setNavigationOpen((value) => !value)}
					icon={navigationOpen ? "‹" : "›"}
					className={styles.navigationToggle}
					buttonRef={navigationToggleRef}
				/>

				<section
					className={styles.stage}
					data-testid="world-workspace-stage"
					aria-hidden={navigationIsModal ? "true" : "false"}
					inert={navigationIsModal}
				>
					{children}
				</section>
			</div>
		</WorldWorkspaceControlsContext.Provider>
	);
}
