# CI/CD — plano de simplificação

> Status: concluído — Fases 1–6 implementadas e comprovadas
> Owner: operations / architecture
> Última revisão: 2026-09-14
> Fonte de verdade: ADR-0015, evidências das PRs/runs e runbooks operacionais vigentes

## Resultado

A simplificação da entrega web do TDA foi concluída em 2026-09-14.

O objetivo era reduzir complexidade operacional sem remover proteções proporcionais ao risco. O fluxo deixou de usar uma branch permanente `Preview`, promoção `Preview -> main`, testes pesados indiscriminados e auditoria pública global de mídia no caminho comum.

Estado final:

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

incidente recuperável
       |
       v
rollback -> corrigir -> nova PR -> redeploy
```

## Princípios preservados

1. `main` é a única branch longa necessária para a entrega web.
2. Preview é deployment imutável de PR, não branch de integração.
3. GitHub Actions é o único controlador da entrega; Vercel Git auto-deploy permanece desligado.
4. Production continua staged para separar teste do artefato e movimentação de tráfego.
5. DB, Companion e mídia só entram no caminho quando a alteração realmente toca seu domínio.
6. Migration pendente continua acumulativa até o SHA realmente publicado alcançar o código.
7. Mídia histórica não relacionada não bloqueia deploy web.
8. Rollback é mecanismo operacional normal de recuperação.
9. `required-ci` é o único required status check da branch `main` para a entrega web comum.

## Resumo das fases

| Fase | Estado | Evidência principal |
| --- | --- | --- |
| 1 — inventário e direção | **concluída** | PR #329; merge `fe9145631c21da064e9b9cb5dad0f2680722bed0` |
| 2 — CI rápido | **concluída** | PR #332; `validate` ~5m05s -> ~37s; merge `6352f73636aa5bc8040ad3ba7db22527d7591397` |
| 3 — domínios pesados condicionais | **concluída** | PRs #334/#337/#338; docs-only sem PostgreSQL/Companion/mídia pesada |
| 4 — Preview por PR / main-only | **concluída** | PR #341; PR #345 provou `feature/fix -> main` direto |
| 5 — Production v3 | **concluída** | PRs #343/#344/#345; run `34900630352` success |
| 6 — limpeza final | **concluída** | PR #347 + cutover administrativo + pacote 6B final |

## Fase 1 — inventário e direção

O baseline registrou SHAs, protections, workflows e os gargalos do desenho anterior. O estado observado tinha branch `Preview` permanente, promoção `Preview -> main`, testes pesados repetidos e auditoria pública global de mídia no caminho comum.

ADR-0015 formalizou a direção recovery-oriented: gates proporcionais ao risco, SHA exato e rollback simples.

## Fase 2 — CI rápido

Baseline observado na PR docs-only #329:

```text
validate:          ~5m05s
Playwright install ~25s
E2E:               ~3m50s
PostgreSQL:        ~47s
Companion:         ~4m05s
MSI docs-only:     sim
```

Depois da PR #332:

```text
workflow-contract: ~13s
actionlint:        ~1s após pull da imagem
validate:          ~37s
required-ci:       ~2s
redução validate:  ~88%
```

O fast CI preservou `pnpm check`, build e migration safety policy; Chromium/E2E/processing completos saíram do caminho comum.

## Fase 3 — domínios pesados condicionais

Um único classificador passou a produzir:

```text
web=true|false
db=true|false
companion=true|false
media=true|false
```

A PR #337 ativou a seletividade real. A PR #338 foi o aceite docs-only:

```text
workflow-contract: success
validate:          success
PostgreSQL:        skipped
Companion:         skipped
mídia:             skipped
required-ci:       success
```

Mudanças relevantes continuam fail-closed: domínio relevante exige `success`; apenas domínio irrelevante pode terminar `skipped`.

## Fase 4 — Preview por PR e main-only

A PR #341 substituiu o Preview CD baseado em branch por deployment Vercel dentro do próprio grafo do CI:

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

O job de Preview usa `always()` combinado com `ci-gate == success` para não herdar falsamente o `success()` implícito de ancestrais legitimamente `skipped`.

A PR #345 provou o fluxo direto:

```text
fix/production-v3-media-release-scope -> main
```

Sem passagem por uma branch de integração.

## Fase 5 — Production v3

### Problema comprovado no desenho anterior

O Production legado run `34896656582` executou trabalho de Supabase mesmo sem migration nova e morreu antes do build ao fazer full public audit de mídia por causa de um asset histórico com HTTP 403.

Esse run foi a evidência concreta de acoplamento indevido entre deploy web comum e estado global do acervo de mídia.

### Contrato novo

Production v3 preserva apenas os gates úteis:

- SHA solicitado precisa ser o HEAD atual de `main`;
- SHA precisa vir de PR realmente mergeada em `main`;
- baseline é o SHA que `/api/version` informa estar realmente publicado;
- baseline precisa ser ancestral da nova release;
- migration SQL pendente no intervalo Production real -> novo main ativa Supabase fail-closed;
- sem migration, Supabase CLI e credenciais de DB não participam;
- mídia automática considera apenas manifest canônico alterado no merge atual;
- build ocorre uma vez;
- deployment é staged sem tráfego;
- smoke valida o staged artifact;
- o mesmo deployment é promovido;
- `/api/health` e `/api/version` canônicos precisam convergir para SHA/release esperados;
- receipt final registra a release.

A primeira tentativa v3 (`34899700811`) falhou de forma segura antes de mutação porque o desenho ainda tratava um manifest histórico como mídia a publicar. A PR #345 separou os escopos:

```text
migrations:
  acumulativas desde o SHA realmente publicado

