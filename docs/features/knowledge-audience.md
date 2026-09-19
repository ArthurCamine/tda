# Feature — Conhecimento e audiência

> Status: em desenho
> Owner: narrative-memory/security
> Última revisão: 2026-09-19

## Valor

Modelar corretamente "quem sabe o quê?" sem vazar segredos e sem confundir verdade canônica com crença de personagem/público.

## Fonte histórica revalidada

O legado distinguiu:

- conhecimento do jogador;
- conhecimento do personagem;
- conhecimento público;
- segredo do mestre;
- rumor;
- mentira.

Também previa memórias íntegras, fragmentadas, contestadas, roubadas/restauradas, mentira oficial e verdade descoberta.

Essas ideias são direção de produto, **não schema já aprovado**.

## Problema de modelagem

Uma claim pode ter várias dimensões:

1. é verdadeira no canon?
2. quem acredita nela?
3. quem teve acesso a ela?
4. quando passou a saber?
5. a percepção é rumor/mentira/fragmento?
6. qual evidence sustenta o knowledge state?

Um único campo `visibility` não responde tudo isso.

## Base existente

- `canon_entries` para verdade/memória aprovada;
- `entities` para subjects/objects;
- `profiles` para jogadores;
- visibility em entities/publications/canon;
- review/candidates/evidence.

## Projection técnica de audience já implementada no World

A semântica ampla de knowledge abaixo continua em desenho. Em paralelo, o World Explorer já precisa aplicar a visibility técnica existente **antes** de montar o payload enviado ao browser.

A projection server-side do World usa quatro audiences operacionais:

| Audience | Visibilities entregues |
| --- | --- |
| visitante público | `public_web` |
| jogador autenticado da campanha | `private_players`, `public_campaign`, `public_web` |
| mestre autenticado da campanha | `private_master`, `private_players`, `public_campaign`, `public_web` |
| editor completo autorizado | todas, incluindo `review_only` |

Regras importantes:

- possuir login não basta para receber audience de jogador; a membership da campaign é resolvida server-side;
- capability editorial completa prevalece sobre a projection de jogador, porque o editor precisa revisar todos os estados;
- `review_only` não chega ao jogador nem ao mestre apenas por serem membros da campanha;
- relações `public_campaign`/`public_web` continuam sujeitas ao gate de provenance/review; `private_players` não ganha artificialmente essa exigência;
- o público anônimo continua separado e pode permanecer no dataset demonstrativo enquanto o gate canônico web estiver desativado;
- nenhum desses níveis modela crença/conhecimento dentro da ficção; eles apenas controlam audiência técnica do produto.

Essa matriz existe justamente para evitar o erro de persistir `private_players` corretamente e depois servi-lo apenas como `public_web`, que transformaria uma opção de UI em promessa sem consumidor real.

## Modelo conceitual a decidir

Possível separação:

```text
claim/fact
  ├─ canonical truth state
  └─ knowledge assertions
       ├─ knower: entity/profile/public group
       ├─ belief state
       ├─ learned_at
       ├─ source/evidence
       └─ visibility to product audience
```

Não aprovar essa estrutura como DDL ainda; ela serve para explicitar perguntas que a spec precisa resolver.

## Estados possíveis a avaliar

- knows;
- believes;
- suspects;
- rumor heard;
- false belief;
- forgotten;
- stolen/blocked memory;
- restored;
- contested.

O vocabulário deve ser pequeno, testável e compatível com a narrativa real antes de virar enum.

## Security boundary

É possível existir:

- fato verdadeiro secreto do mestre;
- personagem que sabe esse fato;
- jogador daquele personagem autorizado a vê-lo;
- outros jogadores não autorizados;
- público web sem acesso.

Portanto **audience de UI** e **knowledge dentro da ficção** são camadas diferentes.

## Critérios antes da migration

- definir sujeito do knowledge: profile, entity ou grupo;
- definir se claim aponta para canon entry ou pode existir como crença falsa sem canon correspondente;
- definir temporalidade;
- definir rumor/lie semantics;
- definir audience/security independentemente;
- definir retcon/forgetting;
- definir review/source;
- validar exemplos reais da campanha.

## Critérios de aceite futuro

- responder "quem sabia X na sessão N?";
- mostrar informação diferente para DM/player conforme permissão;
- representar crença falsa sem transformá-la em canon;
- representar segredo revelado depois;
- preservar histórico quando conhecimento muda;
- busca/LLM respeitam audience e knowledge state.

## Não fazer agora

- guardar `knows: [...]` em metadata de entity;
- usar visibility como sinônimo de knowledge;
- enviar todos os facts ao browser e esconder com CSS;
- deixar embedding/LLM consultar segredos fora do scope do usuário.
