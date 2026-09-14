# CI/CD — operação, promoção e recuperação

> Status: vigente
> Owner: operations / release / dados
> Última revisão: 2026-09-14

## Objetivo

Este é o runbook canônico da entrega web do TDA. A arquitetura atual segue a direção recovery-oriented da [ADR-0015](../adr/0015-recovery-oriented-delivery.md): CI rápido, Preview imutável por PR, `main` como fonte de Production, gates pesados condicionais e rollback como mecanismo normal de recuperação.

Contrato atual:

```text
branch temporária
      |
      v
    PR -> main
      |
      +-- workflow-contract / actionlint
      +-- validate rápido
      +-- DB somente se relevante
      +-- Companion somente se relevante
      +-- mídia local somente se relevante
      +-- Preview Vercel do SHA exato
      +-- smoke
      |
      v
  required-ci
      |
      v
 merge main
      |
      v
 Production CD
      |
      +-- prova SHA atual + PR mergeada em main
      +-- calcula baseline Production real
      +-- migrations pendentes? executa lifecycle Supabase
      +-- manifest canônico no merge atual? executa lifecycle de mídia
      +-- build
      +-- stage sem tráfego
      +-- smoke
      +-- promote mesmo artifact
      +-- canonical health/version
      +-- receipt
```

## Fonte e controle

GitHub Actions é o único controlador da entrega. Vercel Git auto-deploy permanece desligado.

Fonte canônica de Production:

```text
main
```

Uma release automática só nasce depois de CI verde no push de `main`. O workflow de Production confirma em runtime que o SHA atual é resultado de uma PR realmente mergeada em `main` e recusa SHA stale/arbitrário.

A antiga branch Git `Preview` foi aposentada da entrega web. Preview agora significa exclusivamente o deployment Vercel imutável criado para uma PR.

## CI de pull request

Workflow: `.github/workflows/ci.yml`.

Toda PR executa o núcleo comum:

- `classify-changes`;
- `workflow-contract` com `actionlint` e testes dos classificadores;
- `validate` com migration safety policy, `pnpm check` e `pnpm build`;
- `ci-gate`;
- Vercel Preview do SHA exato da PR;
- `required-ci`.

Jobs pesados são condicionais:

```text
DB relevante        -> synthetic PostgreSQL
Companion relevante -> synthetics + MSI
mídia relevante     -> contratos locais de publicação
irrelevante         -> skipped legítimo
```

`required-ci` aceita `skipped` apenas quando o classificador marcou o domínio como irrelevante. Se o domínio é relevante, somente `success` satisfaz o agregador.

## Preview por PR

Workflow reutilizável: `.github/workflows/deploy-preview.yml`.

Preview não é uma branch. Cada PR recebe um deployment Vercel construído do SHA exato informado pelo evento.

O workflow confirma o SHA antes do deploy e injeta:

```text
APP_ENV=preview
APP_COMMIT_SHA=<sha real da PR>
TDA_RELEASE_ID=pr-<numero>-<sha curto>
```

Smoke mínimo:

- `/api/health`;
- `/api/version`;
- `/`;
- `/sessoes`;
- `/lore/yllith`.

`required-ci` só fica verde em PR depois que esse Preview passa. Em push, `preview-deployment=skipped` é o resultado esperado.

## Production v3

Workflow: `.github/workflows/production.yml`.

### Identidade da release

O workflow aceita apenas o SHA que é atualmente o HEAD de `main`. `workflow_dispatch` existe para redeploy controlado do HEAD atual; não serve para publicar commit arbitrário antigo.

Depois, a API do GitHub precisa confirmar:

```text
PR mergeada
base = main
merge_commit_sha = SHA da release
```

Não existe requisito `head=Preview`.

### Baseline real de Production

Antes de decidir trabalho destrutivo, o workflow consulta:

```text
https://dnd.faysk.dev/api/version
```

O `commit` retornado é o baseline canônico. Ele precisa existir no repositório e ser ancestral do novo SHA.

Isso permite calcular:

```text
SHA realmente publicado .. novo main
```

Uma release que falhou antes do promote não faz o pipeline esquecer migrations ainda pendentes.

### Migrations

Migration de Production só é acionada quando existe SQL em:

```text
supabase/migrations/*.sql
```

no intervalo ainda não publicado.

Sem migration pendente:

- Supabase CLI não é instalado;
- `SUPABASE_ACCESS_TOKEN` e `SUPABASE_DB_PASSWORD` não são necessários para aquela release;
- nenhum link/dry-run/apply é executado.

