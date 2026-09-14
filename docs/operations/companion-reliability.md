# TDA Companion — confiabilidade, manutenção e aceite real

> Status: R1/R2 implementados; R3 C-12/C-13/C-14 implementados em candidato; stable bloqueada até aceite físico do artefato exato
> Owner: local-companion / processing / operations
> Última revisão: 2026-09-13
> Fonte de verdade: este documento + ADR-0013 + código/receipts do candidato exato

## Objetivo

Definir a correção estrutural dos problemas encontrados no teste físico do TDA Companion 0.3.2. O objetivo não é consertar cada botão como bug isolado, e sim tornar o produto Windows previsível em lifecycle, rede, manutenção, release e processamento ASR.

A implementação é dividida em R1–R4. Integração em `Preview`, merge em `main` ou publicação de uma release não significam aceite físico. **Stable só pode apontar para o mesmo artefato/hash que passou a jornada instalada e o gate ASR aplicável.**

### Estado de implementação em 2026-09-13

- R1 e R2 formam a base atual de confiabilidade do candidato: recovery/identidade do Agent, saída programática, boundary Craig, rede tipada, manifest versionado, manutenção observável, rollback MSI, WebView2 e diagnóstico por capability.
- C-12 está implementado com harness da jornada instalada e receipt sanitizado ligado ao source SHA/MSI. O `pass=true` real continua pendente até execução no Windows físico.
- C-13 está implementado: push em `main` não publica mais stable automaticamente; RC e promoção são workflows manuais separados; a promoção exige receipt físico e transforma o mesmo objeto de release/mesmos assets em stable, sem rebuild/reupload.
- C-14 está implementado no candidato: MSI, Whisper e partes Qwen usam BITS como transporte preferido no Windows, com fallback HTTP verificado; manifest/tag/tamanho/SHA-256 continuam sendo autoridade do Companion. Apenas `DOWNLOAD_CONTINUES_IN_BACKGROUND` preserva estado parcial; falhas terminais limpam o `.partial`.
- O aceite instalado agora exige também a observação `background_download_resume`: interromper uma transferência grande real, confirmar continuidade pelo Windows e concluir a mesma transferência após reconexão sem erro técnico cru.
- R4 não foi iniciado por este marco. C-16 continua exigindo ADR antes de qualquer troca estrutural para `qwen-asr`.

## Contexto observado

O teste físico da 0.3.2 mostrou uma interface visualmente utilizável, mas a jornada operacional falhou em vários pontos:

- `WinError 10061` após o Agent deixar de responder em `127.0.0.1:8765`;
- logs com `Agent shutdown requested` e `Local API stopped` enquanto a UI continuava aberta;
- `WinError 11001 getaddrinfo failed` em operações externas;
- ZIP Craig aceito, faixas/speakers exibidos e depois reportado como ZIP inválido porque a consulta posterior ao Agent falhou;
- update, fechamento e desinstalação sem confirmação confiável de conclusão;
- descoberta de release sujeita a cache/revalidation e portanto capaz de apontar temporariamente para versão anterior;
- diagnóstico reportando WebView2 ausente enquanto a própria UI WebView2 estava ativa;
- CI cobrindo peças do MSI/lifecycle, mas não a jornada completa iniciada pelos botões do aplicativo instalado;
- ausência de benchmark físico suficiente para declarar qualidade de overlap/timestamps como aprovada.

A direção vigente continua válida: Web e cloud não dependem do computador pessoal para disponibilidade; processamento pesado permanece local; Agent e Desktop têm lifecycles separados; MSI é a autoridade da instalação; Craig multitrack preserva speaker por faixa.

## Princípios

1. **Falha de uma camada não vira erro de outra.** ZIP aceito continua aceito se o Agent cair depois.
2. **Estado explícito substitui exceção como UX.** `starting`, `ready`, `reconnecting`, `stopped_by_user`, `unavailable`, `incompatible` e `port_conflict` são estados de produto.
3. **Loopback é verificado antes de autenticar.** Nenhum Bearer token é enviado a listener não identificado na porta 8765.
4. **Manutenção é transação observável.** Update/uninstall precisam de operação, etapas, receipt e log.
5. **Idempotência onde faz sentido.** Parar Agent já parado não é falha; check repetido não deve criar ações duplicadas.
6. **Erro técnico cru não é mensagem principal.** UI recebe código/causa/ação; detalhes ficam em logs e export.
7. **Manifest seleciona a versão e o download fica preso ao asset imutável dessa versão.**
8. **Stable representa evidência física, não apenas CI sintética.**
9. **Timestamp impreciso deve se declarar impreciso.** Nunca converter uma janela ampla em falsa precisão.

