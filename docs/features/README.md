# Especificações de features

> Status: vivo
> Owner: produto + domínios
> Última revisão: 2026-09-12
> Fonte de verdade: specs deste diretório e `../feature-catalog.md`

O [catálogo de features](../feature-catalog.md) responde **qual é o status canônico na `main`**. Este diretório responde **o que a feature significa, quais dados usa, o que falta decidir e qual é o critério para implementá-la sem quebrar o modelo**.

PRs abertas podem conter implementação validada e documentação candidata sem alterar automaticamente os estados deste índice. Dependências entre candidatos ficam no [roadmap](../roadmap.md); cada spec continua dona do contrato da sua área.

## Índice

[Fidelidade dos pacotes de D e Seika](lore-pack-fidelity.md) — contrato visual e aceite da restauração das páginas independentes.

Candidato em revisão: [Estatísticas privadas de transcrições](transcript-statistics.md) — palavras e duração registrada por sessão, totais completos autorizados; implementação de branch, sem publicação.

Candidato em revisão: [Pipipi — lore cinematográfica pioneira](pipipi-lore.md) — experiência editorial longa com cenas dirigidas por scroll, enhancement visual e fallback de leitura; implementação de branch, sem publicação.

Candidato em revisão: [World entity media foundation](world-entity-media-foundation.md) — identidade de asset, upload direto R2 com finalização/read-back, preview privado, vínculo entidade → portrait e publicação verificada; SQL permanece em `supabase/candidates/`.

| Feature | Estado na `main` | Spec |
| --- | --- | --- |
| Edit Workbench / administração | implementação incremental | [Edit Workbench](edit-workbench.md) |
| Edit / permissões | candidato somente leitura; sem grant/revoke | [Consulta de permissões](edit-permissions.md) |
| Edit / processamento local | candidato UI/adapters e ensaio sintético; ASR/sync cloud pendentes | [Processamento local](local-processing.md) |
| Edit / transcript server-side | leitura autorizada com `revision`; persistence atômica ainda pendente | [Slice server-side de transcrição](edit-transcript-server-slice.md) |
| Edit / bypass temporário | workbench disponível por flag explícita, desligada por default | [Modo temporário sem autenticação](edit-unsafe-development.md) |
| PCs/NPCs | preparado | [Personagens e NPCs](characters-and-npcs.md) |
| perfis editoriais de entities | scaffold integrado; projection pendente | [Entity profiles](entity-profiles.md) |
| World Explorer / Ecos da Jornada | slice visual integrado; dados reais pendentes | [World Explorer](world-explorer.md) |
| Pipipi / lore cinematográfica | candidato em branch; não publicado | [Pipipi](pipipi-lore.md) |
| relations/grafo | arquitetura visual aprovada; schema em desenho | [Relações e grafo](relations-graph.md) |
| contrato de dados de relations | proposta para revisão; nenhuma DDL aplicada | [Relations data contract](relations-data-contract.md) |
| knowledge/audience | em desenho | [Conhecimento e audiência](knowledge-audience.md) |
| timeline por entity | preparado | [Timeline](entity-timeline.md) |
| busca semântica | em desenho | [Busca semântica](semantic-search.md) |
| mapas | em desenho | [Mapas](maps.md) |
| músicas/performances | preparado/em desenho | [Músicas](music-performances.md) |
| quests/hooks | preparado/em desenho | [Quests](quests-hooks.md) |
| sessão ao vivo | histórico/planejado | [Live session](live-session.md) |
| assistente Discord | histórico/planejado | [Discord assistant](discord-assistant.md) |
| intents/intenção | não definido | [Intents](intents.md) |

## Design e visualização

Features com superfície visual forte devem apontar para o [Design System oficial](../design-system/README.md).

O World Explorer possui também um contrato de composição em [world-explorer-ui.md](../design-system/world-explorer-ui.md).

O Edit usa o mesmo Design System e possui boundary técnico próprio em [arquitetura do Edit](../architecture/edit-workbench.md), com paridade histórica rastreada em [Edit — paridade com o legado](../legacy/edit-parity.md). A exceção transitória que permite validar a UI antes da convergência Auth/persistence está isolada em [modo temporário sem autenticação](edit-unsafe-development.md).

## Template mínimo para feature futura

Toda spec deve registrar:

- problema/valor;
- status;
- dependências;
- dados existentes reutilizáveis;
- novo schema necessário, se houver;
- authorization/audience;
- fonte/canon quando narrativo;
- UX mínima;
- failure modes;
- critérios de aceite;
- não objetivos;
- decisões pendentes.

## Regra de execução

`em desenho` não autoriza migration. Quando decisões pendentes forem fechadas:

1. atualizar spec;
2. atualizar feature catalog/roadmap;
3. ADR se estrutural;
4. migration/API/UI;
5. testes;
6. mudar status com evidência depois que o estágio correspondente realmente mudar.

`arquitetura aprovada` também não implica schema ou código em produção: significa que o boundary e a direção já foram aceitos, mas a implementação ainda precisa cumprir seus critérios de aceite. `validado` em uma branch também não substitui integração à `main` nem publicação/aplicação, conforme [Documentação viva](../documentation/README.md).
