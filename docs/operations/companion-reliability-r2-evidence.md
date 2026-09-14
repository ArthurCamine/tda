# TDA Companion — Reliability R2 evidence

Status: implementação em `companion-reliability-r2`, PR #274 draft e empilhada sobre R1. Este documento registra o contrato implementado e os gates automáticos; não representa autorização para publicar em `Preview`, `main` ou canal stable.

## Escopo concluído no branch

### C-04 — transporte de rede explícito

- loopback usa transporte sem proxy para `127.0.0.1`;
- Internet preserva proxy/configuração do usuário;
- falhas externas são classificadas em códigos estáveis: `OFFLINE`, `DNS_FAILED`, `PROXY_FAILED`, `CONNECT_TIMEOUT`, `TLS_FAILED`, `HTTP_ERROR`, `MANIFEST_INVALID` e `HASH_MISMATCH`;
- a fronteira Desktop converte esses códigos em mensagens de produto em português, mantendo o código técnico entre colchetes para suporte.

### C-05 — manifest stable sem janela stale

- manifests de Companion e runtimes são consultados sem cache stale;
- a versão escolhida pelo manifest determina a URL do asset exato;
- o fluxo não pode verificar a versão N e depois resolver novamente um endpoint `latest` que já possa apontar para N+1;
- Whisper segue o mesmo contrato version-locked;
- Qwen mantém partes imutáveis/versionadas com tamanho e SHA-256 conferidos.

A instalação stable atualmente publicada ainda pode expor o contrato anterior. O gate físico de um RC R2 deve usar um ambiente web que já contenha o contrato C-05 correspondente; não se deve interpretar incompatibilidade com o endpoint stable anterior como defeito do binário R2.

### C-06 — manutenção observável e correlacionada

Update e uninstall recebem `operation_id` único. O helper grava journal atômico persistente em `Cache/maintenance`, incluindo:

- ação e estado atual;
- estágio e `failure_stage`;
- código de erro sanitizado;
- exit code do MSI quando aplicável;
- versão alvo e informação de purge;
- caminho conhecido de log verbose do MSI no receipt técnico.

O processo pai/UI deve encerrar dentro do prazo. Timeout é falha terminal: o helper não prossegue silenciosamente com manutenção destrutiva.

O Desktop só considera a operação aceita depois de observar o journal do mesmo `operation_id`. Se o handoff não aparecer ou já nascer falho, a UI permanece aberta e recebe erro de handoff.

O helper usado pelo Desktop é copiado para uma pasta temporária fora de `%LOCALAPPDATA%\TDA`, permitindo que purge completo remova a árvore TDA sem o helper tentar apagar o executável que está em uso.

### C-07 — MajorUpgrade com rollback comprovado

O MSI usa `MajorUpgrade` com `Schedule="afterInstallInitialize"`, colocando a remoção do produto anterior dentro da transação do Windows Installer.

O build produz, apenas para teste, um MSI rollback-probe com falha artificial agendada depois de `RemoveExistingProducts`. Esse probe não faz parte dos artifacts publicados.

O lifecycle gate usa a release real `companion-v0.2.0`, presa ao SHA-256 conhecido, e prova a sequência:

1. instalar 0.2.0;
2. semear State/Data/Logs/Cache/Models/Runtime e pairing token;
3. executar upgrade artificial que falha após remover a versão antiga;
4. confirmar que o rollback restaura o contrato histórico real da 0.2.0 e que nenhum executável candidato permanece;
5. executar o MajorUpgrade real para o candidato;
6. provar uninstall preservando dados;
7. reinstalar e provar purge completo.

A baseline compara o estado real da 0.2.0, inclusive campos de Registry que historicamente eram ausentes, em vez de projetar o contrato do MSI moderno sobre uma release antiga.

### C-08 — WebView2 oficial

A detecção deixou de enumerar genericamente produtos EdgeUpdate procurando texto `webview2`.

O diagnóstico usa o client GUID oficial do WebView2 Runtime:

`{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`

No Windows x64 são consultados:

- `HKCU\Software\Microsoft\EdgeUpdate\Clients\{GUID}`;
- `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{GUID}`.

Em Windows 32-bit, HKLM usa `SOFTWARE\Microsoft\EdgeUpdate\Clients\{GUID}`. O valor `pv` precisa representar versão não-zero.

Além disso, enquanto a interface está rodando com `gui="edgechromium"`, o próprio renderer ativo é tratado como evidência positiva. Assim uma UI WebView2 já aberta não pode reportar runtime ausente apenas porque uma leitura do Registry foi bloqueada ou está inconsistente.

### C-09 — diagnóstico por capability

Os checks brutos continuam disponíveis, mas readiness passa a ser agregado por capability:

- `core`: Agent, State/Data, SQLite e espaço em disco;
- `network`: DNS, HTTPS, manifest stable e asset;
- `maintenance`: metadados MSI, helper e canal de update;
- `whisper`: runtime/CUDA e modelos Whisper;
- `qwen`: runtime/CUDA, modelos, aligner e gate físico por perfil.

Semântica:

- `blocked` / `blocker`: a capability não possui caminho utilizável;
- `degraded`: existe caminho utilizável com limitação;
- `ready` / `info`: pronta para uso.

Regras importantes:

- falha de rede não derruba processamento local já preparado;
- falha de DNS local isolada degrada, mas não bloqueia rede se HTTPS/manifest/asset funcionarem por proxy;
- um único perfil Whisper pronto mantém Whisper utilizável;
- um único perfil Qwen com modelo + aligner + gate válido mantém Qwen utilizável;
- readiness global falha quando `core` está bloqueado ou quando ambos os motores ASR estão bloqueados;
- capability summaries são inseridos no topo da lista de checks para a UI responder primeiro o que impede processamento ou update.

O probe do asset não depende de `HEAD`: ele usa `GET` com `Range: bytes=0-0`, valida o tamanho total contra o manifest por `Content-Range`/`Content-Length` e fecha a resposta sem consumir o MSI inteiro.

## Gates automáticos

O workflow Companion cobre Linux e Windows sintéticos, build do bundle, smoke do executável empacotado, MSI install/uninstall e lifecycle real com rollback/upgrade/preserve/purge.

O C-07 já foi comprovado em gate Windows com a falha artificial e rollback completo antes do upgrade real. C-08/C-09 possuem testes específicos para registry oficial WebView2, renderer ativo, semântica de capabilities, transporte de rede, verificação leve do asset e mensagens amigáveis na fronteira Desktop.

Antes de considerar R2 homologado, o head final da PR deve ficar verde em todos os gates aplicáveis e o gate físico/RC continua sendo uma etapa independente conforme R1/R3. CI verde não substitui aceite físico.

## Fora de escopo / próximos blocos

R2 não promove stable e não substitui os gates futuros de R3/R4. Permanecem separados:

- E2E do produto instalado dirigindo a mesma jornada do usuário;
- RC imutável promovido para stable sem rebuild;
- DownloadManager/BITS para assets grandes;
- validação física de Craig/timeline/overlap e qualidade dos motores ASR.