## Matriz canônica

| ID | Problema | Decisão | Prioridade | Fase |
| --- | --- | --- | --- | --- |
| C-01 | Agent morto / `10061` | `AgentConnection` único, recovery serializado, retry único e backoff | P0 | R1 |
| C-02 | hide bloqueia saída de update/uninstall | saída programática independente do gesto de fechar | P0 | R1 |
| C-03 | Craig válido reportado inválido | separar ingest, persistência da seleção e descoberta de perfis | P0 | R1 |
| C-04 | DNS/proxy/TLS sem classificação | `NetworkClient` tipado e diagnóstico em camadas | P0 | R2 |
| C-05 | latest/stable stale | manifest sem stale + asset versionado imutável | P0 | R2 |
| C-06 | update/uninstall sem estado confiável | journal/receipt de manutenção + log MSI + parent timeout fatal | P0 | R2 |
| C-07 | rollback frágil do MajorUpgrade | scheduling seguro e prova de rollback | P0 | R2 |
| C-08 | WebView2 falso negativo | detecção oficial Microsoft | P0 | R2 |
| C-09 | diagnóstico não representa bloqueio real | diagnóstico por capability/severidade | P0 | R2 |
| C-10 | polling/toast storm | circuit breaker e notificação só em transição relevante | P0 | R1 |
| C-11 | porta 8765/Agent antigo aceito por HTTP 200 | handshake forte e conflito explícito | P0 | R1 |
| C-12 | CI passa, jornada instalada falha | E2E do produto instalado | P1 | R3 |
| C-13 | push em main vira stable cedo demais | RC → aceite físico → promoção do mesmo hash | P1 | R3 |
| C-14 | downloads multi-GB frágeis | DownloadManager; BITS para assets grandes no Windows | P1 | R3 |
| C-15 | sync/overlap Craig sem evidência física | benchmark de timeline/overlap mantendo multitrack | P1 | R4 |
| C-16 | Qwen custom duplica upstream | avaliar adapter sobre `qwen-asr` pinado; exige ADR | P1 | R4 |
| C-17 | fallback Qwen com falsa precisão | subchunk/retry + qualidade temporal explícita | P1 | R4 |
| C-18 | qualidade ASR não medida no fluxo real | corpus Craig anotado + métricas de texto/tempo/overlap | P1 | R4 |

## R1 — lifecycle, Agent e boundary de UX

> Implementado e incorporado ao candidato empilhado de confiabilidade. Aceite físico permanece obrigatório no artefato final.

### C-01 — conexão e recuperação do Agent

Toda chamada Desktop→Agent deve passar por uma única camada. Views e polling não implementam recovery próprio.

Fluxo:

```text
request
  -> probe público do Agent
  -> identidade/API válidas?
      -> sim: chamada autenticada
      -> não e porta livre/Agent ausente: tentativa única de spawn
            -> probe verificado
            -> retry único
      -> listener estranho/incompatível: bloquear
  -> falha repetida: unavailable + backoff
```

Backoff inicial: `3 s -> 5 s -> 10 s -> 30 s`. Concorrência de polling deve compartilhar um lock de recovery para impedir spawn storm.

`stopped_by_user` desabilita auto-recovery até ação deliberada de iniciar/reiniciar ou novo bootstrap. Shutdown quando já está parado é idempotente.

### C-11 — handshake forte e porta 8765

O `/api/v1/health` público deve fornecer identidade mínima verificável:

```json
{
  "product_id": "tda-companion",
  "api_version": "1",
  "service_version": "x.y.z",
  "pid": 1234,
  "port": 8765,
  "lifecycle": "ready"
}
```

O Desktop deve validar isso **antes** de enviar o token de pareamento. HTTP 200 sozinho nunca prova que o listener é o TDA. Listener sem identidade vira `port_conflict`; API incompatível vira `incompatible`; mesma API com versão diferente pode ser lida para diagnóstico, mas mutações normais ficam bloqueadas até reconciliação.

### C-02 — fechar, ocultar e sair

Existem dois eventos diferentes:

- **gesto do usuário no X**: respeita `close_behavior`; pode ocultar se tray existir;
- **saída programática**: update, uninstall ou “Sair da interface”; não pode ser cancelada pela preferência de ocultar.

O tray não deve oferecer “Encerrar Agent” como ação casual. Reiniciar Agent continua explícito; sair da interface encerra somente o Desktop.

### C-03 — boundary do Craig

A jornada é composta por etapas independentes:

