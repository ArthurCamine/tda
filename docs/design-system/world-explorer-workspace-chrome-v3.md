# World Workspace — chrome espacial e sobreposição

> Status: direção UX aprovada; implementação planejada
> Owner: product / design-system / frontend / narrative-memory
> Última revisão: 2026-09-12
> Fonte: feedback visual do proprietário sobre `/mundo` em desktop Full HD e modo `Conduzir`

Este documento fecha a direção de composição do **World Workspace** depois do polimento de interação espacial. O objetivo é preservar o canvas como superfície dominante, reduzir chrome vertical e eliminar qualquer comportamento em que menu, inspector ou ferramenta lateral comprimam o mapa.

Ler em conjunto com [World Explorer — composição e UX oficial](world-explorer-ui.md) e [Diretriz geral de UX, design e hierarquia](ux-hierarchy.md). Este documento especializa essas regras para o shell espacial do Mundo; não altera autorização, canon, lease, draft/publish ou o motor React Flow.

## Problema observado

A implementação vigente já bloqueia o documento em `100dvh`, usa pan/zoom espacial e permite recolher navegação/inspector. Porém, em desktop amplo ainda existem sinais de uma composição baseada em colunas tradicionais:

- o painel esquerdo aberto reserva largura e reduz o canvas;
- o inspector público aberto também pode reduzir o canvas;
- a linguagem de recolhimento é inconsistente: `×`, seta, texto vertical e aba superior;
- a aba direita recolhida parece um controle flutuante, em vez de uma extensão física do painel;
- o topo público pode ocupar três faixas sucessivas antes do canvas;
- filtros de categoria gastam uma linha estrutural mesmo sendo controles contextuais leves;
- no modo `Conduzir`, a abertura de menu/detalhes precisa obedecer à mesma mecânica espacial do modo público.

A correção não é diminuir tudo indiscriminadamente. A correção é **separar conteúdo persistente de chrome temporário** e fazer o chrome temporário sobrepor o canvas sem alterar sua geometria.

## Princípio central

> **O canvas mantém tamanho e posição; chrome entra e sai sobre ele.**

Em `/mundo`, nenhum painel lateral temporário deve provocar reflow horizontal do canvas. A câmera React Flow não deve ganhar ou perder largura porque um drawer foi aberto. Isso evita salto visual de nodes, mudança aparente de enquadramento e sensação de interface espremida.

O único conteúdo que pode reduzir altura útil do canvas é uma barra superior realmente persistente para a tarefa corrente. Em Full HD ou maior, essa barra deve ser única e compacta.

## Modelo de camadas

A composição desktop passa a ter quatro planos conceituais:

```text
z4  menus modais / command palette / confirmação
z3  drawers laterais + header principal expandido
z2  workspace bar + filtros flutuantes + edge tabs
z1  canvas React Flow + minimap + controles do mapa
```

O layout base continua `100dvh` e uma única coluna `minmax(0, 1fr)`. Painéis laterais deixam de participar do cálculo de largura da coluna central.

## Edge tabs — padrão único

Topo, esquerda e direita pertencem à mesma família de controles de disclosure.

### Geometria

- esquerda/direita: **40 × 56 px** em desktop;
- topo: **52 × 28 px**, deliberadamente um pouco maior por ser o único controle horizontal;
- mobile/touch: área interativa mínima de **44 × 44 px**, mesmo quando o desenho aparente for menor;
- todos usam o mesmo border token, surface, blur, sombra, radius e estados hover/focus;
- nenhuma edge tab contém texto visível no desktop.

### Iconografia

- esquerda: ícone de navegação/menu;
- direita: ícone de detalhes/inspector;
- topo: chevron/disclosure do menu principal;
- o ícone pode mudar direção/estado, mas o **componente físico não muda de forma**.

Não usar `×` para recolher um drawer persistente do workspace. `×` permanece reservado para superfícies que semanticamente são fechadas/descartadas, como modal ou conteúdo temporário. Drawer usa o mesmo botão/aba para abrir e recolher.

### Ancoragem

A aba é sempre percebida como continuação da borda do drawer:

- drawer esquerdo aberto: aba encaixada na borda direita do drawer;
- drawer esquerdo fechado: aba encaixada na borda esquerda da viewport;
- drawer direito aberto: aba encaixada na borda esquerda do drawer;
- drawer direito fechado: aba encaixada na borda direita da viewport;
- nenhuma aba lateral usa margem que a faça parecer um botão flutuante independente.

## Drawers laterais em desktop

### Regra

