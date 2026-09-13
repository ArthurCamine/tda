"use client";

import type { CSSProperties, Ref } from "react";
import { Select } from "@/components/ui";
import type {
	WorldFilter,
	WorldRelationFilter,
	WorldRelationTypeDTO,
} from "../model";
import chrome from "./world-floating-chrome.module.css";
import styles from "./world-explorer.module.css";

const FILTER_OPTIONS: { value: WorldFilter; label: string }[] = [
	{ value: "all", label: "Todos" },
	{ value: "characters", label: "Personagens" },
	{ value: "npcs", label: "NPCs" },
	{ value: "locations", label: "Lugares" },
	{ value: "factions", label: "Facções" },
	{ value: "songs", label: "Músicas" },
	{ value: "moments", label: "Momentos" },
];

const RELATION_OPTIONS: { value: WorldRelationFilter; label: string }[] = [
	{ value: "all", label: "Todas as relações" },
	{ value: "affinity", label: "Afinidade" },
	{ value: "conflict", label: "Conflito" },
	{ value: "family", label: "Família" },
	{ value: "authority", label: "Autoridade" },
	{ value: "faction", label: "Facção" },
	{ value: "mystic", label: "Místico" },
	{ value: "creative", label: "Criativo" },
	{ value: "origin", label: "Origem" },
	{ value: "context", label: "Contexto" },
];

type WorldView = "canvas" | "list";

type WorldFloatingChromeProps = Readonly<{
	query: string;
	onQueryChange: (query: string) => void;
	filter: WorldFilter;
	onFilterChange: (filter: WorldFilter) => void;
	relationFilter: WorldRelationFilter;
	onRelationFilterChange: (filter: WorldRelationFilter) => void;
	view: WorldView;
	onViewChange: (view: WorldView) => void;
	onReset: () => void;
	resetLabel: string;
	resetDisabled?: boolean;
	demo: boolean;
	activeRelationTypes: WorldRelationTypeDTO[];
	searchInputRef?: Ref<HTMLInputElement>;
}>;

function filterClass(active: boolean) {
	return `${styles.filterActive && active ? styles.filterActive : ""} ${chrome.filterChip}${active ? ` ${chrome.filterChipActive}` : ""}`.trim();
}

function legendItemStyle(color?: string) {
	return color
		? ({ "--world-relation-color": color } as CSSProperties)
		: undefined;
}

export function WorldFloatingChrome({
	query,
	onQueryChange,
	filter,
	onFilterChange,
	relationFilter,
	onRelationFilterChange,
	view,
	onViewChange,
	onReset,
	resetLabel,
	resetDisabled = false,
	demo,
	activeRelationTypes,
	searchInputRef,
}: WorldFloatingChromeProps) {
	return (
		<div className={chrome.root} data-testid="world-floating-chrome">
			<div className={`${styles.toolbar} ${chrome.primary}`} data-world-chrome-primary>
				<label className={`${styles.searchField} ${chrome.searchSurface}`} data-world-search>
					<span className={styles.srOnly}>Buscar no mundo</span>
					<span className={chrome.searchGlyph} aria-hidden="true">
						⌕
					</span>
					<input
						ref={searchInputRef}
						type="search"
						value={query}
						onChange={(event) => onQueryChange(event.target.value)}
						placeholder="Buscar pessoa, lugar ou memória..."
					/>
				</label>

				<div className={`${styles.relationSelect} ${chrome.relationSurface}`} data-world-relation-filter>
					<span>Relação</span>
					<Select
						value={relationFilter}
						options={RELATION_OPTIONS}
						onChange={onRelationFilterChange}
						ariaLabel="Filtrar por relação"
						embedded
					/>
				</div>

				<button
					className={`${styles.resetButton} ${chrome.resetSurface}`}
					type="button"
					data-testid="world-layout-reset"
					data-world-layout-action
					aria-label={resetLabel}
					title={resetLabel}
					disabled={resetDisabled}
					onClick={onReset}
				>
					{resetLabel}
				</button>

				<fieldset className={`${styles.viewToggle} ${chrome.viewSurface}`} data-world-view-toggle>
					<legend className={styles.srOnly}>Modo de visualização</legend>
					<button
						type="button"
						aria-pressed={view === "canvas"}
						aria-label="Canvas"
						title="Canvas"
						onClick={() => onViewChange("canvas")}
					>
						<span className={chrome.viewGlyph} aria-hidden="true">
							⌘
						</span>
						<span className={chrome.viewLabel}>Canvas</span>
					</button>
					<button
						type="button"
						aria-pressed={view === "list"}
						aria-label="Lista"
						title="Lista"
						onClick={() => onViewChange("list")}
					>
						<span className={chrome.viewGlyph} aria-hidden="true">
							☷
						</span>
						<span className={chrome.viewLabel}>Lista</span>
					</button>
				</fieldset>
			</div>

			<div className={chrome.secondary} data-world-filter-overlay>
				<fieldset className={`${styles.filters} ${chrome.filterRail}`} aria-label="Filtrar o grafo">
					{FILTER_OPTIONS.map((option) => (
						<button
							key={option.value}
							type="button"
							className={filterClass(filter === option.value)}
							aria-pressed={filter === option.value}
							onClick={() => onFilterChange(option.value)}
						>
							{option.label}
						</button>
					))}
				</fieldset>

				{demo ? (
					<fieldset className={`${styles.relationLegend} ${chrome.legendRail}`}>
						<legend className={styles.srOnly}>Legenda de relações</legend>
						<span className={chrome.legendItem} data-family="affinity">Afinidade</span>
						<span className={chrome.legendItem} data-family="conflict">Conflito</span>
						<span className={chrome.legendItem} data-family="family">Família</span>
						<span className={chrome.legendItem} data-family="mystic">Místico</span>
						<span className={chrome.legendItem} data-family="creative">Criativo</span>
					</fieldset>
				) : activeRelationTypes.length ? (
					<fieldset className={`${styles.relationLegend} ${chrome.legendRail}`}>
						<legend className={styles.srOnly}>Legenda de tipos de ligação</legend>
						{activeRelationTypes.map((type) => (
							<span
								key={type.slug}
								className={chrome.legendItem}
								data-family={type.family}
								style={legendItemStyle(type.style.color)}
							>
								{type.label}
							</span>
						))}
					</fieldset>
				) : null}
			</div>
		</div>
	);
}
