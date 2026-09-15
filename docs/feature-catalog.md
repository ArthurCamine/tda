# Catálogo canônico de features

> Status: vigente
> Owner: produto / arquitetura
> Última revisão: 2026-09-15
> Fonte de verdade: `Faysk/tda@main`, specs e documentos donos

Este catálogo consolida a direção do TDA sem transformar automaticamente ideias históricas em schema. As referências históricas citadas abaixo vivem no legado `Faysk/dnd-scribe`.

**Escopo:** a tabela descreve maturidade canônica na `main`. PR aberta, mesmo com CI verde, continua candidata e não altera sozinha o estado abaixo. O [roadmap](roadmap.md) registra dependências entre candidatos; [Documentação viva](documentation/README.md) define a diferença entre branch/PR, validação, integração e publicação/aplicação.

Estados:

- **implementado no schema**: já há estrutura de dados real utilizável;
- **preparado**: o schema/código atual sustenta parte relevante da feature, mas falta ingestão/UI/operação/convergência;
- **arquitetura aprovada**: boundary/UX/tecnologia principal foram aceitos, mas implementação ainda não está concluída;
- **documentado, precisa de desenho**: intenção validada historicamente, sem contrato de dados definitivo no reboot;
- **não encontrado**: nenhum conceito canônico correspondente foi localizado.

| Feature | Estado no TDA | Base atual / decisão |
| --- | --- | --- |
| Edit Workbench / administração | arquitetura aprovada; implementação incremental iniciada | spec em `features/edit-workbench.md`, ADR-0007, paridade viva do `dnd-scribe`; shell/transcript e leitura com revision já avançaram, persistence/Auth canônicos ainda não convergiram |
| Processamento local no Edit | ASR local real implementado; sync cloud desativado | [Contrato da tela e gates](features/local-processing.md), ADR-0003 e ADR-0013; Craig real roda localmente em Qwen/Whisper, conclusão local não publica |
| Runs/revisão/publicação de transcrição | arquitetura aprovada; implementação pendente | [Contrato editorial completo](features/transcript-review-publication.md) + ADR-0015: runs imutáveis, comparação A/B, revisão derivada, publish explícito, revisions cloud, restore/unpublish/delete |
| Perfis/jogadores | implementado no schema | `profiles`, identidade Supabase Auth, campaign membership e RBAC; maturidade do schema não implica que todo recorte de acesso administrativo esteja concluído |
| Personagens jogáveis (PCs) | preparado | `entities(type=pc)` + `profile_characters` + `participants.character_entity_id`; Astel, Dandelion e Screacky já canonicalizados |
| NPCs | preparado | `entities(type=npc)`; não precisam de profile humano |
| Lugares | preparado | `entities(type=location)` |
| Itens | preparado | `entities(type=item)` |
| Organizações | preparado | `entities(type=organization)` |
| Facções | preparado | `entities(type=faction)` |
| Arcos | preparado | `entities(type=arc)` |
| Conceitos/lore | preparado | `entities(type=concept)` + canon revisado |
| Lore editorial Pipipi | publicada em production | rota dedicada `/lore/pipipi`, texto editorial versionado, cinematic progressivo e QA concluído; publicação observada em 2026-09-11 sem criar entity/canon por conveniência |
| Músicas/performances | preparado | `entities(type=song)`; performances específicas continuam em desenho |
| Quests/ganchos | preparado | `entities(type=quest)`; estados narrativos precisam ser definidos quando a feature entrar |
| Menções de entidades | implementado no schema | `entity_mentions` liga entity a sessão/segmento/evento; tabela ainda vazia |
| Canon consolidado | implementado no schema | `canon_entries`; só deve receber conteúdo aprovado; tabela ainda vazia |
| Candidatos a canon | implementado no schema | `canon_candidates` + fontes + revisão |
| Citações/outtakes | implementado no schema | candidatos e review flow já existem |
| Publicações | implementado no schema | `publications`; conteúdo publicado atual já existe |
| Perfis editoriais de entities | scaffold integrado; projection pendente | shells compartilhados, scenes e narração opcional; conteúdo real depende de projection autorizada |
| Relações entre entities | fundação física aplicada; provenance/review em evolução | `relation_types`, `entity_relations`, `entity_relation_sources` e `world_relation_styles` aplicados; relações reais revisadas/publicadas e fluxo completo de provenance continuam pendentes |
| World Explorer / Ecos da Jornada | fundação multi-hub e roteamento implementados; dados reais pendentes | React Flow, layout editorial e roteamento existem; fixtures continuam demonstrativas até projections autorizadas |
| Grafo visual | slice visual integrado | `@xyflow/react` integrado; não define schema nem autorização |
| Timeline por entidade | preparado | sessions/participants/mentions/canon já dão a base; UI/query ainda futuras |
| Conhecimento por audiência | documentado, precisa de desenho | distinguir jogador, personagem, público, rumor, mentira e segredo do mestre; não esconder em JSON genérico |
| Busca semântica | documentado, precisa de desenho | embeddings futuros devem manter referência a fonte/entity e nunca alterar canon |
| Mapas | documentado, precisa de desenho | lugares já cabem em `entities`; geografia/coords/map provider ainda não têm contrato canônico |
| Wiki/memória da campanha | documentado e parcialmente preparado | `entities`, mentions e canon formam a base; perfis editoriais possuem contrato próprio |
| Discord para consulta narrativa | histórico/documentado | comandos como NPC/item/canon foram ideias do legado; revisar UX/autorização antes de reimplementar; não confundir com login Discord |
| Retcon/supersession | preparado | `canon_entries.status` e histórico de revisão dão base; experiência visual ainda futura |
| Intents / intenção | não encontrado | nenhuma tabela, coluna ou definição canônica localizada no schema ou documentação histórica revisada; não criar até o conceito ser definido |