Acima do breakpoint de composição ampla, navegação e inspector são **fixed/absolute overlays**, não colunas do grid.

```text
workspace
└─ stage / canvas (100% largura)
   ├─ workspace bar
   ├─ filter rail
   ├─ left drawer overlay
   ├─ right drawer overlay
   └─ edge tabs
```

### Navegação esquerda

- largura alvo: `clamp(224px, 15.5vw, 270px)` ou token equivalente atual;
- `position: fixed`/`absolute`, ancorada abaixo da barra superior efetivamente visível;
- abrir por `transform: translateX(0)`;
- fechar por `transform: translateX(-100%)`;
- estado fechado não reserva nenhum pixel;
- conteúdo interno pode rolar; documento e canvas não rolam.

### Inspector direito

- mesma mecânica de overlay;
- largura atual do inspector pode continuar ajustável dentro dos limites já existentes;
- estado fechado não reserva trilho;
- quando aberto, cobre uma faixa do canvas sem recalcular a câmera;
- se necessário, um veil muito discreto pode existir apenas quando o drawer estiver modal/estreito. Em desktop amplo normal, não escurecer o canvas por padrão.

### Concorrência entre drawers

Em desktop amplo, esquerda e direita podem coexistir sem alterar o layout. Em larguras intermediárias, preferir política de **um drawer lateral por vez** para evitar cobrir área demais do canvas.

## Topo Full HD+ — uma barra principal

Em viewport com largura **>= 1920 px** e altura suficiente para desktop normal, a experiência pública não precisa manter título editorial + condução + toolbar em três faixas.

O título `Ecos da Jornada` continua no documento/semântica e pode aparecer em contextos menores ou no drawer de navegação, mas deixa de consumir uma faixa própria no workspace amplo.

### Conteúdo da barra única

Ordem recomendada:

1. busca — ocupa o espaço flexível;
2. `Conduzir` / status de condução;
3. notificações/feedback — compacto, somente quando houver estado relevante;
4. filtro de relação;
5. `Reorganizar` / `Restaurar posições`;
6. Canvas;
7. Lista.

No modo `Conduzir`, a mesma barra muda de estado em vez de criar outra faixa acima dela. Ações autorais entram progressivamente no mesmo shell: Menu, Detalhes, Comandos, Foco, Publicar/Concluir e Descartar. A ação principal continua dourada; controles auxiliares permanecem discretos.

### Notificações e feedback

Mensagens como lease expirado, rascunho recuperado ou falha de publicação não devem ganhar uma linha permanente. Preferir:

- badge/status curto na barra;
- popover/tooltip para detalhe;
- toast/status transient acessível quando o evento ocorre;
- callout persistente somente quando existe ação obrigatória que bloqueia o fluxo.

## Breakpoints

### >= 1920 px — workspace amplo

- barra principal única;
- título editorial fora da chrome persistente;
- filtros de categoria sobre o canvas;
- drawers laterais em overlay;
- abas laterais icon-only;
- canvas recebe a maior área possível.

### 1280–1919 px — desktop compacto

- permitir a barra principal quebrar em até duas linhas se necessário;
- ainda usar drawers overlay;
- filtros podem ocupar rail separada compacta, mas não criar terceira faixa estrutural se couberem sobre o canvas;
- nunca reduzir o canvas horizontalmente para abrir drawer.

### 821–1279 px — tablet/desktop estreito

- toolbar pode reorganizar ações;
- apenas um drawer lateral aberto por vez;
- inspector pode continuar como sheet/overlay conforme contrato responsivo atual;
- navegação não reserva largura.

### <= 820 px — mobile

- manter drawer/modal para navegação e bottom sheet para inspector;
- touch target mínimo 44 px;
- não impor o padrão icon-only quando texto curto for necessário para entendimento;
- preservar foco, `Escape` quando aplicável e `aria-expanded`.

## Filtros de categoria sobre o canvas

`Todos`, `Personagens`, `NPCs`, `Lugares`, `Facções`, `Músicas` e `Momentos` são controles contextuais, não navegação global. Em desktop amplo devem formar um **filter rail overlay** no topo do canvas.

### Aparência

- surface com transparência leve e `backdrop-filter` moderado;
- chips inativos com contraste reduzido, mas ainda WCAG-legíveis;
- chip ativo com surface mais opaca, border/acento dourado e texto de maior contraste;
- `aria-pressed` continua sendo a fonte semântica do estado;
- foco de teclado deve ser mais evidente que hover;
- rail pode usar scroll horizontal em larguras menores.

