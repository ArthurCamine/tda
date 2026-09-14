# ADR-0015 — Entrega simples orientada a recuperação

> Status: accepted
> Owner: operations / architecture
> Última revisão: 2026-09-14
> Fonte de verdade: decisão de arquitetura desta migração; ADR-0012 e runbooks atuais permanecem vigentes até a implementação

## Contexto

O TDA é atualmente um projeto pessoal e pequeno. O custo dominante não é indisponibilidade crítica ou compliance; é o tempo e a carga cognitiva necessários para desenvolver, testar, publicar e entender uma mudança.

A esteira atual prioriza impedir qualquer publicação incorreta. Esse desenho acumulou gates globais, repetição de testes, uma branch permanente de homologação, promoção `Preview -> main`, provenance adicional e acoplamento entre web, banco, mídia e Companion.

Para o risco atual do produto, uma falha recuperável na aplicação pode ser tratada de forma simples: voltar ao deployment anterior, corrigir e publicar novamente. Proteções mais fortes continuam justificadas onde rollback não resolve bem, principalmente credenciais, autorização e migrations.

## Decisão

A próxima versão da entrega será orientada a **simplicidade, feedback rápido e recuperação fácil**.

Princípios:

1. `main` será a única branch longa da entrega web.
2. Preview será um deployment do SHA da PR, não uma branch permanente.
3. GitHub Actions continua como único controlador da entrega; Vercel Git auto-deploy permanece desligado.
4. Production pode falhar de forma recuperável; rollback da aplicação é uma operação normal, não um desastre.
5. CI comum executa apenas validações rápidas e relevantes.
6. Companion, banco e mídia executam gates pesados somente quando seus domínios mudam.
7. Mídia continua publicada no R2; apenas o ciclo de validação/publicação é separado do deploy web comum.
8. Production continua staged antes de receber tráfego enquanto isso permanecer barato e simples.
9. Toda release continua identificável por source SHA e deployment.
10. Nenhum gate bloqueante é adicionado apenas para antecipar escala hipotética.

## Regra de proporcionalidade

Antes de adicionar um gate, responder:

- qual falha real ele evita hoje;
- qual o custo se a falha chegar a Production;
- se rollback resolve;
- se o check é barato;
- se ele é relevante para a mudança atual.

Falha barata, recuperável e não relacionada à mudança não deve bloquear o deploy por padrão.

## Proteções preservadas

A simplificação não remove:

- proteção de credenciais;
- autenticação e autorização da aplicação;
- identificação de SHA em health/version;
- migrations versionadas;
- validação/dry-run de migration quando migration existir;
- staged deployment e smoke de Production;
- rollback explícito da aplicação;
- integridade de mídia quando mídia nova ou alterada for publicada;
- histórico Git/PR para explicar a evolução do projeto.

## Consequências positivas

- caminho comum menor;
- menos jobs irrelevantes por PR;
- Preview isolado por mudança;
- fim da sincronização `main <-> Preview`;
- fim da promoção intermediária `Preview -> main`;
- mídia antiga não bloqueia mudança web sem mídia;
- Companion não participa de mudança web sem Companion;
- banco não participa de release sem mudança de banco;
- rollback passa a ser parte explícita da estratégia de confiabilidade.

## Custos aceitos

- uma regressão simples pode chegar a Production;
- alguns checks pesados passam a ser condicionais, manuais ou agendados;
- a equipe aceita corrigir e publicar novamente quando rollback for suficiente;
- durante a migração haverá coexistência temporária entre fluxo antigo e novo.

Esses custos são proporcionais ao uso atual do TDA.

## Relação com ADR-0012

ADR-0012 continua sendo evidência histórica e contrato da implementação vigente durante a migração.

Esta decisão preserva sua escolha principal — GitHub Actions como único controlador e Vercel Git auto-deploy desligado — mas substitui progressivamente, conforme cada fase for integrada:

- branch permanente `Preview` por Preview de PR;
- provenance `Preview -> main` por fluxo direto de PR para `main`;
- gates globais por gates condicionais ao domínio alterado.

Não reescrever ADR-0012 para fingir que a arquitetura anterior nunca existiu. Quando a migração terminar, ADR-0012 deve ser marcado como superseded por este ADR sem apagar seu conteúdo histórico.

## Adoção

A implementação está dividida em seis fases documentadas no plano operacional de simplificação. A decisão está aceita, mas o runtime continua seguindo os runbooks vigentes até que cada fase correspondente seja integrada e documentada.
