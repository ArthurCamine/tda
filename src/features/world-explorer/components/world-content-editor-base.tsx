"use client";

import { useMemo, useState } from "react";
import { Select, type SelectOption } from "@/components/ui/select";
import {
	WORLD_ENTITY_TYPES,
	type WorldEntityType,
	type WorldGraphDraft,
	type WorldGraphDraftEdge,
	type WorldGraphDraftRelationType,
	type WorldLineStyle,
	type WorldRelationDirection,
	type WorldRelationFamily,
	type WorldVisibility,
} from "../model";
import styles from "./world-content-editor.module.css";
import { WorldEntityMediaEditor } from "./world-entity-media-editor";

type EditorSection = "entity" | "relation" | "types";

const ENTITY_TYPE_OPTIONS: SelectOption<WorldEntityType>[] = WORLD_ENTITY_TYPES.map((value) => ({
	value,
	label:
		value === "pc"
			? "PC"
			: value === "npc"
				? "NPC"
				: value === "location"
					? "Lugar"
					: value === "organization"
						? "Organização"
						: value === "faction"
							? "Facção"
							: value === "song"
								? "Música"
								: value === "quest"
									? "Quest"
									: value === "item"
										? "Item"
										: value === "arc"
											? "Arco"
											: value === "concept"
												? "Conceito"
												: "Outro",
}));

const VISIBILITY_OPTIONS: SelectOption<WorldVisibility>[] = [
	{ value: "public_web", label: "Público na web" },
	{ value: "public_campaign", label: "Público na campanha" },
	{ value: "private_players", label: "Somente jogadores" },
	{ value: "private_master", label: "Somente mestre" },
	{ value: "review_only", label: "Somente revisão" },
];

const DIRECTION_OPTIONS: SelectOption<WorldRelationDirection>[] = [
	{ value: "symmetric", label: "Simétrica ↔" },
	{ value: "directed", label: "Direcionada →" },
];

const FAMILY_OPTIONS: SelectOption<WorldRelationFamily>[] = [
	{ value: "affinity", label: "Afinidade" },
	{ value: "family", label: "Família" },
	{ value: "conflict", label: "Conflito" },
	{ value: "authority", label: "Autoridade" },
	{ value: "faction", label: "Facção" },
	{ value: "origin", label: "Origem" },
	{ value: "mystic", label: "Místico" },
	{ value: "creative", label: "Criativo" },
	{ value: "context", label: "Contexto" },
];

const LINE_STYLE_OPTIONS: SelectOption<WorldLineStyle>[] = [
	{ value: "solid", label: "Sólida" },
	{ value: "dashed", label: "Tracejada" },
	{ value: "dotted", label: "Pontilhada" },
];

function SelectField<T extends string>({
	label,
	value,
	options,
	onChange,
	ariaLabel,
}: {
	label: string;
	value: T;
	options: readonly SelectOption<T>[];
	onChange: (value: T) => void;
	ariaLabel: string;
}) {
	return (
		<div className={styles.field}>
			<span>{label}</span>
			<Select value={value} options={options} onChange={onChange} ariaLabel={ariaLabel} />
		</div>
	);
}

function slugify(value: string): string {
	return value
		.normalize("NFD")
		.replace(/[\u0300-\u036f]/gu, "")
		.toLocaleLowerCase("pt-BR")
		.replace(/[^a-z0-9]+/gu, "-")
		.replace(/^-+|-+$/gu, "")
		.slice(0, 96);
}

function uniqueSlug(base: string, used: Set<string>): string {
	const normalized = base || "elemento";
	if (!used.has(normalized)) return normalized;
	for (let index = 2; index < 10000; index += 1) {
		const candidate = `${normalized.slice(0, 88)}-${index}`;
		if (!used.has(candidate)) return candidate;
	}
	return `${normalized.slice(0, 80)}-${crypto.randomUUID().slice(0, 8)}`;
}

