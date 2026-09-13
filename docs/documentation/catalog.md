# Catálogo documental gerado

Gerado por `pnpm docs:generate`; não editar manualmente. O [índice editorial](../README.md) continua sendo a entrada canônica. Este catálogo localiza páginas e lacunas de metadados sem duplicar contratos.

Datas e estados são extraídos do cabeçalho, não inferidos do Git. `Não declarado` é lacuna de metadados, não ausência de implementação. O catálogo não concede aprovação nem substitui evidências.

## docs

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Documentação TDA](../README.md) | documentação/arquitetura | vigente | 2026-09-12 |
| [Arquitetura](../architecture.md) | Não declarado | Não declarado | Não declarado |
| [Modelo de dados canônico](../data-model.md) | Não declarado | Não declarado | Não declarado |
| [Auditoria do banco de produção](../database-audit.md) | Não declarado | Não declarado | Não declarado |
| [Catálogo canônico de features](../feature-catalog.md) | produto / arquitetura | vigente | 2026-09-11 |
| [Infraestrutura e estado](../infrastructure.md) | infraestrutura/operação | vigente; production ativa | 2026-09-07 |
| [Publicação controlada](../releases.md) | Não declarado | Não declarado | Não declarado |
| [Roadmap](../roadmap.md) | produto / arquitetura | vigente | 2026-09-11 |

## docs/adr

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [ADR-0001 — TDA como identidade canônica; dnd-scribe como legado](../adr/0001-project-identity.md) | Não declarado | accepted | Não declarado |
| [ADR-0002 — Reutilizar o Supabase existente como única base](../adr/0002-existing-supabase.md) | Não declarado | accepted | Não declarado |
| [ADR-0003 — Processamento pesado local; produto cloud](../adr/0003-local-heavy-processing.md) | Não declarado | accepted | Não declarado |
| [ADR-0004 — Registry única de entities para PC, NPC e mundo](../adr/0004-canonical-entities.md) | Não declarado | accepted | Não declarado |
| [ADR-0005 — Canon exige fonte e revisão](../adr/0005-canon-review-gate.md) | Não declarado | accepted | Não declarado |
| [ADR-0006 — React Flow como engine de visualização do World Explorer](../adr/0006-react-flow-world-explorer.md) | frontend / narrative-memory | aceito | Não declarado |
| [ADR-0007 — Edit como workbench server-first orientado a capabilities](../adr/0007-edit-workbench.md) | Não declarado | Não declarado | Não declarado |
| [ADR-0008 — autorização orientada a capabilities e scope](../adr/0008-capability-authorization.md) | identity/access + arquitetura + segurança | accepted | Não declarado |
| [ADR-0009 — World Explorer multi-hub e layout espacial reorganizável](../adr/0009-world-explorer-multihub-layout.md) | frontend / narrative-memory | accepted | 2026-09-08 |
| [ADR-0010 — persistência editorial do layout do World Explorer separada do canon](../adr/0010-world-explorer-editorial-layout-persistence.md) | frontend / narrative-memory / identity-access | accepted | 2026-09-08 |
| [ADR-0011 — persistência física candidata do layout editorial do World Explorer](../adr/0011-world-explorer-layout-physical-persistence.md) | frontend / narrative-memory / dados / identity-access | accepted | Não declarado |
| [ADR-0012 — GitHub Actions controla a entrega; Vercel Git auto-deploy permanece desligado](../adr/0012-github-actions-controlled-delivery.md) | operations / arquitetura / dados | accepted | Não declarado |
| [ADR-0013 — TDA Companion como Agent local, Desktop de controle e runtime ASR multi-engine](../adr/0013-companion-agent-desktop-asr.md) | local-companion / processing | accepted | Não declarado |
| [Architecture Decision Records](../adr/README.md) | arquitetura | vigente | Não declarado |

