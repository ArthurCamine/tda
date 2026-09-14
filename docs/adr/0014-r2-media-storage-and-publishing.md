# ADR-0014 — R2 como boundary de mídia publicada

- Status: accepted
- Data: 2026-09-14
- Owner: architecture / integrations-media / operations

## Decisão

Toda mídia editorial pública consumida em runtime — imagens, backgrounds, portraits, layers de parallax, mapas, social cards, áudio e vídeo — usa o R2 como storage de entrega, com keys imutáveis/content-addressed e verificação de integridade antes da promoção.

O repositório mantém código, markup, manifestos, metadata, tooling e pequenos assets técnicos diretamente acoplados ao documento. Masters e fontes de trabalho permanecem em storage privado apropriado; o bucket público recebe derivados aprovados.

Projetos não implementam upload próprio. Eles declaram mídia e a Media Pipeline compartilhada valida bytes, MIME e SHA-256, publica no R2, faz read-back, verifica a entrega pública e registra receipt.

## Autorização

Credenciais de storage pertencem ao ambiente de automação e nunca ao browser. O fluxo normal de CI/CD usa secrets do ambiente e não depende de endpoint ou autorização por lore.

Quando uma operação manual ou uma futura superfície administrativa precisar de intake server-side, a autorização deve ser genérica para mídia do TDA, não específica de lore. Essa autorização é da aplicação, não acesso direto ao storage: permanece server-only, é rotacionável e cobre somente as operações necessárias de staging, finalização e verificação.

A autorização temporária específica da Yllith é legado de migração e deve ser removida após o cutover. Futuras lores não criam autorizações ou uploaders próprios.

Para upload no browser, a direção futura é autenticação normal do TDA + autorização temporária restrita para staging. Nenhum segredo permanente chega ao cliente.

## Consequências

- uma arquitetura de mídia para lores, sessões, personagens, entidades, grafo, mapas e social;
- rollback natural por keys imutáveis;
- separação entre código, masters privados e derivados públicos;
- nenhum uploader específico por projeto;
- arquivos grandes podem entrar por intake dedicado sem transformar Git em storage de binários.

## Guardrails

- não sobrescrever key content-addressed;
- não promover antes de read-back e verificação pública;
- não colocar master privado no bucket público;
- não usar autorização da aplicação como credencial direta de storage;
- não criar endpoint ou autorização específico por lore.

## Referências

- [Mídia — fluxo único](../integrations/r2/media-pipeline.md)
- [Runbook R2](../operations/r2-media-runbook.md)
- [Arquitetura de entrega das lores](../features/lore-delivery-architecture.md)