function typeSlug(value: string, used: Set<string>): string {
	const base = slugify(value).replaceAll("-", "_").slice(0, 64) || "relacao";
	if (!used.has(base)) return base;
	for (let index = 2; index < 10000; index += 1) {
		const candidate = `${base.slice(0, 56)}_${index}`;
		if (!used.has(candidate)) return candidate;
	}
	return `${base.slice(0, 48)}_${crypto.randomUUID().slice(0, 8)}`;
}

function updateNode(
	draft: WorldGraphDraft,
	id: string,
	patch: Partial<WorldGraphDraft["nodes"][number]>,
): WorldGraphDraft {
	return {
		...draft,
		nodes: draft.nodes.map((node) => (node.id === id ? { ...node, ...patch } : node)),
	};
}

function updateEdge(
	draft: WorldGraphDraft,
	id: string,
	patch: Partial<WorldGraphDraftEdge>,
): WorldGraphDraft {
	return {
		...draft,
		edges: draft.edges.map((edge) => (edge.id === id ? { ...edge, ...patch } : edge)),
	};
}

function updateType(
	draft: WorldGraphDraft,
	slug: string,
	patch: Partial<WorldGraphDraftRelationType>,
): WorldGraphDraft {
	return {
		...draft,
		relationTypes: draft.relationTypes.map((type) =>
			type.slug === slug ? { ...type, ...patch } : type,
		),
	};
}