## docs/architecture

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Arquitetura — índice detalhado](../architecture/README.md) | arquitetura do TDA | vigente | 2026-09-07 |
| [Fluxos ponta a ponta](../architecture/data-flows.md) | arquitetura + domínios | vigente/parcialmente preparado | 2026-09-06 |
| [Arquitetura do Edit Workbench](../architecture/edit-workbench.md) | arquitetura + Edit | accepted / implementação incremental | 2026-09-07 |
| [Princípios e invariantes](../architecture/invariants.md) | arquitetura | vigente | 2026-09-10 |
| [Contexto e limites do sistema](../architecture/system-context.md) | arquitetura | vigente | 2026-09-06 |

## docs/database

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Banco de dados — índice](../database/README.md) | dados/Supabase | vigente | 2026-09-07 |
| [Reconciliações do migration history](../database/migration-reconciliations.md) | dados/Supabase + operations | vigente | 2026-09-10 |
| [Migrations e evolução do schema](../database/migrations.md) | dados/Supabase | vigente | 2026-09-10 |
| [Relacionamentos e ownership de dados](../database/relationships.md) | dados + domínios | vigente | 2026-09-06 |
| [Inventário de RPCs privilegiadas do Supabase](../database/rpc-inventory.md) | segurança/dados | vigente / revisão de hardening em andamento | Não declarado |
| [Catálogo do schema Supabase](../database/schema-catalog.md) | dados/Supabase | implementado | 2026-09-06 |
| [Segurança do banco: Auth, RLS, RBAC, RPCs e grants](../database/security.md) | segurança/dados | implementado + transição em andamento | 2026-09-10 |
| [Log de verificações do banco de produção](../database/verification-log.md) | dados/Supabase | vigente / append-only por intenção | Não declarado |

## docs/delivery

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Gestão de entregas](../delivery/README.md) | Prancheta - Organização de entregas | preparado | 2026-09-07 |
| [Inventário de entregas](../delivery/inventory.md) | Prancheta - Organização de entregas | vigente | 2026-09-11 |
| [Medição de esforço e qualidade](../delivery/measurement.md) | Prancheta - Organização de entregas | preparado | 2026-09-07 |
| [Composição de candidato e marcos](../delivery/release-candidate.md) | Prancheta - Organização de entregas; decisão de escopo por Polvo - Coordenação e produto | preparado | 2026-09-07 |
| [Fluxo de entregas](../delivery/workflow.md) | Prancheta - Organização de entregas; execução por Polvo - Coordenação | preparado | 2026-09-07 |

## docs/design-system

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Design System oficial do TDA](../design-system/README.md) | design-system / frontend | canônico; fundação runtime e superfícies públicas implementadas | 2026-09-12 |
| [Plano de migração do Design System para o reboot](../design-system/migration-plan.md) | design-system / frontend | DS-1/DS-2/DS-3 concluídas; DS-4 parcial; DS-5 implementada; DS-7 cleanup legado aplicado | 2026-09-07 |
| [Assets oficiais da marca TDA](../design-system/official-assets.md) | brand / design-system | canônico para marca; integração runtime parcial e verificável | 2026-09-06 |
| [Superfícies públicas — ownership visual e composição](../design-system/public-surfaces.md) | design-system / frontend público | implementado; atualizado após Home V2 e shell responsiva | 2026-09-12 |
| [TDA — Diretriz geral de UX, design e hierarquia visual](../design-system/ux-hierarchy.md) | design-system / frontend | canônico | 2026-09-12 |
| [World Explorer — composição e UX oficial](../design-system/world-explorer-ui.md) | product / design-system / narrative-memory | direção visual aprovada; workspace atual implementado, chrome v3 planejado | 2026-09-12 |
| [World Workspace — chrome espacial e sobreposição](../design-system/world-explorer-workspace-chrome-v3.md) | product / design-system / frontend / narrative-memory | direção UX aprovada; implementação planejada | 2026-09-12 |