A sobreposição precisa reservar uma safe-area visual interna no canvas apenas para evitar colisão direta com outros controles flutuantes; ela **não altera height do React Flow**.

## Modo `Conduzir`

Condução não recebe um segundo sistema de layout. O mesmo workspace troca de estado.

### Regras

- shell, edge tabs, drawers e breakpoints são compartilhados com o modo público;
- `Menu` abre o drawer esquerdo sobre o canvas;
- `Detalhes` abre o inspector/editor direito sobre o canvas;
- `Comandos` continua modal/command palette;
- `Foco` esconde chrome não essencial sem mudar a câmera;
- abrir/fechar Menu ou Detalhes não altera largura/posição do canvas;
- o estado de edição pode adicionar borda/acento ao canvas, nunca mudar sua geometria;
- Publicar/Descartar permanecem acessíveis mesmo com drawers fechados.

O editor direito pode ser mais largo que o inspector público, mas deve continuar overlay. Em 1920 px, algo entre 380 e 480 px é adequado; em 2560 px pode chegar ao limite já previsto de ~520 px sem reflow.

## Estratégia de implementação recomendada

A implementação deve ser incremental e evitar um rewrite do World Explorer.

### 1. Criar uma primitive `WorldEdgeTab`

Centralizar em um componente reutilizável:

```ts
type WorldEdgeTabProps = {
  edge: "top" | "left" | "right";
  expanded: boolean;
  controls: string;
  label: string;
  onToggle(): void;
  icon: ReactNode;
};
```

Responsabilidades:

- `aria-controls`;
- `aria-expanded`;
- tooltip/title acessível;
- geometria compartilhada;
- estado open/closed;
- foco visível;
- reduced motion.

Não codificar o comportamento por seletores CSS baseados em `aria-label` como contrato de layout. Usar `data-world-edge-tab`, `data-edge` e `data-expanded` explícitos.

### 2. Tirar os drawers do grid

No `WorldWorkspaceShell`, manter o stage sempre com largura total. A navegação deixa de alterar `grid-template-columns`. Estado aberto controla `transform`, visibility/inert e pointer-events do drawer.

No layout do World Explorer, aplicar a mesma regra ao inspector público. Remover o padrão `grid-template-columns: canvas inspector` para desktop e usar overlay posicionado.

### 3. Compartilhar o mesmo mecanismo com Authoring

O modo `Conduzir` já usa inspector overlay em parte do CSS. Em vez de manter uma implementação paralela, extrair tokens/classes comuns para o mesmo contrato de drawer usado no público. O authoring apenas troca conteúdo, largura e prioridade de z-index.

### 4. Introduzir `WorldWorkspaceBar`

Separar **conteúdo da barra** da composição atual `WorldConductorBar + WorldFloatingChrome`.

Não fundir toda a lógica em um componente monolítico. Recomenda-se:

```text
WorldWorkspaceBar
├─ WorldWorkspaceSearch
├─ WorldConductorControls
├─ WorldRelationFilter
├─ WorldLayoutActions
└─ WorldViewToggle
```

`WorldConductorBar` pode manter a lógica de commands/status, mas oferecer uma variante `compact`/slots para a barra ampla. `WorldFloatingChrome` pode deixar de ser proprietário da linha inteira e fornecer search/relation/view/filter primitives.

### 5. Mover filter rail para overlay do canvas

O rail de categorias deve ser sibling visual do React Flow dentro do stage/canvas wrapper, com `position: absolute`. Não colocá-lo dentro do viewport transformável do React Flow para que não acompanhe pan/zoom.

### 6. Feedback sem linha estrutural

Converter feedback não-bloqueante do conductor para região `aria-live` visualmente compacta/toast. Mensagens persistentes continuam possíveis quando exigem ação, mas não devem recriar a terceira faixa por padrão.

### 7. Manter a câmera estável

Abrir/fechar drawer **não chama `fitView`**, não reseta viewport e não recalcula seed/layout. A sobreposição é exclusivamente chrome. Se o usuário quiser reenquadrar nodes que ficaram cobertos, usa `fitView`/Reorganizar deliberadamente.

## Estados e foco

### Drawer desktop não modal

- foco não é preso dentro do drawer;
- botão/edge tab usa `aria-expanded` e `aria-controls`;
- `Escape` pode recolher o drawer quando foco está dentro dele;
- ao recolher via teclado, foco retorna à edge tab correspondente;
- conteúdo fechado usa `inert` + hidden/visibility apropriado para sair da árvore interativa.

