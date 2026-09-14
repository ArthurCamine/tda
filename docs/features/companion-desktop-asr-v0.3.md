# TDA Companion v0.3 — Desktop, Agent e ASR

> Status: especificação aceita para implementação; estabilização R1–R4 em andamento
> Owner: local-companion / processing
> Última revisão: 2026-09-13
> ADR: `docs/adr/0013-companion-agent-desktop-asr.md`
> Confiabilidade: `docs/operations/companion-reliability.md`

## Princípio do produto

**A Web gerencia o trabalho; o Companion gerencia a máquina que executa o trabalho.**

A Web continua responsável por sessões, fila editorial, revisão, resultados e publicação. O Desktop cuida de Agent, saúde, consumo, logs técnicos, diagnóstico, modelos, update, storage e manutenção.

O teste físico da 0.3.2 confirmou que a separação conceitual é correta, mas reprovou a confiabilidade da jornada instalada. O contrato complementar `companion-reliability.md` é obrigatório para lifecycle, rede, manutenção, release e aceite físico.

## Arquitetura

```text
Windows login
  -> TDACompanion.exe --agent
       -> loopback API 127.0.0.1:8765
       -> SQLite / queue / events
       -> telemetry / system logs
       -> model registry / updates
       -> ASR worker subprocess

TDACompanion.exe --ui
  -> WebView2 local UI -> AgentConnection -> Agent

TDA Web/Edit
  -> pareamento explícito -> Agent
```

Fechar a janela não encerra o Agent nem o processamento. Crash da UI não afeta Agent. Crash do worker não derruba Agent/API/UI.

O Desktop não trata HTTP 200 como identidade suficiente do Agent. Antes de enviar Bearer token, o health público precisa provar `product_id`, `api_version`, `service_version`, `pid` e porta esperada. Os estados de conexão de produto são:

```text
starting
ready
reconnecting
stopped_by_user
unavailable
incompatible
port_conflict
```

`paused` continua sendo estado da fila/Agent, não substitui o estado da conexão.

## Startup e raízes locais

O Agent permanece per-user, sem Windows Service administrativo. `Iniciar com o Windows` usa startup por usuário.

Layout alvo:

```text
%LOCALAPPDATA%\TDA\
├── Companion\versions\<version>\
├── State\
├── Data\
├── Logs\
├── Cache\updates\
├── Models\
└── Runtime\
```

Upgrade substitui binários, mas preserva State/Data/Models. A migração 0.2→0.3 preserva token de pareamento e `jobs.sqlite3`. Nenhum diretório DnDScribe é consultado ou modificado.

Startup/recovery não podem iniciar múltiplos Agents concorrentes. A camada `AgentConnection` serializa tentativa de recovery e aplica backoff quando a porta está livre mas o Agent não consegue iniciar.

## Desktop

Tkinter deixa de ser UI de produto. A implementação preferida é WebView2/Edge Chromium via camada leve Python compatível com PyInstaller, com assets HTML/CSS/JS locais e tokens do Design System TDA.

Navegação:

```text
Visão geral
Logs
Diagnóstico
Configurações
```

### Visão geral

Mostrar:

- estado real da conexão e uptime do Agent quando disponível;
- versão e update disponível;
- Windows/CPU/GPU;
- GPU e VRAM;
- CPU e RAM;
- espaço livre do volume de Data;
- processando / na fila / concluídos / com atenção;
- Abrir TDA;
- pausar/retomar novas execuções;
- reiniciar Agent;
- abrir pasta local.

Quando o Agent estiver indisponível, a UI continua renderizável com dados locais possíveis. Não deve apagar uma sessão Craig já validada nem gerar toast a cada polling.

O Desktop não replica sessões, mundo, lores ou revisão editorial.

### Tray

Quando habilitado, menu mínimo:

```text
Abrir Companion
Abrir TDA
Pausar/retomar fila
Reiniciar Agent
Sair da interface
```

O botão X respeita a preferência `close_behavior` e pode apenas ocultar a UI. **Saída programática** usada por update, uninstall ou “Sair da interface” não pode ser cancelada por essa preferência. Parar deliberadamente o Agent não é ação casual do tray; operações que realmente precisam encerrar o Agent devem fazê-lo por lifecycle/maintenance controlado.

## Logs técnicos

Separar `system logs` de `job events`.