```text
selecionar arquivo
  -> validar/ingerir Craig
  -> persistir source_id/metadata local
  -> renderizar sessão aceita
  -> descobrir capabilities/perfis do Agent
  -> preparar runtime/modelo
  -> criar job
```

Se a quarta etapa falhar, as três anteriores permanecem válidas. A UI deve dizer “sessão validada; Agent indisponível para verificar perfis”, nunca “ZIP inválido”. Reconexão deve refazer apenas a descoberta de perfis, sem obrigar o usuário a escolher o ZIP novamente.

### C-10 — polling e comunicação de falha

Snapshot/logs/perfis em background não devem produzir toast a cada ciclo. Notificações ocorrem em transições de família de estado, por exemplo:

```text
ready -> recovering      : uma notificação
recovering -> ready      : “Agent recuperado” uma vez
ready -> port_conflict   : blocker explícito
```

Background deve renderizar estado degradado inline. Ação manual pode produzir feedback imediato.

### Aceite R1

R1 só fica pronta para `Preview` quando:

- matar o Agent com a UI aberta resulta em recovery único ou estado `unavailable`, sem storm;
- porta 8765 ocupada por processo estranho não recebe Bearer token;
- Agent incompatível/versão diferente é distinguido de “offline”;
- X com preferência `hide` oculta; saída programática realmente fecha;
- tray “Sair da interface” fecha UI sem matar o Agent;
- Craig já validado continua selecionado durante falha/recovery do Agent;
- logs/perfis em background degradam sem apagar o contexto da sessão;
- testes Linux/Windows, bundle e MSI smoke permanecem verdes.

## R2 — rede, update, uninstall e diagnóstico

### C-04 — NetworkClient

Separar dois transports:

- **loopback**: `127.0.0.1`, proxy explicitamente desabilitado;
- **Internet**: respeita a configuração do usuário e classifica falhas.

Códigos mínimos:

```text
OFFLINE
DNS_FAILED
PROXY_FAILED
CONNECT_TIMEOUT
TLS_FAILED
HTTP_ERROR
MANIFEST_INVALID
HASH_MISMATCH
```

Diagnóstico externo deve testar DNS, conexão HTTPS, manifest e asset separadamente. `URLError`/WinError cru pode aparecer no log técnico, não como mensagem principal.

### C-05 — stable/latest sem stale

Endpoint usado por updater não pode aceitar uma janela em que uma versão promovida ainda retorna a anterior. O manifest stable deve ser obtido sem cache stale e retornar versão/tag/tamanho/SHA do asset escolhido.

A aplicação deve baixar um endereço versionado preso àquele manifest. Não é permitido verificar `N` e depois baixar um endpoint “latest” que já possa resolver para `N+1`.

### C-06 — manutenção observável

Update/uninstall recebem `operation_id` e journal persistido em `Cache/maintenance`, com estados como:

```text
accepted
waiting_for_ui_exit
stopping_agent
verifying_asset
running_msi
verifying_install
restarting_agent
completed
failed
```

O helper deve considerar falha em encerrar o processo pai como **terminal**, não prosseguir silenciosamente depois de timeout. `msiexec` deve gerar log verbose com path conhecido e receipt sanitizado deve registrar exit code, versão/hash e estágio de falha.

Job ativo continua bloqueando update que exigiria encerrar o Agent.

### C-07 — MajorUpgrade e rollback

O MSI deve preservar MajorUpgrade/UpgradeCode estável, mas a sequência deve ser escolhida para permitir rollback confiável se a instalação nova falhar. O gate precisa provar uma falha artificial durante upgrade e confirmar que a versão anterior permanece ou é restaurada conforme o contrato escolhido.

### C-08 — WebView2

A detecção deve seguir o mecanismo oficial Microsoft: GUID/runtime/API documentado, incluindo layout de registry correto em Windows x64. Se a própria UI Edge Chromium está ativa, o diagnóstico não pode reportar “runtime ausente” por heurística genérica.

### C-09 — diagnóstico por capability

Checks individuais alimentam capacidades, e capacidades determinam severidade:

```text
core        -> Agent, porta, State/Data, SQLite
network     -> DNS/HTTPS/manifest
maintenance -> MSI metadata, helper, update channel
whisper     -> runtime/model/worker/GPU
qwen        -> runtime/model/aligner/gate físico/GPU
```

`blocker` significa que aquela capability não funciona. `degraded` significa que existe caminho utilizável com limitação. `info` não altera readiness.

A tela deve responder “o que está impedindo processamento/update?” e não apenas listar checks verdes/amarelos.

## R3 — E2E instalado, RC e downloads grandes

