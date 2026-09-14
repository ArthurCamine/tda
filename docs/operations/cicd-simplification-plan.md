# CI/CD — plano de simplificação

> Status: em execução — Fases 1, 2 e 3 concluídas; Fase 4 planejada
> Owner: operations / architecture
> Última revisão: 2026-09-14
> Fonte de verdade: ADR-0015 e baseline da simplificação; runbooks atuais continuam vigentes até a implementação

## Progresso

| Fase | Estado | Evidência principal |
| --- | --- | --- |
| 1 — inventário e direção | **concluída** | PR #329; merge `fe9145631c21da064e9b9cb5dad0f2680722bed0` |
| 2 — CI rápido | **concluída** | PR #332; merge `6352f73636aa5bc8040ad3ba7db22527d7591397`; `validate` ~5m05s → ~37s |
| 3 — separar domínios pesados | **concluída** | PRs #334/#337/#338; merges `c22d0cbd54f7c4ef14ed5b6071ae55bfa8a2dbc9` / `5cbf298c06094c3b3ce83c07c861629bb06ebee4`; protections cortadas para `required-ci`; aceite docs-only sem DB/Companion/mídia pesada |
| 4 — Preview por PR / main-only | planejada | — |
| 5 — Production simples | planejada | — |
| 6 — limpeza e documentação final | planejada | — |

## Objetivo

Simplificar a entrega do TDA para o risco real do projeto: aplicação pessoal/de jogo, operada por uma pessoa com apoio de automação, sem requisito atual de alta disponibilidade ou compliance.

A direção otimiza feedback rápido, entendimento simples, rollback fácil e rastreabilidade suficiente. Proteções fortes ficam concentradas onde uma falha custa mais: credenciais, autorização e migrations.

## Estado-alvo

```text
feature/fix branch
       |
       v
      PR
       |
       +--> CI rápido
       |     actionlint
       |     typecheck
       |     lint
       |     unit
       |     build
       |
       +--> jobs condicionais
       |     DB se DB/data layer mudar
       |     Companion se Companion mudar
       |     mídia se mídia/tooling mudar
       |
       +--> Preview do SHA da PR
               |
               +--> health/version
               +--> smoke pequeno
       |
       v
   merge em main
       |
       v
 Production staged
       |
       +--> migrations se aplicável
       +--> mídia se aplicável
       +--> smoke
       +--> promote
       +--> canonical health/version
       +--> registro simples da release

falhou depois da publicação?
       |
       v
rollback -> corrigir -> publicar novamente
```

## Princípios

1. `main` será a única branch longa da entrega web.
2. Preview será um deployment de PR, não uma branch permanente.
3. GitHub Actions continua como único controlador; Vercel Git auto-deploy permanece desligado.
4. Production continua staged enquanto isso for simples e barato.
5. Mídia continua no R2; apenas o ciclo de validação/publicação é desacoplado do deploy web comum.
6. Companion e runtimes não participam do caminho web sem mudança no domínio deles.
7. Gates pesados devem ser condicionais ao risco real da mudança.
8. Falha recuperável em Production é aceitável quando rollback resolve rapidamente.

## Fase 1 — inventário e direção

**Estado: concluída em 2026-09-14.**

Entregas:

- baseline com SHAs e protections;
- inventário de workflows;
- classificação KEEP / SIMPLIFY / REPLACE / DELETE;
- estado-alvo;
- ADR-0015;
- plano das seis fases.

Evidência:

```text
PR:        #329
Head:      931e5e37e6fe7f654fb0c44be2f950008761ebc2
Merge:     fe9145631c21da064e9b9cb5dad0f2680722bed0
Base:      Preview
Runtime:   sem alteração funcional
```

Definition of Done atingida:

- nenhuma mudança de runtime;
- documentação distingue estado vigente de estado planejado;
- baseline possui data e SHA;
- branch de trabalho era descartável sem impacto operacional.

## Fase 2 — CI rápido

**Estado: concluída em 2026-09-14.**

