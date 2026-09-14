# CI/CD — plano de simplificação

> Status: planejado
> Owner: operations / architecture
> Última revisão: 2026-09-14
> Fonte de verdade: ADR-0015 e baseline da simplificação; runbooks atuais continuam vigentes até a implementação

## Progresso

| Fase | Estado | Evidência principal |
| --- | --- | --- |
| 1 — inventário e direção | **concluída** | PR #329; merge `fe9145631c21da064e9b9cb5dad0f2680722bed0` |
| 2 — CI rápido | **validada; aguardando merge** | PR #332; CI run `34877237056` |
| 3 — separar domínios pesados | planejada | — |
| 4 — Preview por PR / main-only | planejada | — |
| 5 — Production simples | planejada | — |
| 6 — limpeza e documentação final | planejada | — |

## Objetivo

Simplificar a entrega do TDA para o risco real do projeto: aplicação pessoal/de jogo, operada por uma pessoa com apoio de automação, sem requisito atual de alta disponibilidade ou compliance.

A direção otimiza feedback rápido, entendimento simples, rollback fácil e rastreabilidade suficiente. Proteções fortes ficam concentradas onde uma falha custa mais: credenciais, autorização e migrations.

## Estado-alvo

```text
feature/fix branch
       |
       v
      PR
       |
       +--> CI rápido
       |     actionlint
       |     typecheck
       |     lint
       |     unit
       |     build
       |
       +--> jobs condicionais
       |     DB se DB/data layer mudar
       |     Companion se Companion mudar
       |     mídia se mídia/tooling mudar
       |
       +--> Preview do SHA da PR
               |
               +--> health/version
               +--> smoke pequeno
       |
       v
   merge em main
       |
       v
 Production staged
       |
       +--> migrations se aplicável
       +--> mídia se aplicável
       +--> smoke
       +--> promote
       +--> canonical health/version
       +--> registro simples da release

falhou depois da publicação?
       |
       v
rollback -> corrigir -> publicar novamente
```

## Princípios

1. `main` será a única branch longa da entrega web.
2. Preview será um deployment de PR, não uma branch permanente.
3. GitHub Actions continua como único controlador; Vercel Git auto-deploy permanece desligado.
4. Production continua staged enquanto isso for simples e barato.
5. Mídia continua no R2; apenas o ciclo de validação/publicação é desacoplado do deploy web comum.
6. Companion e runtimes não participam do caminho web sem mudança no domínio deles.
7. Gates pesados devem ser condicionais ao risco real da mudança.
8. Falha recuperável em Production é aceitável quando rollback resolve rapidamente.

## Fase 1 — inventário e direção

**Estado: concluída em 2026-09-14.**

Entregas:

- baseline com SHAs e protections;
- inventário de workflows;
- classificação KEEP / SIMPLIFY / REPLACE / DELETE;
- estado-alvo;
- ADR-0015;
- plano das seis fases.

Evidência:

```text
PR:        #329
Head:      931e5e37e6fe7f654fb0c44be2f950008761ebc2
Merge:     fe9145631c21da064e9b9cb5dad0f2680722bed0
Base:      Preview
Runtime:   sem alteração funcional
```

Definition of Done atingida:

- nenhuma mudança de runtime;
- documentação distingue estado vigente de estado planejado;
- baseline possui data e SHA;
- branch de trabalho era descartável sem impacto operacional.

## Fase 2 — CI rápido

**Estado: validada na PR #332; conclusão formal no merge.**

Objetivo: criar o núcleo mínimo de validação web para PR, sem ainda desacoplar os domínios pesados que pertencem à Fase 3.

### Baseline real antes da mudança

A PR #329, que alterava somente documentação, forneceu uma amostra real do custo anterior:

```text
CI run:                  34876284417
CI início:               2026-09-14T17:41:33Z
CI fim:                  2026-09-14T17:46:43Z
validate:                ~5m05s
PostgreSQL job:          ~47s
Playwright install:      ~25s
E2E:                     ~3m50s
processing:              ~7s
Companion run:           34876284413
Companion:               ~4m05s
MSI para PR docs-only:   sim
```

Essa medição não é benchmark universal; é uma execução real do estado anterior usada para comparar a própria PR da Fase 2.

### Resultado real da primeira execução da Fase 2

Na PR #332, head `bdea998c4b1806b14fc7190df018948ecc51ab54`:

```text
CI run:                    34877237056
workflow-contract:         ~13s total; actionlint em ~1s após pull da imagem
validate:                  ~37s
required-ci:               ~2s
transcript-import-postgres ~51s
Chromium no validate:      não
E2E completo no validate:  não
processing no validate:    não
Resultado CI:              success
```

Comparação do `validate` observado:

```text
antes: ~305s
Fase 2: ~37s
redução: ~268s / ~88%
```

O ganho não depende de cache especial nem de pular `pnpm check`/build: ambos continuaram verdes. O que saiu foi a bateria pesada que não precisa bloquear toda alteração.

### Mudança da Fase 2

`workflow-contract` executa `actionlint` em `.github/workflows`. Nesta primeira adoção, shellcheck e pyflakes ficam desligados para a introdução do contrato YAML/expressions não virar uma rodada paralela de lint de todos os scripts inline legados.

`validate` permanece com migration safety policy, o teste curto de SVG, `pnpm check` e `pnpm build`. Saem do caminho comum a instalação do Chromium, `pnpm test:e2e` e `pnpm test:processing`. Essas suítes continuam disponíveis como scripts e serão reposicionadas por relevância/smoke nas fases seguintes.

`required-ci` é um agregador de nome estável e só passa quando `workflow-contract` e `validate` passam. Ele prepara a branch protection para a Fase 3, quando jobs especializados poderão ser pulados legitimamente sem deixar required checks pendentes.

