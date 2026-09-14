# Operação — índice

> Status: vigente
> Owner: operations
> Última revisão: 2026-09-13

Este diretório contém os procedimentos que devem ser executáveis por alguém que não estava na cabeça de quem implementou a feature.

## Fonte de verdade operacional

Para CI/CD, a leitura deve seguir esta ordem:

1. [CI/CD — operação, promoção e recuperação](ci-cd.md): contrato técnico completo da esteira;
2. [CI/CD — configuração administrativa](cicd-admin-setup.md): GitHub Environments, secrets, proteção de branches e estado operacional confirmado;
3. [Ambientes e configuração](environments.md): limites entre Development, Preview e Production;
4. [ADR-0012](../adr/0012-github-actions-controlled-delivery.md): decisão arquitetural que torna GitHub Actions o único controlador da entrega.

Para o TDA Companion, [Confiabilidade, manutenção e aceite real](companion-reliability.md) é o contrato da rodada de estabilização iniciada após o teste físico da v0.3.2. A [evidência de Reliability R2](companion-reliability-r2-evidence.md) registra o estado verificável do segundo bloco dessa estabilização. A [auditoria pesada do Companion 0.3.3](companion-0.3.3-heavy-audit.md) registra a fotografia adversarial que originou as remediações posteriores do candidato 0.3.4. Esses documentos complementam o runbook [Companion — operação, instalação e rollback](local-companion.md) e impedem que CI sintética seja confundida com aceite físico do produto instalado.

Se uma seção histórica datada em outro documento descrever um estado anterior do bootstrap, ela deve ser lida como evidência daquele momento. O estado operacional corrente é o registrado nos runbooks acima com a revisão mais recente.

## Como usar a esteira no dia a dia

Fluxo normal:

```text
feature/* | fix/* | refactor/* | ops/*
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
        +--> build imutável
        +--> /api/health
        +--> /api/version
        +--> smoke / e /sessoes
        |
        v
   homologação aprovada
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
        +--> provenance Preview -> main
        +--> staged Vercel --skip-domain
        +--> Supabase overlay/dry-run/apply/verify
        +--> staged smoke
        +--> vercel promote
        +--> canonical smoke
        +--> GitHub Release receipt
        |
        v
 https://dnd.faysk.dev
```

Regras práticas:

1. nunca desenvolver diretamente em `Preview` ou `main`;
2. abrir PR de branch temporária para `Preview`;
3. não contornar CI/Companion nem os smoke gates;
4. considerar homologado somente o SHA de Preview cujo Preview CD terminou verde;
5. promover Production somente por PR `Preview -> main`;
6. usar **merge commit** na promoção `Preview -> main`, pois o Production CD valida o próprio `merge_commit_sha`;
7. não executar `supabase db push` direto do checkout canônico para Production;
8. não publicar diretamente em `dnd.faysk.dev`; Production é staged antes de `vercel promote`;
9. rollback de aplicação usa o workflow `Production Rollback`; banco não sofre rollback automático;
10. nunca copiar valores de secrets para docs, PRs, issues, logs ou inputs de workflow.

## Estado operacional confirmado — 2026-09-11

A esteira web/cloud foi exercitada de ponta a ponta e está operacional. **Isso não equivale ao aceite físico do TDA Companion instalado**, que possui gates adicionais em [companion-reliability.md](companion-reliability.md).

```text
CI / Companion                    PASS
Preview real                      PASS
Preview smoke                     PASS
Preview -> main provenance        PASS
Production credentials            PASS
Supabase authentication           PASS
Migration dry-run/apply/history   PASS
Vercel staged Production          PASS
Staged smoke                      PASS
Vercel promote                    PASS
Canonical smoke                   PASS
Release receipt                   PASS
Runtime error scan pós-release    PASS (sem erros observados na janela consultada)
Branch protection Preview         ENABLED
Branch protection main            ENABLED
Force push/deletion               BLOCKED nas branches canônicas
```

Primeira release completa pela esteira final:

```text
Source SHA: bc131b120fa6d3286da13e6781e0197b5b367ebd
Release:    prod-bc131b120fa6
Production: https://dnd.faysk.dev
```

O runtime canônico confirmou:

```text
/api/health.ok          = true
/api/health.environment = production
/api/health.commit      = bc131b120fa6d3286da13e6781e0197b5b367ebd
/api/version.commit     = bc131b120fa6d3286da13e6781e0197b5b367ebd
/api/version.release    = prod-bc131b120fa6
```

A evidência imutável de cada Production normal passa a ser o GitHub Release receipt `prod-<short-sha>`. `deployments.md` continua como histórico operacional e deve receber entradas para deploys manuais, excepcionais, incidentes ou eventos que precisem de contexto adicional; não é necessário duplicar manualmente cada receipt automático.

## Runbooks

- [CI/CD — operação, promoção e recuperação](ci-cd.md)
- [CI/CD — configuração administrativa](cicd-admin-setup.md)
- [Ambientes e configuração](environments.md)
- [Companion — confiabilidade, manutenção e aceite real](companion-reliability.md)
- [Companion — evidência Reliability R2](companion-reliability-r2-evidence.md)
- [Companion 0.3.3 — auditoria pesada de confiabilidade, segurança e release](companion-0.3.3-heavy-audit.md)
- [Companion — operação, instalação e rollback](local-companion.md)
- [Release, deploy e rollback](release-runbook.md)
- [Histórico de deployments](deployments.md)
- [Operação do banco / Supabase](database-runbook.md)
- [Checklist de segurança operacional](security-checklist.md)
- [Política resumida de publicação](../releases.md)
- [Infraestrutura e estado](../infrastructure.md)

## Princípios operacionais

1. merge e deploy são eventos diferentes;
2. production não é sandbox;
3. secret não entra em Git/log/browser;
4. toda release conhece seu SHA;
5. migration e app precisam de compatibilidade coordenada;
6. rollback é pensado antes da promoção;
7. Preview não usa Production irrestrita;
8. deploy não é forma de testar mudança em loop;
9. estado de fornecedor precisa ser verificado na conta correta;
10. incidentes e desvios viram documentação/ADR quando revelam regra nova;
11. GitHub Actions é o controlador de entrega e Vercel Git auto-deploy permanece desligado;
12. CI verde em `Preview` publica homologação automaticamente;
13. Production só publica SHA comprovadamente originado de PR `Preview -> main`;
14. branch protection é governança adicional e o provenance gate de Production continua obrigatório mesmo com protection ativa.

## Matriz rápida

| Mudança | Precisa CI | Precisa migration | Precisa revisão segurança | Pode exigir deploy |
| --- | --- | --- | --- | --- |
| docs | sim | não | normalmente não | não |
| UI estática | sim | não | se muda exposição | sim |
| query/API | sim | talvez | sim | sim |
| schema | sim | sim | sim | geralmente |
| RLS/RPC/grant | sim | sim | obrigatório | talvez |
| env/secret | validação | não | obrigatório | normalmente |
| DNS/domain | smoke | não | obrigatório | operação separada |

## Runbook incompleto é dívida

Toda feature que exige procedimento manual recorrente deve adicionar/atualizar runbook. Não deixar passos críticos apenas em chat, memória ou histórico de terminal.

Alteração em workflow, credencial, migration boundary, provenance, estratégia staged/promotion ou rollback deve revisar [CI/CD — operação, promoção e recuperação](ci-cd.md) e, quando estrutural, o [ADR-0012](../adr/0012-github-actions-controlled-delivery.md).

Configuração de Environments, secrets e branch protection deve seguir [CI/CD — configuração administrativa](cicd-admin-setup.md). Valores secretos nunca entram na documentação.