export function WorldContentEditor({
	draft,
	selectedId,
	onDraftChange,
	onSelect,
}: {
	draft: WorldGraphDraft;
	selectedId: string | null;
	onDraftChange: (draft: WorldGraphDraft, message?: string) => void;
	onSelect: (id: string | null) => void;
}) {
	const [section, setSection] = useState<EditorSection>("entity");
	const [editingRelationId, setEditingRelationId] = useState<string | null>(null);
	const [editingTypeSlug, setEditingTypeSlug] = useState<string | null>(null);
	const selected = selectedId
		? draft.nodes.find((node) => node.id === selectedId) ?? null
		: null;
	const activeNodes = draft.nodes.filter((node) => node.status !== "archived");
	const activeTypes = draft.relationTypes.filter((type) => type.isActive);
	const connectedEdges = selected
		? draft.edges.filter(
				(edge) =>
					edge.status !== "archived" &&
					(edge.source === selected.id || edge.target === selected.id),
			)
		: [];

	return (
		<section className={styles.editor} aria-label="Editar Mundo">
			<fieldset className={styles.modeBar}>
				<legend className={styles.srOnly}>Ferramentas de edição do Mundo</legend>
				{([
					["entity", selected ? "Elemento" : "Novo elemento"],
					["relation", "Ligações"],
					["types", "Tipos e cores"],
				] as const).map(([id, label]) => (
					<button
						key={id}
						type="button"
						aria-pressed={section === id}
						onClick={() => setSection(id)}
					>
						{label}
					</button>
				))}
			</fieldset>

			{section === "entity" ? (
				selected ? (
					<EntityEditor
						draft={draft}
						entityId={selected.id}
						onChange={onDraftChange}
						onArchive={() => {
							const next = updateNode(draft, selected.id, { status: "archived" });
							onDraftChange(
								{
									...next,
									edges: next.edges.map((edge) =>
										edge.source === selected.id || edge.target === selected.id
											? { ...edge, status: "archived" as const }
											: edge,
									),
								},
								`${selected.name} foi arquivado no rascunho.`,
							);
							onSelect(null);
						}}
					/>
				) : (
					<NewEntityForm
						draft={draft}
						onCreate={(next, id) => {
							onDraftChange(next, "Novo elemento criado no rascunho.");
							onSelect(id);
						}}
					/>
				)
			) : null}

			{section === "relation" ? (
				<div className={styles.stack}>
					<NewRelationForm
						draft={draft}
						selectedId={selected?.id ?? null}
						onCreate={(edge) => {
							onDraftChange(
								{ ...draft, edges: [...draft.edges, edge] },
								"Ligação criada no rascunho.",
							);
							setEditingRelationId(edge.id);
						}}
					/>
					{editingRelationId ? (
						<RelationEditor
							draft={draft}
							edgeId={editingRelationId}
							onChange={onDraftChange}
							onClose={() => setEditingRelationId(null)}
						/>
					) : null}
					<div className={styles.listBlock}>
						<h3>{selected ? `Ligações de ${selected.name}` : "Ligações ativas"}</h3>
						{(selected
							? connectedEdges
							: draft.edges.filter((edge) => edge.status !== "archived")).length ? (
							<ul>
								{(selected
									? connectedEdges
									: draft.edges.filter((edge) => edge.status !== "archived")
								).map((edge) => {
									const source = draft.nodes.find((node) => node.id === edge.source);
									const target = draft.nodes.find((node) => node.id === edge.target);
									const type = draft.relationTypes.find(
										(item) => item.slug === edge.relationType,
									);
									return (
										<li key={edge.id}>
											<button
												type="button"
												onClick={() => setEditingRelationId(edge.id)}
											>
												<strong>{edge.labelOverride ?? type?.label ?? edge.relationType}</strong>
												<span>
													{source?.name ?? "?"} {type?.direction === "directed" ? "→" : "↔"}{" "}
													{target?.name ?? "?"}
												</span>
											</button>
										</li>
									);
								})}
							</ul>
						) : (
							<p>Nenhuma ligação ativa ainda.</p>
						)}
					</div>
				</div>
			) : null}

			{section === "types" ? (
				<div className={styles.stack}>
					<NewRelationTypeForm
						draft={draft}
						onCreate={(type) => {
							onDraftChange(
								{ ...draft, relationTypes: [...draft.relationTypes, type] },
								"Novo tipo de ligação criado no rascunho.",
							);
							setEditingTypeSlug(type.slug);
						}}
					/>
					{editingTypeSlug ? (
						<RelationTypeEditor
							draft={draft}
							typeSlug={editingTypeSlug}
							onChange={onDraftChange}
							onClose={() => setEditingTypeSlug(null)}
						/>
					) : null}
					<div className={styles.listBlock}>
						<h3>Vocabulário da campanha</h3>
						{draft.relationTypes.length ? (
							<ul>
								{draft.relationTypes.map((type) => (
									<li key={type.slug}>
										<button type="button" onClick={() => setEditingTypeSlug(type.slug)}>
											<span
												className={styles.colorDot}
												style={{ background: type.color }}
												aria-hidden="true"
											/>
											<strong>{type.label}</strong>
											<span>
												{type.direction === "directed" ? "→" : "↔"} · {type.lineStyle}
											</span>
										</button>
									</li>
								))}
							</ul>
						) : (
							<p>Crie o primeiro tipo para começar a conectar o Mundo.</p>
						)}
					</div>
				</div>
			) : null}

			<p className={styles.editorHint}>
				Alterações ficam privadas nesta sessão. Só entram no Mundo quando você publicar.
			</p>
			{selected?.entityType === "pc" ? (
				<p className={styles.editorHint}>
					Criar um PC aqui cria a identidade narrativa. Vincular esse PC a uma conta de jogador
					continua sendo uma ação separada de permissões.
				</p>
			) : null}
			<span className={styles.srOnly}>
				{activeNodes.length} elementos e {activeTypes.length} tipos ativos no rascunho.
			</span>
		</section>
	);
}

