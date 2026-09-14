# Companion — operação, instalação e rollback

> Status: candidato v0.3 em estabilização; CI técnica válida, aceite físico da 0.3.2 reprovado
> Owner: local-companion/processing
> Última revisão: 2026-09-13

Referências: [contrato de confiabilidade e aceite real](companion-reliability.md), [contrato API](../integrations/local-companion-v1.md), [especificação v0.3](../features/companion-desktop-asr-v0.3.md), [política de dependências](companion-dependency-policy.md) e [processamento no Edit](../features/local-processing.md).

> **Estado físico observado em 2026-09-13:** a build 0.3.2 passou os gates técnicos existentes, mas a jornada instalada reprovou em lifecycle do Agent, rede/manutenção e boundaries de erro da UI. Portanto 0.3.2 não é baseline de confiabilidade operacional. O plano e os critérios que bloqueiam uma próxima stable estão em [companion-reliability.md](companion-reliability.md). CI sintética verde continua sendo evidência válida das peças que testa, mas não substitui o aceite do produto instalado.

## Modelo de processo Windows

O TDA Companion é independente do antigo `DnDScribeCompanion.exe`. O produto não consulta, inicia, encerra, modifica ou depende da instalação antiga.

O processo é per-user, sem Windows Service administrativo:

```text
login do Windows
  -> TDACompanion.exe --agent --startup
       -> 127.0.0.1:8765/api/v1
       -> SQLite / fila / eventos / telemetria
       -> worker ASR separado

atalho/Menu Iniciar
  -> TDACompanion.exe --ui
       -> Desktop WebView2
       -> Agent já existente
```

Fechar ou ocultar a UI não encerra o Agent. Encerrar o Agent é uma ação diferente e trabalho ativo não deve ser morto silenciosamente. Durante a estabilização, a UI deve distinguir fechamento pelo usuário de saída programática usada por update/uninstall; o contrato detalhado fica em `companion-reliability.md`.

Raízes locais v0.3:

```text
%LOCALAPPDATA%\TDA\
├── Companion\
├── State\
├── Data\
├── Logs\
├── Cache\
├── Models\
└── Runtime\
```

A migração 0.2→0.3 é limitada ao namespace TDA e não usa o DnDScribe como fallback.

## Instalador Windows

O pacote principal continua sendo `TDACompanion-x64.msi`, per-user e sem elevação administrativa.

O MSI candidato v0.3:

- instala versões sob `%LOCALAPPDATA%\TDA\Companion\versions\<versão>`;
- mantém `current-version.txt` e metadata de instalação;
- cria o atalho `TDA Companion` no Menu Iniciar;
- registra o Agent em `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`;
- instala o helper de manutenção junto do aplicativo;
- usa `MajorUpgrade` com UpgradeCode estável;
- não cria Windows Service;
- não instala CUDA/Python globalmente;
- não toca no DnDScribe.

O ZIP portátil pode existir como artefato técnico, mas o MSI é o caminho de produto.

### Gates do MSI

O workflow `Companion` comprova em Windows:

1. bundle PyInstaller e MSI WiX;
2. smoke do bundle e do Agent instalado;
3. health/version e job real de smoke via loopback autenticado;
4. instalação/desinstalação com Agent ativo e encerramento controlado;
5. upgrade real do MSI oficial `companion-v0.2.0` para o candidato corrente;
6. preservação de State/Data/Logs/Cache/Models/Runtime e token no upgrade;
7. uninstall normal preservando dados;
8. reinstalação seguida de purge completo dos roots TDA-owned;
9. ausência de processo, porta, startup, atalhos, registry e binários esperados após remoção.

O gate usa o artefato oficial v0.2.0 e SHA-256 conhecido como N-1; portanto a matriz fresh install, N-1→N, preserve e purge é executada no CI, não apenas documentada. **Esse gate não prova a jornada iniciada pelos botões da UI instalada**; essa lacuna virou C-12 no contrato de confiabilidade.

## Distribuição e updates

Companion, runtime Whisper e runtime Qwen possuem canais de release separados.

Companion:

```text
companion-v<versão>
TDACompanion-x64.msi
TDACompanion-x64.msi.sha256
TDACompanion-<versão>-windows-x64.zip
```

Runtime Whisper:

```text
companion-whisper-runtime-v<versão>
TDAWhisperRuntime-<versão>-windows-x64.zip
TDAWhisperRuntime-<versão>-windows-x64.zip.sha256
```

Runtime Qwen:

```text
companion-qwen-runtime-v<versão>
TDAQwenRuntimeBundle-<versão>-windows-x64.json
TDAQwenRuntimePackage-<versão>-windows-x64.json
TDAQwenRuntime-<versão>-windows-x64.zip.part*
```

Os endpoints do TDA selecionam somente a família correta de tags/assets, e os downloads são verificados por tamanho e SHA-256 antes da instalação. Os runtimes ASR ficam fora do MSI para não transformar o instalador principal em um pacote de vários gigabytes. O bundle Qwen pode ser dividido em múltiplas partes; o archive lógico e cada parte possuem identidade/hash verificados antes da materialização.

