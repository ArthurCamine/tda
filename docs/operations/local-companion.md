# Companion — operação, instalação e rollback

> Status: candidato 0.3.14 em validação; Stable bloqueada até aceite físico real
> Owner: local-companion/processing
> Última revisão: 2026-09-21

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
- registra `tda-companion://open` em `HKCU\Software\Classes` para abertura explícita pelo site;
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

### Recuperação de instalações legadas 0.3.1

O Companion 0.3.1 possui um bug conhecido no downloader: ao seguir a cadeia legítima de redirect do asset publicado pelo GitHub, ele pode retornar `UPDATE_REDIRECT_REJECTED`. Essa instalação **não deve** relaxar validação de origem/hash e não deve depender de autocorreção pelo updater quebrado.

O caminho suportado para uma instalação 0.3.1 afetada é um **upgrade manual in-place pelo MSI Stable oficial**:

1. confirmar que `%LOCALAPPDATA%\TDA\Companion\current-version.txt` contém `0.3.1`;
2. não apagar `%LOCALAPPDATA%\TDA\Data`, `State`, `Logs`, `Cache`, `Models` ou `Runtime`;
3. baixar o MSI e o checksum do release Stable oficial `companion-v0.3.9`;
4. verificar o MSI antes de executar:

```powershell
$msi = ".\TDACompanion-x64.msi"
$expected = "67abdb127ae2d1569f3f3200274bad8da2a0a79e8abc45eb6cafca291edfe39c"
$actual = (Get-FileHash -LiteralPath $msi -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "TDA Companion MSI SHA-256 inválido" }

Start-Process msiexec.exe -ArgumentList @(
  "/i", ('"{0}"' -f (Resolve-Path $msi)),
  "/qn", "/norestart"
) -Wait
```

5. depois do upgrade, confirmar `current-version.txt = 0.3.9` e que os roots de dados locais continuam presentes;
6. a partir da 0.3.9, o downloader corrigido aceita a cadeia oficial de redirect **sem** desativar verificação de tamanho/SHA-256.

O teste versionado `tools/acceptance/verify-legacy-031-recovery.ps1` exercita esse bootstrap em Windows descartável usando:
- o MSI 0.3.1 realmente publicado e seu SHA-256;
- o source SHA exato `d175c6d95c117e8324bb063292906b55e021b162` para reproduzir `UPDATE_REDIRECT_REJECTED`;
- o MSI Stable 0.3.9 realmente publicado e seu payload manifest;
- um marcador sintético em `Data` para provar preservação no upgrade e no uninstall normal;
- o updater do source SHA exato da 0.3.9 para provar redirect + hash no caminho corrigido.