function EntityEditor({
	draft,
	entityId,
	onChange,
	onArchive,
}: {
	draft: WorldGraphDraft;
	entityId: string;
	onChange: (draft: WorldGraphDraft, message?: string) => void;
	onArchive: () => void;
}) {
	const entity = draft.nodes.find((node) => node.id === entityId);
	if (!entity) return null;
	return (
		<div className={styles.form}>
			<div className={styles.formHeading}>
				<div>
					<span>Elemento selecionado</span>
					<h3>{entity.name}</h3>
				</div>
			</div>
			<WorldEntityMediaEditor
				entity={entity}
				onChange={(assetId) =>
					onChange(
						updateNode(
							draft,
							entity.id,
							assetId
								? {
									primaryMediaAssetId: assetId,
									primaryMediaFocalPoint: entity.primaryMediaFocalPoint ?? { x: 0.5, y: 0.5 },
								}
								: {
									primaryMediaAssetId: null,
									primaryMediaFocalPoint: undefined,
								},
						),
						assetId
							? "Imagem atualizada no rascunho."
							: "Imagem removida do rascunho.",
					)
				}
				onFocalPointChange={(focalPoint) =>
					onChange(
						updateNode(draft, entity.id, { primaryMediaFocalPoint: focalPoint }),
						"Enquadramento da imagem atualizado no rascunho.",
					)
				}
			/>
			<label>
				Nome
				<input
					value={entity.name}
					onChange={(event) =>
						onChange(updateNode(draft, entity.id, { name: event.target.value }))
					}
				/>
			</label>
			<label>
				Slug
				<input
					value={entity.slug ?? ""}
					onChange={(event) =>
						onChange(
							updateNode(draft, entity.id, {
								slug: slugify(event.target.value) || null,
							}),
						)
					}
				/>
			</label>
			<div className={styles.twoColumns}>
				<SelectField
					label="Tipo"
					value={entity.entityType}
					options={ENTITY_TYPE_OPTIONS}
					onChange={(value) => onChange(updateNode(draft, entity.id, { entityType: value }))}
					ariaLabel="Tipo do elemento"
				/>
				<SelectField
					label="Visibilidade"
					value={entity.visibility}
					options={VISIBILITY_OPTIONS}
					onChange={(value) => onChange(updateNode(draft, entity.id, { visibility: value }))}
					ariaLabel="Visibilidade do elemento"
				/>
			</div>
			<label>
				Resumo
				<textarea
					rows={4}
					value={entity.summary}
					onChange={(event) =>
						onChange(updateNode(draft, entity.id, { summary: event.target.value }))
					}
				/>
			</label>
			<label>
				Aliases
				<input
					value={entity.aliases.join(", ")}
					onChange={(event) =>
						onChange(
							updateNode(draft, entity.id, {
								aliases: event.target.value
									.split(",")
									.map((item) => item.trim())
									.filter(Boolean)
									.slice(0, 50),
							}),
						)
					}
					placeholder="nome antigo, apelido"
				/>
			</label>
			<button className={styles.dangerButton} type="button" onClick={onArchive}>
				Arquivar elemento
			</button>
		</div>
	);
}

function NewEntityForm({
	draft,
	onCreate,
}: {
	draft: WorldGraphDraft;
	onCreate: (draft: WorldGraphDraft, id: string) => void;
}) {
	const [name, setName] = useState("");
	const [entityType, setEntityType] = useState<WorldEntityType>("npc");
	const [visibility, setVisibility] = useState<WorldVisibility>("private_players");
	const usedSlugs = useMemo(
		() => new Set(draft.nodes.flatMap((node) => (node.slug ? [node.slug] : []))),
		[draft.nodes],
	);
	return (
		<form
			className={styles.form}
			onSubmit={(event) => {
				event.preventDefault();
				const trimmed = name.trim();
				if (!trimmed) return;
				const id = crypto.randomUUID();
				const slug = uniqueSlug(slugify(trimmed), usedSlugs);
				onCreate(
					{
						...draft,
						nodes: [
							...draft.nodes,
							{
								id,
								name: trimmed,
								slug,
								entityType,
								status: "active",
								visibility,
								summary: "",
								aliases: [],
							},
						],
					},
					id,
				);
				setName("");
			}}
		>
			<div className={styles.formHeading}>
				<div>
					<span>Adicionar ao mapa</span>
					<h3>Novo elemento</h3>
				</div>
			</div>
			<label>
				Nome
				<input
					value={name}
					onChange={(event) => setName(event.target.value)}
					placeholder="Nome do personagem, lugar..."
					required
				/>
			</label>
			<div className={styles.twoColumns}>
				<SelectField
					label="Tipo"
					value={entityType}
					options={ENTITY_TYPE_OPTIONS}
					onChange={setEntityType}
					ariaLabel="Tipo do novo elemento"
				/>
				<SelectField
					label="Visibilidade"
					value={visibility}
					options={VISIBILITY_OPTIONS}
					onChange={setVisibility}
					ariaLabel="Visibilidade do novo elemento"
				/>
			</div>
			<button className={styles.primaryButton} type="submit">
				Criar elemento
			</button>
		</form>
	);
}