Update não pode interromper job ativo. Enquanto não houver assinatura Authenticode confiável, instalação de update continua exigindo confirmação explícita. A estabilização adiciona ainda dois invariantes: manifest stable não pode ficar stale e o download precisa apontar para o asset imutável da mesma versão selecionada pelo manifest.

## Pareamento e segurança

O token de pareamento é local, fica em `State`, com proteção do usuário do Windows, e não é cookie, query string, storage persistente do browser, log ou dado cloud.

A API continua somente em IPv4 loopback, com Host exato, Origin permitido e Bearer nos endpoints privados. A Web não envia path arbitrário do filesystem e não existe descoberta LAN/proxy cloud.

Antes de qualquer request autenticada do Desktop, o listener local deve provar identidade TDA/API/versão conforme `companion-reliability.md`; HTTP 200 isolado não é suficiente e um processo estranho na porta 8765 não deve receber o token.

O ingest Craig da Web envia o ZIP diretamente para o loopback. O Agent recebe em streaming, limita tamanho, calcula SHA-256 durante a gravação, materializa um `source_id` content-addressed, usa o ingestor seguro existente e remove o ZIP temporário. O áudio não passa pelo cloud.

## Processamento real candidato

A v0.3 possui worker em subprocesso, job `transcription.craig`, ingest Craig browser→loopback, checkpoints por track, timeline comum, deduplicação conservadora entre tracks e turns canônicos em `tda_transcript_v1`.

Craig é materializado por `source_id` opaco; o worker recebe roots controlados pelo Agent. Speaker vem da track Craig, portanto diarização não é usada como substituto para informação que o pacote já fornece.

O output de engines diferentes converge para `tda_transcript_v1`. O texto integral permanece no artefato local; mensagens do worker e logs técnicos carregam apenas estado, métricas, hashes e códigos estáveis.

Perfis registrados:

```text
whisper-turbo
whisper-detailed
qwen-fast
qwen-quality
```

Whisper é anunciado quando seu runtime isolado está íntegro. Qwen possui runtime, adapter e Forced Aligner implementados, mas cada perfil Qwen só entra em `/capabilities` depois de um gate físico válido, ligado criptograficamente à identidade do runtime, modelo e aligner atuais. Trocar qualquer um deles invalida o gate e retira o perfil da Web até nova aceitação física.

## Runtimes ASR isolados

O runtime Whisper é versionado sob `Runtime\whisper` e contém Faster-Whisper/CTranslate2 e as DLLs CUDA necessárias à própria engine. O runtime Qwen é versionado sob `Runtime\qwen` e contém Torch/Transformers e dependências próprias. Nenhum deles modifica Toolkit CUDA, Python ou PATH global do usuário.

Os manifests de build fixam Python e dependências. A política de dependências exige a versão estável mais recente e compatível e um gate verifica drift de dependências e revisions de modelos.

`TDAWhisperWorker.exe --probe` e `TDAQwenWorker.exe --probe` comprovam importação dos stacks empacotados sem baixar/carregar modelo. Runner comum do GitHub sem GPU valida empacotamento, bundle e smoke de instalação, mas **não substitui a prova física na RTX 4070 8 GB**.

## Gate físico — RTX 4070

O gate físico final usa áudio local autorizado e deve cobrir os quatro perfis. O harness entregue junto do aplicativo evita quatro comandos manuais, resolve as versões correntes dos runtimes, valida o SHA-256 dos workers contra `.tda-runtime.json`, executa `--probe`, roda os perfis sequencialmente e agrega os receipts.

Depois de instalar o candidato, localizar o script pelo `current-version.txt`:

```powershell
$tda = "$env:LOCALAPPDATA\TDA"
$version = (Get-Content "$tda\Companion\current-version.txt" -Raw).Trim()
$gate = "$tda\Companion\versions\$version\run-physical-acceptance.ps1"

& $gate -Audio "C:\caminho\amostra.flac"
```

Por padrão são executados:

```text
whisper-turbo
whisper-detailed
qwen-fast
qwen-quality
```

A GPU exigida por padrão é `RTX 4070`. Para um subconjunto explícito:

```powershell
& $gate -Audio "C:\caminho\amostra.flac" -Profiles whisper-turbo,qwen-fast
```

Contexto/glossário entram por arquivo local, nunca precisam ser colocados na linha de comando como conteúdo:

```powershell
& $gate `
  -Audio "C:\caminho\amostra.flac" `
  -ContextFile "C:\caminho\contexto.txt" `
  -GlossaryFile "C:\caminho\glossario.txt"
