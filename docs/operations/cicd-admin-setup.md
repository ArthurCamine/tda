# CI/CD — configuração administrativa

> Status: vigente
> Owner: operations / release
> Última revisão: 2026-09-14

Este runbook cobre as superfícies administrativas da esteira atual do TDA: GitHub Environments, secrets, branch protection, Vercel, Supabase e os poucos passos que não vivem no código do repositório.

O comportamento técnico da entrega está em [CI/CD — operação, promoção e recuperação](ci-cd.md). As decisões arquiteturais continuam registradas em [ADR-0012](../adr/0012-github-actions-controlled-delivery.md) e [ADR-0015](../adr/0015-recovery-oriented-delivery.md).

## Regra de segurança

Nunca registrar valores de secrets neste arquivo, em issues, PRs, comentários, workflow inputs ou logs. A documentação guarda apenas nomes, escopo, finalidade, estado observado e procedimento.

## Estado administrativo alvo após a simplificação

### GitHub branches

`main` é a única branch longa necessária para a entrega web.

O contrato administrativo esperado de `main` é:

```text
required status check: required-ci
force push:            bloqueado
deletion:              bloqueado
merge:                 por pull request
```

O contexto `promotion-source` existiu apenas como shim temporário durante o cutover main-only. Depois que `required-ci` foi comprovado em PRs diretas para `main`, ele deve ser removido da branch protection e o workflow `.github/workflows/promotion-policy.yml` deve deixar de existir.

A antiga branch permanente `Preview` não participa mais da entrega. Preview agora é um deployment Vercel criado para cada PR pelo workflow reutilizável `deploy-preview.yml`.

Antes de apagar a branch remota `Preview`, confirmar:

1. `main` contém todo o histórico dela;
2. nenhum workflow depende de `branches: [Preview]`;
3. `preview-branch-guard.yml` já foi removido;
4. a proteção administrativa da branch antiga foi removida.

Na evidência da Fase 6A, `Preview` estava 0 commits à frente e 9 atrás de `main`, portanto sem trabalho exclusivo.

### GitHub Environments

Continuam existindo dois environments de entrega:

```text
preview
production
```

O nome `preview` representa o target Vercel de PR, não uma branch Git.

Secrets esperados:

#### `preview`

```text
VERCEL_TOKEN
```

#### `production`

Sempre necessário:

```text
VERCEL_TOKEN
```

Necessários somente quando uma release contém migrations novas:

```text
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
```

Necessários somente quando o merge atual contém manifest canônico que deve ser publicado pelo lifecycle de mídia do Production:

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

Uma release web comum não deve exigir Supabase nem R2. A ausência de credencial condicional só bloqueia a release quando o próprio plano de release determina que aquele domínio precisa ser executado.

Finalidades:

- `VERCEL_TOKEN`: autentica Vercel CLI para pull/build/deploy/curl/promote/rollback;
- `SUPABASE_ACCESS_TOKEN`: Personal Access Token Supabase `sbp_...` para Supabase CLI/Management API;
- `SUPABASE_DB_PASSWORD`: senha Postgres do projeto canônico usada por migration operations;
- `R2_*`: escrita/readback do objeto canônico alterado, quando uma release de mídia realmente exige publicação.

Não confundir:

```text
SUPABASE_ACCESS_TOKEN  != SUPABASE_SECRET_KEY
SUPABASE_ACCESS_TOKEN  != SUPABASE_SERVICE_ROLE_KEY
```

## Recursos canônicos

Vercel:

```text
Team:    team_9wuTfarCQ3L63xtufPKUDzi0
Project: prj_hDiDvvRiesg3qCDekGWE8JQMkIyH
Domain:  https://dnd.faysk.dev
```

Supabase:

```text
Project ref: dmrqnbdvbkfqzctcerbx
TDA migration boundary: 20260906210333
```

Esses IDs são não secretos e ficam pinados nos workflows para evitar execução contra contexto ambíguo.

## Fluxo administrativo normal

```text
branch temporária
  -> PR para main
  -> workflow-contract / validate
  -> domínios pesados somente se relevantes
  -> Preview Vercel do SHA exato da PR
  -> smoke
  -> required-ci
  -> merge main
  -> Production CD automático
  -> prova de SHA atual + PR mergeada em main
  -> migration somente se pendente
  -> mídia somente se o merge atual exigir publicação
  -> staged deployment
  -> smoke
  -> promote do mesmo artefato
  -> canonical health/version
  -> release receipt
```

Não existe mais uma promoção Git `Preview -> main`.

## Provenance de Production