## Fontes visuais oficiais

O projeto possui fontes oficiais explicitamente aprovadas e complementares:

- **TDA Design System v1.0.0** — tokens, temas, tipografia, acessibilidade, governança e composição visual;
- **TDA Brand Pack (official)** — masters de marca, logo, pato, favicons, PWA e social cards;
- **Diretriz geral de UX, design e hierarquia** — prioridade de conteúdo, densidade, proporção, composição e regra contra exagero para superfícies públicas e operacionais.

A autoridade operacional está em [docs/design-system](design-system/README.md), com a diretriz transversal em [design-system/ux-hierarchy.md](design-system/ux-hierarchy.md). Design/Brand são fundação transversal: não precisam ocupar uma posição artificial na fila de features para continuarem sendo obrigatórios.

## World Explorer

A decisão de visualização foi fechada em [ADR-0006](adr/0006-react-flow-world-explorer.md):

- React Flow (`@xyflow/react`) para o canvas quando o slice correspondente for integrado;
- custom nodes/edges;
- projection layer server-authorized;
- layout radial próprio no primeiro slice;
- 1-hop default;
- lista alternativa acessível;
- sem edição de relations no modo público;
- sem modelar o banco com conceitos da biblioteca.

A fundação física de relations foi aplicada no Supabase canônico em 2026-09-10, conforme [contrato de dados para relações](features/relations-data-contract.md). Isso não significa que relações reais estejam publicadas: fixtures continuam explicitamente demonstrativas até fonte/canon, provenance/review, visibility e autorização permitirem projections reais.

## Edit Workbench

A direção estrutural foi fechada em [ADR-0007](adr/0007-edit-workbench.md):

- mesma aplicação Next.js do TDA;
- server-first com ilhas client-side localizadas;
- autorização por capability + scope;
- migração vertical e incremental do comportamento útil do legado;
- transcript como primeiro fluxo crítico;
- autosave com proteção explícita contra writes fora de ordem;
- Design System atual como única autoridade visual;
- paridade registrada em [legacy/edit-parity.md](legacy/edit-parity.md).

A `main` já contém o workbench temporário e leitura autorizada com `revision`, mas isso não encerra a convergência: Auth oficial, persistence atômica/auditável, UX de conflito conectada ao resultado real e retirada do bypass continuam etapas distintas. O mapa corrente está no [roadmap](roadmap.md); os detalhes continuam nos documentos donos do Edit/banco/identity.

## Transcrição local, revisão e publicação

