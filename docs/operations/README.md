# Operação — índice

> Status: vigente
> Owner: operations
> Última revisão: 2026-09-14

Este diretório contém os procedimentos operacionais do TDA. O objetivo é permitir que alguém execute, diagnostique e recupere a entrega sem depender de conhecimento informal do histórico.

## Fonte de verdade operacional

Para CI/CD, a leitura deve seguir esta ordem:

1. [CI/CD — operação, promoção e recuperação](ci-cd.md): contrato técnico vigente da esteira;
2. [CI/CD — configuração administrativa](cicd-admin-setup.md): GitHub Environments, secrets e branch protection;
3. [Ambientes e configuração](environments.md): limites entre Development, Preview por PR e Production;
4. [ADR-0015](../adr/0015-recovery-oriented-delivery.md): decisão recovery-oriented que governa a topologia atual;
5. [ADR-0012](../adr/0012-github-actions-controlled-delivery.md): decisão preservada de GitHub Actions como controlador e Vercel Git auto-deploy desligado;
6. [Baseline](cicd-simplification-baseline.md) e [plano de simplificação](cicd-simplification-plan.md): evidência histórica da migração concluída.

Se um documento histórico descreve `Preview` como branch permanente ou promoção `Preview -> main`, ele registra uma etapa anterior da arquitetura. O estado operacional corrente é o dos runbooks vigentes acima.

Para o TDA Companion, [Confiabilidade, manutenção e aceite real](companion-reliability.md) continua sendo o contrato da estabilização física. A [evidência Reliability R2](companion-reliability-r2-evidence.md), a [auditoria pesada do Companion 0.3.3](companion-0.3.3-heavy-audit.md) e o [contrato A-017 de integridade dos modelos ASR](companion-a017-model-integrity.md) complementam o runbook [Companion — operação, instalação e rollback](local-companion.md). CI sintética não substitui aceite físico do produto instalado.

## Como usar a esteira no dia a dia

```text
feature/* | fix/* | refactor/* | ops/*
        |
        v
      PR -> main
        |
        +--> workflow-contract / actionlint
        +--> validate rápido
        +--> DB somente se relevante
        +--> Companion somente se relevante
        +--> mídia local somente se relevante
        +--> Vercel Preview do SHA exato da PR
        +--> smoke
        |
        v
    required-ci
        |
        v
      merge main
        |
        v
 Production CD automático
        |
        +--> SHA atual + PR mergeada em main
        +--> baseline do Production canônico
        +--> migration somente se pendente
        +--> mídia somente se o merge atual exigir publicação
        +--> build
        +--> staged deploy sem tráfego
        +--> smoke
        +--> promote do MESMO artifact
        +--> canonical health/version
        +--> release receipt
        |
        v
 https://dnd.faysk.dev
```

Preview é um **deployment de PR**, não uma branch de integração.

## Regras práticas atuais

1. desenvolver em branch temporária e abrir PR diretamente para `main`;
2. não contornar `required-ci`, os domínios relevantes ou o smoke do Preview;
3. considerar válido apenas o Preview construído do SHA exato da PR;
4. não executar `supabase db push` manual para destravar uma release;
5. migrations pendentes continuam sendo calculadas desde o SHA realmente publicado em Production;
6. uma release web sem migration não instala nem executa Supabase CLI;
7. mídia histórica não relacionada não bloqueia deploy web; publicação R2 só entra quando o merge atual exige esse lifecycle;
8. Production sempre é staged antes de mover tráfego;
9. o mesmo artefato testado no stage é o artefato promovido;
10. rollback de aplicação usa `Production Rollback`; banco não sofre rollback automático;
11. nunca copiar valores de secrets para docs, PRs, issues, logs ou workflow inputs.

## Estado operacional confirmado — 2026-09-14

A topologia main-only foi exercitada de ponta a ponta. Isso continua separado do aceite físico do TDA Companion instalado.

Primeira PR real direta para `main` após o cutover:

```text
PR:             #345
Merge SHA:      a8a9253e13c159263fc1f4a4672d8690f4c62e33
CI push:        34900494222 = success
Production CD:  34900630352 = success
```

