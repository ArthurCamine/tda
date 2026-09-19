# Feature — World Explorer / Ecos da Jornada

> Status: multi-hub, autoria canônica, audience de campanha e recuperação durável em implementação integrada
> Owner: narrative-memory / frontend
> Última revisão: 2026-09-19

## Valor

O World Explorer é a superfície que transforma memória estruturada em exploração visual do universo da campanha.

Ele deve permitir responder perguntas como:

- quem está ligado a determinada personagem, NPC ou lugar?
- qual é a relação entre duas entities?
- quais lugares, facções, músicas ou momentos estão ligados aos protagonistas?
- como navegar de uma memória para outra sem ler dezenas de páginas?
- quais conexões merecem aprofundamento em perfil, lore ou timeline?

O World Explorer não substitui perfis, lore ou timeline. Ele conecta essas superfícies.

## Nome de produto

Nome de seção recomendado:

**Ecos da Jornada**

Nome técnico/documental:

**World Explorer**

A interface usa `Mundo` como item de navegação principal e `Ecos da Jornada` como título editorial da experiência.

## Referências oficiais

- referências visuais aprovadas pelo proprietário;
- [Design System oficial](../design-system/README.md);
- [composição visual](../design-system/world-explorer-ui.md);
- [ADR-0006 — React Flow](../adr/0006-react-flow-world-explorer.md);
- [ADR-0009 — multi-hub](../adr/0009-world-explorer-multihub-layout.md);
- [ADR-0010 — layout editorial](../adr/0010-world-explorer-editorial-layout-persistence.md);
- [relations](relations-graph.md);
- [knowledge/audience](knowledge-audience.md);
- legado revalidado em [legacy/README.md](../legacy/README.md).

## Escopo V1

A primeira versão precisa:

1. abrir em `/mundo` como visão geral multi-hub;
2. mostrar protagonistas visíveis com peso narrativo equivalente, sem centro permanente;
3. mostrar relações autorizadas entre heroes e contexto;
4. permitir seleção para inspector sem alterar a URL;
5. permitir foco explícito e temporário via `?foco=`;
6. permitir busca e filtros de node/relation;
7. permitir reorganização local por dragging;
8. abrir inspector contextual e navegar ao perfil completo quando houver rota canônica;
9. mostrar lista alternativa de relações;
10. funcionar em light/dark, desktop/mobile e largura mínima suportada;
11. respeitar audience/RBAC antes do payload chegar ao browser.

## Fora do escopo V1

- edição de relation pelo canvas público;
- criação de entity pelo canvas;
- grafo completo da campanha como default;
- persistência automática do dragging público;
- storage físico do layout editorial antes do contrato de dados/autorização específico;
- multiplayer/realtime cursor;
- physics simulation contínua;
- conhecimento/segredos completos antes do modelo ser aprovado;
- IA gerando edges automaticamente em produção;
- mapa geográfico;
- timeline completa;
- busca semântica em todo o canon.

## Rodada #99 — dados reais e edição autorizada