function NewRelationForm({
	draft,
	selectedId,
	onCreate,
}: {
	draft: WorldGraphDraft;
	selectedId: string | null;
	onCreate: (edge: WorldGraphDraftEdge) => void;
}) {
	const nodes = draft.nodes.filter((node) => node.status !== "archived");
	const types = draft.relationTypes.filter((type) => type.isActive);
	const [source, setSource] = useState(selectedId ?? nodes[0]?.id ?? "");
	const [target, setTarget] = useState(
		nodes.find((node) => node.id !== (selectedId ?? nodes[0]?.id))?.id ?? "",
	);
	const [relationType, setRelationType] = useState(types[0]?.slug ?? "");
	const [visibility, setVisibility] = useState<WorldVisibility>("private_players");
	const nodeOptions = nodes.map((node) => ({ value: node.id, label: node.name }));
	const typeOptions = types.map((type) => ({ value: type.slug, label: type.label }));
	if (nodes.length < 2 || !types.length) {
		return (
			<div className={styles.emptyCallout}>
				{nodes.length < 2
					? "Crie pelo menos dois elementos para conectar."
					: "Crie um tipo de ligação em “Tipos e cores” antes de conectar."}
			</div>
		);
	}
	return (
		<form
			className={styles.form}
			onSubmit={(event) => {
				event.preventDefault();
				if (!source || !target || source === target || !relationType) return;
				onCreate({
					id: crypto.randomUUID(),
					source,
					target,
					relationType,
					labelOverride: null,
					status: "active",
					visibility,
					colorOverride: null,
					lineStyleOverride: null,
					lineWidthOverride: null,
				});
			}}
		>
			<div className={styles.formHeading}>
				<div>
					<span>Conectar o mapa</span>
					<h3>Nova ligação</h3>
				</div>
			</div>
			<SelectField
				label="Origem"
				value={source}
				options={nodeOptions}
				onChange={setSource}
				ariaLabel="Origem da ligação"
			/>
			<SelectField
				label="Destino"
				value={target}
				options={nodeOptions.map((option) => ({
					...option,
					disabled: option.value === source,
				}))}
				onChange={setTarget}
				ariaLabel="Destino da ligação"
			/>
			<SelectField
				label="Tipo"
				value={relationType}
				options={typeOptions}
				onChange={setRelationType}
				ariaLabel="Tipo da ligação"
			/>
			<SelectField
				label="Visibilidade"
				value={visibility}
				options={VISIBILITY_OPTIONS}
				onChange={setVisibility}
				ariaLabel="Visibilidade da ligação"
			/>
			<button className={styles.primaryButton} type="submit">
				Criar ligação
			</button>
		</form>
	);
}

