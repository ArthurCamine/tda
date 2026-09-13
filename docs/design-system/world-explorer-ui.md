# World Explorer — composição e UX oficial

> Status: direção visual aprovada; workspace atual implementado, chrome v3 planejado
> Owner: product / design-system / narrative-memory
> Última revisão: 2026-09-12

Este documento traduz as referências visuais oficiais fornecidas para o **Mundo / Ecos da Jornada** em um contrato de composição aplicável ao reboot.

As imagens de referência representam a direção desejada de produto, não screenshots de implementação existente. Quando houver conflito entre composição ilustrativa e acessibilidade/arquitetura do TDA, preservar a intenção visual e adaptar a mecânica.

**Direção de polimento aprovada em 2026-09-12:** a composição desktop do workspace passa a tratar navegação/inspector como overlays que não comprimem o canvas, unificar as edge tabs e condensar o topo em Full HD+. O contrato detalhado, breakpoints, estratégia incremental e testes geométricos estão em [World Workspace — chrome espacial e sobreposição](world-explorer-workspace-chrome-v3.md). Em caso de conflito sobre chrome/layout do workspace, esse documento especializado prevalece sobre os diagramas desktop históricos abaixo.

## Objetivo

Criar uma superfície de exploração narrativa em que pessoas, NPCs, lugares, facções, músicas, quests e momentos possam ser descobertos pelas relações entre si sem transformar o site em um editor de diagramas.

A sensação desejada é:

- mapa de memória;
- arquivo vivo;
- exploração de mundo;
- personagem no centro de uma rede de histórias;
- leitura editorial com riqueza visual;
- controles discretos.

Não é:

- dashboard de BI;
- editor BPMN;
- diagrama técnico;
- tela de administração;
- visualização de todas as linhas do banco ao mesmo tempo.

## Princípio de produto

> **Visitante vê história; editor vê estado editorial.**

Portanto, no World Explorer público:

- não mostrar IDs;
- não mostrar status de processamento;
- não mostrar confidence de IA como informação principal;
- não mostrar botões de criar edge/delete node;
- não mostrar handles de conexão;
- não expor campos de revisão;
- não transformar candidate em conteúdo visual canônico antes da aprovação.

## Arquitetura visual desktop

A referência oficial original foi organizada em três zonas persistentes e uma barra superior leve. O chrome v3 preserva as responsabilidades dessas zonas, mas transforma navegação e inspector em overlays para impedir que comprimam o canvas.

```text
┌─────────────┬───────────────────────────────────┬──────────────────┐
│             │ topbar / busca / tema / conta     │                  │
│ sidebar     ├───────────────────────────────────┤ inspector        │
│             │                                   │                  │
│ navegação   │      World Explorer / grafo       │ entity quick     │
│ principal   │                                   │ view             │
│             │                                   │                  │
│             ├───────────────────────────────────┤                  │
│             │ destaques / relacionados          │                  │
└─────────────┴───────────────────────────────────┴──────────────────┘
```

### Sidebar

Responsabilidade: navegação macro do universo.

Itens candidatos revalidados pelas referências:

- Visão Geral;
- Ecos da Jornada / Mundo;
- Personagens;
- Lugares;
- Facções;
- Eventos;
- Músicas;
- Linha do Tempo;
- Galeria.

A sidebar é a navegação principal no desktop. Evitar duplicar todos esses itens na topbar.

A marca TDA pode aparecer no topo em lockup compacto oficial.

### Topbar

Responsabilidade:

- busca global;
- contexto quando necessário;
- tema;
- conta/autenticação.

A topbar **não precisa repetir** a mesma navegação da sidebar. Isso simplifica hierarquia e libera espaço para busca.

### Cabeçalho do canvas

Exemplo editorial:

```text
ECOS DA JORNADA
Pessoas, lugares e histórias que se entrelaçam
```

Pode conter filtros contextuais:

- Todos;
- Personagens;
- NPCs;
- Lugares;
- Facções;
- Eventos;
- Músicas/quests quando fizer sentido.

Os filtros alteram a projection do grafo, não o conteúdo canônico no banco.

### Canvas

É o centro da experiência.

Características:

- pan/zoom;
- seleção de node;
- foco visual forte na entity principal;
- relações legíveis com labels;
- arte/retrato quando disponível;
- fallback visual coerente quando não houver arte;
- níveis de relação por proximidade;
- sem edição estrutural no modo público.