## docs/documentation

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Documentação viva](README.md) | documentação/arquitetura | vigente | 2026-09-07 |
| [ADR-NNNN — Título](adr-template.md) | Não declarado | proposed  /  accepted  /  superseded  /  rejected | Não declarado |
| [Template de documento](document-template.md) | Não declarado | Não declarado | Não declarado |

## docs/domains

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Domínios do TDA](../domains/README.md) | produto/arquitetura | vigente | 2026-09-06 |
| [Canon, revisão e publicação](../domains/canon-review.md) | review/canon | schema implementado; operação integrada ainda preparada/planejada | 2026-09-08 |
| [Entidades, personagens e mundo narrativo](../domains/entities.md) | narrative-memory/entities | preparado | 2026-09-06 |
| [Evidências, transcrição e classificação](../domains/evidence.md) | evidence/transcription | implementado + modernização planejada | 2026-09-06 |
| [Identidade, Auth e autorização](../domains/identity-access.md) | identity/access | arquitetura aprovada + convergência em andamento | 2026-09-07 |
| [Processamento, jobs e áudio](../domains/processing.md) | processing/local-companion | legado funcional + modernização planejada | 2026-09-06 |
| [Campanhas, sessões e participantes](../domains/sessions.md) | sessions | implementado | 2026-09-06 |

## docs/features

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Especificações de features](../features/README.md) | produto + domínios | vivo | 2026-09-12 |
| [Feature — Personagens e NPCs](../features/characters-and-npcs.md) | entities/narrative-memory | preparado | 2026-09-06 |
| [TDA Companion v0.3 — Desktop, Agent e ASR](../features/companion-desktop-asr-v0.3.md) | local-companion / processing | especificação aceita para implementação | 2026-09-11 |
| [Feature — Assistente Discord](../features/discord-assistant.md) | integrations/discord + narrative query | histórico/planejado | 2026-09-06 |
| [Edit — consulta de permissões](../features/edit-permissions.md) | identity/access + Edit | implementação candidata, somente leitura | 2026-09-07 |
| [Edit — slice server-side de transcrição](../features/edit-transcript-server-slice.md) | Edit / aplicação + dados | leitura autorizada implementada com revision; mutation canônica preparada; persistence atômica pendente; bypass temporário de UI separado | 2026-09-07 |
| [Edit — modo temporário sem autenticação](../features/edit-unsafe-development.md) | Edit / aplicação + segurança | compatibilidade temporária de desenvolvimento | 2026-09-07 |
| [Edit Workbench — área administrativa do TDA](../features/edit-workbench.md) | Edit / produto + frontend | arquitetura aprovada; implementação incremental em andamento | 2026-09-07 |
| [Feature — Perfis editoriais de entities](../features/entity-profiles.md) | narrative-memory / frontend | preparado; projection publicada pendente | 2026-09-08 |
| [Feature — Timeline por entidade](../features/entity-timeline.md) | narrative-memory | preparado | 2026-09-06 |
| [Lores independentes — publicação, liberdade visual e catálogo](../features/independent-lores.md) | narrative-memory / frontend / produto | arquitetura aprovada; decisão editorial, não comprovação de implementação | 2026-09-12 |
| [Feature/conceito — Intents / intenção](../features/intents.md) | não atribuído | **não definido / não encontrado como conceito canônico** | 2026-09-06 |
| [Feature — Conhecimento e audiência](../features/knowledge-audience.md) | narrative-memory/security | em desenho | 2026-09-06 |
| [Feature — Modo sessão ao vivo](../features/live-session.md) | sessions/live | histórico/planejado; fora das entregas imediatas | 2026-09-06 |
| [Processamento local no Edit](../features/local-processing.md) | Processamento UI/adapters (Painelzinho); API/export local: Motorzinho; importação cloud: Carteiro | implementação candidata | 2026-09-13 |
| [Fidelidade dos pacotes de D e Seika](../features/lore-pack-fidelity.md) | lores e mídia | publicado e verificado em 2026-09-12 | 2026-09-12 |
| [Feature — Mapas narrativos](../features/maps.md) | narrative-memory/maps | em desenho | 2026-09-06 |
| [Feature — Músicas e performances](../features/music-performances.md) | narrative-memory/media | preparado/em desenho | 2026-09-06 |
| [Pipipi — lore cinematográfica pioneira](../features/pipipi-lore.md) | narrative-memory / frontend | implementação, QA e publicação em production concluídos | 2026-09-12 |
| [Feature — Quests e ganchos](../features/quests-hooks.md) | narrative-memory | preparado/em desenho | 2026-09-06 |
| [Feature — contrato de dados para relações](../features/relations-data-contract.md) | narrative-memory / database / security | fundação física aplicada; provenance/review e vocabulário factual continuam em evolução | 2026-09-10 |
| [Feature — Relações entre entidades e grafo](../features/relations-graph.md) | narrative-memory | arquitetura visual aprovada; schema de relations em desenho | 2026-09-06 |
| [Feature — Busca semântica com fontes](../features/semantic-search.md) | search/narrative-memory | em desenho | 2026-09-06 |
| [Estatísticas privadas de transcrições](../features/transcript-statistics.md) | transcrições / leitura e estatísticas | implementação candidata em branch; não publicada | 2026-09-07 |
| [World entity media foundation](../features/world-entity-media-foundation.md) | narrative-memory / integrations-media / frontend | implementação candidata; schema remoto não aplicado | 2026-09-13 |
| [Feature — World Explorer / Ecos da Jornada](../features/world-explorer.md) | narrative-memory / frontend | fundação multi-hub e roteamento implementados; layout editorial preparado; dados reais pendentes | 2026-09-08 |

