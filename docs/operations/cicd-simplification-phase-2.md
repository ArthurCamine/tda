# CI/CD — Fase 2: núcleo rápido

> Status: em andamento
> Owner: operations / architecture
> Última revisão: 2026-09-14
> Fonte de verdade: `.github/workflows/ci.yml`, GitHub Actions da PR da Fase 2 e baseline abaixo

## Objetivo

Reduzir o custo do CI web comum sem misturar ainda a separação de banco, Companion e mídia prevista para a Fase 3.

A Fase 2 introduz um contrato estático de workflows, mantém os checks rápidos já existentes no `pnpm check`, mantém o build e remove do `validate` comum a instalação do Chromium e as suítes E2E/processing completas.

## Baseline observado

A PR #329, que alterava somente documentação, forneceu uma amostra real do custo anterior:

```text
CI run:                  34876284417
CI início:               2026-09-14T17:41:33Z
CI fim:                  2026-09-14T17:46:43Z
validate início:         17:41:37Z
validate fim:            17:46:42Z
validate aproximado:     5m05s
PostgreSQL job:          ~47s
Playwright install:      ~25s
E2E:                     ~3m50s
processing:              ~7s
Companion run:           34876284413
Companion aproximado:    4m05s
MSI para PR docs-only:   sim
```

Essa medição não é benchmark universal; registra apenas uma execução real do estado anterior para comparação com a própria PR da Fase 2.

## Mudança implementada

### `workflow-contract`

Novo job barato que executa `actionlint` sobre `.github/workflows`.

Objetivo: detectar workflow YAML/expressions inválidos antes de merge. Shellcheck e pyflakes ficam desativados nesta primeira adoção para não transformar a introdução do contrato YAML em uma rodada paralela de lint de todos os scripts inline existentes.

### `validate`

Permanece com:

- checkout e dependências;
- migration safety policy;
- teste Python curto de SVG de lore;
- `pnpm check`;
- `pnpm build`.

Sai do caminho comum:

- `pnpm exec playwright install --with-deps chromium`;
- `pnpm test:e2e`;
- `pnpm test:processing`.

Essas suítes continuam disponíveis como scripts do projeto e serão reposicionadas por relevância/smoke nas fases seguintes, em vez de desaparecerem silenciosamente.

### `required-ci`

Novo job agregador com nome estável. Ele só passa quando:

```text
workflow-contract = success
validate          = success
```

O objetivo é permitir que a branch protection futura dependa de um único contrato estável enquanto jobs especializados passam a ser condicionais na Fase 3.

## Compatibilidade temporária

`transcript-import-postgres` continua rodando nesta fase.

Motivo: ele ainda é required check na proteção atual de `Preview`/`main`, e a separação por tipo de mudança pertence à Fase 3. Removê-lo ou pular o workflow antes de ajustar a estratégia de required checks poderia deixar PRs permanentemente pendentes.

O mesmo vale para os checks sintéticos do Companion: a Fase 2 não altera `companion.yml`.

## Antes / alvo da fase

| Sinal | Antes | Alvo Fase 2 |
| --- | --- | --- |
| validação estática de workflows | ausente | `workflow-contract` com actionlint |
| contrato estável agregador | ausente | `required-ci` |
| Chromium no `validate` comum | sim | não |
| E2E completo no `validate` comum | sim | não |
| processing no `validate` comum | sim | não |
| PostgreSQL em toda PR | sim | **ainda sim; Fase 3** |
| Companion/MSI em toda PR | sim | **ainda sim; Fase 3** |

## Critério para concluir

A Fase 2 só muda de `em andamento` para `concluída` depois que a PR da própria fase provar:

1. `workflow-contract` verde;
2. `validate` verde sem Chromium/E2E/processing;
3. `required-ci` verde;
4. checks legados necessários à protection atual continuam verdes;
5. tempo/etapas reais do run novo forem registrados neste documento;
6. a mudança for integrada em `Preview` sem contornar branch protection.