Com migration pendente, o lifecycle continua fail-closed em `tools/ci/apply-production-migrations.sh`:

```text
migration policy
-> link/fetch remoto
-> valida boundary/histórico
-> dry-run
-> apply
-> fetch novamente
-> compara histórico TDA exato
```

Falha em qualquer etapa impede o promote.

### Mídia

Mídia e deploy web possuem ciclos independentes.

O web deploy comum não faz full public audit de todo o R2.

O Production workflow só tenta lifecycle de publicação quando **o merge atual** altera manifest canônico em:

```text
media/manifests/*.json
```

Isso evita que asset histórico não relacionado bloqueie release web futura.

Quando o merge realmente altera manifest, o caminho permanece fail-closed e exige credenciais R2. `tools/ci/publish-production-media.sh` seleciona somente os manifests alterados e chama `tools/media/pipeline.mjs publish`, que valida integridade, publica objeto imutável quando ausente, faz readback e valida entrega pública.

Mudança apenas no tooling de mídia continua coberta pelo CI local, mas não republica automaticamente manifests antigos.

## Staged deploy

O artefato é construído uma vez com Vercel Production config:

```text
APP_ENV=production
APP_COMMIT_SHA=<sha main>
TDA_RELEASE_ID=prod-<sha curto>
```

Depois:

```text
vercel build --prod
vercel deploy --prebuilt --prod --skip-domain
```

O staged deployment ainda não recebe tráfego do domínio oficial.

O smoke verifica `health`, `version` e rotas principais. SHA e release retornados precisam corresponder exatamente ao esperado.

Somente então:

```text
vercel promote <deployment staged>
```

O mesmo artifact testado é o promovido.

## Verificação canônica

Depois do promote, `tools/ci/verify-production-canonical.mjs` consulta o domínio oficial até confirmar convergência de:

- `health.ok=true`;
- `health.environment=production`;
- `health.commit=<SHA esperado>`;
- `version.commit=<SHA esperado>`;
- `version.release=<release esperado>`.

A raiz do site também precisa responder.

## Receipt

Uma release GitHub pequena registra:

- SHA Production anterior;
- SHA novo;
- PR mergeada em `main`;
- release id;
- staged/tested deployment;
- canonical origin;
- se migrations foram executadas;
- se lifecycle de mídia foi executado;
- staged + canonical smoke PASS.

O receipt é histórico útil, não mecanismo de autorização.

## Rollback

Workflow: `.github/workflows/rollback.yml`.

Rollback é o mecanismo normal para falha recuperável depois de Production.

```text
identificar deployment anterior saudável
-> rollback/promote anterior
-> verificar canonical health/version
-> corrigir em nova branch
-> PR -> main
-> novo Production v3
```

Não se tenta criar uma arquitetura que impossibilite todo incidente recuperável. O objetivo é detectar cedo quando barato e recuperar rápido quando algo escapar.

## Secrets mínimos

### Preview

GitHub Environment `preview`:

```text
VERCEL_TOKEN
```

### Production web comum

GitHub Environment `production`:

```text
VERCEL_TOKEN
```

Quando existe migration:

```text
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
```

Quando o merge atual exige publicação canônica de mídia:

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

Credencial condicional não deve ser adicionada apenas para fazer uma release não relacionada passar.

## Evidência do desenho atual

O Production legado `34896656582` instalou/autenticou Supabase mesmo sem migration nova e morreu antes do build ao fazer full public audit de asset antigo com HTTP 403.

O primeiro Production v3 `34899700811` falhou de forma segura no gate de credenciais antes de qualquer mutação porque o desenho inicial confundia manifest histórico no backlog com mídia do merge atual. A PR #345 separou os escopos.

Primeiro aceite main-only completo:

```text
PR:             #345
main SHA:       a8a9253e13c159263fc1f4a4672d8690f4c62e33
CI:             34900494222 success
Production CD:  34900630352 success
Supabase:       skipped
mídia publish:  skipped
stage/smoke:    success
promote:        success
canonical:      success
receipt:        success
```

Aceite após limpeza da antiga branch web:

```text
PR:             #347
main SHA:       a46e8292eaed7e1cff32addd181668d83fd76be4
CI:             34902095910 success
Production CD:  34902180398 success
Supabase:       skipped
mídia publish:  skipped
stage/smoke:    success
promote:        success
canonical:      success
receipt:        success
```