Isso é recuperação de bootstrap, não promoção de versão nova. Authenticode continua sendo um gate separado (#395); enquanto ele não estiver provisionado, o checksum publicado é obrigatório, mas não deve ser descrito como assinatura de publisher.

## Assinatura Authenticode do release Windows

O build suporta três modos explícitos em `build-windows.ps1`:

- `none`: somente para build/teste não publicável;
- `certificate-store`: certificado local/KSP, identificado por thumbprint configurada;
- `artifact-signing`: Microsoft Artifact Signing via SignTool `/dlib` + `/dmdf`.

Em modo publicável, assinatura é **fail-closed** e ocorre nesta ordem:

```text
TDACompanion.exe
TDACompanionMaintenance.exe
  -> assinar + verificar trust/subject/timestamp
  -> montar ZIP/MSI
TDACompanion-x64.msi
  -> assinar + verificar
  -> calcular SHA-256/payload/candidate evidence
  -> acceptance físico nos mesmos bytes
  -> promoção sem rebuild
```

O MSI de rollback probe é fixture de teste e não é publicado.

Para Artifact Signing, o leaf certificate gerenciado é curto e pode rotacionar; portanto thumbprint fixa não é identidade configurável. A identidade estável é o provider/account/certificate profile mais o `ExpectedSubject`, cadeia Windows válida e timestamp. O thumbprint observado pertence à evidência do artifact.

No GitHub Actions, o caminho preferido é **Microsoft Entra workload identity federation (OIDC)**:

1. usar um GitHub Environment protegido para signing/release;
2. federar exatamente o repositório/environment com uma app registration ou user-assigned managed identity;
3. conceder somente `Artifact Signing Certificate Profile Signer` no escopo necessário;
4. habilitar `id-token: write` somente no job confiável que realmente assina;
5. evitar `AZURE_CLIENT_SECRET`; client/tenant/subscription IDs não substituem a credencial federada;
6. PRs/forks não recebem acesso ao environment de signing.

O metadata passado ao dlib contém somente configuração do Artifact Signing (endpoint HTTPS, account e certificate profile). Senhas, access tokens, refresh tokens e client secrets não pertencem ao arquivo e são rejeitados pelo build.

A ativação real continua bloqueada até existir identidade/provider confiável (#395/#548). Não descrever MSI atual como publisher-signed antes de um build real passar `Get-AuthenticodeSignature` + `signtool verify /pa /all` e o acceptance físico dos mesmos bytes.

Referências oficiais:
- Microsoft Artifact Signing — signing integrations: https://learn.microsoft.com/azure/artifact-signing/how-to-signing-integrations
- Microsoft Entra — workload identity federation: https://learn.microsoft.com/entra/workload-id/workload-identity-federation
- Azure Login com OIDC no GitHub Actions: https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect

## Conexão local e segurança

O token mestre do Companion continua local em `State`, protegido para o usuário do Windows, mas deixou de ser uma tarefa de produto. A Web não pede copiar/colar esse segredo.

Quando o site encontra um Agent 0.3.14+ compatível, chama `POST /api/v1/session`. O Agent emite um bearer temporário, origin-bound, mantido somente em memória e armazenado internamente apenas por digest. Restart do Agent invalida a sessão. Não há cookie, query string de credencial, storage persistente do browser, log ou dado cloud.

A API continua somente em IPv4 loopback, com Host exato, Origin permitido e Bearer nos endpoints privados. A Web não envia path arbitrário do filesystem e não existe descoberta LAN/proxy cloud.

Antes de bootstrap/autorização, o listener local deve provar identidade TDA/API/versão conforme `companion-reliability.md`; HTTP 200 isolado não é suficiente. Companion anterior a 0.3.14 é apresentado como incompatível com a sessão automática, em vez de receber um request que não entende.

O ingest Craig da Web envia o ZIP diretamente para o loopback. O Agent recebe em streaming, limita tamanho, calcula SHA-256 durante a gravação, materializa um `source_id` content-addressed, usa o ingestor seguro existente e remove o ZIP temporário. O áudio não passa pelo cloud.

## Processamento real candidato

A v0.3 possui worker em subprocesso, job `transcription.craig`, ingest Craig browser→loopback, checkpoints por track, timeline comum, deduplicação conservadora entre tracks e turns canônicos em `tda_transcript_v1`.

Craig é materializado por `source_id` opaco; o worker recebe roots controlados pelo Agent. Speaker vem da track Craig, portanto diarização não é usada como substituto para informação que o pacote já fornece.

O output de engines diferentes converge para `tda_transcript_v1`. O texto integral permanece no artefato local; mensagens do worker e logs técnicos carregam apenas estado, métricas, hashes e códigos estáveis.

### Cleanup da fila e autoridade histórica

`Excluir da Fila` remove estado operacional terminal, mas não pode alterar a autoridade de um run imutável nem apagar a prova de uma submissão já aceita. Antes de remover a row de `jobs`, o Store grava atomicamente um receipt metadata-only com `job_id`, attempt, status terminal, disponibilidade de resultado e timestamp. As aliases de idempotência permanecem preservadas.

A visibilidade de Results usa essa ordem de evidência: fence `cancel` ou fence inválido falha fechado; attempt histórica só é autorizada por fence `commit`; um run pré-fence `succeeded` pode preservar sua visibilidade através do receipt criado no cleanup. Ausência simultânea de row, receipt e fence `commit` não é tratada como sucesso. Retry, restart ou cleanup nunca funcionam como prova implícita de commit.

O receipt não contém transcript, contexto, glossário, path local ou token. Ele é provenance operacional, não substitui `run.json`, não publica conteúdo e não é tombstone de exclusão editorial do resultado.

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

O **harness de aceite deste candidato** exige por padrão `RTX 4070`, porque a máquina física certificadora deste corte usa essa GPU. Isso não é uma restrição de produto: o Agent aceita a GPU local que cumpra o contrato CUDA e compute capability mínimo; um nome exato só é exigido quando o harness recebe `-RequireGpuName`. Para um subconjunto explícito:

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


## Revalidação instalada RTX 4070 — 2026-09-26 / #416

Por decisão explícita do usuário em 26/09, a investigação física da RTX 2080
fica adiada e pode ser reaberta com os detalhes de uma falha futura. O aceite
autorizado nesta rodada usa a RTX 4070 disponível; isso não certifica Turing nem
remove gates de compatibilidade. Não houve GPU SM 7.5 disponível nesta execução.

Os quatro perfis passaram em CUDA real na RTX 4070 Laptop 8 GB / driver 616.56,
com áudio sintético de 110,588 s. Qwen runtime 1.0.11 e Whisper 1.1.5 tiveram
os workers verificados contra seus manifests SHA-256 antes da execução. Qwen
fast/quality concluíram ASR e Forced Aligner em BF16 + SDPA; Whisper turbo/detailed
usaram FP16 sem fallback de memória. Nenhuma transcrição foi gravada.

| Perfil | ASR (s) | Alinhamento (s) | Pico GPU ASR (GiB) |
| --- | ---: | ---: | ---: |
| qwen-fast | 11,406 | 0,906 | 4,33 |
| qwen-quality | 12,359 | 0,828 | 6,74 |
| whisper-turbo | 5,094 | nativo | 4,14 |
| whisper-detailed | 7,766 | nativo | 6,00 |

[Receipts sanitizados dos runtimes instalados](evidence/rtx4070-installed-validation-2026-09-26.json)
registram hashes, versões, GPU, tempos e contagens, sem áudio, texto ou paths locais.
Esta evidência não representa teste da RTX 2080, avaliação editorial de qualidade,
validação de Craig longo, nem certificação de MSI/RC produzido pela main atual.
Não houve instalação, promoção de release, deploy ou publicação de transcript.

## Recuperação da preparação após reinício (#656)

O Agent mantém somente `State/preparation/latest.json`, um receipt sanitizado de até 4 KiB com identidade, etapa, sequência, timestamps, código seguro e predecessor opcional. O arquivo usa escrita temporária, fsync e substituição atômica; symlinks/junctions no diretório/arquivo são rejeitados. Não contém caminhos, tokens, URLs, áudio, transcrição ou contexto. A primeira gravação deve passar antes de iniciar a thread; falhas posteriores preservam o último snapshot válido e registram um código seguro no SystemLog.

No startup, uma operação `running` vira `interrupted` antes de servir a API. Terminais permanecem legíveis; um receipt corrompido não impede startup e produz `PREPARATION_RECEIPT_INVALID`. Nenhum receipt é autoridade de readiness: catálogo, seals de runtime/modelo e gate físico continuam sendo revalidados. Recovery de `.partial` e reconexão BITS permanecem nos mecanismos existentes.

A Web mostra a interrupção e oferece **Retomar preparação**, usando a fonte local anterior sem novo upload. A execução recebe novo `operation_id`; quando fonte/perfil coincidem, `resumes_operation_id` preserva a ligação. Cancelar a operação antiga nunca sinaliza a nova. Se o catálogo já estiver pronto, a nova operação apenas verifica a fonte e conclui sem download.

Compatibilidade e rollout: publicar primeiro a Web capaz de ler o estado adicional `interrupted`, depois o Companion; clientes antigos não reconhecem esse estado. Rollback do Companion pode ignorar o receipt, mas perde a explicação do reinício; preserve o arquivo e artefatos locais. Esta implementação não significa release instalada nem validação de download pesado real.

## Decisão de granularidade Whisper (#648, 2026-09-27)

**Decisão:** a unidade suportada de recuperação permanece a track inteira. Não anunciar retomada por segmento. Esta é a alternativa C da investigação #648: tornar a garantia explícita e testada, sem modificar silenciosamente qualidade, VAD ou coordenadas. Uma track interrompida recomeça do início; tracks integralmente commitadas e com assinatura compatível evitam nova inferência. Não há novo artefato parcial nem migração de runs.

A versão fixada no runtime é Faster-Whisper 1.2.1. A [implementação oficial dessa versão](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py) expõe `clip_timestamps`, mas aplica VAD apenas quando o clip é `"0"`; os clips selecionam seek sobre features, e o generator mantém estado temporal. O TDA usa VAD e word timestamps. Portanto, trocar para seek parcial não prova equivalência do pipeline atual. `condition_on_previous_text` já é false no TDA, mas isso não resolve VAD/mapeamento temporal e fronteiras lexicais.

Alternativas avaliadas: persistir segmentos e descartá-los depois de recomputar não economiza inferência; usar clip/seek muda a semântica de VAD; chunking independente precisa de contrato novo de ownership, fala cruzando bordas e mapeamento de timestamps. Nenhuma delas foi promovida como resume seguro nesta entrega. Isso não é uma alegação de impossibilidade técnica futura nem benchmark físico de qualidade.

Evidência reproduzível: `test_whisper_recovery_granularity.py` interrompe um generator após progresso da segunda track, por cancelamento e falha da engine. No retry, três unidades da primeira track são realmente evitadas; as três da track interrompida são executadas desde o prefixo. O resultado preserva seis segmentos e timestamps; novo retry totalmente cacheado chama a engine zero vezes. São contadores sintéticos de trabalho, não RTF de GPU. Testes existentes cobrem assinatura/contexto/runtime divergentes, corrupção de checkpoints e fast path. Não houve áudio privado ou alteração de engine/modelo.

Critério para reabrir a investigação: candidato que prove redução de inferência com VAD/word timestamps preservados, sem perda/duplicação em bordas, assinatura completa, cancel/crash e comparação física sobre fala/silêncio. Até lá, o custo de refazer a track corrente é uma limitação declarada. Rollback apenas remove esta documentação/cobertura; storage e processamento continuam iguais.


## Posição factual das janelas Qwen (#605)

`QWEN_WINDOW_TRANSCRIBED` inclui speaker normalizado, total de tracks e `start_seconds`/`end_seconds` copiados da janela efetivamente processada. Os tempos são locais à faixa, antes do offset de sessão; não são estimados por índice nem representam alinhamento concluído. A apresentação identifica esse sistema de coordenadas. Campos adicionais são opcionais para consumidores de eventos históricos. A allowlist valida números finitos/bounded e continua descartando texto reconhecido, prompt, contexto, glossário e paths. Não há I/O extra, evento adicional ou transmissão cloud. Whisper mantém o contrato de segmento atual; timing por unidade pertence à instrumentação específica. Rollback pode omitir os novos campos sem reescrever histórico.