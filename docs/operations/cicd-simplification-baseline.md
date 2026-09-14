# CI/CD — baseline da simplificação

> Status: auditoria
> Owner: operations / architecture
> Última revisão: 2026-09-14
> Fonte de verdade: GitHub e Vercel observados no corte abaixo

## Escopo

Este documento é uma fotografia do estado anterior à simplificação. Ele não substitui `ci-cd.md` e não muda comportamento.

Corte técnico:

```text
Preview SHA: 7b7b03ac751d4152b1f98262eb47138f0997c896
main SHA:    08b1705ddcda50ba39f04ab07676aeb96935d9c9
Production source SHA observado: 42b5d50d840f5b0dd7bf5a8b5d475c98673d454c
```

No corte, Preview, main e Production pública estão em três SHAs diferentes. O desenho atual permite isso, mas aumenta a carga para responder qual versão está em cada ambiente.

## Branch protection observada

`Preview` exige:

- `validate`;
- `transcript-import-postgres`;
- `synthetic (ubuntu-latest, .venv/bin/python)`;
- `synthetic (windows-latest, .venv/Scripts/python.exe)`.

`main` exige os quatro checks acima e também `promotion-source`.

## Inventário de workflows

Existem 15 workflows versionados no corte. A coluna Direção descreve a intenção da migração, não o estado vigente.

| Workflow | Papel atual | Direção |
| --- | --- | --- |
| `ci.yml` | CI geral, PostgreSQL, build e E2E | **SIMPLIFY** para CI rápido e seletivo |
| `companion.yml` | testes Linux/Windows e MSI em PRs gerais | **SIMPLIFY** e desacoplar do web |
| `companion-dependency-freshness.yml` | freshness por paths + schedule | **KEEP** especializado; ajustar branches depois |
| `companion-rc.yml` | RC manual do Companion | **KEEP** especializado/manual |
| `companion-promote.yml` | promoção estável do Companion | **KEEP** especializado/manual |
| `preview-branch-guard.yml` | recria `Preview` se deletada | **DELETE** quando `Preview` for aposentada |
| `preview.yml` | deploy após CI da branch `Preview` | **REPLACE** por Preview do SHA da PR |
| `production.yml` | Production staged + banco + mídia + promote | **SIMPLIFY** e tornar gates condicionais |
| `promotion-policy.yml` | exige `Preview -> main` | **DELETE** no fluxo main-only |
| `qwen-runtime.yml` | plano/probe Qwen por paths | **KEEP** especializado |
| `qwen-runtime-package.yml` | pacote Qwen por paths | **KEEP** especializado |
| `whisper-runtime.yml` | build/smoke Whisper por paths | **KEEP** especializado |
| `runtime-rc.yml` | RC manual de runtime | **KEEP** especializado/manual |
| `runtime-promote.yml` | promoção manual de runtime | **KEEP** especializado/manual |
| `rollback.yml` | rollback explícito da aplicação | **KEEP** como mecanismo principal de recuperação |

## Leitura correta da contagem

A meta não é reduzir 15 arquivos para cinco artificialmente. Vários workflows pertencem ao Companion e aos runtimes e já são especializados.

A meta é tornar o **caminho comum do site** aproximadamente:

```text
ci
preview de PR
production
media quando aplicável
rollback
```

Companion e runtimes continuam separados e só participam quando o domínio deles muda.

## Desperdícios principais a remover

1. mesma mudança validada repetidamente ao atravessar `Preview` e `main`;
2. Companion pesado em mudança sem Companion;
3. PostgreSQL e testes de banco em mudança sem banco;
4. verificação global de mídia bloqueando release sem mudança de mídia;
5. branch `Preview` acumulando responsabilidades de integração e candidato;
6. `workflow_run` separando orquestração do código efetivamente testado;
7. `promotion-source` e genealogia `Preview -> main` existindo apenas para sustentar a topologia atual.

## Itens que não são alvo de corte cego

Continuam valiosos:

- GitHub Actions como único controlador de deploy;
- Vercel Git auto-deploy desligado;
- health/version com SHA;
- staged Production antes de tráfego;
- rollback explícito;
- migrations versionadas e protegidas quando existem;
- integridade de mídia quando a mídia muda;
- workflows especializados do Companion/runtime fora do caminho web.

## Baseline para comparação por fase

| Sinal | Antes da migração |
| --- | --- |
| branch longa além de `main` | `Preview` |
| promoção intermediária | `Preview -> main` |
| check específico de origem | `promotion-source` |
| PostgreSQL em PR web comum | sim |
| Companion em PR web comum | sim |
| MSI em PR web comum | sim |
| verificação global de mídia em deploy web | sim |
| rollback de aplicação disponível | sim |
| mídia pública no R2 | sim |

Cada fase deve atualizar seu próprio antes/depois com evidência real, sem inventar ganho antes de medir.