> Implementado no candidato R3. O pipeline sintético não transforma esse estado em aceite físico; a stable permanece bloqueada até o receipt do MSI/RC exato.

### C-12 — E2E do produto real

O gate instala/exercita o MSI candidato e possui harness de aceite da fronteira usada pelo usuário. O receipt sanitizado exige as observações de Agent, porta, diagnóstico, close/tray, Craig e resume de download em background; também verifica layout instalado, source SHA/MSI SHA e readiness de `core`, `network` e `maintenance`.

A matriz automática continua cobrindo bundle, MSI, install/uninstall, upgrade N-1→N, preserve, purge e rollback. **Ações físicas deliberadas e Craig real não são simulados como se fossem evidência real**: permanecem obrigatórias antes da promoção stable.

### C-13 — RC para stable sem rebuild

`main` não é sinônimo de “artefato local aceito”. A publicação stable automática foi removida do workflow normal. O fluxo implementado é:

```text
source SHA exato
  -> workflow Companion verde gera artifact
  -> workflow manual cria RC imutável sem rebuild
  -> instalação física do RC
  -> jornada do produto + gate ASR aplicável
  -> receipt sanitizado ligado a source SHA + MSI SHA-256
  -> workflow manual valida receipt/manifest/assets
  -> promoção do MESMO objeto de release/mesmos bytes para companion-vX.Y.Z
```

O candidate manifest fixa MSI, checksum e ZIP por nome, tamanho e SHA-256. A promoção falha se `local-companion` ou `.github/workflows` mudaram após o source testado, se o stable tag já existe, se o receipt pertence a outro candidato ou se qualquer asset divergir. Rebuild/reupload depois do aceite físico invalida a evidência e exige novo RC.

### C-14 — DownloadManager/BITS

Manifests continuam pequenos e usam HTTPS normal/no-store. No Windows, MSI, runtime Whisper e cada parte do runtime Qwen usam BITS como transporte preferido. O BITS recebe somente uma URL pública exata derivada internamente da identidade já validada (`https://github.com/Faysk/tda/releases/download/<tag>/<asset>`); ele não escolhe versão, tag, asset, tamanho ou hash.

Contrato implementado:

```text
manifest TDA validado
  -> tag/version/asset fixados
  -> URL GitHub exata derivada pelo Companion
  -> BITS assíncrono/reanexável no Windows
  -> tamanho esperado
  -> SHA-256 esperado
  -> rename atômico para arquivo final
```

Se BITS estiver indisponível, o fallback preserva o transporte HTTP anterior com cadeia de redirect TDA→release GitHub verificada. Falha/interrupção do fallback remove `.partial`. Falha terminal BITS cancela estado inválido e remove `.partial`. Apenas `DOWNLOAD_CONTINUES_IN_BACKGROUND` pode preservar o arquivo pertencente ao job BITS, permitindo que uma chamada posterior reanexe ao mesmo job. Mesmo quando o `.partial` já aparenta estar completo, o Companion exige `Complete-BitsTransfer` antes de promovê-lo localmente, evitando job órfão.

Nenhum byte vira instalável antes de tamanho e SHA-256 corresponderem ao manifest. O gate físico `background_download_resume` exige interromper/reconectar uma transferência grande real e confirmar continuidade/retomada sem `WinError`, `URLError` ou `BITS_*` cru na UI.

## R4 — Craig, Qwen, Whisper e qualidade

### C-15 — timeline e fala simultânea

Craig fornece uma faixa por participante; speaker vem da track, não de diarização. Fala simultânea semanticamente diferente deve permanecer como overlap real. Dedup entre tracks só pode remover bleed quando houver forte combinação de overlap temporal, similaridade textual e dominância por energia/confiança.

O gate físico deve conter pontos anotados de interrupção/fala simultânea e comparar timestamps com o áudio real. A hipótese de timeline comum dos FLACs deve ser comprovada no export real usado pelo produto.

### C-16 — Qwen oficial

O código atual usa Transformers diretamente. A possibilidade de um adapter fino sobre o pacote oficial `qwen-asr` será avaliada para reduzir drift com upstream, **mas essa troca exige ADR específico e benchmark na RTX 4070 8 GB**. R1–R3 não dependem dessa decisão.

### C-17 — honestidade temporal

Falha de forced alignment não pode gerar um segmento de até 180 s apresentado como se tivesse precisão fina. O contrato futuro deve qualificar timestamps, por exemplo:

```text
precise   -> word/segment alignment validado
coarse    -> janela/subchunk conhecido, sem precisão de palavra
failed    -> texto preservado, timestamp final não confiável
```