Objetivo: criar o núcleo mínimo de validação web para PR, sem ainda desacoplar os domínios pesados que pertencem à Fase 3.

### Baseline real antes da mudança

A PR #329, que alterava somente documentação, forneceu uma amostra real do custo anterior:

```text
CI run:                  34876284417
CI início:               2026-09-14T17:41:33Z
CI fim:                  2026-09-14T17:46:43Z
validate:                ~5m05s
PostgreSQL job:          ~47s
Playwright install:      ~25s
E2E:                     ~3m50s
processing:              ~7s
Companion run:           34876284413
Companion:               ~4m05s
MSI para PR docs-only:   sim
```

### Resultado real da Fase 2

Na PR #332:

```text
CI run inicial:            34877237056
workflow-contract:         ~13s total; actionlint em ~1s após pull da imagem
validate:                  ~37s
required-ci:               ~2s
transcript-import-postgres ~51s
Chromium no validate:      não
E2E completo no validate:  não
processing no validate:    não
Resultado CI final:        success
Resultado Companion final: success
Merge Preview:             6352f73636aa5bc8040ad3ba7db22527d7591397
```

Comparação do `validate` observado:

```text
antes: ~305s
Fase 2: ~37s
redução: ~268s / ~88%
```

`workflow-contract` executa `actionlint` em `.github/workflows`. `validate` permanece com migration safety policy, teste curto de SVG, `pnpm check` e `pnpm build`. `required-ci` introduz um nome estável para o contrato de merge.

PostgreSQL e Companion foram preservados deliberadamente nesta fase porque a branch protection ainda exigia seus nomes diretamente.

Definition of Done atingida:

- `validate` comum não instala Chromium nem executa E2E/processing completo;
- workflow inválido é detectado por `actionlint` antes do merge;
- `required-ci` existe;
- medições antes/depois foram registradas;
- integração ocorreu em `Preview` sem contornar branch protection.

## Fase 3 — separar domínios pesados

**Estado: concluída em 2026-09-14.**

### Objetivo

Tirar PostgreSQL, Companion/MSI e auditoria pública global de mídia do caminho comum quando a mudança não toca esses riscos, sem transformar `skipped` legítimo em bypass de segurança.

A classificação é feita pelos arquivos alterados, não pelo título, autor ou descrição da PR.

### Evidência executada — 3A / 3B / 3C

#### 3A — shadow mode

PR #334 comprovou o classificador e o agregador no mesmo SHA.

```text
Head validado: f49b7156aff3b4ec98cf175c944662eec4dc9354
CI run:        34889341770
Resultado:    success
DB:           success
Companion:    Linux + Windows + MSI success
Mídia:        contrato local success
required-ci:  success
Merge Preview: c22d0cbd54f7c4ef14ed5b6071ae55bfa8a2dbc9
```

O primeiro teste de mídia em shadow mode reproduziu o 403 público do asset antigo `backgroud_jornada.avif`. Isso confirmou que o full public audit global via rede não deveria ser merge gate. O gate de PR ficou restrito à integridade local de manifests/tooling/contratos; auditoria pública global permanece separada do caminho comum.

A Fase 3A foi promovida para `main` pela PR #336, merge `2e85d835c4c9815cfd2d74190fba6749a0fb3b79`.

#### 3B — cutover administrativo

Depois de `required-ci` estar comprovado em `Preview` e `main`, os required contexts foram alterados sem mexer nas demais proteções:

```text
Preview:
  required-ci

main:
  required-ci
  promotion-source
```

`promotion-source` continua temporariamente porque a topologia `Preview -> main` ainda existe até o cutover Production/main-only.

#### 3C — seletividade ativa

PR #337 ativou os jobs condicionais depois do cutover das protections.

```text
Head:          81680ac665567226c1cfcd7337e2e1495b7ef406
CI run:        34891945990
DB relevante: false
PostgreSQL:    skipped
Mídia:         skipped
Companion:     Linux + Windows + MSI success, uma única chamada via CI
required-ci:   success
Merge Preview: 5cbf298c06094c3b3ce83c07c861629bb06ebee4
```