A direção estrutural do pós-ASR foi fechada em [ADR-0015](adr/0015-transcript-runs-review-publication.md) e na [spec detalhada](features/transcript-review-publication.md).

O TDA passa a distinguir explicitamente:

```text
source Craig
  -> run local imutável
  -> revisão/comparação
  -> published revision
  -> revision atual
```

Decisões principais:

- o mesmo source pode ter vários runs Qwen/Whisper/retries;
- output bruto do modelo não é editado;
- edição cria revision derivada;
- concluir ASR não publica;
- publicação exige ação humana explícita;
- substituir cria/ativa nova revision e preserva a anterior;
- restore/unpublish/delete possuem semânticas distintas;
- áudio bruto continua local;
- transcript publicado continua evidência/fonte e não vira canon automaticamente.

A candidata de transcript import existente continua desativada até ser adaptada a esse lifecycle. Hashes, atomicidade, idempotência, authorization e receipt devem ser reaproveitados; o modelo de publicação direta sobre `transcript_segments` não deve ser ativado como atalho.

## Fontes históricas revalidadas

- `Faysk/dnd-scribe/docs/01_objetivos_e_escopo.md`: objetivo de transformar sessões em memória auditável/publicável e futuro de wiki/grafo/timeline/busca.
- `Faysk/dnd-scribe/docs/02_contexto_da_campanha.md`: necessidade de separar canon, interpretação, rumor, mentira, piada e gancho.
- `Faysk/dnd-scribe/docs/02_mapa_de_telas.md`: entidades, segredos, "quem sabe o quê", canon e revisão como superfícies distintas.
- `Faysk/dnd-scribe/docs/03_regras_de_visibilidade.md` e `03_segredos_e_conhecimento.md`: separar quem vê no sistema de quem sabe na ficção.
- `Faysk/dnd-scribe/docs/09_modelo_de_dados_supabase.md`: separação entre pessoas e entidades; tipos PC/NPC/local/item/organização/facção/arco/conceito/música/quest.
- `Faysk/dnd-scribe/docs/08_classificacao_auditoria_canon.md`: fonte, classificação, revisão e canon.
- `Faysk/dnd-scribe/docs/16_ideias_futuras.md`: wiki viva, relações, mapas, knowledge layers, busca semântica, músicas e consultas via Discord.
- `Faysk/dnd-scribe/docs/35_roadmap_proximas_10_etapas.md`: entidades/canon/timeline e superfícies futuras.
- `Faysk/dnd-scribe/docs/49_resultado_etapa_21_entidades_canon_consolidado.md`: consolidator de canon aprovado.

Esses documentos são evidência histórica. A decisão vigente sempre é este catálogo, `data-model.md`, ADRs e o roadmap do repositório TDA.

## Ordem recomendada de evolução

1. consolidar **Home/sessões públicas** e superfícies narrativas já publicadas: origem canônica, metadata comum, mídia pública verificável e release/smoke deliberados;
2. fechar **operação local + revisão de transcrição**: runs imutáveis, biblioteca local, comparação, revisão derivada e UX clara de resultado não publicado;
3. fechar **Auth/capabilities + publicação revisionada**: persistence atômica, receipt/readback, published revisions, current revision, conflito, restore/unpublish e retirada posterior dos bypasses temporários;
4. popular **memória estruturada** (`entities`, mentions, canon) somente a partir de fontes revisadas/autorizadas;
5. integrar **perfis editoriais e World Explorer** sobre contratos compartilhados, fixtures não-canônicas isoladas e projections públicas autorizadas;
6. completar **relations first-class** com sources/audience/provenance e então ligar o World Explorer a dados reais;
7. expandir perfis com timeline/wiki e demais superfícies derivadas;
8. fechar modelo de **knowledge/audience**;
9. evoluir busca semântica, mapas, músicas/performances, quests e consultas narrativas.

Essa ordem preserva primeiro o produto público que já existe, depois transforma o ASR local em uma fonte editorial realmente confiável e só então aumenta a superfície narrativa. Design System, documentação viva, segurança proporcional, cloud gratuita/Hobby quando possível e processamento pesado local permanecem transversais a todas as etapas.
