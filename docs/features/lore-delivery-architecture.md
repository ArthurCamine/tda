# Arquitetura de entrega das lores

> Status: decisão aprovada; implementação parcial
> Owner: narrative-memory / frontend / produto
> Última revisão: 2026-09-13

## Objetivo

Padronizar como novas páginas em `/lore/<slug>` são publicadas sem misturar três decisões diferentes: forma de entrega técnica, presença no catálogo `/lore` e vínculo narrativo com campanha/universo.

A URL de uma lore não determina automaticamente se ela pertence à campanha principal. Publicar também não significa listar ou indexar.

## Dimensões independentes

Cada lore deve declarar separadamente:

- `delivery`: como a experiência é servida (`app` ou `standalone`);
- `listed`: se aparece no catálogo `/lore`;
- `campaign`/`universe`: vínculo narrativo confirmado, quando existir;
- `indexable`: se mecanismos de busca podem indexá-la.

Não criar campanha, entity ou relação fictícia apenas para hospedar uma página.

## Dois modos de entrega

### `app` — lore integrada

Usar quando a lore faz parte da aplicação TDA e se beneficia de Next/React, dados estruturados, componentes e integração direta com o produto.

Estrutura típica:

```text
src/app/lore/<slug>/
public/lore/<slug>/   # mídia quando necessário
```

Pipipi permanece neste modelo. `src/app/lore/pipipi` é a página; `public/lore/pipipi` contém mídia consumida por ela. Não é duplicação da página.

### `standalone` — microsite editorial

Usar quando a experiência nasce como HTML/CSS/JS autocontido, com identidade visual e comportamento próprios, sem depender do shell do TDA.

Para novas standalone, preferir:

```text
public/
  lore/
    <slug>/
      index.html
      styles.css
      script.js
      reading.css        # quando houver modo Leitura
      reading-mode.js    # quando houver modo Leitura
      favicon.svg        # ou outro ícone próprio
      assets/
```

A URL pública continua `/lore/<slug>`. Quando necessário, usar rewrite de `/lore/<slug>` para `/lore/<slug>/index.html` sem expor essa diferença ao visitante.

Mídia pesada pode ser entregue pelo R2 público com keys imutáveis/content-addressed. Masters permanecem separados dos derivados públicos, seguindo [Do ZIP à produção](../operations/zip-to-production.md).

## Situação atual

| Lore | Delivery | Listada | Campanha principal | Indexação desejada agora |
| --- | --- | --- | --- | --- |
| Pipipi | `app` | Sim | Sim, conforme o projeto existente | Preservar política pública atual |
| D | `standalone` estática | Não | Não | Não indexar |
| Seika | Route Handler standalone legado | Não | Não | Não indexar; alinhar runtime em entrega própria se necessário |
| Yllith | `standalone` estática planejada | Não | Não | Não indexar |

D e Seika chegaram à produção por estratégias técnicas diferentes. Essa diferença é histórica, não editorial.

- D, em `public/lore/d`, é o modelo mais próximo do padrão novo.
- Seika, em `src/app/lore/seika/route.ts` e rotas auxiliares, continua válida, mas é exceção legada e não deve ser copiada para novas lores.
- Yllith deve inaugurar o padrão standalone estático novo.

Não migrar Seika apenas por simetria de diretório. Uma migração futura precisa ser uma entrega própria, preservando URL, composição, reading mode, favicon, mídia, comportamento e fidelidade visual.

## Publicação, listagem, vínculo e indexação

Essas decisões não se inferem umas das outras:

- **publicada**: pode ser aberta por URL;
- **listada**: aparece no catálogo `/lore`;
- **vinculada**: pertence a campanha/universo confirmado;
- **indexável**: pode entrar em mecanismos de busca.

D e Seika ficam, no estado atual, públicas por URL, não listadas, sem vínculo com a campanha principal e não indexáveis. Yllith permanece planejada: quando for publicada, seguirá o mesmo estado editorial de não listada, sem vínculo com a campanha principal e não indexável, salvo nova decisão explícita. `noindex` não é controle de acesso; quem souber a URL de uma lore publicada ainda pode abrir a página.

## Contrato de produção para standalone

Além da identidade específica de cada personagem, novas standalone devem procurar manter:

- canonical próprio em `/lore/<slug>`;
- `title`, `description`, `og:*` e Twitter card próprios;
- favicon/ícone próprio quando houver identidade adequada, declarado no `<head>` sem depender de JavaScript;
- imagem social dedicada/derivada, sem apontar para diretório de masters;
- modo Cinemático como experiência principal quando esse for o conceito aprovado;
- modo Leitura quando a experiência cinematográfica resumir, fragmentar ou tornar menos confortável o acesso ao texto completo;
- uma fonte narrativa oficial única para evitar divergência entre Cinemático e Leitura;
- navegação por capítulos coerente entre os modos quando aplicável;
- `prefers-reduced-motion` e alternativa legível à animação;
- mobile tratado como composição própria, não desktop comprimido;
- camadas de parallax preservadas separadamente quando a direção de arte depender delas;
- nenhum vínculo automático com catálogo, campanha, grafo ou entidades.

O comportamento Cinemático/Leitura pode ser consistente entre lores sem compartilhar a mesma estética. O controle pertence visualmente à identidade de cada personagem.

## Registro central leve

A arquitetura prevê um registro versionado e leve para evitar que o estado editorial fique espalhado por `page.tsx`, rewrites e diretórios. Isso não é banco, CMS nem sistema multi-jogo completo.

Campos mínimos esperados:

```ts
{
  slug: "yllith",
  delivery: "standalone",
  listed: false,
  campaign: null,
  universe: null,
  indexable: false,
  title: "Yllith — Nascida para conquistar"
}
```

Esse registro responde “como esta lore é entregue e qual é seu estado editorial?”. Sua implementação no código é uma tarefa separada desta decisão documental.

## Futuro multi-jogo

Suporte a múltiplos jogos, campanhas e universos fica fora do escopo atual. A estrutura acima permite publicar histórias paralelas hoje sem inventar vínculo com a campanha principal e sem exigir migração de banco ou CMS genérico.

Quando o TDA evoluir para multi-jogo/multiuniverso, catálogo e registro podem ganhar agrupamentos explícitos mantendo, quando desejável, as URLs já publicadas.