O workflow `Companion` deixou de disparar automaticamente em toda PR/push. Ele continua reutilizável via `workflow_call` e disponível manualmente via `workflow_dispatch`. O workflow `Companion Dependency Freshness` mantém seus próprios `paths`, agenda e dispatch.

A PR #338 foi usada como aceite docs-only. Na primeira execução, o classificador já confirmou `db=false`, `companion=false` e `media=false`; PostgreSQL, Companion e mídia ficaram `skipped`, e nenhum MSI foi iniciado. O primeiro run falhou apenas porque o catálogo documental gerado ainda carregava o status antigo deste próprio plano; o catálogo foi regenerado antes do merge. Essa falha não alterou runtime e demonstrou que `required-ci` continuou fail-closed quando o fast CI falhou.

### Regra central

`required-ci` é o único contrato genérico de merge.

```text
workflow-contract  -> success obrigatório
validate           -> success obrigatório
DB                 -> success OU skipped legítimo
Companion          -> success OU skipped legítimo
media-local        -> success OU skipped legítimo
                         |
                         v
                    required-ci
```

Se um domínio for classificado como relevante, falha desse domínio faz `required-ci` falhar. Se não for relevante, `skipped` é aceito explicitamente.

### Classificador

A regra única e testável vive em `tools/ci/classify-changes.mjs`, em vez de copiar listas de paths em vários YAMLs.

Saídas:

```text
web=true|false
db=true|false
companion=true|false
media=true|false
```

`web` não significa “somente frontend”; significa que o núcleo rápido (`workflow-contract`, `pnpm check`, build) continua sendo a validação comum da aplicação/repositório.

O classificador aceita range Git explícito e produz resumo legível dos arquivos/classes detectados. A mesma regra poderá ser reutilizada por Preview/Production nas fases seguintes.

### Contrato de relevância

#### Sempre / CI rápido

Toda PR continua executando:

- `workflow-contract`;
- `validate` com `pnpm check`;
- `pnpm build`;
- `required-ci`.

Docs-only, CSS/UI, lore textual e alterações comuns de aplicação não acionam automaticamente PostgreSQL ou MSI.

#### DB / integração PostgreSQL

Classificar `db=true` quando houver mudança em:

```text
supabase/**
src/features/transcript-sync/**
tools/transcript-sync-db.py
tools/world-layout-db.py
tools/world-entity-media-db.py
tools/test_world_layout_db.py
tools/test_world_entity_media_db.py
tools/ci/check-migrations.mjs
tools/check-migration-naming.py
tools/check-relation-migration-safety.py
```

`supabase/**` é intencionalmente amplo porque os synthetics carregam migrations e fixtures reais do repositório. O teste `src/features/transcript-sync/database.test.ts` importa cliente, consumer, HTTP, contrato e validação do próprio domínio, portanto mudança nessa feature inteira justifica o synthetic PostgreSQL.

Documentação de banco, por si só, continua protegida por `db:docs:check` dentro de `pnpm check` e não precisa subir PostgreSQL.

#### Companion

Classificar `companion=true` quando houver mudança em:

```text
local-companion/**
.github/workflows/companion.yml
tools/check-companion-*.py
```

O `companion.yml` aceita `workflow_call` para ser chamado condicionalmente pelo CI. Seus synthetics Linux/Windows e MSI continuam iguais quando o domínio é relevante; a economia vem de não iniciá-los quando o domínio não mudou.

Workflows especializados de RC/runtime (`companion-rc`, `companion-promote`, `runtime-*`, `qwen-*`, `whisper-*`) mantêm seus próprios contratos, paths e/ou dispatch. Alterá-los é sempre coberto pelo `workflow-contract`, mas não deve construir automaticamente o MSI genérico apenas por terem sido editados.

`docs/companion/**` também não deve, isoladamente, construir MSI. Receipts e documentação continuam sujeitos aos validadores específicos de release quando forem usados para promoção.

#### Mídia

Classificar `media=true` quando houver mudança no contrato de armazenamento/publicação ou nos manifests/fontes canônicos:

```text
media/**
tools/media/**
tools/media-pipeline.py
tools/check-canonical-media-usage.py
tools/check-lore-assets.py
tools/migrate-r2-keys.mjs
tools/world-entity-media-r2-policy.test.mjs
```

O fast CI continua executando os testes locais de mídia que já fazem parte de `pnpm check` enquanto seu custo permanecer pequeno.

O que saiu do caminho comum foi a verificação **pública/global via rede** de todos os objetos R2.

Mudança em `public/lore/**` que apenas altera HTML/CSS/JS/texto e referencia mídia já publicada continua sendo web comum. Se a mesma PR altera `media/**` ou tooling de publicação, `media=true` é acionado.

### Lifecycle de mídia na Fase 3

```text
validação local do manifest/tooling
    -> barata; continua no CI

publicação/alteração de mídia canônica
    -> somente quando media=true

full public audit do R2
    -> separado do merge gate comum
```

Preview/Production comuns não devem falhar porque um asset antigo e não relacionado recebeu 403 temporário. Mudanças de mídia continuam fail-closed para integridade local e contratos de publicação; o ciclo de publicação/readback continua responsável pelo conteúdo realmente alterado.

### Transição segura da branch protection

#### Fase 3A — shadow mode

1. promover a Fase 2 de `Preview` para `main` usando a topologia atual, para que `required-ci` exista também no default branch;
2. adicionar o classificador com testes;
3. estender `required-ci` para conhecer DB/Companion/media;
4. tornar `companion.yml` reutilizável, mantendo temporariamente os triggers antigos;
5. executar PR de prova e comparar classificação esperada x observada;
6. ainda não pular os checks exigidos pela protection antiga.

**Executada:** PR #334, promoção #336 e evidências acima.

#### Fase 3B — cutover administrativo

`Preview` passou de quatro checks diretos para:

```text
required-ci
```

Enquanto `main` ainda usa promoção `Preview -> main`, ficou:

```text
required-ci
promotion-source
```

`promotion-source` desaparece somente quando Production deixar de exigir provenance `Preview -> main`.

**Executada:** protections verificadas após o cutover com os contexts acima.

#### Fase 3C — ativar seletividade

- `transcript-import-postgres` recebeu `if: db == true`;
- Companion deixou de disparar como workflow PR independente e passou a ser chamado pelo CI quando `companion == true`;
- media job executa somente quando `media == true`;
- `required-ci` aceita `skipped` apenas para domínio classificado como irrelevante e exige `success` quando relevante.

**Executada:** PR #337; PR #338 comprova o caminho docs-only sem jobs pesados.

### Casos de prova

| Mudança | Fast CI | PostgreSQL | Companion/MSI | mídia pesada |
| --- | --- | --- | --- | --- |
| docs-only | sim | não | não | não |
| CSS/UI/web comum | sim | não | não | não |
| `local-companion/**` | sim | não, salvo mudança DB separada | sim | não |
| `supabase/migrations/**` | sim | sim | não | não |
| `src/features/transcript-sync/**` | sim | sim | não | não |
| `media/**` / `tools/media/**` | sim | não, salvo DB separada | não | sim |
| PR mista DB + Companion | sim | sim | sim | conforme arquivos |
| PR mista web + mídia | sim | não, salvo DB separada | não | sim |

PRs usadas como regressão/evidência:

- #329: docs-only antes da simplificação;
- #326: tooling de mídia;
- #317: Companion isolado;
- #318: runtime/Companion especializado;
- #320: web/lore + mídia;
- #325: workflow de delivery;
- #334: contrato/classificador fail-safe, todos os domínios relevantes;
- #337: Companion relevante com DB/mídia irrelevantes e `skipped` legítimo;
- #338: docs-only com DB/Companion/mídia irrelevantes e `skipped` legítimo.

### Definition of Done da Fase 3

