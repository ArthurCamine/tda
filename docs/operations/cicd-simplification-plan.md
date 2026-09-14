# CI/CD — plano de simplificação

> Status: em execução — Fases 1, 2 e 3 concluídas; Fase 4 planejada
> Owner: operations / architecture
> Última revisão: 2026-09-14
> Fonte de verdade: ADR-0015 e baseline da simplificação; runbooks atuais continuam vigentes até a implementação

> Atualização operacional de 2026-09-14: as Fases 4 e 5 foram implementadas e comprovadas. O metadata acima será normalizado junto com o catálogo gerado na Fase 6 para evitar uma regeneração intermediária sem valor operacional.

## Progresso real

| Fase | Estado | Evidência principal |
| --- | --- | --- |
| 1 — inventário e direção | **concluída** | PR #329; merge `fe9145631c21da064e9b9cb5dad0f2680722bed0` |
| 2 — CI rápido | **concluída** | PR #332; `validate` ~5m05s → ~37s; merge `6352f73636aa5bc8040ad3ba7db22527d7591397` |
| 3 — separar domínios pesados | **concluída** | PRs #334/#337/#338; `required-ci`; docs-only sem DB/Companion/mídia pesada |
| 4 — Preview por PR / main-only | **concluída tecnicamente** | PR #341; Preview por SHA da PR; PR #345 provou `feature/fix -> main` direto |
| 5 — Production simples | **concluída tecnicamente** | PRs #343/#344/#345; Production run `34900630352` = `success` |
| 6 — limpeza e documentação final | **próxima** | remover branch/gates legados, normalizar protections, metadata e catálogo |

## Objetivo

Simplificar a entrega do TDA para o risco real do projeto: feedback rápido, entendimento simples, rollback fácil e gates fortes somente onde uma falha é destrutiva ou difícil de recuperar.

O estado operacional comprovado ao final da Fase 5 é:

```text
feature/fix branch
       |
       v
      PR -> main
       |
       +--> workflow-contract / actionlint
       +--> validate rápido
       +--> DB somente se relevante
       +--> Companion somente se relevante
       +--> mídia local somente se relevante
       +--> Vercel Preview do SHA exato da PR
       +--> smoke
       |
       v
   required-ci
       |
       v
     merge main
       |
       v
 Production v3
       |
       +--> prova SHA atual + PR mergeada em main
       +--> calcula Production real -> novo main
       +--> migrations pendentes? aplica/verifica
       +--> manifest do merge atual? lifecycle de mídia
       +--> build Production
       +--> staged deploy sem tráfego
       +--> smoke
       +--> promote do MESMO artifact
       +--> canonical health/version
       +--> receipt pequeno

falhou depois da publicação?
       |
       v
rollback -> corrigir -> publicar novamente
```

## Princípios mantidos

1. `main` é a única branch longa necessária para a entrega web.
2. Preview é deployment de PR, não ambiente mantido por uma branch de integração.
3. GitHub Actions continua sendo o único controlador; Vercel Git auto-deploy permanece desligado.
4. Production continua staged porque isso entrega proteção útil com pouca complexidade.
5. DB, Companion e mídia só entram no caminho quando a alteração realmente toca seu domínio.
6. Migration pendente é acumulativa até o SHA realmente publicado alcançar o código.
7. Mídia histórica não relacionada não bloqueia deploy web; publicação de mídia é ligada ao merge que alterou manifest canônico.
8. Rollback é mecanismo normal de recuperação, não exceção vergonhosa.

## Fase 1 — inventário e direção

**Estado: concluída em 2026-09-14.**

O baseline registrou SHAs, protections, workflows e os principais gargalos. O desenho anterior possuía uma branch `Preview` permanente, promoção `Preview -> main`, testes pesados repetidos e auditoria pública global de mídia no caminho comum.

Evidência:

```text
PR:    #329
Merge: fe9145631c21da064e9b9cb5dad0f2680722bed0
```

