import type { Metadata } from "next";
import { cache } from "react";
import "@xyflow/react/dist/style.css";
import { buildPublicMetadata } from "@/config/public-metadata";
import { authorizeCampaignCapabilityServer } from "@/features/auth/server";
import { EDIT_CAPABILITIES } from "@/features/edit/access/policy";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import { WorldExplorerClient } from "@/features/world-explorer/components/world-explorer-client";
import { WorldExplorerProvider } from "@/features/world-explorer/components/world-explorer-provider";
import { resolveWorldAudienceServer } from "@/features/world-explorer/world-audience-server";
import { loadPublishedWorldLayout } from "@/features/world-explorer/layout-repository";
import {
	buildWorldProjection,
	resolveWorldFocusId,
} from "@/features/world-explorer/projection";
import { loadWorldDataset } from "@/features/world-explorer/world-repository";

type MundoPageProps = {
	searchParams: Promise<{ foco?: string | string[] }>;
};

const mundoAccess = cache(async () => {
	const [layoutAccess, contentAccess] = await Promise.all([
		authorizeCampaignCapabilityServer({
			action: EDIT_CAPABILITIES.worldLayoutEdit,
			campaignSlug: CAMPAIGN_SLUG,
		}),
		authorizeCampaignCapabilityServer({
			action: EDIT_CAPABILITIES.contentEdit,
			campaignSlug: CAMPAIGN_SLUG,
		}),
	]);
	const canEditLayout = layoutAccess.ok === true;
	const canEditContent = contentAccess.ok === true;
	const fullWorldEditor = canEditLayout && canEditContent;
	const audience = await resolveWorldAudienceServer({
		fullWorldEditor,
		campaignSlug: CAMPAIGN_SLUG,
	});
	return { canEditLayout, canEditContent, fullWorldEditor, audience };
});

function requestedFocusFrom(
	query: Awaited<MundoPageProps["searchParams"]>,
): string | undefined {
	return Array.isArray(query.foco) ? query.foco[0] : query.foco;
}

export async function generateMetadata({
	searchParams,
}: MundoPageProps): Promise<Metadata> {
	const query = await searchParams;
	const requestedFocus = requestedFocusFrom(query);
	const { audience } = await mundoAccess();
	const dataset = await loadWorldDataset(audience);
	const focusId = resolveWorldFocusId(dataset, requestedFocus);
	const focus = focusId ? dataset.nodes.find((node) => node.id === focusId) : undefined;
	const shareFocusedEntity = Boolean(requestedFocus && focus?.slug);
	const pathname = shareFocusedEntity
		? `/mundo?foco=${encodeURIComponent(focus?.slug ?? "")}`
		: "/mundo";
	const demoSuffix = dataset.demo ? " — demonstração" : "";
	const title = shareFocusedEntity
		? `${focus?.label ?? "Memória"} · Ecos da Jornada${demoSuffix}`
		: `Ecos da Jornada${demoSuffix}`;
	const description = dataset.demo
		? shareFocusedEntity
			? `Demonstração do World Explorer do TDA com ${focus?.label ?? "uma memória"} em foco. As relações exibidas neste recorte não são canon.`
			: "Demonstração multi-hub do World Explorer do TDA. As relações exibidas neste recorte visual não são canon."
		: shareFocusedEntity
			? `Explore os laços públicos de ${focus?.label ?? "uma memória"} no Mundo da campanha.`
			: "Pessoas, lugares e histórias conectadas no Mundo da campanha.";

	return buildPublicMetadata({ title, description, pathname });
}

export default async function MundoPage({ searchParams }: MundoPageProps) {
	const query = await searchParams;
	const requestedFocus = requestedFocusFrom(query);
	const { canEditLayout, fullWorldEditor, audience } = await mundoAccess();
	const dataset = await loadWorldDataset(audience);
	const focusId = resolveWorldFocusId(dataset, requestedFocus);
	const projection = buildWorldProjection(dataset, focusId);
	projection.layout = await loadPublishedWorldLayout(projection);

	return (
		<div
			style={{
				display: "grid",
				minWidth: 0,
				maxWidth: "100%",
				minHeight: "100dvh",
				overflowX: "clip",
			}}
		>
			<WorldExplorerProvider>
				<WorldExplorerClient
					projection={projection}
					canEditLayout={canEditLayout}
					canEditContent={fullWorldEditor}
				/>
			</WorldExplorerProvider>
		</div>
	);
}