```

Para inspeção humana da qualidade, transcrições locais só são gravadas com consentimento explícito:

```powershell
& $gate -Audio "C:\caminho\amostra.flac" -WriteTranscripts
```

Sem `-WriteTranscripts`, o harness grava apenas `%LOCALAPPDATA%\TDA\State\acceptance\physical-acceptance-suite.json`. O receipt agregado declara `contains_audio=false` e `contains_transcript=false`; contém hashes, versões, GPU/driver, VRAM, tempos, RTF, contagens e resultados por perfil. O path do áudio não entra no receipt.

Nos perfis Qwen o harness usa `--record-gate`; isso persiste um gate sanitizado por perfil. Apenas depois dele estar `ready` o Agent anuncia o respectivo Qwen em `/capabilities`. Whisper não depende desse gate de anúncio, mas os dois perfis continuam obrigatórios para aceite do RC.

Critério mínimo do gate físico: `pass=true` nos quatro perfis, CUDA real, GPU esperada, fala reconhecida, Forced Aligner válido nos Qwen e receipts completos. A avaliação de qualidade em português é um gate separado: comparar os JSONs gerados com `-WriteTranscripts` contra o áudio/referência e registrar nomes próprios, termos de D&D, omissões, alucinações, overlap e timestamps. O contrato de confiabilidade amplia esse gate com erro temporal e falso dedup explícitos.

Não versionar áudio privado nem transcrição integral como evidência do CI. Um receipt sanitizado pode ser arquivado posteriormente.

### Comandos individuais de diagnóstico

Se o harness falhar antes de um perfil, os workers continuam podendo ser executados separadamente:

```powershell
& "$env:LOCALAPPDATA\TDA\Runtime\whisper\<versao>\TDAWhisperWorker.exe" --probe
& "$env:LOCALAPPDATA\TDA\Runtime\qwen\<versao>\TDAQwenWorker.exe" --probe
```

Os modos `--acceptance` individuais aceitam `--audio`, `--models-root`, `--profile`, `--require-gpu-name`, `--context-file`, `--glossary-file` e `--transcript-out`. Qwen também aceita `--record-gate`, `--runtime-root` e `--state-root`.

## ASR Whisper — receita preservada

Os dois perfis Whisper preservam inicialmente a receita comprovada pelo legado:

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
initial_prompt com contexto limitado da campanha
GPU float16
fallback int8_float16 apenas em falha real de memória e quando suportado
CPU int8 apenas quando solicitado
```

Modelos são baixados separadamente em `Models` usando revision imutável e marker local com hash do conteúdo.

## Diagnóstico

A implementação 0.3.2 executa checks locais de Agent, State/Data, SQLite, disco, WebView2 e NVIDIA e verifica runtimes instalados. O teste físico mostrou que esse conjunto ainda não representa readiness real: houve falso negativo de WebView2 e falhas operacionais não apareceram como blockers adequados.

A estabilização substitui essa interpretação por diagnóstico orientado a capability (`core`, `network`, `maintenance`, `whisper`, `qwen`) e usa detecção oficial de WebView2. Export continua sanitizado, sem token de pareamento, áudio ou texto integral de transcrição.

## Atualização, repair e desinstalação

O helper de manutenção roda fora do processo principal para permitir MSI upgrade/uninstall sem o executável tentar substituir a si mesmo.

Dois conceitos permanecem distintos:

- **desinstalar preservando dados**: remove aplicativo/integrações, mantendo conteúdo local destinado a reinstalação;
- **remover completamente**: remove também State/Data/Logs/Cache/Models/Runtime pertencentes ao TDA, com confirmação explícita.

"Remover completamente" significa conteúdo de propriedade do TDA. Não há promessa de apagar cache do Windows Installer, Prefetch, Defender ou outros artefatos administrados pelo Windows.

Update/uninstall pela UI só serão considerados confiáveis quando houver journal/receipt da operação, timeout de parent tratado como falha e log MSI recuperável, conforme C-06.

## Rollback

Rollback do aplicativo significa instalar uma versão compatível e preservar dados. Schema local não é rebaixado in-place. Mudanças de schema futuras exigem snapshot/migração versionada.

O antigo `DnDScribeCompanion.exe` não participa do rollback.

## Gates antes de promoção

Antes de promover uma versão do Companion:

```text
python -m pytest local-companion/tests -q
pnpm check
pnpm build
pnpm test:processing
```

Além disso:

- `Companion` verde em Windows/Linux, incluindo lifecycle MSI N-1→N/preserve/purge;
- `CI` verde na árvore reconciliada com `main`;
- `Whisper Runtime` verde;
- `Qwen Runtime Candidate` verde;
- `Qwen Runtime Package` verde;
- `Companion Dependency Freshness` verde;
- revisions ASR atuais e pinadas;
- gate físico RTX nos quatro perfis;
- benchmark PT-BR antes de escolher default definitivo;
- jornada física do aplicativo instalado conforme `companion-reliability.md`;
- o **mesmo artefato/hash** fisicamente aceito é o que será promovido para stable;
- documentação descrevendo somente capabilities realmente ativas.

CI sem GPU prova empacotamento e contratos, não prova qualidade, throughput, VRAM, jornada da UI instalada ou compatibilidade física da RTX.
