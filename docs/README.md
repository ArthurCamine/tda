# Documentação TDA

> Status: vigente
> Owner: documentação/arquitetura
> Última revisão: 2026-09-12
> Fonte de verdade: `Faysk/tda@main` e documentos donos desta árvore

> **Fonte de verdade do reboot.** Esta árvore documenta o produto, a arquitetura, o banco, a operação e as decisões vigentes do `Faysk/tda`.
>
> `Faysk/dnd-scribe` é referência histórica. Nenhuma decisão, status ou arquitetura do legado passa a valer no TDA sem revalidação explícita e registro aqui.

## Como ler esta documentação

A documentação é organizada em camadas para continuar navegável quando o projeto crescer:

1. **Visão e estado** — o que é o TDA, onde estamos e para onde vamos.
2. **Arquitetura** — limites do sistema, componentes, fluxos e invariantes.
3. **Design System** — identidade visual oficial, tokens, assets e composição.
4. **Domínios** — regras de negócio e ownership conceitual.
5. **Banco** — schema real, segurança, migrations e dívida técnica.
6. **Features** — catálogo e especificações de capacidades implementadas, preparadas e planejadas.
7. **Integrações** — contratos com serviços externos.
8. **Operação** — ambientes, release, deploy, rollback e runbooks.
9. **Decisões** — ADRs que explicam por que escolhas estruturais foram feitas.
10. **Legado** — o que foi herdado, revalidado, substituído ou descartado.

### Onboarding pelo estado atual

Para entender o TDA sem confundir candidato com produção, seguir esta ordem:

1. **Home e sessões públicas** — [Infraestrutura e estado](infrastructure.md), [Roadmap](roadmap.md), [Campanhas, sessões e participantes](domains/sessions.md) e [runbook de release](operations/release-runbook.md). Aqui ficam o que já existe na `main`, o que foi realmente publicado e os gates da próxima release.
2. **Edit e transcrições** — [Edit Workbench](features/edit-workbench.md), [slice server-side](features/edit-transcript-server-slice.md), [arquitetura do Edit](architecture/edit-workbench.md) e [paridade do legado](legacy/edit-parity.md). A ordem é identidade/capability, persistence concorrente/auditável e então convergência da UX, sem promover adapters temporários a arquitetura final.
3. **Novas superfícies narrativas** — [Perfis editoriais](features/entity-profiles.md), [World Explorer](features/world-explorer.md), [relações/grafo](features/relations-graph.md) e demais features. Elas vêm depois da consolidação do público e do primeiro fluxo crítico do Edit.
4. **Operação** — só ao publicar, aplicar migration ou alterar serviço, usar os runbooks da área. Merge de código/documentação não substitui deployment, aplicação de banco ou configuração remota.

O [Roadmap](roadmap.md) é o ponto editorial para dependências entre frentes/candidatos abertos. O contrato detalhado continua sempre no documento dono de cada área; auditorias datadas não são copiadas para índices gerais.

## Índice canônico

### Produto e direção

- [Roadmap](roadmap.md) — entregas e ordem de evolução.
- [Catálogo de features](feature-catalog.md) — status canônico de cada feature.
- [Infraestrutura e estado](infrastructure.md) — inventário operacional atual.
- [Gestão de entregas](delivery/README.md) — Kanban leve, inventário operacional, composição de candidatos e medição.
- [Versões verificadas](versions.json) — versões de runtime/ferramentas deliberadamente fixadas.

### Arquitetura

- [Arquitetura — visão executiva](architecture.md)
- [Arquitetura — índice detalhado](architecture/README.md)
- [Contexto e limites do sistema](architecture/system-context.md)
- [Fluxos ponta a ponta](architecture/data-flows.md)
- [Princípios e invariantes](architecture/invariants.md)
- [Edit Workbench — boundary administrativo](architecture/edit-workbench.md)

### Design System e marca

- [Design System oficial](design-system/README.md) — TDA Design System v1.0.0, tokens, princípios e migração para o reboot.
- [Diretriz geral de UX, design e hierarquia](design-system/ux-hierarchy.md) — princípios transversais de composição, densidade, hierarquia e prioridade do conteúdo.
- [Plano de migração visual](design-system/migration-plan.md) — fases para introduzir tokens, primitives e assets sem big bang.
- [Assets oficiais da marca](design-system/official-assets.md) — TDA Brand Pack, masters, logo, pato, favicon/PWA/social.
- [World Explorer — composição e UX](design-system/world-explorer-ui.md) — tradução das referências visuais aprovadas para contrato de interface.