- docs-only não sobe PostgreSQL nem constrói MSI;
- web comum não sobe PostgreSQL nem constrói MSI;
- mudança de Companion continua executando synthetics Linux/Windows + MSI;
- mudança de DB continua executando synthetic PostgreSQL relevante;
- CI comum sem mudança de mídia não faz full public audit global do R2;
- mudança de mídia mantém validações locais/contratos fail-closed e o ciclo de publicação continua responsável pelo readback do conteúdo alterado;
- `required-ci` é o contrato estável de merge;
- jobs especializados podem ser `skipped` sem deixar PR pendente e sem permitir falha quando classificados como relevantes;
- classificação e transição estão documentadas com evidências antes/depois.

## Fase 4 — Preview por PR e transição para main-only

Objetivo: separar o conceito de Preview do conceito de branch e provar o deployment imutável por PR antes de alterar a provenance de Production.

### Fase 4A — Preview imutável por PR

**Implementação comprovada na PR #341.**

O antigo `.github/workflows/preview.yml`, disparado por `workflow_run` no HEAD mutável de `Preview`, foi substituído por `.github/workflows/deploy-preview.yml` reutilizável. O `CI` passou a usar a sequência:

```text
fast/domain checks
       |
       v
    ci-gate
       |
       v
Preview exato da PR
       |
       v
  required-ci
```

Em PR, `required-ci` somente fica verde depois que o Preview do SHA exato faz build, deploy e smoke. Em push sem PR, o Preview é `skipped` legitimamente.

Evidência principal:

```text
PR:              #341
Head comprovado: c86f519b4b2e4a12916779729a8131f90790d656
CI run:          34895256681
release Preview: pr-341-c86f519b4b2e
Vercel Preview:  https://tda-ox3wglak9-projeto-desenv-6905s-projects.vercel.app
ci-gate:         success
PostgreSQL:      skipped
Companion:       skipped
mídia pesada:    skipped
Preview deploy:  success
required-ci:     success
```

O smoke verificou `/api/health`, `/api/version`, `/`, `/sessoes` e `/lore/yllith`, exigindo `environment=preview`, commit igual ao SHA da PR e release igual a `pr-<numero>-<shortsha>`.

O full public audit global de R2 não participa mais do Preview web. A validação de mídia continua no domínio próprio definido na Fase 3.

### Falha encontrada e contrato corrigido

As duas primeiras tentativas da PR #341 falharam de forma segura antes de alcançar Vercel: `ci-gate` estava verde, mas `preview-deployment` apareceu como `skipped` porque GitHub Actions propaga o estado de ancestrais `skipped` através de `needs` com o `success()` implícito.

A condição final ficou explícita:

```text
always()
+ evento pull_request
+ ci-gate == success
```

Isso permite ignorar somente os skips legítimos de DB/Companion/mídia enquanto continua impedindo Preview quando `ci-gate` falha. `required-ci` permaneceu fail-closed nas tentativas anteriores e só ficou verde depois do Preview real passar.

### Dependência descoberta: Production legado

A retirada imediata da branch `Preview` foi adiada deliberadamente depois de inspecionar o `production.yml` vigente. Ele ainda prova provenance procurando uma PR mergeada com:

```text
head = Preview
base = main
merge_commit_sha = SHA de Production
```

Apagar `Preview`, `promotion-source` e `preview-branch-guard` antes de substituir esse contrato faria todo deploy novo de Production falhar por design.

Por isso a sequência segura passa a ser:

```text
Fase 4A
Preview por PR comprovado
antigo Preview CD removido
        |
        v
Fase 5
Production v3 aceita SHA exato de PR mergeada em main
Production fica condicional por DB/mídia
        |
        v
cutover main-only
retira promotion-source
PRs normais passam a mirar main
        |
        v
Fase 6
apaga branch Preview + guard e referências residuais
```

Até esse cutover, a branch `Preview` permanece apenas como compatibilidade da provenance de Production; ela não representa mais a implementação desejada de homologação.

### Critério atualizado da Fase 4

A parte de Preview da fase é considerada comprovada quando:

- Preview de uma PR não depende do HEAD mutável de outra branch;
- o SHA exato é usado no checkout, build, deploy, health e version;
- `required-ci` depende do Preview verde em PR;
- `workflow_run` deixa de controlar o Preview web;
- full public audit global de mídia não bloqueia Preview web comum.

A remoção física da branch `Preview` e da promoção intermediária fica condicionada ao Production v3 da Fase 5, para preservar deploy funcional durante a migração.

## Fase 5 — Production simples e recuperável

Objetivo: reduzir `production.yml` ao necessário para publicar com segurança proporcional ao projeto e concluir o cutover main-only sem quebrar provenance.

Direção:

- aceitar como fonte o SHA exato de uma PR realmente mergeada em `main`, sem exigir branch de origem chamada `Preview`;
- build Production;
- staged deploy;
- smoke básico;
- migrations apenas quando houver migrations relevantes;
- mídia apenas quando houver mudança relevante;
- promote do mesmo deployment testado;
- health/version canônico;
- registro simples do SHA/deployment;
- rollback permanece caminho oficial de recuperação;
- depois da prova do Production v3, retirar `promotion-source` e fazer PR normal mirar `main`.

Definition of Done:

- release web sem DB/mídia não executa a bateria desses domínios;
- deploy ruim pode ser revertido sem reconstrução;
- provenance exige merge real em `main`, mas não uma branch intermediária artificial;
- PR normal pode usar `main` como base depois do cutover;
- workflow fica legível como orquestração, com lógica longa movida para scripts quando necessário.

## Fase 6 — limpeza e documentação final

Objetivo: remover o legado depois que o fluxo novo estiver provado.

Direção:

- apagar workflows/gates/branches obsoletos;
- apagar a branch `Preview` e seu branch guard depois do cutover Production/main-only;
- retirar referências à topologia antiga dos runbooks atuais;
- atualizar branch protections;
- revisar configurações não utilizadas;
- consolidar operação cotidiana e rollback;
- preservar ADRs antigos como histórico.

Definition of Done:

- `docs/operations/ci-cd.md` descreve exatamente o runtime vigente;
- não existem triggers fantasma da topologia antiga;
- a documentação permite entender o fluxo comum sem reconstruir a história por logs;
- histórico de decisões continua disponível.

## Regra documental por fase

Toda fase só termina quando quatro itens existem juntos:

```text
implementação
+ validação
+ documentação vigente
+ registro antes/depois
```

Usar medições simples:

| Sinal | Antes | Depois |
| --- | --- | --- |
| duração do `validate` web comum | ~5m05s na PR #329 | ~37s na Fase 2 |
| Chromium/E2E em `validate` comum | sim | não |
| PostgreSQL em mudança web comum | sim | Fase 3: não quando `db=false` |
| MSI em mudança web comum | sim | Fase 3: não quando `companion=false` |
| full media audit sem mudança de mídia | sim | Fase 3/4: não no required CI nem no Preview web |
| Preview ligado ao HEAD de branch intermediária | sim | Fase 4A: não; Preview usa SHA exato da PR |
| branch longa além de `main` | `Preview` | compatibilidade temporária até Production v3; remoção final na Fase 6 |
| promoção intermediária | `Preview -> main` | compatibilidade temporária até cutover main-only da Fase 5 |

Não criar dashboard novo apenas para acompanhar a migração.

## Estratégia de transição

Construir o caminho novo antes de retirar o velho:

```text
estado atual
  -> CI novo comprovado
  -> domínios pesados desacoplados
  -> Preview por PR comprovado
  -> Production v3 comprovado
  -> main-only
  -> remoção do legado
```

Cada fase deve ser reversível pelo Git. Branch, protection ou workflow antigo só é aposentado depois de confirmar que a alternativa funciona.

## Itens adiados deliberadamente

Não implementar agora apenas por possibilidade futura:

- release lock sofisticado da aplicação web;
- tree-SHA attestations adicionais;
- DORA dashboard;
- auto-sync `main -> Preview`;
- ledger de release complexo;
- receipts adicionais além do necessário para identificar SHA/deployment;
- gates globais sem relação com a classe da mudança.
