# Mídia — autorização compartilhada de staging

> Status: decisão aprovada
> Owner: integrations/media + operations
> Última revisão: 2026-09-14

## Objetivo

Evitar autorização específica por lore, sessão ou projeto. Toda operação manual/assistida de staging de mídia usa uma única capacidade compartilhada do TDA.

## Contrato

- a autorização pertence à plataforma de mídia, não a uma lore;
- ela protege o serviço compartilhado de intake/staging, não concede acesso direto ao bucket;
- permanece somente no backend;
- pode ser rotacionada sem trocar as credenciais do storage;
- cobre apenas operações aditivas de staging, finalização e verificação;
- não inclui delete, listagem total ou escrita arbitrária por padrão;
- o deploy normal não depende dela: a Media Pipeline continua sendo o caminho canônico de publicação automática;
- uma futura UI usa a autenticação normal do TDA e recebe apenas autorização temporária e restrita para o lote/objeto necessário.

## Naming

A configuração operacional genérica deve usar um nome de plataforma, e não de lore. O identificador recomendado é `TDA_MEDIA_STAGING_AUTH`.

A configuração específica criada durante a migração da Yllith é temporária e deve ser removida após o cutover. Novas lores não criam segredo ou endpoint próprios.

## Relação com storage

A credencial do storage e a autorização da aplicação são coisas diferentes. A primeira fica no ambiente da automação que publica pelo R2; a segunda apenas autoriza uma operação server-side controlada quando isso ainda for necessário.

Ver também [ADR-0014](../../adr/0014-r2-media-storage-and-publishing.md) e [Mídia — fluxo único](media-pipeline.md).