### Modelo de dados e banco

- [Modelo de dados canônico](data-model.md) — vocabulário e identidades do domínio.
- [Banco — índice](database/README.md)
- [Catálogo das 43 tabelas públicas](database/schema-catalog.md)
- [Relacionamentos e ownership](database/relationships.md)
- [RLS, RBAC, RPCs e segurança](database/security.md)
- [Migrations e evolução do schema](database/migrations.md)
- [Auditoria do banco de produção](database-audit.md) — fotografia observada, não substitui o contrato.

### Domínios

- [Domínios — índice](domains/README.md)
- [Identidade, Auth e autorização](domains/identity-access.md)
- [Campanhas, sessões e participantes](domains/sessions.md)
- [Evidências, transcrição e classificação](domains/evidence.md)
- [Entidades, personagens e mundo narrativo](domains/entities.md)
- [Canon, revisão e publicação](domains/canon-review.md)
- [Processamento, jobs e áudio](domains/processing.md)

### Features e expansão

- [Diários dos personagens](features/character-diaries.md) — livros independentes em `/diario`, separados das lores.

- [Lores independentes — liberdade visual e catálogo](features/independent-lores.md)
- [Especificações de features — índice](features/README.md)
- [Edit Workbench / administração](features/edit-workbench.md)
- [Processamento local no Edit](features/local-processing.md) — UI/adapters, ensaio sintético e gates de integração.
- [TDA Companion v0.3 — Desktop, Agent e ASR](features/companion-desktop-asr-v0.3.md) — Agent/Desktop, worker subprocess, ingest Craig e perfis ASR locais.
- [Personagens e NPCs](features/characters-and-npcs.md)
- [Perfis editoriais de entities](features/entity-profiles.md)
- [World Explorer / Ecos da Jornada](features/world-explorer.md)
- [Relações e grafo](features/relations-graph.md)
- [Contrato proposto de relations](features/relations-data-contract.md)
- [Conhecimento e audiência](features/knowledge-audience.md)
- [Timeline por entidade](features/entity-timeline.md)
- [Busca semântica](features/semantic-search.md)
- [Mapas narrativos](features/maps.md)
- [Músicas e performances](features/music-performances.md)
- [Quests e ganchos](features/quests-hooks.md)
- [Sessão ao vivo](features/live-session.md)
- [Assistente Discord](features/discord-assistant.md)
- [Intents / intenção — conceito ainda não definido](features/intents.md)

### Integrações

- [Integrações — índice](integrations/README.md)
- [Supabase](integrations/supabase.md)
- [Cloudflare R2](integrations/r2.md)
- [Fluxo obrigatório de imagens](integrations/r2/media-pipeline.md) — preparação, upload, verificação, responsabilidades e aceite.
- [Vercel](integrations/vercel.md)
- [Craig, Discord e Roll20](integrations/table-sources.md)
- [Companion local](integrations/local-companion.md)

### Operação

- [Operação — índice](operations/README.md)
- [Ambientes e configuração](operations/environments.md)
- [Login Discord — configuração e verificação](operations/discord-auth.md)
- [Companion — política de versões e dependências](operations/companion-dependency-policy.md) — pins compatíveis, freshness e gate de release do Companion.
- [Release, deploy e rollback](operations/release-runbook.md)
- [Publicação controlada](releases.md) — política resumida.
- [Segurança operacional](operations/security-checklist.md)

### Decisões arquiteturais