function RelationEditor({
	draft,
	edgeId,
	onChange,
	onClose,
}: {
	draft: WorldGraphDraft;
	edgeId: string;
	onChange: (draft: WorldGraphDraft, message?: string) => void;
	onClose: () => void;
}) {
	const edge = draft.edges.find((item) => item.id === edgeId);
	if (!edge) return null;
	const type = draft.relationTypes.find((item) => item.slug === edge.relationType);
	const typeOptions = draft.relationTypes
		.filter((item) => item.isActive || item.slug === edge.relationType)
		.map((item) => ({ value: item.slug, label: item.label }));
	return (
		<div className={styles.form}>
			<div className={styles.formHeading}>
				<div>
					<span>Ligação selecionada</span>
					<h3>{edge.labelOverride ?? type?.label ?? edge.relationType}</h3>
				</div>
				<button type="button" onClick={onClose}>
					Fechar
				</button>
			</div>
			<SelectField
				label="Tipo"
				value={edge.relationType}
				options={typeOptions}
				onChange={(value) => onChange(updateEdge(draft, edge.id, { relationType: value }))}
				ariaLabel="Tipo da ligação selecionada"
			/>
			<label>
				Nome específico
				<input
					value={edge.labelOverride ?? ""}
					onChange={(event) =>
						onChange(
							updateEdge(draft, edge.id, {
								labelOverride: event.target.value || null,
							}),
						)
					}
					placeholder={type?.label ?? "Nome opcional"}
				/>
			</label>
			<SelectField
				label="Visibilidade"
				value={edge.visibility}
				options={VISIBILITY_OPTIONS}
				onChange={(value) => onChange(updateEdge(draft, edge.id, { visibility: value }))}
				ariaLabel="Visibilidade da ligação selecionada"
			/>
			<details className={styles.advanced}>
				<summary>Aparência específica desta ligação</summary>
				<label>
					Cor personalizada
					<input
						type="color"
						value={edge.colorOverride ?? type?.color ?? "#8f9aa8"}
						onChange={(event) =>
							onChange(updateEdge(draft, edge.id, { colorOverride: event.target.value }))
						}
					/>
				</label>
				<SelectField
					label="Traço"
					value={edge.lineStyleOverride ?? type?.lineStyle ?? "solid"}
					options={LINE_STYLE_OPTIONS}
					onChange={(value) =>
						onChange(updateEdge(draft, edge.id, { lineStyleOverride: value }))
					}
					ariaLabel="Traço específico da ligação"
				/>
				<label>
					Espessura
					<input
						type="number"
						min={1}
						max={8}
						step={0.5}
						value={edge.lineWidthOverride ?? type?.lineWidth ?? 3}
						onChange={(event) =>
							onChange(
								updateEdge(draft, edge.id, {
									lineWidthOverride: Math.min(
										8,
										Math.max(1, Number(event.target.value) || 3),
									),
								}),
							)
						}
					/>
				</label>
				<button
					type="button"
					onClick={() =>
						onChange(
							updateEdge(draft, edge.id, {
								colorOverride: null,
								lineStyleOverride: null,
								lineWidthOverride: null,
							}),
						)
					}
				>
					Usar aparência do tipo
				</button>
			</details>
			<button
				className={styles.dangerButton}
				type="button"
				onClick={() => {
					onChange(
						updateEdge(draft, edge.id, { status: "archived" }),
						"Ligação arquivada no rascunho.",
					);
					onClose();
				}}
			>
				Arquivar ligação
			</button>
		</div>
	);
}