### Drawer mobile modal

Mantém o contrato atual de focus trap, backdrop e retorno de foco.

### Command Palette

Continua sendo modal e permanece acima de drawers. Não transformar command palette em drawer.

## Tokens sugeridos

Antes de espalhar números em CSS modules, introduzir custom properties locais do workspace:

```css
--world-edge-tab-inline: 40px;
--world-edge-tab-block: 56px;
--world-top-tab-inline: 52px;
--world-top-tab-block: 28px;
--world-overlay-gap: 12px;
--world-left-drawer-width: clamp(224px, 15.5vw, 270px);
--world-right-drawer-width: clamp(360px, 28vw, 480px);
--world-chrome-blur: 14px;
--world-workspace-bar-height: 52px;
```

Os valores finais devem ser ajustados por screenshot/E2E visual, mas a geometria deve vir de um único conjunto de tokens.

## Anti-padrões proibidos

- painel aberto alterar `grid-template-columns` do canvas;
- `×` em um drawer e chevron em outro sem diferença semântica real;
- edge tab com texto vertical em desktop;
- botão de reabrir inspector solto a 12 px da borda sem ligação visual;
- três barras empilhadas em 1920 px quando o conteúdo cabe em uma;
- filtros de categoria ocupando altura estrutural permanente em Full HD+;
- esconder conteúdo por `display:none` sem atualizar estado/foco/inert;
- usar `fitView` automático para compensar abertura de painel;
- duplicar shell público e shell de condução.

## Critérios de aceite

### Desktop 1920 × 1080

- canvas não muda de bounding box ao abrir/fechar navegação esquerda;
- canvas não muda de bounding box ao abrir/fechar inspector direito;
- título editorial não ocupa faixa própria persistente;
- busca + condução/status + relação + reorganizar + view toggle cabem em uma barra principal;
- filtros de categoria ficam sobre o canvas com transparência e estado ativo inequívoco;
- abas esquerda/direita possuem mesma geometria e somente ícone;
- aba direita fica visualmente colada à borda do inspector/viewport;
- documento continua sem scroll.

### Desktop 2560 × 1440

- os mesmos contratos permanecem; espaço extra amplia o canvas, não o chrome;
- drawer direito pode crescer até o limite definido sem empurrar o mapa.

### Modo `Conduzir`

- abrir Menu não move nenhum node em coordenadas de tela por reflow do stage;
- abrir Detalhes não reduz a largura do canvas;
- Menu/Detalhes usam a mesma edge-tab grammar;
- Publicar/Descartar continuam alcançáveis;
- command palette continua fechando por `Esc`, botão e backdrop.

### Responsividade e acessibilidade

- 1366 × 768 continua funcional mesmo que a barra use duas linhas;
- <=1120 usa overlay/sheet sem scroll horizontal;
- mobile mantém alvos de 44 px;
- Tab/focus order previsível;
- `aria-expanded` representa estado real;
- reduced motion remove transições não essenciais;
- light/dark preservam a mesma hierarquia.

## Testes recomendados

Adicionar E2E específico de geometria, sem depender apenas de screenshot:

1. capturar `boundingBox()` do canvas;
2. abrir drawer esquerdo;
3. exigir diferença de largura/posição < 2 px;
4. repetir para inspector direito;
5. em authoring, repetir para Menu e Detalhes;
6. em 1920 × 1080, exigir uma única workspace bar antes do canvas;
7. verificar que filter rail intersecta a área do canvas em overlay, sem reduzir seu `height`;
8. verificar edge tabs com dimensões iguais esquerda/direita;
9. verificar `window.scrollY === 0` e `scrollWidth <= innerWidth`;
10. abrir/fechar drawer e garantir que o transform do `.react-flow__viewport` não muda.

Screenshots comparativos continuam úteis para polimento, mas os invariantes de geometria devem ser testados diretamente.

## Sequência de implementação

1. primitive/tokens de edge tab;
2. navegação esquerda overlay;
3. inspector público overlay;
4. unificação com inspector/menu de `Conduzir`;
5. `WorldWorkspaceBar` responsiva;
6. filter rail sobre o canvas;
7. feedback/status compacto;
8. testes de geometria e acessibilidade;
9. revisão visual 1366, 1920 e 2560 + mobile;
10. somente depois remover CSS legado de grid/push que ficar comprovadamente sem consumidor.

A migração deve ser feita em passos pequenos para que cada commit tenha rollback claro. O objetivo é mudar a composição, não reescrever a lógica do grafo ou o ciclo editorial.