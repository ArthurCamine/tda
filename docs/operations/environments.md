# Ambientes e configuração

> Status: vigente
> Owner: operations
> Última revisão: 2026-09-13

Este documento define os ambientes do TDA, seus limites de dados/segredos e o relacionamento com a esteira. Procedimentos de entrega estão em [CI/CD — operação, promoção e recuperação](ci-cd.md); configuração administrativa está em [CI/CD — configuração administrativa](cicd-admin-setup.md).

## Ambientes conceituais

Há três ambientes lógicos e dois targets cloud de publicação.

| Ambiente | Fonte | Publicação | Dados |
| --- | --- | --- | --- |
| Development | branches temporárias | nenhuma | local/sintético/configurado deliberadamente |
| Preview / homologação | `Preview` | Vercel Preview automática após CI verde | sem migration automática em Production; R2 Preview |
| Production | `main` proveniente de `Preview -> main` | Vercel staged → gates → promote para `dnd.faysk.dev` | Supabase Production + R2 Production |

Não existe necessidade de um terceiro projeto Vercel apenas para Development.

## Fluxo entre ambientes

```text
branch temporária
    |
    v
PR -> Preview
    |
    +--> CI
    +--> Companion
    |
    v
Preview CD automático
    |
    v
homologação
    |
    v
PR Preview -> main
    |
    +--> promotion-source
    +--> CI
    +--> Companion
    |
    v
Production CD automático
    |
    +--> staged deploy
    +--> migration gates
    +--> smoke
    +--> promote
    |
    v
dnd.faysk.dev
```

`Preview` e `main` são protegidas. Desenvolvimento normal não acontece diretamente nessas branches.

## Development

Objetivo: desenvolver e testar sem publicar.

Regras:

- `.env.local` e outros `.env*` secretos não são versionados;
- `.env.example` é o único modelo de ambiente que pode ser versionado;
- build/test local deve ser reproduzível a partir do repo;
- integração externa só é usada quando configurada deliberadamente;
- mock/scratch não deve ser confundido com Production;
- branches `feat/*`, `fix/*`, `refactor/*`, `ops/*` são temporárias e normalmente seguem para PR em `Preview`.

`TDA_EDIT_UNSAFE=true` continua sendo flag transitória de desenvolvimento quando aplicável. Ela não é mecanismo de CI/CD e nunca deve ser usada como atalho para guards de Production.

## Preview / homologação

Objetivo: validar o candidato real antes de Production.

Fonte canônica:

```text
Preview
```

Comportamento:

- recebe mudanças por PR;
- required checks precisam passar antes do merge;
- CI verde no HEAD de `Preview` dispara Preview CD automaticamente;
- o workflow fixa o SHA exato e recusa SHA stale/arbitrário;
- o deployment recebe `APP_ENV=preview`;
- `APP_COMMIT_SHA` recebe o SHA real;
- `TDA_RELEASE_ID=preview-<12-char-sha>`;
- `/api/health` e `/api/version` precisam provar o SHA/release;
- `/` e `/sessoes` precisam responder;
- nenhuma migration é aplicada no Supabase Production;
- `dnd.faysk.dev` nunca é alterado por Preview.

### GitHub Environment `preview`

Secret mínimo:

```text
VERCEL_TOKEN
```

O secret está configurado e o Preview CD já foi exercitado com deployment e smoke reais.

### Dados de Preview

Preview não recebe credencial irrestrita de Production apenas por conveniência.

- R2 Preview: `tda-media-preview`;
- leitura de dados publicados de Production só deve ocorrer quando deliberadamente autorizada e segura;
- escrita administrativa em Production a partir de Preview não é o padrão;
- migrations são validadas em CI, mas aplicadas somente por Production CD;
- testes de banco do CI usam PostgreSQL scratch/sintético;
- ambiente Supabase dedicado é opcional e só deve ser criado quando um risco específico não puder ser validado razoavelmente por CI/smoke e o custo operacional estiver justificado;
- features candidatas que dependem de novo schema, como World entity media, permanecem com o feature flag desligado até o schema/storage do ambiente alvo e um smoke controlado estarem autorizados e validados.

## Production

Objetivo: servir o TDA aprovado no domínio oficial.