## docs/integrations

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Integrações — índice](../integrations/README.md) | integrations | vigente/parcialmente preparado | 2026-09-11 |
| [Companion — protocolo local v1](../integrations/local-companion-v1.md) | local-companion/processing | implementação candidata | 2026-09-11 |
| [Companion local](../integrations/local-companion.md) | local-companion/processing | base sintética implementada em branch/PR; ASR real legado preservado | 2026-09-07 |
| [Pré-flight R2 e assets das novas lores](../integrations/lore-media-preparation-2026-09-07.md) | integrations/media | preparado; execução central pendente | 2026-09-07 |
| [Inventário de mídia — 2026-09-07](../integrations/media-inventory-2026-09-07.md) | integrations/media | auditoria observada | Não declarado |
| [Reparo do site e entrega pública de imagens](../integrations/media-public-delivery-2026-09-07.md) | integrations/media | implementado parcialmente; promoção R2 pendente | 2026-09-07 |
| [Recuperação de imagens — 2026-09-07](../integrations/media-recovery-2026-09-07.md) | integrations/media | auditoria observada | 2026-09-07 |
| [R2 — governança de mídia e lifecycle](../integrations/r2-governance.md) | integrations/media (Balde), em coordenação com infraestrutura/operação (Nuvem) | vigente | 2026-09-11 |
| [Integração Cloudflare R2](../integrations/r2.md) | integrations/media | preparado | 2026-09-12 |
| [Integração Supabase](../integrations/supabase.md) | integrations + data + identity | implementado/canônico | 2026-09-06 |
| [Craig, Discord e Roll20](../integrations/table-sources.md) | integrations/table-sources | legado funcional/parcialmente implementado | 2026-09-06 |
| [Importação de transcrição local](../integrations/transcript-import.md) | sync/consumer + dados/Supabase | implementado em branch/PR; ativação negada | 2026-09-07 |
| [Integração Vercel](../integrations/vercel.md) | operations/hosting | production ativa; publicação manual controlada | 2026-09-07 |