ADR-0015 formalizou a direção recovery-oriented: gates proporcionais ao risco, SHA exato e rollback simples.

## Fase 2 — CI rápido

**Estado: concluída em 2026-09-14.**

Baseline observado na PR docs-only #329:

```text
validate:          ~5m05s
Playwright install ~25s
E2E:               ~3m50s
PostgreSQL:        ~47s
Companion:         ~4m05s
MSI docs-only:     sim
```

Resultado da PR #332:

```text
workflow-contract: ~13s
actionlint:        ~1s após pull da imagem
validate:          ~37s
required-ci:       ~2s
redução validate:  ~88%
```

O fast CI preservou `pnpm check`, build e migration safety policy; Chromium/E2E/processing completos saíram do caminho comum.

## Fase 3 — domínios pesados condicionais

**Estado: concluída em 2026-09-14.**

### 3A — shadow mode

PR #334 provou classificador + agregador. Um teste de mídia reproduziu o HTTP 403 do asset antigo `backgroud_jornada.avif`, demonstrando por evidência que full public audit global não deveria ser merge gate.

### 3B — branch protection

Depois do shadow mode, protections foram cortadas para:

```text
Preview:
  required-ci

main:
  required-ci
  promotion-source
```

O segundo contexto de `main` permaneceu temporariamente apenas para a transição da topologia antiga.

### 3C — seletividade ativa

PR #337:

```text
DB relevante: false
PostgreSQL:    skipped
mídia:         skipped
Companion:     uma única chamada reutilizável quando relevante
required-ci:   success
```

PR #338 foi o aceite docs-only: DB, Companion e mídia pesados ficaram `skipped`; nenhum MSI foi iniciado.

Regra central:

```text
workflow-contract -> success obrigatório
validate          -> success obrigatório
domínio relevante -> success obrigatório
domínio irrelevante -> skipped legítimo
                         |
                         v
                    required-ci
```

## Fase 4 — Preview por PR e cutover main-only

**Estado: concluída tecnicamente em 2026-09-14.**

### Preview por PR

PR #341 substituiu o Preview CD baseado na branch permanente por um deployment Vercel imutável no próprio grafo do CI.

Contrato:

```text
PR
 -> fast/domain CI
 -> ci-gate
 -> Vercel Preview do SHA exato
 -> /api/health
 -> /api/version
 -> /, /sessoes, /lore/yllith
 -> required-ci
```

A primeira implementação expôs um detalhe do GitHub Actions: ancestrais `skipped` propagavam o `success()` implícito pelo `needs`. O job de Preview passou a usar explicitamente `always()` + `ci-gate == success`, aceitando skips legítimos sem aceitar falha real.

Depois do merge da #341, um push na branch `Preview` gerou apenas CI; o antigo `Preview CD` por `workflow_run` não disparou. Em push, `preview-deployment=skipped` é esperado; em PR, Preview é obrigatório antes do `required-ci` verde.

### Prova main-only

A PR #345 foi aberta diretamente:

```text
fix/production-v3-media-release-scope -> main
```

Sem passagem por `Preview`.

Resultados:

```text
promotion-source shim: success
workflow-contract:     success
validate:              success
DB:                    skipped
Companion:             skipped
mídia:                 skipped
PR Preview + smoke:    success
required-ci:           success
merge main:            a8a9253e13c159263fc1f4a4672d8690f4c62e33
```

Isso comprova que a branch `Preview` deixou de ser dependência lógica do fluxo web. A remoção física ocorre na Fase 6.

## Fase 5 — Production v3

**Estado: concluída tecnicamente em 2026-09-14.**

### Baseline antes

O Production legado do merge `5715fa02...` executou run `34896656582`.

Mesmo sem migration nova, ele:

- instalou Supabase CLI;
- autenticou no Supabase Production;
- preparou o caminho de migration;
- executou full public audit global de mídia.

A release morreu em:

```text
backgroud_jornada.avif -> HTTP 403
```

Build, staged deploy, smoke e promote não chegaram a executar. Era o exemplo exato de uma falha antiga de mídia bloqueando uma mudança web não relacionada.