Antes de cair para `coarse`, o pipeline pode tentar subchunks menores mantendo offset absoluto. O documento canônico deve registrar `alignment_source`/qualidade.

### C-18 — benchmark final

O corpus autorizado deve conter PT-BR normal/rápido, nomes próprios, D&D, overlap, bleed, eco, risada, ruído e microfone ruim. Medir no mínimo:

- WER/CER ou métrica textual equivalente;
- acerto de nomes/termos críticos;
- erro temporal p50/p95 em pontos anotados;
- preservação de overlap;
- falso dedup;
- elapsed/RTF;
- VRAM máxima e utilização GPU;
- comportamento de checkpoint/recovery.

Nenhum engine é declarado vencedor apenas por benchmark público. Qwen e Whisper convergem para o mesmo `tda_transcript_v1` e o default só é escolhido após evidência local.

## Definition of Done de uma próxima stable confiável

A próxima stable só pode ser promovida se, **no mesmo MSI/hash publicado**:

- recovery do Agent não causar spawn/toast storm;
- hide, sair, restart, update e uninstall respeitarem a semântica definida;
- Craig válido permanecer válido com Agent indisponível;
- diagnóstico identificar blockers reais de Agent/rede/WebView2/runtime;
- manifest e asset corresponderem imediatamente à stable promovida;
- download estiver preso à versão e SHA-256 do manifest;
- download grande real sobreviver a perda/reconexão de rede e concluir pelo mesmo estado BITS verificado;
- falha de upgrade tiver rollback comprovado;
- update N-1→N funcionar pelo botão real;
- uninstall preservando dados e purge funcionarem pelo botão real;
- Whisper processar Craig real autorizado;
- Qwen, se anunciado, processar Craig real com alignment qualificado;
- overlap permanecer representado;
- timestamps passarem quality gate;
- receipt físico registrar hardware, versões, hashes e resultados sem áudio/transcrição privada.

## Governança e ordem

- **R0:** congelar features do Companion enquanto P0 estiver aberto.
- **R1:** C-01/C-02/C-03/C-10/C-11.
- **R2:** C-04/C-05/C-06/C-07/C-08/C-09.
- **R3:** C-12/C-13/C-14.
- **R4:** C-15/C-16/C-17/C-18.

Cada fase deve entrar por PR rastreável em `Preview`, com documentação e testes correspondentes. Nenhuma fase isolada autoriza promoção de stable. C-16 é a única mudança desta lista que ainda exige ADR antes da troca estrutural de implementação Qwen.

## Referências do repositório

- `docs/adr/0013-companion-agent-desktop-asr.md`
- `docs/features/companion-desktop-asr-v0.3.md`
- `docs/operations/local-companion.md`
- `docs/operations/release-runbook.md`
- `.github/workflows/companion.yml`
- `.github/workflows/companion-rc.yml`
- `.github/workflows/companion-promote.yml`
- `local-companion/tda_companion/agent.py`
- `local-companion/tda_companion/desktop_runtime.py`
- `local-companion/tda_companion/desktop_session_bridge.py`
- `local-companion/tda_companion/installed_acceptance.py`
- `local-companion/tda_companion/release_evidence.py`
- `local-companion/tda_companion/large_download.py`
- `local-companion/tda_companion/ui/app.js`
- `local-companion/tda_companion/diagnostics.py`
- `local-companion/tda_companion/asr_timeline.py`
- `local-companion/tda_companion/asr_whisper.py`
- `local-companion/tda_companion/asr_qwen.py`
- `local-companion/packaging/run-installed-acceptance.ps1`
- `local-companion/packaging/maintenance_entry.py`
- `local-companion/packaging/TDACompanion.wxs`

## Referências oficiais de pesquisa

- Microsoft WebView2 distribution/detection: https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution
- Microsoft BITS: https://learn.microsoft.com/en-us/windows/win32/bits/about-bits
- Microsoft msiexec: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/msiexec
- Microsoft Restart Manager: https://learn.microsoft.com/en-us/windows/win32/rstmgr/restart-manager-portal
- WiX MajorUpgrade: https://docs.firegiant.com/wix3/xsd/wix/majorupgrade/
- Python urllib/proxies: https://docs.python.org/3/library/urllib.request.html
- pywebview API/events: https://pywebview.flowrl.com/api/
- Next.js fetch/cache: https://nextjs.org/docs/app/api-reference/functions/fetch
- Craig: https://craig.chat/
- Faster-Whisper: https://github.com/SYSTRAN/faster-whisper
- Qwen3-ASR: https://github.com/QwenLM/Qwen3-ASR