Log técnico estruturado contém timestamp, level, component, code, mensagem curta e contexto pequeno. Componentes: bootstrap, agent, api, storage, queue, worker, asr, aligner, gpu, models, update, installer e diagnostics.

Não registrar segredo de pareamento, Authorization, áudio ou texto integral de transcrição.

Baseline de retenção: rotação de 10 MiB, até 5 arquivos ou 14 dias. Debug desligado por padrão em release.

Polling de logs em background degrada silenciosamente para estado inline quando o Agent está offline. Toast é reservado para ação manual ou transição relevante de estado.

## Diagnóstico

Checks não destrutivos continuam cobrindo:

- Agent e loopback API;
- ownership/uso da porta 8765;
- escrita em State/Data;
- SQLite integrity check;
- espaço livre;
- WebView2 runtime;
- NVIDIA/NVML;
- runtime CUDA da engine instalada;
- integridade dos modelos;
- spawn do ASR worker;
- endpoint de update.

Durante R2, os checks passam a alimentar capabilities `core`, `network`, `maintenance`, `whisper` e `qwen`, com severidade `blocker/degraded/info`. WebView2 deve usar detecção oficial Microsoft, não heurística genérica de nome no registry.

Export gera ZIP sanitizado com manifest/system/health/model state/logs recentes, sem credenciais, áudio ou transcrição integral.

## Configurações

- iniciar com Windows;
- tray;
- update automático apenas para verificação;
- tema;
- comportamento ao fechar;
- paths/tamanho de Data e Models;
- copiar/regenerar pareamento;
- instalar/remover modelos;
- versão/API/build;
- reparar;
- desinstalar.

## Update

Endpoint cloud:

```text
GET /api/downloads/companion/windows/manifest
```

Retorna versão estável, tag, asset MSI, tamanho e SHA-256. O Companion baixa para Cache, verifica SHA-256 e só então inicia o fluxo MSI.

O contrato de confiabilidade adiciona dois invariantes: a descoberta stable não pode ficar deliberadamente stale e o asset baixado precisa ser imutavelmente ligado à versão/hash devolvidos pelo manifest. Não interromper job ativo para atualizar. Sem assinatura Authenticode confiável, a aplicação da atualização exige confirmação explícita.

Update iniciado pela UI só é considerado concluído depois de receipt/journal de manutenção e verificação da nova instalação/Agent; lançar um helper e fechar a janela não é definição de sucesso.

## MSI e desinstalação

WiX/MSI continua per-user.

Dois fluxos:

1. **Remover aplicativo e manter dados** — remove binários, startup, atalhos e integrações; preserva dados destinados a futura reinstalação.
2. **Remover completamente** — também remove State/Data/Logs/Cache/Models/Runtime e `%LOCALAPPDATA%\TDA` se vazio.

CI deve validar fresh install, upgrade N-1→N, uninstall mantendo dados e purge completo, incluindo processo encerrado e porta loopback fechada. O E2E de produto também precisa iniciar update/uninstall pela mesma bridge usada pela UI instalada; chamar `msiexec` diretamente não cobre essa jornada.

## API local

`api_version="1"` permanece enquanto mudanças forem aditivas. O health público possui identidade mínima necessária ao handshake do Desktop. Endpoints privados continuam autenticados.

Capabilities candidatas:

```text
agent.desktop
agent.logs
agent.diagnostics
agent.updates
models.manage
transcription.craig
transcription.qwen3
transcription.whisper
alignment.qwen3
```

Capability só aparece quando o caminho real correspondente estiver implementado e validado. A UI Desktop não justifica enfraquecer CORS/Origin do browser.

## ASR — quatro perfis

Idioma padrão: português explícito.

| ID | Modelo |
| --- | --- |
| `qwen-fast` | `Qwen/Qwen3-ASR-0.6B-hf` |
| `qwen-quality` | `Qwen/Qwen3-ASR-1.7B-hf` |
| `whisper-turbo` | `dropbox-dash/faster-whisper-large-v3-turbo` |
| `whisper-detailed` | `Systran/faster-whisper-large-v3` |

Alinhador preferencial:

```text
Qwen/Qwen3-ForcedAligner-0.6B-hf
```

Todos os modelos e o alinhador usam revision imutável no registry. `main` flutuante não é aceito em job de produção.

### Receita Whisper preservada

A implementação nova mantém inicialmente a receita comprovada do legado:

```text
language=pt
task=transcribe
beam_size=5
vad_filter=true
min_silence_duration_ms=500
speech_pad_ms=300
word_timestamps=true
condition_on_previous_text=false
hotwords=glossary
initial_prompt com contexto de RPG/campanha
GPU-first float16
fallback int8_float16 somente em OOM e quando suportado
CPU somente quando solicitado
```

### Receita Qwen inicial

A implementação vigente usa o suporte nativo do Transformers 5.x, não o pacote `qwen-asr` como runtime principal.

```text
AutoProcessor
AutoModelForMultimodalLM
language=Portuguese
prompt limitado com contexto/glossário
torch.inference_mode()
dtype=bfloat16 na RTX quando suportado
CUDA GPU-first
batch/janelas adaptados a 8 GB de VRAM
```

`apply_transcription_request` é o entry point preferido. O texto é extraído via decode estruturado do processor. O Forced Aligner usa `AutoModelForTokenClassification`, `prepare_forced_aligner_inputs` e `decode_forced_alignment`.

C-16 de `companion-reliability.md` abre uma avaliação futura para um adapter fino sobre o pacote oficial `qwen-asr`; **essa troca não está aprovada por este documento e exige ADR/benchmark antes de substituir o runtime vigente**.

`torch.compile` é candidato de otimização depois da correção funcional; não entra como pré-requisito da primeira inferência real.

## Runtimes ASR isolados

Whisper e Qwen não precisam compartilhar a mesma família CUDA. Eles são runtimes separados justamente para evitar que uma limitação do CTranslate2 impeça uma stack PyTorch mais atual.

### Whisper

Baseline atual candidata:

```text
Python 3.12.14
Faster-Whisper 1.2.1
CTranslate2 4.8.2
CUDA Runtime 12.9
cuDNN 9
```

O runtime é empacotado e publicado separadamente do MSI.

### Qwen

Baseline candidata, ainda não declarada suportada:

```text
Python 3.12.14
PyTorch 2.14.0 + cu132
Transformers 5.17.0
Accelerate 1.15.0
CUDA runtime fornecido pelo wheel PyTorch cu132
```

O CI comum pode resolver/importar essa stack e verificar que o wheel contém CUDA 13.2, mas não possui GPU física. O runtime Qwen só será declarado suportado após materialização isolada, probe na máquina real e inferência dos dois perfis na RTX 4070 8 GB.

CUDA 13.x exige driver compatível da família 580 ou superior. O Companion não instala nem altera driver NVIDIA automaticamente.

A distribuição final do runtime Qwen deve permanecer separada do MSI e dos modelos. Antes de decidir entre archive pré-construído e materialização local gerenciada, o CI mede o tamanho real do ambiente PyTorch/Transformers para evitar um pacote desnecessariamente gigantesco.

## CUDA e modelos

O Companion não altera CUDA Toolkit, Python ou PATH global do usuário. Runtime de ASR é isolado e versionado.

Modelos não entram no MSI; são downloads gerenciados em `%LOCALAPPDATA%\TDA\Models`. Cada instalação registra ID, revision, alignment revision e hash do conteúdo.

A política `docs/operations/companion-dependency-policy.md` é gate de release: usamos a versão estável mais recente e compatível, com exceções documentadas. GPU/ASR só vira baseline suportada depois de teste físico.

## Craig ZIP

Job: `transcription.craig`.

Entrada esperada: ZIP com 1..N tracks de áudio, `info.txt` opcional e `raw.dat` opcional. O ingest rejeita path traversal, paths absolutos, links inesperados, quantidade/tamanho descompactado fora do limite e archives aninhados não suportados.

Cada track guarda speaker, filename, hash, duração e `timeline_offset_seconds=0` quando o pacote Craig confirma timeline comum.

A seleção/ingest bem-sucedida é estado persistente da jornada de UI: falha posterior ao consultar perfis do Agent não invalida o Craig nem exige nova seleção.

A Web não envia path arbitrário do filesystem; jobs usam IDs opacos de staging local.

## Pipeline

```text
package_validation
metadata
track_probe
speech_regions
model_prepare
transcription
alignment
cross_track_dedup
merge_timeline
turn_building
result_prepare
complete
```

VAD economiza inferência, mas não remove tempo: regiões de fala mantêm offsets absolutos.

O scheduler trabalha por janelas/regiões, não exige completar uma track inteira de horas antes das demais. Batch deve ocupar a GPU sem estourar VRAM.

## Alinhamento