Nesse Production:

```text
source/provenance             PASS
baseline/release plan          PASS
Supabase lifecycle             SKIPPED
media publication              SKIPPED
build + stage                  PASS
staged smoke                   PASS
promote mesmo artifact         PASS
canonical health/version       PASS
release receipt                PASS
```

A Fase 6A removeu os triggers da antiga branch `Preview` e o workflow que a recriava. A PR #347 foi mergeada no SHA:

```text
a46e8292eaed7e1cff32addd181668d83fd76be4
```

E foi novamente comprovada por:

```text
CI:             34902095910 = success
Production CD:  34902180398 = success
Supabase:       skipped
R2 publish:     skipped
stage/smoke:    success
promote:        success
canonical:      success
receipt:        success
```

## Runbooks e evidências

- [CI/CD — operação, promoção e recuperação](ci-cd.md)
- [CI/CD — configuração administrativa](cicd-admin-setup.md)
- [Ambientes e configuração](environments.md)
- [CI/CD — baseline da simplificação](cicd-simplification-baseline.md)
- [CI/CD — plano de simplificação](cicd-simplification-plan.md)
- [Companion — confiabilidade, manutenção e aceite real](companion-reliability.md)
- [Companion — evidência Reliability R2](companion-reliability-r2-evidence.md)
- [Companion 0.3.3 — auditoria pesada de confiabilidade, segurança e release](companion-0.3.3-heavy-audit.md)
- [Companion — integridade dos modelos ASR / A-017](companion-a017-model-integrity.md)
- [Companion — operação, instalação e rollback](local-companion.md)
- [Release, deploy e rollback](release-runbook.md)
- [Histórico de deployments](deployments.md)
- [Operação do banco / Supabase](database-runbook.md)
- [R2 e mídia — runbook operacional](r2-media-runbook.md)
- [Checklist de segurança operacional](security-checklist.md)

## Princípios operacionais vigentes

1. merge e deploy são eventos diferentes;
2. Production não é sandbox;
3. secret não entra em Git, log ou browser;
4. toda release conhece seu SHA;
5. migration e app precisam de compatibilidade coordenada;
6. rollback é mecanismo normal de recuperação;
7. GitHub Actions é o controlador de entrega e Vercel Git auto-deploy permanece desligado;
8. `main` é a única branch longa necessária à entrega web;
9. Preview pertence à PR e ao SHA testado;
10. `required-ci` é o contrato estável de merge;
11. domínios pesados só executam quando a mudança realmente os toca;
12. Production aceita somente o HEAD corrente de `main` originado de uma PR mergeada;
13. o domínio canônico só muda depois do smoke do artefato staged;
14. branch protection é governança adicional; provenance em Production continua obrigatório.

## Matriz rápida

| Mudança | Fast CI | DB pesado | Companion | mídia pesada | Production pode mutar domínio externo |
| --- | --- | --- | --- | --- | --- |
| docs | sim | não | não | não | não |
| UI/web | sim | não | não | não | Vercel apenas |
| query/API | sim | se classificada DB | não | não | Vercel; DB só se houver migration |
| migration | sim | sim | não | não | Supabase + Vercel |
| Companion | sim | só se também DB | sim | não | fluxo próprio do Companion |
| manifest canônico de mídia | sim | só se também DB | não | sim | R2 + Vercel |
| tooling de mídia sem manifest | sim | não | não | sim/local | não republica manifests antigos |

## Runbook incompleto é dívida

Toda feature que exige procedimento manual recorrente deve adicionar ou atualizar runbook. Não deixar passos críticos apenas em chat, memória ou histórico de terminal.

Alteração em workflow, credencial, migration boundary, provenance, estratégia staged/promotion ou rollback deve revisar [CI/CD — operação, promoção e recuperação](ci-cd.md) e, quando estrutural, os ADRs relevantes. Configuração de Environments, secrets e branch protection deve seguir [CI/CD — configuração administrativa](cicd-admin-setup.md).
