# Architecture Decision Records

> Status: vigente
> Owner: arquitetura

ADRs registram **por que** decisões estruturais foram tomadas. Eles não substituem docs de implementação; evitam perder contexto e repetir debates.

## Estados

- `proposed` — em discussão;
- `accepted` — decisão vigente;
- `superseded` — substituída por ADR posterior;
- `rejected` — considerada e não adotada.

## Índice

| ADR | Status | Decisão |
| --- | --- | --- |
| [0001](0001-project-identity.md) | accepted | `tda` é reboot canônico; `dnd-scribe` é legado |
| [0002](0002-existing-supabase.md) | accepted | reutilizar Supabase existente como única base |
| [0003](0003-local-heavy-processing.md) | accepted | processamento pesado local, produto cloud |
| [0004](0004-canonical-entities.md) | accepted | PC/NPC/mundo na registry única `entities` |
| [0005](0005-canon-review-gate.md) | accepted | fonte → candidato → revisão → canon/publicação |
| [0006](0006-react-flow-world-explorer.md) | accepted | React Flow visualiza o World Explorer sem definir domínio/schema |
| [0007](0007-edit-workbench.md) | accepted | Edit é workbench server-first, incremental e orientado a capabilities |
| [0008](0008-capability-authorization.md) | accepted | Auth novo autoriza por capability + scope, sem super-role implícita |
| [0009](0009-world-explorer-multihub-layout.md) | accepted | World Explorer abre multi-hub; foco é temporário e dragging é layout local |
| [0010](0010-world-explorer-editorial-layout-persistence.md) | accepted | layout editorial é snapshot versionado separado de canon/relations e filtrado por audience |
| [0011](0011-world-explorer-layout-physical-persistence.md) | accepted | snapshot físico fica em storage dedicado, com capability própria, optimistic concurrency e audit atômico |
| [0012](0012-github-actions-controlled-delivery.md) | accepted | GitHub Actions é o único controlador de entrega; Vercel Git auto-deploy permanece desligado |
| [0013](0013-companion-agent-desktop-asr.md) | accepted | Companion separa Agent/UI, permanece per-user e adota runtime ASR multi-engine para Craig/português |
| [0014](0014-r2-media-storage-and-publishing.md) | accepted | R2 é o boundary da mídia pública e a publicação usa integridade/read-back antes de promover referências |
| [0015](0015-recovery-oriented-delivery.md) | accepted | entrega web evolui para main-only, Preview por PR, gates proporcionais e rollback como recuperação normal |

## Quando criar ADR

Criar quando a decisão:

- altera boundary do sistema;
- cria/remove banco/serviço principal;
- muda estratégia de Auth/security;
- muda ownership de dados;
- introduz compromisso difícil de reverter;
- escolhe tecnologia que vira boundary importante da experiência;
- altera processamento local vs cloud;
- substitui uma decisão accepted anterior.

Não criar ADR para detalhe puramente visual ou refactor local sem consequência arquitetural.

A adoção de React Flow recebeu ADR porque define a engine de uma superfície principal e estabelece explicitamente que a biblioteca fica isolada atrás de uma projection layer, evitando acoplamento de schema.

O Edit recebeu ADR porque define uma superfície administrativa principal, seu boundary de autorização, sua estratégia de migração do legado e a decisão de permanecer dentro do mesmo frontend/runtime do TDA.

Auth/capabilities recebeu ADR porque muda a estratégia de autorização do reboot: novas superfícies deixam de decidir acesso por nome de role e passam a exigir capability + scope + ownership explícitos.

O World Explorer multi-hub recebeu ADR porque substitui partes estruturais do primeiro slice do ADR-0006: a visão padrão deixa de ter um único foco central e o dragging público passa a ser reorganização visual local, sem virar dado de canon ou persistência implícita.

A persistência editorial do World Explorer recebeu ADR porque cria um novo ownership de estado: coordenadas podem ser salvas no futuro, mas continuam fora de canon/relations, exigem audience filtering, revision e autorização própria antes de qualquer storage físico.

A persistência física do World Explorer recebeu ADR porque fecha a forma de storage e mutation boundary sem ativá-los ainda: snapshot dedicado por campaign/view, capability `campaign.world.layout.edit`, função server-only com optimistic concurrency e audit atômico.

A entrega controlada recebeu ADR porque define um boundary operacional difícil de reverter: GitHub Actions é o controlador único, Vercel Git auto-deploy permanece desligado, Production é staged antes de tráfego e migrations usam overlay efêmero para preservar o history legado sem falsificá-lo no Git.

O TDA Companion v0.3 recebeu ADR porque separa lifecycle de Agent/UI, altera empacotamento e startup per-user, introduz update/uninstall verificáveis e define o boundary multi-engine do ASR local com ingest Craig e output canônico independente da engine.

O R2 recebeu ADR porque mídia pública virou um boundary compartilhado entre lores e outras superfícies: storage, keys imutáveis, integridade, read-back e publicação não devem ser reinventados por feature.

A entrega orientada a recuperação recebeu ADR porque muda a filosofia da esteira web: preserva GitHub Actions como controlador, mas troca a branch permanente de Preview e os gates globais por Preview de PR, gates proporcionais ao domínio alterado e rollback simples como mecanismo normal de recuperação.

## Regra histórica

Não editar ADR antigo para fazer parecer que a decisão sempre foi outra. Criar novo ADR e marcar `superseded`.

Template: [adr-template.md](../documentation/adr-template.md).