### Production v3

PR #343 reescreveu Production para preservar somente os gates úteis:

- SHA pedido precisa ser o `main` atual;
- source precisa ser resultado de uma PR realmente mergeada em `main`;
- baseline é o SHA que `/api/version` informa estar realmente em Production;
- esse SHA precisa ser ancestral do novo `main`;
- migration SQL pendente no intervalo Production real -> novo main ativa Supabase fail-closed;
- sem migration, Supabase CLI e credenciais de DB não participam da release;
- build ocorre uma vez;
- deployment é staged sem tráfego;
- smoke valida o staged artifact;
- o mesmo deployment é promovido;
- canonical `/health` e `/version` precisam convergir para SHA/release esperados;
- receipt final é pequeno.

A longa lógica de migrations saiu do YAML para `tools/ci/apply-production-migrations.sh`.

### Primeira tentativa do v3 — falha segura que melhorou o desenho

Run `34899700811`, SHA `3462685a...`:

```text
source/provenance: success
baseline Production: 42b5d50d840f5b0dd7bf5a8b5d475c98673d454c
migrations: false
mediaPublish: true
falha: R2_ACCOUNT_ID ausente
build/stage/promote: não executados
```

O intervalo acumulado desde o Production antigo continha um manifest histórico. Isso revelou que o deploy web estava tentando assumir um contrato de escrita R2 que nunca existiu nos GitHub Environments históricos.

A correção #345 separou os dois conceitos:

```text
migrations:
  acumulativas desde o SHA realmente publicado
  -> uma release falha não esquece schema pendente

media publish:
  somente manifests alterados no merge atual
  -> backlog histórico de mídia não bloqueia web deploy
```

Teste explícito garante que `manifest histórico + merge atual sem mídia => mediaPublish=false`.

### Primeiro Production v3 verde

PR #345 mergeou diretamente em `main`:

```text
main SHA:       a8a9253e13c159263fc1f4a4672d8690f4c62e33
CI push:        34900494222 -> success
Production CD:  34900630352 -> success
```

No Production run:

```text
source SHA atual:                   success
PR mergeada em main:                success
baseline canonical:                 success
release plan:                       success
credentials condicionais:           success
build Production:                   success
stage sem tráfego:                  success
Supabase CLI:                       skipped
migration policy/apply:             skipped
publish/readback de mídia:          skipped
staged smoke:                       success
promote do mesmo artifact:          success
canonical health/version:           success
release receipt:                    success
```

Esse run é o aceite da Fase 5.

## Fase 6 — limpeza final

**Estado: próxima.**

A limpeza só começa depois da prova Production acima e não muda o modelo técnico já comprovado.

Objetivos:

- remover `promotion-source` dos required contexts de `main`;
- apagar o workflow shim `promotion-policy.yml`;
- remover `Preview` dos triggers do CI;
- apagar `preview-branch-guard.yml`;
- revisar workflows especializados que ainda referenciem `Preview` e preservar apenas referências realmente necessárias ao domínio deles;
- apagar a branch remota `Preview` depois de não existir dependência funcional;
- atualizar `ci-cd.md`, `environments.md`, índices/ADR quando aplicável;
- normalizar o metadata deste plano e regenerar `docs/documentation/catalog.md`;
- verificar secrets/triggers obsoletos;
- provar uma PR final direta para `main` e um Production comum verde.

## Estado alvo aceito

```text
feature/fix
   |
   v
PR -> main
   |
   +-- actionlint + fast CI
   +-- domínio pesado somente quando relevante
   +-- Preview exato da PR + smoke
   |
   v
required-ci
   |
   v
merge main
   |
   v
Production staged
   +-- migration somente se pendente
   +-- mídia somente se o merge atual trouxer manifest canônico
   +-- smoke
   +-- promote mesmo artifact
   +-- canonical health/version
   +-- receipt pequeno

incidente recuperável -> rollback -> fix -> redeploy
```