A entity focada pode usar escala maior, aro/acento forte e label mais destacado.

### Inspector direito

O inspector é **quick view**, não substitui o perfil completo.

Estrutura recomendada:

1. hero/artwork;
2. nome;
3. subtítulo/epíteto;
4. tags curtas;
5. citação opcional aprovada;
6. tabs contextuais;
7. resumo;
8. relações em destaque;
9. link para perfil completo.

Tabs dependem do tipo da entity.

Exemplo para personagem:

- Visão Geral;
- Laços;
- Momentos;
- Músicas.

Exemplo para lugar:

- Visão Geral;
- Pessoas;
- Eventos;
- História.

Não criar tabs vazias apenas para manter simetria.

### Faixa inferior

As referências mostram cards relacionados/destaques.

A faixa pode exibir:

- momentos importantes;
- sessão relacionada;
- música;
- quest;
- evento;
- arco;
- entities próximas.

Essa superfície deve responder à entity focada e aos filtros.

## Navegação de URLs

O grafo é uma porta de entrada para páginas editoriais reais.

Rotas de produto podem ser amigáveis e tipadas, mesmo que o banco use uma registry única:

```text
/mundo
/personagens/dandelion
/npcs/ivory
/lugares/euclix
/faccoes/zhentarim
/musicas/o-reino-vai-cantar
```

A URL de experiência **não define a estrutura do banco**. Todas podem resolver para `entities` por UUID/slug e tipo.

## Nodes visuais

Tipos de visualização iniciais:

### Character node

Usado para PC/NPC quando a distinção visual precisa ser mínima e o conteúdo resolve o papel.

Possui:

- retrato;
- nome;
- estado de seleção;
- tipo opcional acessível;
- indicadores discretos de status narrativo quando aprovados.

### Location node

Artwork ou símbolo do lugar; formato pode diferir levemente do retrato humano, mas deve pertencer à mesma gramática visual.

### Faction / organization node

Pode usar emblema/símbolo.

### Song node

Pode usar ícone/cover e atuar como node projetado no grafo quando conectado à memória da entity.

### Quest node

Usado apenas se quest for uma `entity` canônica relevante para a exploração atual.

### Event / moment node

**Não precisa ser `entities.entity_type=event`.** Pode ser uma projection de `canon_entries`, sessões ou outro contrato futuro de momentos.

## Estados de entity

Estados como `deceased` não devem ser transformados em tipos de relação.

Exemplos visuais possíveis:

- dessaturação;
- aro específico;
- badge textual acessível;
- ícone discreto.

Nunca comunicar morte/hostilidade/segredo somente pela cor.

## Edges

Relações devem comunicar:

- direção quando existir;
- label humano;
- categoria semântica;
- seleção/hover;
- temporalidade quando a UI solicitar;
- visibilidade já filtrada no servidor.

Exemplos de labels:

- Amizade;
- Rivalidade;
- Família;
- Mentor;
- Companheiros;
- Origem;
- Aliança;
- Dívida;
- Serve a;
- Controla.

O texto apresentado pode ser localizado/humano enquanto o banco utiliza slugs estáveis.

## Cor das relações

Cor é camada visual, não identidade no banco.

Uma taxonomia visual inicial pode agrupar tipos em famílias como:

- afinidade/aliado;
- neutro/contextual;
- conflito/inimigo;
- família;
- vínculo místico/faccional;
- histórico/inativo.

Essa taxonomia só será fechada depois que `relation_types` estiver definido e contrastes forem medidos nos dois temas.

## Layout do grafo

### Direção escolhida para o primeiro slice

Usar **layout radial centrado na entity focada**.

Motivos:

- combina com as referências;
- comunica imediatamente "mundo em torno de X";
- funciona bem para profundidade curta;
- evita aparência de organograma;
- permite transição elegante ao trocar o foco.

### Profundidade

Default: **1 hop**.

Opcional: **2 hops** quando o usuário expandir.

Não renderizar o grafo completo da campanha por padrão.

### Posição

A posição é projection/UI state. Não deve ser gravada em `entities` como dado narrativo.

Se futuramente houver layout manual persistente, usar storage próprio de apresentação, versionado e separado do domínio.

## Interação pública

Por padrão:

- pan: sim;
- zoom: sim;
- selecionar node: sim;
- abrir inspector: sim;
- focar entity: sim;
- expandir vizinhança: sim;
- criar conexão: não;
- deletar node/edge: não;
- editar relation: não;
- handles visíveis: não;
- drag persistente: não.

Node dragging pode ser avaliado como interação local não persistente, mas não é requisito do primeiro slice.

## Busca

A busca superior deve procurar entidades e histórias autorizadas.

Resultados podem incluir:

- personagem;
- NPC;
- lugar;
- facção;
- música;
- quest;
- sessão;
- canon/momento.

Ao selecionar uma entity, ela vira o novo centro da projection.

Busca não pode revelar existência/nome de entities secretas fora da audience atual.

## Light e dark

As duas referências fornecidas demonstram a mesma composição em luminâncias diferentes. Isso é coerente com o Design System oficial.

Não criar dois layouts.

Os mesmos elementos mantêm:

- ordem;
- prioridade;
- tamanho relativo;
- relação espacial;
- significado.

Mudam apenas tokens de luminância, contraste, superfície, sombra e intensidade.

## Mobile

Mobile **não é desktop espremido**.

Direção:

- sidebar vira drawer/menu;
- topbar mantém busca/tema/conta de forma compacta;
- canvas ocupa a maior área útil;
- filtros podem virar scroll horizontal/menu;
- inspector vira bottom sheet/drawer;
- faixa inferior vira carousel/lista vertical;
- controles de zoom respeitam 44px de alvo;
- perfil completo abre página normal.

### Bottom sheet

Estados recomendados:

- fechado;
- peek: nome + relação principal;
- médio: resumo/relações;
- completo: inspector inteiro.

Não cobrir permanentemente o canvas com um painel lateral estreito em telas pequenas.

## Acessibilidade

O grafo nunca será a única forma de acessar relações.

Obrigatório:

- nodes e edges navegáveis por teclado quando interativos;
- accessible name descritivo;
- relação anunciada em texto;
- lista alternativa de relações;
- foco visível;
- não usar cor como único significado;
- zoom e pan sem bloquear teclado da página;
- reduced motion;
- inspector com heading/focus management correto;
- touch targets adequados;
- conteúdo textual disponível fora do canvas.

## Movimento

Animação deve ajudar a entender mudança de foco.

Permitido:

- transição curta de seleção;
- realocação radial suave;
- fade de nodes filtrados;
- abertura do inspector;
- highlight de caminho selecionado.

Evitar:

- partículas permanentes;
- glow pulsando continuamente;
- edges animados sem significado;
- parallax que dificulte leitura do grafo;
- transições longas ao trocar de entity.

Com `prefers-reduced-motion`, reduzir/rejeitar movimentos não essenciais.

## Conteúdo e canon

O World Explorer só apresenta conteúdo autorizado pelo pipeline narrativo.

```text
evidence
  -> candidate
  -> review
  -> canon / entity / relation ativa
  -> projection autorizada
  -> World Explorer
```

Coocorrência em transcrição não cria amizade.

Menção não cria relation.

IA pode sugerir, nunca oficializar automaticamente.

## Primeiro vertical slice

Entidade focal recomendada: **Dandelion**.

Motivo: as referências oficiais já demonstram visualmente esse cenário e ele cruza vários tipos de vínculo.

Conjunto candidato para fixture/protótipo, sujeito a validação canônica antes de persistência:

- Dandelion;
- Screacky;
- Astel;
- Ivory;
- Euclix;
- Thalindra;
- Leonard;
- Raphael;
- Hugin;
- Raven Queen;
- família Nightshade;
- Reino das Fadas;
- Fantasminhos;
- música `O Reino Vai Cantar`.

**A presença em uma referência de UI não transforma automaticamente cada relação desenhada em canon.** Fixtures de layout devem ser marcadas como demo até a relação ser confirmada por fonte/revisão.

## Critérios de aceite visual do slice

- dark semelhante em hierarquia às referências, sem copiar pixels cegamente;
- light preserva a mesma hierarquia;
- entity focada evidente sem dourar tudo;
- edge labels legíveis;
- 1-hop não vira spaghetti;
- inspector funciona sem reload;
- perfil completo navegável;
- teclado consegue selecionar nodes/relações;
- lista alternativa disponível;
- mobile usa bottom sheet;
- nenhuma informação secreta chega ao browser;
- nenhum estado editorial vaza na experiência pública.