media publish:
  somente manifests alterados no merge atual
```

Primeiro Production v3 verde:

```text
PR main-only:   #345
main SHA:       a8a9253e13c159263fc1f4a4672d8690f4c62e33
CI:             34900494222 success
Production CD:  34900630352 success
Supabase:       skipped
mídia publish:  skipped
stage:          success
smoke:          success
promote:        success
canonical:      success
receipt:        success
```

## Fase 6 — limpeza final

### 6A — remover dependências funcionais da branch antiga

A PR #347 removeu `Preview` dos triggers do CI web e do Companion Dependency Freshness e apagou `preview-branch-guard.yml`, que existia apenas para recriar a antiga branch permanente.

Aceite da PR #347:

```text
workflow-contract: success
validate:          success
DB:                skipped
Companion:         skipped
mídia:             skipped
PR Preview:        success
required-ci:       success
```

Merge em `main`:

```text
a46e8292eaed7e1cff32addd181668d83fd76be4
```

CI do push main-only:

```text
run 34902095910 -> success
preview-deployment -> skipped esperado em push
required-ci -> success
```

Production após a limpeza:

```text
run 34902180398 -> success
build -> success
Supabase -> skipped
mídia -> skipped
staged smoke -> success
promote -> success
canonical -> success
receipt -> success
```

### 6B — cutover administrativo e documentação

Antes da remoção física, foi verificado que a branch `Preview` não continha commits exclusivos: `main` estava 9 commits à frente e `Preview` 0 à frente.

Cutover administrativo executado em 2026-09-14:

```text
main required status checks:
  required-ci

promotion-source:
  removido dos required contexts

Preview protection:
  removida

branch Preview:
  removida; API retorna HTTP 404
```

O pacote final remove `promotion-policy.yml`, normaliza os runbooks para o modelo vigente e fecha o catálogo documental.

## Antes e depois

### Antes

```text
feature/fix
 -> PR Preview
 -> CI comum + Postgres frequente + Companion/MSI frequente
 -> merge Preview
 -> Preview CD separado
 -> homologação
 -> PR Preview -> main
 -> promotion-source
 -> CI novamente
 -> Production monolítico
 -> Supabase mesmo sem migration
 -> full audit global R2
 -> build/stage/promote
```

### Depois

```text
feature/fix
 -> PR main
 -> fast CI
 -> somente domínios relevantes
 -> Preview exato da PR + smoke
 -> required-ci
 -> merge main
 -> Production v3
 -> somente migrations/mídia relevantes
 -> stage
 -> smoke
 -> promote mesmo artifact
 -> canonical health/version
 -> receipt
```

## Definition of Done final

- [x] actionlint no contrato de CI;
- [x] fast CI comum;
- [x] DB pesado seletivo;
- [x] Companion/MSI seletivo;
- [x] mídia local seletiva;
- [x] Preview imutável por PR;
- [x] `required-ci` agrega CI + Preview quando aplicável;
- [x] PR normal aponta diretamente para `main`;
- [x] Production prova SHA e PR mergeada em `main`;
- [x] migrations remotas somente quando pendentes;
- [x] mídia histórica não bloqueia deploy web comum;
- [x] Production staged promove exatamente o artefato testado;
- [x] canonical health/version verificados;
- [x] branch `Preview` removida sem perda de commits;
- [x] `promotion-source` removido da protection de `main`;
- [x] workflows de guard/promoção legados removidos;
- [x] runbooks atualizados para o estado vigente;
- [x] evidências before/after preservadas.

**Estado final: simplificação CI/CD concluída.**