`production.yml` aceita somente o SHA corrente de `main` e exige que esse SHA seja o `merge_commit_sha` de uma PR realmente mergeada em `main`.

Isso substitui o gate antigo que exigia literalmente `head=Preview`.

O workflow também lê `/api/version` do Production canônico para determinar o baseline realmente publicado. Migrations são avaliadas no intervalo acumulado entre esse baseline e o novo SHA; publicação de mídia é avaliada no merge atual, evitando que um manifest histórico não relacionado bloqueie releases web futuras.

## Branch protection — verificação

Consulta sem valores secretos:

```powershell
gh api repos/Faysk/tda/branches/main --jq '{branch:.name, protected:.protected, checks:.protection.required_status_checks.contexts}'
```

Estado final esperado:

```text
branch=main
protected=true
checks=["required-ci"]
```

Não manter `promotion-source` depois do cutover.

## Como configurar/rotacionar credenciais

### Vercel

Usar token dedicado de CI com acesso ao team/projeto canônicos.

Após criar/rotacionar:

1. atualizar `preview/VERCEL_TOKEN`;
2. validar uma PR e seu Preview;
3. atualizar `production/VERCEL_TOKEN`;
4. validar um Production staged completo.

### Supabase PAT

Criar um Personal Access Token válido (`sbp_...`) e atualizar:

```text
production/SUPABASE_ACCESS_TOKEN
```

`SUPABASE_SECRET_KEY`/`SERVICE_ROLE_KEY` não substituem esse PAT.

### Supabase database password

Atualizar:

```text
production/SUPABASE_DB_PASSWORD
```

Não resetar a senha apenas para descobrir seu valor. Rotação deve considerar clientes externos que possam usar conexão Postgres direta.

### R2

Se o Production for autorizado a publicar manifests canônicos, cadastrar as credenciais R2 no environment `production` com privilégio mínimo sobre o bucket público canônico.

Não adicionar essas credenciais apenas para fazer uma release web comum passar: se `media_publish=false`, elas não são necessárias.

## Rollback

O workflow `Production Rollback` exige target explícito e confirmação `ROLLBACK_TDA`.

Antes do rollback:

1. identificar o deployment explicitamente;
2. validar `/api/version` do candidato;
3. confirmar compatibilidade com schema/migrations atuais;
4. executar o workflow manual;
5. validar `/api/health` e `/api/version` canônicos após mover o tráfego.

Banco não sofre rollback automático.

## Troubleshooting

### `Missing production secret ...`

Verificar primeiro se o release plan realmente marcou o domínio como necessário. Se marcou, cadastrar/rotacionar a credencial correspondente no Environment `production`; não passar secret por workflow input.

### `SUPABASE_ACCESS_TOKEN must be ... sbp_`

O valor não é um PAT Supabase. Usar Personal Access Token da conta, não anon key, service role ou `sb_secret_...`.

### `vercel pull` não encontra Project Settings

Confirmar se o token atual possui acesso ao team/projeto pinados. Não trocar IDs do workflow para contornar problema de token.

### Production falha em provenance

Confirmar que o SHA solicitado é o HEAD corrente de `main` e o resultado de uma PR mergeada em `main`. Não restaurar a antiga exigência `Preview -> main`.

### Migration falha

Não aplicar SQL manualmente só para destravar a esteira. Investigar migration authoring, boundary e drift antes de nova release.

### Mídia pede R2 em release não relacionada

Isso é bug no release planner. Uma release só deve exigir publicação R2 quando o merge atual altera manifest canônico.

## Evidência do cutover main-only

A primeira PR direta para `main` foi a #345.

```text
merge SHA:      a8a9253e13c159263fc1f4a4672d8690f4c62e33
CI push:        34900494222 = success
Production CD:  34900630352 = success
Supabase:       skipped
mídia:          skipped
staged smoke:   success
promote:        success
canonical:      success
receipt:        success
```

A Fase 6A removeu os triggers da branch antiga e o guard que a recriava. O merge #347 publicou o SHA `a46e8292eaed7e1cff32addd181668d83fd76be4`; o Production run `34902180398` passou novamente com Supabase/R2 skipped e staged/promote/canonical verdes.

## Histórico

A branch `Preview`, o contexto `promotion-source` e o guard de restauração foram mecanismos importantes da arquitetura anterior e permanecem documentados no baseline e no histórico de PRs/runs. Eles não fazem parte do contrato operacional atual.

**Estado final desejado:** uma branch longa (`main`), um required check estável (`required-ci`), Preview por PR e Production staged orientado a recuperação.