O Forced Aligner Qwen suporta português e é o refinamento temporal preferido. Qwen usa o aligner diretamente; Whisper mantém timestamps nativos como fallback e pode ter o texto refinado pelo mesmo aligner.

Na RTX 4070 8 GB, o perfil de qualidade não deve manter ASR 1.7B e aligner carregados simultaneamente. O lifecycle preferido é transcrever a janela/track, liberar VRAM e então carregar/alimentar o aligner. Falha de alignment não descarta transcrição concluída.

Resultado temporal futuro deve declarar a qualidade/origem do alinhamento. Fallback de janela ampla não pode ser apresentado como timestamp preciso; R4 fecha o contrato `precise/coarse/failed` e subchunk/retry antes de cair para `coarse`.

Janelas destinadas ao aligner permanecem abaixo do limite prático documentado, com baseline alvo de aproximadamente 3–4 minutos, preservando offsets absolutos da timeline Craig.

## Cross-track dedup e diálogo

Craig já fornece speaker por track, então diarização não é o mecanismo primário.

Bleed/crosstalk duplicado só é suprimido quando houver combinação forte de overlap temporal, similaridade textual e evidência de track dominante por energia/confiança. Duas falas diferentes ao mesmo tempo continuam como overlap real.

Depois, palavras/segmentos são ordenados pela timeline comum e agrupados em turnos sem alterar timestamps originais.

## Contexto e glossário

Contexto estático pode incluir participantes, personagens, NPCs, locais e termos de D&D. Contexto dinâmico pode usar poucos turnos anteriores com limite rígido.

Contexto ajuda reconhecimento; nunca deve funcionar como autorização para inventar fala ausente.

## Checkpoints

Checkpoint inclui assinatura do request, source hash, engine/profile, model revision, alignment revision, hash de contexto/glossário e versões de VAD/alignment. Só é reutilizado quando compatível.

O comportamento validado do legado — reaproveitar tracks concluídas após interrupção — deve permanecer.

## Output canônico

Qwen e Whisper convergem para o mesmo `tda_transcript_v1`, contendo engine metadata, language, tracks, words, turns e metrics (duração, elapsed, RTF, VRAM quando disponível). A Web não depende de classes internas da engine.

## Benchmark obrigatório

Antes de escolher um default definitivo, rodar os quatro perfis sobre áudio real revisado do TDA, incluindo PT-BR normal, fala rápida, nomes próprios, termos de D&D, overlaps, bleed, ruído, eco e risada.

Medir qualidade textual, nomes, erro temporal p50/p95 em pontos anotados, preservação de overlap, falso dedup, elapsed, RTF, pico de VRAM, uso GPU e recoverability/checkpoints.

## Ordem de estabilização

A ordem original de implementação permanece como histórico da construção, mas a estabilização vigente segue:

1. **R1:** lifecycle/Agent/boundaries de UI;
2. **R2:** rede/update/uninstall/diagnóstico;
3. **R3:** E2E instalado/RC→stable/downloads grandes;
4. **R4:** timeline física/Qwen/alignment/benchmark ASR.

Nenhuma feature nova do Companion deve furar os P0 dessa sequência.

## Definition of Done v0.3

Só chamar v0.3 de concluído quando:

- Agent sobreviver ao fechamento/crash da UI e recuperar falha inesperada sem storm;
- MSI fresh install/upgrade/uninstall/purge estiver validado;
- startup/tray/logs/diagnóstico/update estiverem funcionais na jornada instalada;
- update N-1→N e uninstall/purge forem exercitados pelos botões/bridge reais do produto;
- o mesmo MSI/hash fisicamente aceito for o promovido para stable;
- os quatro perfis executarem job Craig real em português quando anunciados;
- alignment/fallback estiver explícito e sem falsa precisão;
- checkpoint/restart estiver comprovado;
- output for canônico e independente da engine;
- fala simultânea e dedup passarem corpus físico;
- benchmark em RTX 4070 8 GB estiver registrado;
- docs descreverem exatamente o que está ativo.

## Referências

- `docs/operations/companion-reliability.md`
- https://huggingface.co/docs/transformers/model_doc/qwen3_asr
- https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf
- https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf
- https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf
- https://github.com/SYSTRAN/faster-whisper
- https://pytorch.org/
- https://learn.microsoft.com/en-us/microsoft-edge/webview2/
- https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution
- https://learn.microsoft.com/windows/win32/setupapi/run-and-runonce-registry-keys
- https://github.com/CraigChat/craig