Fonte canônica:

```text
main
```

Porém estar em `main` isoladamente não autoriza publicação. O SHA precisa ser comprovadamente resultado de:

```text
Preview -> main
```

O `production.yml` verifica pela API do GitHub que o SHA atual é o `merge_commit_sha` de uma PR mergeada com `head=Preview` e `base=main`.

A branch `main` também exige `promotion-source` como required check. Assim, governança administrativa e provenance runtime se complementam.

Push direto ou PR de outra branch para `main` não constitui origem válida para Production.

### Recursos canônicos

Supabase:

```text
dmrqnbdvbkfqzctcerbx
```

Vercel team:

```text
team_9wuTfarCQ3L63xtufPKUDzi0
```

Vercel project:

```text
prj_hDiDvvRiesg3qCDekGWE8JQMkIyH
```

Domínio:

```text
https://dnd.faysk.dev
```

R2 Production:

```text
tda-media-public
tda-media-private
```

### GitHub Environment `production`

Secrets mínimos:

```text
VERCEL_TOKEN
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
```

Esses secrets controlam deployment/migration. Runtime secrets da aplicação continuam configurados na Vercel por ambiente.

`SUPABASE_ACCESS_TOKEN` precisa ser Personal Access Token da conta Supabase (`sbp_...`). Não confundir com `SUPABASE_SECRET_KEY`, anon key ou service role key.

## Runtime e versões

Node é fixado pelo `.node-version`; package manager pelo `package.json`. CLIs usadas na entrega são pinadas nos workflows.

Alteração de runtime/CLI deve passar por CI e revisão do runbook quando mudar comportamento de deployment/migration.

## Variáveis de runtime

### Public client config

Somente valores seguros para browser. `NEXT_PUBLIC_*` significa publicação deliberada.

### Server secrets

Supabase secret/service credentials, R2 credentials, OAuth secrets e semelhantes. Nunca entram no bundle do browser.

### Feature/config

Flags e endpoints não secretos, mas ainda específicos de ambiente.

Exemplos atuais:

- `TDA_READ_PUBLISHED_DATA`;
- `TDA_READ_EDIT_DATA`;
- `TDA_EDIT_UNSAFE`;
- `TDA_WORLD_ENTITY_MEDIA_ENABLED` — server-side e `false` por padrão; só habilitar após schema/storage/smoke do ambiente alvo;
- `TDA_AUTH_ORIGIN`;
- `APP_ENV`;
- `APP_COMMIT_SHA`;
- `TDA_RELEASE_ID`.

## Variáveis antigas de bootstrap da esteira

As seguintes flags fizeram parte da montagem inicial, mas não fazem parte da autorização final:

```text
TDA_CICD_BOOTSTRAP_READY
TDA_PREVIEW_CD_ENABLED
TDA_PRODUCTION_CD_ENABLED
TDA_ENFORCE_PROMOTION_SOURCE
```

O contrato final usa Preview automático e provenance verificável para Production. Se alguma dessas variables antigas ainda existir, ela não deve ser tratada como gate de segurança.

## Supabase por ambiente

### Production

Usa o projeto existente. O migration history remoto contém legado anterior ao reboot TDA.

Boundary do TDA:

```text
20260906210333
```

Semântica do Git:

```text
supabase/migrations/ = autorizado para Production
supabase/candidates/ = candidato ainda não autorizado
```

Production cria overlay efêmero, faz `migration fetch`, recusa drift TDA-era, executa dry-run, aplica somente o necessário e busca o history novamente antes de qualquer promote.

Não existe `migration repair` automático.

A primeira Production completa pela esteira final passou preflight de autenticação, overlay, dry-run, apply e verificação exata de history.

### Preview

Não executa `db push` no projeto Production. Testes de banco acontecem em PostgreSQL scratch/sintético no CI e esse é o gate padrão para schema candidato enquanto a feature permanece desligada.

Um projeto/branch Supabase dedicado **não é requisito padrão de homologação**. Ele pode ser criado pontualmente quando houver um risco específico que exija comportamento remoto que não possa ser coberto de forma razoável pelo PostgreSQL efêmero e por um smoke controlado, mediante decisão explícita de custo e teardown. Para o fluxo normal, candidatos permanecem em `supabase/candidates/` até a autorização de promoção; a ativação segue os gates normais do ambiente alvo com feature flag fail-closed.