- [ADRs — índice](adr/README.md)
- [ADR-0001 — TDA como identidade canônica; dnd-scribe como legado](adr/0001-project-identity.md)
- [ADR-0002 — Supabase existente como única base](adr/0002-existing-supabase.md)
- [ADR-0003 — processamento pesado local; cloud para produto e conteúdo sincronizado](adr/0003-local-heavy-processing.md)
- [ADR-0004 — registry única de entities para PC/NPC/mundo](adr/0004-canonical-entities.md)
- [ADR-0005 — canon exige fonte e revisão](adr/0005-canon-review-gate.md)
- [ADR-0006 — React Flow como engine do World Explorer](adr/0006-react-flow-world-explorer.md)
- [ADR-0007 — Edit como workbench server-first orientado a capabilities](adr/0007-edit-workbench.md)
- [ADR-0008 — autorização orientada a capabilities e scope](adr/0008-capability-authorization.md)
- [ADR-0009 — World Explorer multi-hub e layout espacial reorganizável](adr/0009-world-explorer-multihub-layout.md)
- [ADR-0010 — persistência editorial do layout separada do canon](adr/0010-world-explorer-editorial-layout-persistence.md)
- [ADR-0011 — persistência física candidata do layout editorial](adr/0011-world-explorer-layout-physical-persistence.md)
- [ADR-0012 — GitHub Actions controla a entrega](adr/0012-github-actions-controlled-delivery.md)
- [ADR-0013 — TDA Companion como Agent local, Desktop de controle e runtime ASR multi-engine](adr/0013-companion-agent-desktop-asr.md)

### Governança da própria documentação

- [Documentação viva — política e manutenção](documentation/README.md)
- [Catálogo completo gerado e lacunas de metadados](documentation/catalog.md)
- [Retirada do projeto Vercel legado](operations/legacy-retirement.md)
- [Template de documento](documentation/document-template.md)
- [Template de ADR](documentation/adr-template.md)
- [Registro de fontes históricas](legacy/README.md)
- [Edit — matriz de paridade com o legado](legacy/edit-parity.md)

## Status usados em todos os docs

Os estados abaixo descrevem **maturidade do contrato/capacidade**, não estágio de entrega de uma mudança concreta.

| Status | Significado |
| --- | --- |
| **implementado** | existe e é utilizável no sistema/schema vigente |
| **preparado** | estrutura existe, mas operação/UI/população ainda não está completa |
| **arquitetura aprovada** | boundary/UX/tecnologia principal aceitos; implementação ainda pode estar pendente |
| **planejado** | direção aprovada no reboot; implementação ainda não iniciada |
| **em desenho** | objetivo aceito, porém contrato ainda precisa ser fechado |
| **legado compatível** | continua operando apenas para não quebrar a transição |
| **histórico** | referência útil do `dnd-scribe`, sem autoridade sobre o reboot |
| **fora de escopo** | explicitamente não pertence à entrega/arquitetura atual |

Para mudanças concretas, a [política de documentação viva](documentation/README.md) separa `implementado em branch/PR`, `validado`, `integrado à main` e `publicado/aplicado`. **Validado não implica integrado; integrado não implica publicado.**

## Regras de manutenção

- Mudança estrutural de código, schema, segurança, integração ou operação **deve atualizar o documento dono do assunto na mesma PR**.
- Mudança visual sistêmica deve atualizar o documento/tokens donos em `docs/design-system/`.
- DDL aplicada no Supabase deve possuir migration versionada em `supabase/migrations` com a mesma versão registrada remotamente.
- Feature futura primeiro recebe contrato/documentação; depois schema/código.
- Não duplicar fatos: um documento é canônico e os demais apontam para ele.
- Auditorias com data descrevem uma fotografia; contratos descrevem a regra vigente.
- Não armazenar secrets, tokens de autenticação, chaves ou dados privados na documentação.
- Decisões irreversíveis ou de alto impacto recebem ADR.
- Assets de marca não são redesenhados fora do Brand Pack oficial.
- `pnpm docs:check` valida recursivamente links Markdown e falha se houver documento órfão fora da árvore deste índice.

## Identidades e fontes fixas atuais

- Produto: `tda`.
- Campanha principal: `yuhara-main`.
- Supabase: `dmrqnbdvbkfqzctcerbx`.
- Repositório vigente: `Faysk/tda`.
- Legado: `Faysk/dnd-scribe`.
- Design System oficial: `TDA Design System v1.0.0` fornecido em 2026-09-06.
- Brand Pack oficial: `TDA — Tem Dado Aqui — Brand Pack` fornecido em 2026-09-06.
- World Explorer: React Flow (`@xyflow/react`) como engine de visualização, domínio independente.
- Transcrição pesada: local.
- Binários cloud: Cloudflare R2, separados por visibilidade/ambiente.
- Vercel correta para futuras operações: conta/contexto `projeto-desenv-6905` / `projeto_desenv@outlook.com`.

Última revisão estrutural: **2026-09-11**.

- [Do ZIP à produção — páginas e mídia com fidelidade](operations/zip-to-production.md) — preparação, preservação, integração, publicação e rollback.