## docs/integrations/r2

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [R2 — documentação detalhada](../integrations/r2/README.md) | integrations/media | vigente | 2026-09-12 |
| [R2 — identidade e object keys](../integrations/r2/identity-and-keys.md) | integrations/media | vigente | 2026-09-11 |
| [R2 — lifecycle e estados](../integrations/r2/lifecycle.md) | integrations/media | vigente | 2026-09-11 |
| [Mídia — fluxo único de preparação e entrega](../integrations/r2/media-pipeline.md) | integrations/media + frontend + operations | arquitetura aprovada | 2026-09-12 |
| [R2 — placement de binários](../integrations/r2/placement.md) | integrations/media | vigente | 2026-09-12 |
| [R2 — publicação e social](../integrations/r2/publication-and-social.md) | integrations/media | vigente | 2026-09-11 |
| [R2 — segurança e custos](../integrations/r2/security-and-costs.md) | integrations/media + infraestrutura/operação | vigente | 2026-09-12 |
| [R2 — variantes e crops](../integrations/r2/variants-and-crops.md) | integrations/media | vigente | 2026-09-12 |

## docs/legacy

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Legado e fontes históricas — `Faysk/dnd-scribe`](../legacy/README.md) | documentação/arquitetura | histórico/referência | 2026-09-07 |
| [Edit — paridade com `Faysk/dnd-scribe`](../legacy/edit-parity.md) | Edit + arquitetura | vivo; auditoria inicial concluída para transcript/access | 2026-09-07 |

## docs/operations

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Operação — índice](../operations/README.md) | operations | vigente | 2026-09-11 |
| [CI/CD — operação, promoção e recuperação](../operations/ci-cd.md) | operations / release / dados | vigente | 2026-09-10 |
| [CI/CD — configuração administrativa](../operations/cicd-admin-setup.md) | operations / release | vigente | 2026-09-11 |
| [Companion — política de versões e dependências](../operations/companion-dependency-policy.md) | local-companion / processing | requisito de release | 2026-09-11 |
| [Runbook operacional do banco / Supabase](../operations/database-runbook.md) | dados/Supabase | vigente | 2026-09-07 |
| [Histórico de deployments](../operations/deployments.md) | operations | vigente | 2026-09-11 |
| [Login Discord: configuração e verificação](../operations/discord-auth.md) | identity/access | publicado na Production #006; OAuth real, acesso e logout verificados | 2026-09-07 |
| [Ambientes e configuração](../operations/environments.md) | operations | vigente | 2026-09-13 |
| [Retirada do projeto Vercel legado](../operations/legacy-retirement.md) | infraestrutura/operação | executado e verificado | 2026-09-07 |
| [Companion — operação, instalação e rollback](../operations/local-companion.md) | local-companion/processing | candidato RC v0.3 validado em CI; validação física pendente | 2026-09-12 |
| [R2 — checklists de mídia](../operations/r2-media-checklists.md) | integrations/media | vigente | 2026-09-11 |
| [R2 e mídia — runbook operacional](../operations/r2-media-runbook.md) | integrations/media + operations | vigente | 2026-09-12 |
| [Runbook — release, deploy e rollback](../operations/release-runbook.md) | operations/release | vigente | 2026-09-08 |
| [Checklist de segurança operacional](../operations/security-checklist.md) | security/operations | vigente | 2026-09-07 |
| [Do ZIP à produção — páginas e mídia com fidelidade](../operations/zip-to-production.md) | frontend / integrations/media / operations | procedimento vigente; execução por entrega, sem importador genérico automático | 2026-09-12 |

## docs/templates

| Documento | Owner declarado | Estado declarado | Revisão declarada |
| --- | --- | --- | --- |
| [Modelo — entrega de pacote de lore](../templates/lore-pack-delivery.md) | frontend / integrations/media / operations | modelo manual; não é schema de importador implementado | 2026-09-12 |

## Cobertura

122 páginas inventariadas, além deste catálogo gerado. 12 sem Owner e 21 sem Última revisão no cabeçalho. Corrigir durante revisão real; não preencher datas automaticamente.