## R2 por ambiente

- Production public/private separados por audience;
- Preview usa bucket próprio;
- local pode usar filesystem/mock explícito ou integração configurada;
- rollback do app não implica apagar/reverter objetos R2;
- upload browser → `tda-media-preview` exige CORS para a origem exata da homologação e lifecycle curto restrito ao prefixo efêmero `uploads/pending/`; nunca ampliar a regra aos namespaces canônicos `campaigns/`, `lore/` ou `site/`.

## Vercel

A integração Git automática permanece desligada. GitHub Actions é o controlador.

### Preview

```text
vercel pull --environment=preview
vercel build
vercel deploy --prebuilt
```

### Production staged

```text
vercel pull --environment=production
vercel build --prod
vercel deploy --prebuilt --prod --skip-domain
```

O candidate staged só recebe tráfego depois de provenance, migration gates e smoke:

```text
vercel promote <deployment>
```

O mesmo artefato testado é o artefato promovido; não há rebuild entre staged smoke e promote.

## Health e provenance

### Preview

Obrigatório:

```text
health.ok = true
health.environment = preview
health.commit = source sha
version.commit = source sha
version.release = preview-<shortsha>
```

### Production

Obrigatório antes e depois do promote:

```text
health.ok = true
health.environment = production
health.commit = source sha
version.commit = source sha
version.release = prod-<shortsha>
```

Primeira release completa e rastreável da esteira final:

```text
Source SHA: bc131b120fa6d3286da13e6781e0197b5b367ebd
Release:    prod-bc131b120fa6
```

O domínio canônico confirmou esse SHA e release em `/api/health` e `/api/version`.

## Regras de secret

- não versionar `.env.local`, `.env.legado` ou outro arquivo com valores reais;
- não colocar valores em docs/PR/issues;
- não expor em client bundle;
- não imprimir em logs;
- preferir menor escopo possível;
- rotacionar em caso de suspeita;
- validar Preview depois de rotação de Vercel antes de liberar nova Production;
- não sobrescrever secrets atuais automaticamente com valores de arquivo legado.

## Branches e proteção administrativa

Fluxo esperado:

```text
branch temporária -> PR -> Preview -> PR -> main
```

Estado confirmado em 2026-09-11:

### `Preview`

```text
protected=true
PR obrigatório
required status checks
force push blocked
deletion blocked
enforce admins enabled
```

Checks obrigatórios:

```text
validate
transcript-import-postgres
synthetic (ubuntu-latest, .venv/bin/python)
synthetic (windows-latest, .venv/Scripts/python.exe)
```

### `main`

```text
protected=true
PR obrigatório
required status checks
force push blocked
deletion blocked
enforce admins enabled
```

Checks obrigatórios:

```text
validate
transcript-import-postgres
synthetic (ubuntu-latest, .venv/bin/python)
synthetic (windows-latest, .venv/Scripts/python.exe)
promotion-source
```

O provenance gate de Production permanece obrigatório mesmo com branch protection ativa.

## Estado operacional confirmado — 2026-09-11

- GitHub Actions é o único controlador de entrega;
- Vercel Git auto-deploy permanece desligado;
- `Preview` e `main` estão protegidas;
- auto-delete de head branch foi desativado para preservar `Preview`;
- `Preview Branch Guard` existe como fallback;
- Preview CD executa automaticamente e passou deployment/smoke real;
- Production CD passou provenance, credentials, Supabase gates, staged smoke, promote e canonical smoke;
- release receipt `prod-bc131b120fa6` foi criado;
- `dnd.faysk.dev` responde com o SHA/release promovidos;
- runtime error scan pós-release não encontrou erros na janela consultada.

## Checklist de novo ambiente

1. finalidade definida;
2. branch/source definida;
3. data boundary definido;
4. storage boundary definido;
5. secrets mínimos criados;
6. nenhum Production secret desnecessário;
7. runtime vars coerentes;
8. smoke positivo e negativo;
9. observability ativa;
10. rollback/teardown definidos;
11. branch protection/governança definida;
12. documentação atualizada.