A [issue #99](https://github.com/Faysk/tda/issues/99) prioriza substituir a demonstração por dados reais revisados e preparar uma experiência de edição autorizada. Isso **não transforma o canvas público em editor de canon** e não altera sozinho o estado de implementação deste documento.

### Projection de dados reais

A primeira projection real deve entrar somente depois de curadoria/revisão conforme [canon-review](../domains/canon-review.md) e [relations-data-contract](relations-data-contract.md):

- cada entity/relation exibida precisa estar resolvida para IDs canônicos e permitida para a audience;
- a relação precisa preservar provenance suficiente para voltar à decisão/fonte revisada;
- inferência, conflito e candidato não aprovado não aparecem como fato apenas para preencher o grafo;
- visibility do edge é avaliada independentemente dos endpoints;
- transcript bruto, notes de review, confidence interna e source payload não chegam ao browser.

### Duas edições diferentes

A experiência deve distinguir de forma inequívoca:

1. **Mover/reorganizar node** — edita somente layout editorial de apresentação. Não altera entity, relation, canon, source ou visibility.
2. **Editar relação/fato** — abre fluxo administrativo separado, com seleção explícita, formulário compreensível, `Salvar`/`Cancelar`, feedback de sucesso/erro e conflito de revisão. Essa operação pertence ao contrato narrativo e não pode ser inferida a partir de dragging.

A UI pode partir de seleção no grafo, mas toda mutation factual precisa revalidar server-side:

- identidade;
- capability exata;
- campaign/scope/ownership;
- revision/expected version quando o storage suportar concorrência otimista;
- fonte/review/visibility exigidos pelo contrato;
- payload mínimo sem confiar em estado visual do cliente.

Login por si só não concede nenhuma dessas capacidades.

### Conflito, durabilidade e confirmação

O lease exclusivo serializa quem pode escrever, mas **não é o armazenamento durável do trabalho**. O rascunho salvo precisa sobreviver à expiração/remoção do lease, reload da página e falha de publicação.

- autosave de layout ou grafo atualiza um checkpoint server-only separado do lease;
- além do debounce normal, uma janela máxima de segurança força flush periódico do estado mais recente durante interação contínua, para que atividade sem pausa não adie o checkpoint indefinidamente;
- release comum encerra o lock, mas não apaga o checkpoint;
- descarte é uma operação explícita, confirmada pelo usuário, e preserva uma cópia tombstonada para auditoria/recuperação;
- o mesmo editor recupera automaticamente o último checkpoint compatível quando volta a conduzir;
- se o estado publicado avançou, o checkpoint antigo permanece preservado e é marcado como recovery obsoleto; ele não é aplicado cegamente sobre a nova revision;
- conflito de revision nunca destrói o rascunho;
- publicação só é apresentada como concluída quando existe confirmação de revision;
- o banco persiste um receipt de publicação no mesmo commit do estado canônico antes de remover o lease, permitindo reconciliar uma resposta HTTP perdida sem adivinhar se o commit ocorreu;
- erro de transporte é apresentado como resultado **não confirmado**, não como certeza de sucesso ou fracasso;
- falha de autosave fica visível durante a condução e orienta o editor a manter a aba aberta/reestabelecer a sessão;
- undo visual de posição não sugere rollback factual.

### Gate operacional atual

O drift remoto de persistência de layout identificado na issue #95 continua uma dependência de governança. A #99 não deve reaplicar migration, inventar timestamp local equivalente nem usar a existência remota como prova de que o fluxo editorial de layout está reconciliado. A edição factual de relations também continua dependente do contrato/migration próprios.

## Rotas

### Canônica

`/mundo`

Estado exploratório serializável pode usar query:

```text
/mundo?foco=<slug-ou-id>
/mundo?foco=astel
```

Não colocar listas gigantes de edge IDs nem posições de canvas na URL.

### Rotas editoriais derivadas

A navegação pode expor:

- `/personagens`;
- `/personagens/[slug]`;
- `/npcs/[slug]`;
- `/lugares/[slug]`;
- `/faccoes/[slug]`;
- `/musicas/[slug]`;
- `/quests/[slug]`.

Internamente todas podem resolver para `entities`, respeitando `entity_type` e o resolver canônico de Lore.

## Query/projection

O canvas não consulta tabelas narrativas livremente do browser.

Pipeline:

```text
request + identidade/audience
  -> construir conjunto autorizado de nodes/edges
  -> resolver overview ou foco temporário
  -> carregar metadata pública necessária
  -> carregar layout editorial aplicável, quando existir
  -> intersectar layout com IDs já autorizados
  -> construir projection mínima
  -> enviar ao browser
```

### Node DTO

```ts
type WorldNodeDTO = {
  id: string;
  slug: string | null;
  kind: "entity" | "moment";
  entityType?: string;
  label: string;
  subtitle?: string;
  imageUrl?: string;
  status?: string;
  route?: string;
  prominence?: "hero" | "primary" | "supporting" | "context";
  layoutHint?: { x: number; y: number };
};
```

`prominence` e `layoutHint` são apresentação. Não aumentam autoridade canônica.

### Edge DTO

```ts
type WorldEdgeDTO = {
  id: string;
  source: string;
  target: string;
  relationType: string;
  label: string;
  direction: "directed" | "symmetric";
  family: string;
};
```

### Layout projection opcional

```ts
type WorldLayoutProjection = {
  schemaVersion: 1;
  view: "overview";
  revision: number;
  positions: Record<string, { x: number; y: number }>;
};
```

Esse layout é estado editorial de apresentação e precisa chegar ao browser já filtrado para a mesma audience da graph projection.

Não incluir no DTO público:

- reviewer notes;
- hidden evidence IDs desnecessários;
- confidence interna;
- source transcript privada;
- metadata integral;
- relations secretas;
- positions de nodes não autorizados;
- dados de profiles que não pertencem à narrativa exibida.

## Visão geral multi-hub

`/mundo` abre em `overview`.

Nesse estado:

- nenhum personagem é centro permanente;
- PCs visíveis são hubs pares;
- contexto se distribui como constelação;
- o seed inicial é determinístico;
- `layoutHint` pode orientar composição curatorial sem virar canon;
- um layout editorial autorizado pode substituir posições do seed;
- dragging local continua podendo reorganizar a sessão atual.

A existência de múltiplos hubs é decisão de apresentação, não classificação de importância narrativa persistida no banco.

## Focus model

`?foco=<slug>` é uma exploração temporária da vizinhança de uma entity.

Ao entrar em foco:

1. a projection pode ser reduzida a 1-hop;
2. a entity fica centralizada apenas nesse recorte;
3. seleção continua separada de foco;
4. voltar a `/mundo` restaura a visão geral;
5. o layout editorial de `overview` não é reaplicado ao recorte focado no contrato inicial.

Selecionar um node atualiza inspector/destaque e não muda a URL. Promover a seleção a foco exige ação explícita `Explorar conexões de ...`.

## Layout e dragging

Precedência de posição:

```text
seed determinístico
  -> layoutHint curatorial
  -> layout editorial autorizado
  -> override local do dragging da sessão atual
```

A ação `Reorganizar` restaura o seed da projection atual no cliente. Ela não grava no Supabase.

O roteamento de edges usa ports/lane allocation determinísticos e recalcula as rotas quando nodes são movidos, evitando que todas as relações saiam do mesmo ponto de um hub congestionado.

## Persistência editorial

ADR-0010 separa layout persistente de canon/relations.

Contrato inicial:

- somente `overview` é persistível;
- coordinates usam espaço lógico do canvas, não pixels de viewport;
- câmera/pan/zoom não são persistidos;
- snapshot possui `revision` para optimistic concurrency;
- stale IDs são ignorados;
- nodes novos usam seed determinístico;
- leitura pública recebe apenas positions de nodes já autorizados;
- dragging público nunca salva automaticamente.

O contrato versionado local e o estado físico remoto de layout estão em reconciliação operacional pela issue #95. Até essa reconciliação concluir, não reaplicar DDL nem declarar o fluxo editorial persistente pronto apenas porque tabela/RPC remotas foram observadas.

## Profundidade

### Overview

Mostra a constelação autorizada necessária para compreender a campanha sem obrigar um foco central.

### 1-hop focado

`?foco=` reduz a leitura às relações diretas da entity quando a exploração precisa de clareza.

### 2-hop

Pode ser adicionado por expansão explícita com limite e filtros.

### Full graph

Não é V1. Se existir no futuro, será uma visão especializada e permission-aware.

## Filtros

Filtros atuais/candidatos:

- todos;
- PCs/personagens;
- NPCs;
- lugares;
- facções/organizações;
- músicas;
- quests;
- momentos/eventos projetados;
- famílias de relação;
- status temporal/ativo.

Filtros podem preservar heroes/contexto necessário para a relação continuar compreensível.

Filtro de UI nunca substitui filtro de autorização.

## Busca

Busca global deve ser permission-aware.

Ao encontrar uma entity, a interface pode:

- selecionar no overview;
- abrir foco explícito;
- abrir perfil completo conforme ação.

Sessões/momentos podem abrir a sessão ou projetar um moment node quando o contrato real existir.

## Inspector

O inspector recebe a entity/moment selecionado.

Dados mínimos desejados:

- título;
- subtítulo;
- imagem;
- tags editoriais autorizadas;
- resumo;
- relations em destaque;
- CTA para detalhe;
- indicação do foco temporário quando pertinente.

O inspector é resumo, não duplicação da página completa.

Próximos recortes devem ampliar navegação contextual e informações úteis sem introduzir um segundo resolver de perfis.

## Relations

World Explorer consome relações first-class.

Não derivar edge canônico diretamente de:

- duas entities mencionadas no mesmo segmento;
- embeddings semelhantes;
- LLM sugerindo vínculo;
- artwork mostrando personagens juntos;
- fixture visual.

O modelo de dados continua em [relations-data-contract.md](relations-data-contract.md).

## Moments/eventos

Momentos podem ser projections de sessão/canon entry/contrato futuro.

Não adicionar `event` a `entities` apenas para satisfazer o canvas.

## Música

Música pode existir como `entities(type=song)`.

Uma performance específica em determinada sessão pode ser moment/canon relation, não outra song entity obrigatoriamente.

## Segurança e knowledge

Conexões podem revelar segredos mesmo quando textos individuais parecem inofensivos.

Autorização é aplicada em:

- node;
- edge;
- label;
- inspector;
- busca;
- relation list;
- paths/expansion;
- layout persistido antes de sua projection pública.

O servidor deve assumir que **a própria existência da relação ou de um node no layout pode ser segredo**.

## Semântica de “quem sabe”

O World Explorer V1 mostra a visão permitida ao usuário, não necessariamente tudo que o personagem sabe na ficção.

Quando [knowledge-audience.md](knowledge-audience.md) amadurecer, poderão existir perspectivas públicas, da mesa, de personagem ou DM. Isso exige projection authorization-aware e não pode ser simulado escondendo nodes no cliente.

## Acessibilidade

Toda graph projection precisa de representação textual acessível.

Requisitos:

- nodes com accessible name;
- foco visível e navegação previsível;
- lista textual alternativa de relações;
- inspector utilizável sem depender de cor;
- relation family comunicada por label e estilo, não só cor;
- controles touch adequados;
- `prefers-reduced-motion` respeitado;
- nenhuma armadilha de foco no canvas.

## Mobile

Contrato:

- canvas permanece utilizável;
- inspector vira composição sticky/sheet;
- filtros continuam compactos;
- MiniMap pode ser omitido em telas estreitas;
- relation list é alternativa natural;
- controles essenciais têm alvos adequados;
- viewport não cria overflow horizontal no mínimo suportado.

## Empty/loading/error

### Sem relações

Não mostrar canvas vazio sem explicação.

### Loading

Skeleton discreto; não desenhar nodes fake como se fossem dados reais.

### Erro

Oferecer retry e navegação por lista/perfil.

### Entity inexistente/privada

Responder como não disponível conforme boundary de segurança; não revelar que existe mas é secreta.

## Estado atual do vertical slice

A implementação atual usa fixture explícita em `src/features/world-explorer/fixtures/dandelion.ts`. As relações são marcadas como demonstração não canônica e nunca são escritas no Supabase.

A fundação já possui:

- `/mundo` em overview multi-hub;
- `?foco=` como 1-hop temporário;
- custom nodes/edges em React Flow;
- nodes arrastáveis;
- busca e filtros;
- seleção separada de foco;
- MiniMap/controls;
- inspector responsivo;
- lista textual alternativa;
- edge ports/lane routing;
- layout editorial DTO opcional e sanitização defensiva;
- testes unitários/E2E para interação e viewport mínimo.

`@xyflow/react` permanece fixado na linha 12.x verificada pelo lockfile do projeto.

Este recorte não aplica relation real, não publica dado privado e não transforma a observação remota de layout em autorização para nova DDL/deploy.

## Critérios para ligar ao Supabase

Antes de substituir fixtures por relations reais:

- migration de relations revisada;
- seed/backfill com fonte conhecida;
- RLS/autorização testadas;
- nenhuma relation criada apenas por coocorrência;
- relation types estáveis;
- queries indexadas para projection esperada;
- profile/slug resolution consistente;
- tests com visão DM/player/public.

Antes de considerar persistência editorial de layout operacionalmente pronta:

- reconciliar a issue #95 entre history remoto e arquivos versionados;
- shape físico revisado pelo owner de dados/Supabase;
- capability oficial confirmada no catálogo e com origem versionada;
- scope/ownership validados;
- optimistic concurrency por revision;
- auditoria de `updated_by/updated_at` equivalente;
- testes que provem ausência de leak de IDs/positions secretos;
- mutation transacional e rollback operacional definidos.

## Métricas futuras

Avaliar utilidade, não quantidade de edges:

- tempo para localizar uma entity;
- taxa de clique para perfil;
- mudanças de foco;
- uso de filtros;
- performance com datasets maiores;
- completion por teclado;
- ausência de vazamento em testes de audience;
- necessidade real de ajuste editorial persistente vs seed determinístico.

## Critério de pronto V1

Um usuário autorizado consegue abrir `/mundo`, compreender a constelação visível da campanha, selecionar e reorganizar nodes localmente, explorar uma vizinhança focada, consultar relações por lista/inspector e navegar para perfis sem depender do grafo como única fonte e sem receber dados fora de sua audience.

A rodada #99 só pode declarar a evolução para dados reais/edição concluída quando houver evidência separada de: dataset revisado e autorizado; projection sem leak; mutation factual server-side com concorrência/erro cobertos; edição de layout diferenciada; CI do SHA; e, se houver publicação, smoke do ambiente deliberadamente publicado.
