# Processamento local no Edit

> Status: implementação candidata
> Owner: Processamento UI/adapters (Painelzinho); API/export local: Motorzinho; importação cloud: Carteiro
> Última revisão: 2026-09-13
> Fonte de verdade: `src/features/edit/processing`, `src/app/edit/processamento`, `local-companion/tda_companion` e testes associados

`/edit/processamento` é a superfície operacional para conexão com o TDA Companion, ingest local de sessões Craig, fila local, telemetria e eventos. O processamento pesado e os áudios permanecem no computador do usuário; o site cloud não depende do PC estar ligado para continuar disponível.

## Estado atual

O recorte atual entrega:

- workbench próprio do Edit;
- conexão explícita com `http://127.0.0.1:8765/api/v1`;
- fila local persistida;
- eventos estruturados para log;
- telemetria best-effort de CPU, RAM, GPU e VRAM;
- aplicativo Windows `TDACompanion.exe`;
- instalador `TDACompanion-x64.msi` por usuário;
- link estável no próprio Processamento para baixar a release mais recente do Companion;
- ingest seguro de ZIP Craig pelo loopback local, com staging content-addressed e metadados sanitizados;
- submissão real de `transcription.craig` ao pipeline canônico do Companion;
- fluxo Desktop equivalente, com picker nativo, participantes, perfis de qualidade e acompanhamento do job;
- perfis atuais `qwen-quality`, `qwen-fast`, `whisper-detailed` e `whisper-turbo`, derivados das capabilities anunciadas pelo Agent.

O processamento Craig já é ASR real ponta a ponta no Web e no Desktop. `synthetic.fixture` continua existindo somente como ensaio sintético quando anunciado. Sincronização/publicação cloud permanece não configurada, e conclusão local não implica importação, revisão, canon ou publicação.

O candidato 0.3.2 usa Whisper runtime 1.1.1 e Qwen runtime 1.0.1. O gate físico Qwen continua obrigatório por perfil antes de declarar aprovação física do candidato.

## Download e instalação

A tela de Processamento oferece uma ação compacta **Baixar TDA Companion** para Windows x64. O href fica sob controle do próprio TDA:

```text
/api/downloads/companion/windows
```

O resolver consulta as releases públicas do repositório, filtra apenas tags `companion-vX.Y.Z`, exige o asset `TDACompanion-x64.msi` e redireciona para a maior versão válida. Releases `prod-*` do site não entram nessa seleção.

Assim o frontend não precisa conhecer a versão atual nem depender de `/releases/latest` global do repositório.

O MSI instala em `%LOCALAPPDATA%\TDA\Companion`, mantém dados em `%LOCALAPPDATA%\TDA\Data` e cria atalho no Menu Iniciar. O antigo `DnDScribeCompanion.exe` não é usado, consultado ou modificado.

O MSI deste corte ainda não possui assinatura Authenticode configurada; a interface não deve afirmar que existe publisher assinado.

## Workbench de processamento

A tela segue a regra de que uma superfície operacional deve mostrar primeiro o trabalho. A primeira viewport prioriza:

1. computador local e estado da conexão;
2. CPU/RAM/GPU/VRAM quando conectadas;
3. sessão Craig selecionada e perfil de processamento;
4. resumo da fila;
5. trabalho em execução e progresso real;
6. próximos trabalhos e finalizados;
7. detalhes e log do trabalho observado;
8. estado de sincronização.

O título é compacto. A navegação própria do Edit é restrita a destinos de trabalho; o logo TDA é a saída intencional para a superfície pública.

O estado desconectado não deve inventar dados. Métricas desconhecidas usam `—`/estado vazio e o pareamento fica disponível. Quando conectado, o campo de pareamento deixa de dominar a tela e a faixa do computador passa a mostrar dados operacionais.

## Ingest Craig e perfis

A superfície Web envia o ZIP Craig somente para o Agent em loopback. O Companion cria um snapshot local, calcula identidade por conteúdo e reutiliza staging existente quando seguro. O frontend recebe apenas metadados necessários ao trabalho; caminho absoluto do disco não deve ser exposto ao JavaScript.

O Desktop usa o mesmo pipeline canônico: escolhe o ZIP por picker nativo, mostra participantes/faixas e submete `transcription.craig`. Não existe um transcriber legado paralelo.

Os perfis executáveis vêm de `capabilities`. No candidato atual:

- `qwen-quality` — melhor precisão e opção recomendada;
- `qwen-fast` — Qwen priorizando velocidade;
- `whisper-detailed` — Whisper com maior qualidade;
- `whisper-turbo` — Whisper priorizando velocidade.

Qwen prepara runtime/modelos e executa o gate necessário antes do job. Para aceitação física, uma faixa Craig suficientemente longa pode gerar uma janela temporária de 180 s escolhida por energia; essa amostra é local e removida após o gate. O receipt do gate não deve carregar transcript integral.

## Progresso e dados editoriais

A UI usa somente progresso que o Companion realmente reporta. `completed/total/unit` pode ser convertido em porcentagem quando esses valores existem; ausência de medida não vira estimativa.

A tela não inventa título, resumo, thumbnail ou classificação. Dados como duração, quantidade de arquivos, participantes, data e contagem de palavras entram somente quando a fonte real os fornecer.

O pipeline real pode fornecer contexto por track, incluindo `track`, `total_tracks`, `speaker` e `percent`. A interface deve refletir o paralelismo realmente executado pelo engine e não simular múltiplas faixas avançando ao mesmo tempo quando isso não estiver acontecendo.

## Eventos e zueira

`GET /api/v1/jobs/{job_id}/events` fornece eventos factuais. A camada de apresentação pode adicionar comentários leves e engraçados, mas a telemetria original permanece separada.

Exemplos:

- `TRACK_PROGRESS` com speaker conhecido pode gerar uma segunda linha divertida sobre a voz daquele participante;
- redução de ruído só pode gerar piada sobre chiado se a etapa real existir;
- conversa ao fundo só aparece depois de uma detecção real;
- cachorro só aparece depois de um evento real correspondente.

O companion persiste fatos, não piadas. A interface nunca deve fingir que executou uma operação só para ficar engraçada.

## Telemetria

Quando `system.telemetry` é anunciada, a UI consulta `GET /api/v1/system` e recebe uma projeção limitada de SO, CPU, RAM e GPUs. CPU/RAM usam `psutil`; NVIDIA GPU/VRAM usam NVML através de `nvidia-ml-py`.

Ausência de GPU NVIDIA, driver incompatível ou falha do sensor resulta em telemetria parcial e não desconecta a fila.

## Pareamento e segurança

O painel começa desconectado e não sonda portas automaticamente. Após ação explícita, consulta health público mínimo, exige versão compatível e então usa o Bearer do pareamento em endpoints privados.

O token fica somente na memória da aba. Não há cookie, storage, query string, log ou envio cloud. Requests mantêm CORS, `credentials: omit`, `redirect: error`, `cache: no-store`, `referrerPolicy: no-referrer` e limites de payload/resposta.

O companion escuta somente loopback, exige Host correto, restringe Origin e não descobre outros PCs.

Áudio Craig e artefatos de preparação permanecem locais. O resultado Web não transporta transcript integral para o frontend/cloud como efeito colateral do processamento.

## Fila e ações

Falha recuperável/interrupção permite **Repetir trabalho**, sem prometer checkpoint exato. Cancelar exige confirmação. Retomar fila confirma que trabalhos pendentes podem voltar a executar; pausar impede novos claims sem interromper o trabalho já ativo.

O ensaio sintético existe apenas quando `synthetic.fixture` é anunciado e não usa áudio/modelo/GPU para produzir transcrição.

## Sincronização

A UI continua mostrando **Sincronização não configurada.** Conclusão local não significa envio, importação, revisão, canon ou publicação.

O handoff futuro permanece: artefato versionado → identidade server-side → autorização explícita → persistência durável → receipt consultável → revisão no Edit.

## Validação

Gates web:

```text
pnpm check
pnpm build
pnpm test:processing
```

Gates do Companion:

- pytest em Windows e Linux;
- build do wheel;
- build do `TDACompanion.exe`;
- build do `TDACompanion-x64.msi`;
- smoke do executável empacotado;
- instalação real do MSI no runner Windows;
- inicialização + health do app instalado;
- desinstalação real do MSI;
- gates dos artifacts Whisper/Qwen e dependency freshness no SHA candidato.

Esses testes automatizados não substituem o gate de qualidade/desempenho em GPU física. A aprovação física final dos perfis que a exigem deve registrar runtime/model revision, GPU/VRAM observada, elapsed/RTF e avaliação qualitativa adequada ao perfil.
