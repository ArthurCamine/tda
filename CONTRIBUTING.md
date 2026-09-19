# Contribuindo com o TDA

Este repositório separa desenvolvimento local de operações autenticadas de infraestrutura. O objetivo é permitir contribuição normal sem distribuir segredos de Production.

## Setup básico

```bash
pnpm install --frozen-lockfile
pnpm check
pnpm build
pnpm dev
```

Copie `.env.example` para `.env.local` apenas quando a tarefa precisar de integrações autenticadas. Não é necessário preencher todos os campos para trabalhar no projeto.

## Contribuição de mídia sem credenciais R2

Para adicionar mídia versionada:

1. coloque a fonte íntegra em `media/sources/`;
2. adicione ou atualize o manifesto correspondente em `media/manifests/`;
3. registre bytes, SHA-256 e MIME exatos conforme o contrato do manifesto;
4. execute:

```bash
pnpm media:validate
pnpm check
```

Esse fluxo não precisa de `R2_ACCESS_KEY_ID` nem `R2_SECRET_ACCESS_KEY`.

Depois do merge, a Production CD detecta manifests de mídia alterados e executa a publicação canônica usando os secrets protegidos do GitHub Environment `production`. A esteira faz upload/reuso, read-back e verificação pública antes de continuar a release.

## Quando `.env.local` com R2 é necessário

Use credenciais R2 locais somente para uma tarefa explicitamente operacional, como desenvolvimento ou diagnóstico do boundary server-side do World/Edit.

Nesse caso:

- use credencial individual de desenvolvimento/preview com escopo mínimo;
- mantenha `.env.local` fora do Git;
- nunca use `NEXT_PUBLIC_` para segredos;
- nunca coloque segredo em commit, PR, issue, comentário, screenshot, log ou chat;
- não compartilhe a credencial de Production apenas para permitir uma contribuição comum.

Variáveis reconhecidas pelo projeto:

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_PUBLIC_BUCKET
R2_PRIVATE_BUCKET
R2_PREVIEW_BUCKET
```

O runtime mantém essas credenciais no servidor. Upload direto pelo browser usa URL assinada de curta duração para uma pending key; o browser não recebe as credenciais R2.

## Publicação

Não publique mídia canônica de Production manualmente a partir da estação de desenvolvimento. Para conteúdo versionado, o caminho esperado é:

```text
branch -> Pull Request -> CI -> merge -> Production CD
       -> publish changed media -> read-back -> public verification -> smoke
```

A Production CD executa `tools/ci/publish-production-media.sh`, que publica somente manifests canônicos alterados no range da release. O bucket público aprovado é `tda-media-public` e a entrega pública usa `https://media.dnd.faysk.dev`.

O runbook completo está em [docs/operations/r2-media-runbook.md](docs/operations/r2-media-runbook.md).
