# Ambientes e configuração

> Status: vigente
> Owner: operations
> Última revisão: 2026-09-14

Este documento define os ambientes do TDA, seus limites de dados/segredos e o relacionamento com a esteira. Procedimentos de entrega estão em [CI/CD — operação, promoção e recuperação](ci-cd.md); configuração administrativa está em [CI/CD — configuração administrativa](cicd-admin-setup.md).

## Ambientes conceituais

Há três ambientes lógicos, mas apenas uma branch longa necessária para a entrega web.

| Ambiente | Fonte | Publicação | Dados |
| --- | --- | --- | --- |
| Development | branches temporárias | nenhuma | local/sintético/configurado deliberadamente |
| Preview / homologação | SHA exato de cada PR | Vercel Preview durante CI | sem migration automática em Production |
| Production | `main` | Vercel staged → smoke → promote | Supabase Production + R2 conforme lifecycle relevante |

A antiga branch Git `Preview` foi aposentada da entrega. O termo Preview agora representa somente o deployment de homologação de uma PR.

## Fluxo atual

```text
branch temporária
      |
      v
    PR -> main
      |
      +--> fast CI
      +--> jobs condicionais
      +--> Preview do SHA da PR
      +--> smoke
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
      +--> staged artifact
      +--> migration se pendente
      +--> mídia somente se o merge atual trouxer manifest canônico
      +--> staged smoke
      +--> promote do mesmo artifact
      +--> canonical health/version
      |
      v
 dnd.faysk.dev
```

## Development

Objetivo: desenvolver e testar sem publicar Production.

Regras:

- `.env.local` e outros `.env*` secretos não são versionados;
- `.env.example` é o único modelo de ambiente que pode ser versionado;
- build/test local deve ser reproduzível a partir do repo;
- integração externa só é usada quando configurada deliberadamente;
- mock/scratch não deve ser confundido com Production;
- branches `feat/*`, `fix/*`, `refactor/*`, `ops/*`, `docs/*` são temporárias e normalmente abrem PR diretamente para `main`.

`TDA_EDIT_UNSAFE=true` continua sendo flag transitória de desenvolvimento quando aplicável. Ela nunca é atalho para guards de Production.

## Preview / homologação

Preview significa **deployment de pull request**, não branch.

Fonte canônica de cada Preview:

```text
pull_request.head.sha
```

Comportamento:

- `ci-gate` precisa passar antes do deploy;
- o workflow recusa SHA diferente do HEAD da PR;
- deployment recebe `APP_ENV=preview`;
- `APP_COMMIT_SHA` recebe o SHA real;
- `TDA_RELEASE_ID=pr-<numero>-<sha curto>`;
- `/api/health` e `/api/version` precisam provar o SHA/release;
- `/`, `/sessoes` e `/lore/yllith` precisam responder;
- nenhuma migration é aplicada no Supabase Production;
- `dnd.faysk.dev` nunca é alterado pelo Preview.

### GitHub Environment `preview`

Secret mínimo:

```text
VERCEL_TOKEN
```

Preview não recebe credencial irrestrita de Production apenas por conveniência.

## Production

Objetivo: servir o TDA aprovado no domínio oficial.

Fonte canônica:

```text
main
```

Estar em `main` isoladamente ainda não basta para publicação automática. O `production.yml` confirma:

1. o SHA pedido é exatamente o HEAD atual de `main`;
2. esse SHA é resultado de uma PR mergeada em `main`;
3. o SHA atualmente informado por `dnd.faysk.dev/api/version` é ancestral da nova release.

Não existe requisito de origem `Preview -> main`.

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

## GitHub Environment `production`

Secret sempre necessário para deploy web:

```text
VERCEL_TOKEN
```

Secrets necessários apenas quando a release contém migration pendente:

```text
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
```

`SUPABASE_ACCESS_TOKEN` precisa ser Personal Access Token da conta Supabase (`sbp_...`). Não confundir com anon key, secret key da aplicação ou service role key.

Credenciais R2 de escrita pertencem ao lifecycle de publicação de mídia e só são exigidas quando o merge atual altera manifest canônico:

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

A ausência delas não deve bloquear deploy web comum sem mídia nova.

Runtime secrets da aplicação continuam configurados na Vercel por ambiente.

## Dados e migrations

CI usa PostgreSQL sintético quando o classificador marca `db=true`.

Production não instala nem autentica Supabase em toda release. O lifecycle remoto só ocorre quando existe migration SQL pendente desde o SHA realmente publicado até o novo `main`.

Isso preserva duas propriedades:

- release web comum não toca banco sem necessidade;
- migration que ficou pendente por causa de uma release anterior falha continua visível até Production alcançar o commit correspondente.

## Mídia

Mídia continua no R2.

Validação local de manifests/tooling ocorre no CI quando o domínio é relevante. Full public audit de todo o bucket não é gate do deploy web comum.

Publicação automática dentro de Production só é considerada para manifests canônicos alterados no merge atual. Um manifest histórico no intervalo acumulado não cria obrigação retroativa de escrita R2 para uma release web posterior.

## Runtime e versões

Node é fixado por `.node-version`; package manager pelo `package.json`. CLIs usadas na entrega são pinadas nos workflows.

Endpoints de identidade:

```text
/api/health
/api/version
```

Variáveis de release:

```text
APP_ENV
APP_COMMIT_SHA
TDA_RELEASE_ID
```

O deployment staged e o canonical precisam retornar identidade coerente antes e depois do promote.

## Recuperação

Uma falha antes do promote não altera o domínio oficial.

Uma falha recuperável depois do promote usa rollback para deployment anterior saudável e uma nova PR para a correção. O objetivo operacional é recuperação simples, não impedir por arquitetura todo incidente possível.

## Estado comprovado

Primeira PR main-only real:

```text
PR #345
fix/production-v3-media-release-scope -> main
merge a8a9253e13c159263fc1f4a4672d8690f4c62e33
```

Primeiro Production v3 completamente verde:

```text
CI run:         34900494222
Production run: 34900630352
Supabase:       skipped
mídia publish:  skipped
stage/smoke:    success
promote:        success
canonical:      success
receipt:        success
```

Prova posterior à remoção das dependências da antiga branch web:

```text
PR #347
main:           a46e8292eaed7e1cff32addd181668d83fd76be4
CI run:         34902095910
Production run: 34902180398
Supabase:       skipped
mídia publish:  skipped
stage/smoke:    success
promote:        success
canonical:      success
receipt:        success
```