function NewRelationTypeForm({
	draft,
	onCreate,
}: {
	draft: WorldGraphDraft;
	onCreate: (type: WorldGraphDraftRelationType) => void;
}) {
	const [label, setLabel] = useState("");
	const [direction, setDirection] = useState<WorldRelationDirection>("symmetric");
	const [family, setFamily] = useState<WorldRelationFamily>("context");
	const used = useMemo(
		() => new Set(draft.relationTypes.map((type) => type.slug)),
		[draft.relationTypes],
	);
	return (
		<form
			className={styles.form}
			onSubmit={(event) => {
				event.preventDefault();
				const trimmed = label.trim();
				if (!trimmed) return;
				onCreate({
					slug: typeSlug(trimmed, used),
					label: trimmed,
					direction,
					family,
					description: "",
					isActive: true,
					color: "#8f9aa8",
					lineStyle: "solid",
					lineWidth: 3,
				});
				setLabel("");
			}}
		>
			<div className={styles.formHeading}>
				<div>
					<span>Vocabulário visual</span>
					<h3>Novo tipo de ligação</h3>
				</div>
			</div>
			<label>
				Nome
				<input
					value={label}
					onChange={(event) => setLabel(event.target.value)}
					placeholder="Amizade, Rivalidade, Família..."
					required
				/>
			</label>
			<div className={styles.twoColumns}>
				<SelectField
					label="Direção"
					value={direction}
					options={DIRECTION_OPTIONS}
					onChange={setDirection}
					ariaLabel="Direção do novo tipo"
				/>
				<SelectField
					label="Família visual"
					value={family}
					options={FAMILY_OPTIONS}
					onChange={setFamily}
					ariaLabel="Família visual do novo tipo"
				/>
			</div>
			<button className={styles.primaryButton} type="submit">
				Criar tipo
			</button>
		</form>
	);
}

function RelationTypeEditor({
	draft,
	typeSlug: slug,
	onChange,
	onClose,
}: {
	draft: WorldGraphDraft;
	typeSlug: string;
	onChange: (draft: WorldGraphDraft, message?: string) => void;
	onClose: () => void;
}) {
	const type = draft.relationTypes.find((item) => item.slug === slug);
	if (!type) return null;
	return (
		<div className={styles.form}>
			<div className={styles.formHeading}>
				<div>
					<span>Tipo de ligação</span>
					<h3>{type.label}</h3>
				</div>
				<button type="button" onClick={onClose}>
					Fechar
				</button>
			</div>
			<label>
				Nome
				<input
					value={type.label}
					onChange={(event) =>
						onChange(updateType(draft, type.slug, { label: event.target.value }))
					}
				/>
			</label>
			<label>
				Identificador
				<input value={type.slug} readOnly aria-readonly="true" />
			</label>
			<div className={styles.twoColumns}>
				<SelectField
					label="Direção"
					value={type.direction}
					options={DIRECTION_OPTIONS}
					onChange={(value) => onChange(updateType(draft, type.slug, { direction: value }))}
					ariaLabel="Direção do tipo"
				/>
				<SelectField
					label="Família"
					value={type.family}
					options={FAMILY_OPTIONS}
					onChange={(value) => onChange(updateType(draft, type.slug, { family: value }))}
					ariaLabel="Família do tipo"
				/>
			</div>
			<label>
				Descrição
				<textarea
					rows={3}
					value={type.description}
					onChange={(event) =>
						onChange(updateType(draft, type.slug, { description: event.target.value }))
					}
				/>
			</label>
			<div className={styles.styleGrid}>
				<label>
					Cor
					<input
						type="color"
						value={type.color}
						onChange={(event) =>
							onChange(updateType(draft, type.slug, { color: event.target.value }))
						}
					/>
				</label>
				<SelectField
					label="Traço"
					value={type.lineStyle}
					options={LINE_STYLE_OPTIONS}
					onChange={(value) => onChange(updateType(draft, type.slug, { lineStyle: value }))}
					ariaLabel="Traço do tipo"
				/>
				<label>
					Espessura
					<input
						type="number"
						min={1}
						max={8}
						step={0.5}
						value={type.lineWidth}
						onChange={(event) =>
							onChange(
								updateType(draft, type.slug, {
									lineWidth: Math.min(8, Math.max(1, Number(event.target.value) || 3)),
								}),
							)
						}
					/>
				</label>
			</div>
			<label className={styles.checkbox}>
				<input
					type="checkbox"
					checked={type.isActive}
					onChange={(event) =>
						onChange(updateType(draft, type.slug, { isActive: event.target.checked }))
					}
				/>
				Disponível para novas ligações
			</label>
		</div>
	);
}