### Dívida explicitamente preservada para a Fase 3

`transcript-import-postgres` continua rodando nesta fase porque ainda é required check na proteção atual. O Companion também continua intocado e ainda pode construir MSI em uma PR sem mudança de Companion.

Isso é temporário e intencional: a Fase 2 prova primeiro o contrato rápido; a Fase 3 troca a proteção e torna os domínios pesados condicionais sem misturar riscos.

Definition of Done da implementação:

- `validate` comum não instala Chromium nem executa a suíte E2E/processing completa: **atingido**;
- workflow inválido é detectado por `actionlint` antes do merge: **atingido**;
- `required-ci` existe e depende de `workflow-contract` + `validate`: **atingido**;
- tempo/etapas antes e depois registrados: **atingido**;
- PostgreSQL e Companion permanecem explicitamente como dívida temporária: **atingido**;
- integração em `Preview` sem contornar branch protection: **pendente somente do merge da PR #332**.

## Fase 3 — separar domínios pesados

Objetivo: tirar mídia, banco e Companion do caminho comum quando não foram alterados.

Direção:

- Companion por paths relevantes;
- DB/integration tests por paths relevantes;
- media pipeline própria, mantendo R2;
- full media audit manual/agendado;
- cada domínio falha fechado quando ele realmente mudou;
- atualizar branch protection para depender do check agregador estável, evitando required checks presos por jobs legitimamente pulados.

Definition of Done:

- mudança CSS/UI/docs não constrói MSI;
- mudança sem DB não sobe PostgreSQL nem tenta migration;
- mudança sem mídia não verifica globalmente o R2;
- mudança de mídia continua validando hash, MIME, bytes e publicação do que mudou;
- `required-ci` é o contrato estável de merge e jobs condicionais podem ser skipped sem deixar a PR pendente.

## Fase 4 — Preview por PR e retirada da branch `Preview`

Objetivo: separar o conceito de Preview do conceito de branch.

Direção:

- cada PR recebe deployment Preview do SHA daquela PR;
- smoke pequeno confirma SHA e superfícies básicas;
- PR normal passa a ter `main` como base;
- remover `workflow_run` da entrega web;
- remover `promotion-policy.yml`;
- remover `preview-branch-guard.yml`;
- aposentar `Preview` somente depois de provar o fluxo novo.

Definition of Done:

- Preview de uma PR não depende do HEAD mutável de outra branch;
- não existe promoção `Preview -> main`;
- não existe necessidade de sincronizar `main -> Preview`;
- branch protection da `main` reflete apenas checks do fluxo novo.

## Fase 5 — Production simples e recuperável

Objetivo: reduzir `production.yml` ao necessário para publicar com segurança proporcional ao projeto.

Direção:

- build Production;
- staged deploy;
- smoke básico;
- migrations apenas quando houver migrations relevantes;
- mídia apenas quando houver mudança relevante;
- promote do mesmo deployment testado;
- health/version canônico;
- registro simples do SHA/deployment;
- rollback permanece caminho oficial de recuperação.

Definition of Done:

- release web sem DB/mídia não executa a bateria desses domínios;
- deploy ruim pode ser revertido sem reconstrução;
- workflow fica legível como orquestração, com lógica longa movida para scripts quando necessário.

## Fase 6 — limpeza e documentação final

Objetivo: remover o legado depois que o fluxo novo estiver provado.

Direção:

- apagar workflows/gates/branches obsoletos;
- retirar referências à topologia antiga dos runbooks atuais;
- atualizar branch protections;
- revisar configurações não utilizadas;
- consolidar operação cotidiana e rollback;
- preservar ADRs antigos como histórico.

Definition of Done:

- `docs/operations/ci-cd.md` descreve exatamente o runtime vigente;
- não existem triggers fantasma da topologia antiga;
- a documentação permite entender o fluxo comum sem reconstruir a história por logs;
- histórico de decisões continua disponível.

## Regra documental por fase

Toda fase só termina quando quatro itens existem juntos:

```text
implementação
+ validação
+ documentação vigente
+ registro antes/depois
```

Usar medições simples, por exemplo:

| Sinal | Antes | Depois |
| --- | --- | --- |
| duração do `validate` web comum | ~5m05s na PR #329 | ~37s na primeira execução da PR #332 |
| Chromium/E2E em `validate` comum | sim | não |
| PostgreSQL em mudança web comum | sim | alvo F3: não |
| MSI em mudança web comum | sim | alvo F3: não |
| full media audit sem mudança de mídia | sim | alvo F3: não |
| branch longa além de `main` | `Preview` | alvo F4: nenhuma |
| promoção intermediária | `Preview -> main` | alvo F4: nenhuma |

Não criar dashboard novo apenas para acompanhar a migração.

## Estratégia de transição

Construir o caminho novo antes de retirar o velho:

```text
estado atual
  -> CI novo comprovado
  -> domínios pesados desacoplados
  -> Preview por PR comprovado
  -> main-only
  -> Production simplificada
  -> remoção do legado
```

Cada fase deve ser reversível pelo Git. Branch, protection ou workflow antigo só é aposentado depois de confirmar que a alternativa funciona.

## Itens adiados deliberadamente

Não implementar agora apenas por possibilidade futura:

- release lock sofisticado da aplicação web;
- tree-SHA attestations adicionais;
- DORA dashboard;
- auto-sync `main -> Preview`;
- ledger de release complexo;
- receipts adicionais além do necessário para identificar SHA/deployment;
- gates globais sem relação com a classe da mudança.

Reavaliar quando número de contribuidores, criticidade, usuários ou dados justificar o custo.