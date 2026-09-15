# Processamento local no Edit

> Status: ASR local implementado; arquitetura de runs/revisão/publicação aprovada; sync cloud ainda desativado
> Owner: Processamento UI/adapters (Painelzinho); API/export local: Motorzinho; importação cloud: Carteiro
> Última revisão: 2026-09-15
> Fonte de verdade: `src/features/edit/processing`, `src/app/edit/processamento`, `local-companion/tda_companion`, [spec de revisão/publicação](transcript-review-publication.md) e testes associados

`/edit/processamento` é a superfície operacional para conexão com o TDA Companion, ingest local de sessões Craig, fila local, telemetria e eventos. O processamento pesado e os áudios permanecem no computador do usuário; o site cloud não depende do PC estar ligado para continuar disponível.

O contrato editorial pós-processamento é definido em [Transcrição — runs locais, revisão, comparação e publicação versionada](transcript-review-publication.md) e em ADR-0016. A regra central é: **concluir ASR não publica nada**.

## Estado atual

A base vigente e o candidato 0.3.5 desta entrega cobrem:

- workbench próprio do Edit;
- conexão explícita com `http://127.0.0.1:8765/api/v1`;
- fila local persistida;
- eventos estruturados para log;
- telemetria best-effort de CPU, RAM, GPU e VRAM;
- aplicativo Windows `TDACompanion.exe`;
- instalador `TDACompanion-x64.msi` por usuário;
- link controlado pelo próprio TDA para baixar a versão instalável mais recente do Companion;
- ingest seguro de ZIP Craig pelo loopback local, com staging content-addressed e metadados sanitizados;
- submissão real de `transcription.craig` ao pipeline canônico do Companion;
- fluxo Desktop equivalente, com picker nativo, participantes, perfis de qualidade e acompanhamento do job;
- perfis atuais `qwen-quality`, `qwen-fast`, `whisper-detailed` e `whisper-turbo`, derivados das capabilities anunciadas pelo Agent;
- escrita local atômica de transcript somente após conclusão/validação do worker;
- **múltiplos runs concluídos imutáveis por source**, identificados por job + attempt;
- `run.json` versionado com lineage, modelo/perfil, hashes e métricas factuais;
- espelho `staging/<source>/transcript.json` mantido somente para compatibilidade 0.3.x, sem ser a fonte de verdade;
- migração não destrutiva de `transcript.json` legado válido para run histórico;
- endpoint local autenticado `GET /api/v1/sources/<source_id>/runs` com apenas metadados sanitizados;
- resultado do job com `sync.status = "not_configured"`.

O processamento Craig já é ASR real ponta a ponta no Web e no Desktop. `synthetic.fixture` continua existindo somente como ensaio sintético quando anunciado. Sincronização/publicação cloud permanece desativada: conclusão local não implica importação, revisão, canon ou publicação.

### Versão instalável versus candidato de código

Na fotografia anterior a esta entrega, a versão pública instalável é o **TDA Companion 0.3.4 RC**. Como o Slice 1 altera os bytes do Companion, esta entrega sobe a linha de código para **0.3.5** em vez de reutilizar a identidade do RC 0.3.4.

`0.3.5` só passa a ser versão instalável quando o candidato for integrado em `main` e o pipeline de release publicar o RC correspondente a esses bytes exatos. Merge/PR não deve ser descrito antecipadamente como release publicada.

O pipeline continua com Whisper runtime 1.1.1 e Qwen runtime 1.0.1 até novo runtime versionado. Gate físico por perfil continua obrigatório quando o contrato de release exigir evidência da GPU real.

## Runs locais imutáveis — Slice 1

O Slice 1 implementa a fundação de **múltiplos runs por source**, sem overwrite entre Qwen/Whisper/retries.

Layout efetivo deste corte:

```text
Data/staging/craig-<source_sha>/
  manifest.json
  tracks/...
  transcript.json                 # somente mirror de compatibilidade 0.3.x
  runs/
    run-<job_id>-a1/
      transcript.json             # output bruto imutável
      run.json
    run-<job_id>-a2/
      transcript.json
      run.json
```

O uso de `staging/<source>` neste primeiro corte preserva o package root já consumido pelos engines e evita mover tracks/fontes durante a introdução do novo lifecycle. Não existe rotina automática que transforme `transcript.json` da raiz em fonte autoritativa: os diretórios de run são a evidência persistida.

Regras implementadas:

- nova tentativa ASR cria `run-<job>-a<attempt>` distinto;
- run concluído anterior nunca é reescrito por novo processamento;
- `run.json` é escrito somente depois do transcript final e funciona como commit do run concluído;
- diretório parcial/sem `run.json` não aparece como resultado concluído;
- hash integral pode revalidar o transcript do run;
- a listagem normal valida estrutura/tamanho sem rehash pesado a cada poll; publish futuro deve voltar a verificar hash integral antes de confiar nos bytes;
- contexto e glossário são representados no manifest por SHA-256 neste corte, sem expor o texto na listagem;
- transcript legado válido é copiado byte a byte para um run histórico e o original é preservado;
- mirror da raiz cujo hash já corresponde a um run existente não cria falso run legado duplicado;
- transcript legado inválido/corrompido não é promovido nem apagado automaticamente;
- a listagem local não retorna transcript integral nem caminho absoluto.

O endpoint de listagem já prepara a futura área **Resultados locais**, mas **a UI ainda não apresenta a biblioteca nesta etapa**. Revisão derivada, comparação A/B, archive/Trash e publicação revisionada permanecem nos slices seguintes da [spec dona](transcript-review-publication.md).

Exemplo de estado que a fundação passa a suportar:

```text
Craig source
  ├── Qwen Quality — concluído
  ├── Whisper Detailed — concluído
  ├── Qwen Quality + outro contexto — concluído
  └── tentativa interrompida — sem run concluído promovido
```

Cada run concluído preserva seu output bruto. Correções humanas futuras criarão revision derivada. A biblioteca local poderá comparar runs antes de publicar e continuará útil depois da primeira publicação para reprocessar, substituir ou restaurar conteúdo.

## Download e instalação

A tela de Processamento oferece uma ação compacta **Baixar TDA Companion** para Windows x64. O href fica sob controle do próprio TDA:

```text
/api/downloads/companion/windows
```

O resolver consulta releases públicas do repositório e escolhe a **maior versão instalável válida** entre:

- Stable `companion-vX.Y.Z`;
- RC/prerelease `companion-rc-vX.Y.Z-<source_sha12>`.

Para a mesma versão, Stable tem preferência sobre RC. Drafts e releases sem o asset/checksum esperado são recusadas. A UI exibe versão + canal e o download fica preso ao **tag exato** selecionado, evitando mostrar uma versão e baixar bytes de outra release concorrente.

Releases `prod-*` do site e runtimes auxiliares não entram nessa seleção.

Assim o frontend não depende de `/releases/latest` global nem de versão hardcoded.

O MSI instala em `%LOCALAPPDATA%\TDA\Companion`, mantém dados sob `%LOCALAPPDATA%\TDA` e cria atalho no Menu Iniciar. O antigo `DnDScribeCompanion.exe` não é usado, consultado ou modificado.

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
8. estado de sincronização/publicação.

Quando a biblioteca de runs entrar na UI, **fila operacional** e **resultados editoriais concluídos** devem continuar conceitos visualmente distintos. Um run antigo não pode parecer trabalho ainda em execução.

O título é compacto. A navegação própria do Edit é restrita a destinos de trabalho; o logo TDA é a saída intencional para a superfície pública.

O estado desconectado não deve inventar dados. Métricas desconhecidas usam `—`/estado vazio e o pareamento fica disponível. Quando conectado, o campo de pareamento deixa de dominar a tela e a faixa do computador passa a mostrar dados operacionais.

## Ingest Craig e perfis

A superfície Web envia o ZIP Craig somente para o Agent em loopback. O Companion cria um snapshot local, calcula identidade por conteúdo e reutiliza staging existente quando seguro. O frontend recebe apenas metadados necessários ao trabalho; caminho absoluto do disco não deve ser exposto ao JavaScript.

O Desktop usa o mesmo pipeline canônico: escolhe o ZIP por picker nativo, mostra participantes/faixas e submete `transcription.craig`. Não existe um transcriber legado paralelo.

Os perfis executáveis vêm de `capabilities`:

- `qwen-quality` — melhor precisão e opção recomendada;
- `qwen-fast` — Qwen priorizando velocidade;
- `whisper-detailed` — Whisper com maior qualidade;
- `whisper-turbo` — Whisper priorizando velocidade.

Qwen prepara runtime/modelos e executa o gate necessário antes do job. Para aceitação física, uma faixa Craig suficientemente longa pode gerar uma janela temporária de 180 s escolhida por energia; essa amostra é local e removida após o gate. O receipt do gate não deve carregar transcript integral.

## Progresso e dados editoriais

A UI usa somente progresso que o Companion realmente reporta. `completed/total/unit` pode ser convertido em porcentagem quando esses valores existem; ausência de medida não vira estimativa.

A tela não inventa título, resumo, thumbnail ou classificação. Dados como duração, quantidade de arquivos, participantes, data e contagem de palavras entram somente quando a fonte real os fornecer.

O pipeline real pode fornecer contexto por track, incluindo `track`, `total_tracks`, `speaker` e `percent`. A interface deve refletir o paralelismo realmente executado pelo engine e não simular múltiplas faixas avançando ao mesmo tempo quando isso não estiver acontecendo.

Depois do término, métricas como palavras, segmentos, warnings, elapsed/RTF, modelo/revision e percentual revisado podem alimentar a auditoria local definida na spec de revisão. Campo ausente continua desconhecido; não se fabrica nota de qualidade.

## Eventos e zueira

`GET /api/v1/jobs/{job_id}/events` fornece eventos factuais. A camada de apresentação pode adicionar comentários leves e engraçados, mas a telemetria original permanece separada.

Exemplos:

- `TRACK_PROGRESS` com speaker conhecido pode gerar uma segunda linha divertida sobre a voz daquele participante;
- redução de ruído só pode gerar piada sobre chiado se a etapa real existir;
- conversa ao fundo só aparece depois de uma detecção real;
- cachorro só aparece depois de um evento real correspondente.

O Companion persiste fatos, não piadas. A interface nunca deve fingir que executou uma operação só para ficar engraçada.

## Telemetria

Quando `system.telemetry` é anunciado, a UI consulta `GET /api/v1/system` e recebe uma projeção limitada de SO, CPU, RAM e GPUs. CPU/RAM usam `psutil`; NVIDIA GPU/VRAM usam NVML através de `nvidia-ml-py`.

Ausência de GPU NVIDIA, driver incompatível ou falha do sensor resulta em telemetria parcial e não desconecta a fila.

## Pareamento e segurança

O painel começa desconectado e não sonda portas automaticamente. Após ação explícita, consulta health público mínimo, exige versão compatível e então usa o Bearer do pareamento em endpoints privados.

O token fica somente na memória da aba. Não há cookie, storage, query string, log ou envio cloud. Requests mantêm CORS, `credentials: omit`, `redirect: error`, `cache: no-store`, `referrerPolicy: no-referrer` e limites de payload/resposta.

O Companion escuta somente loopback, exige Host correto, restringe Origin e não descobre outros PCs.

Antes de enviar Bearer para um Agent encontrado no loopback, o Desktop empacotado também valida ownership local de porta/PID/executável conforme o hardening vigente.

Áudio Craig e artefatos de preparação permanecem locais. O resultado Web não transporta transcript integral para frontend/cloud como efeito colateral do processamento.

## Fila e ações

Falha recuperável/interrupção permite **Repetir trabalho**, sem prometer checkpoint exato. Cancelar exige confirmação. Retomar fila confirma que trabalhos pendentes podem voltar a executar; pausar impede novos claims sem interromper o trabalho já ativo.

No Slice 1, retry terminalizado cria nova `attempt` e, portanto, identidade de run distinta. Continuar o mesmo run só poderá ser introduzido quando a semântica de checkpoint do engine for explicitamente segura. Resultado concluído anterior nunca é substituído por uma tentativa nova.

O ensaio sintético existe apenas quando `synthetic.fixture` é anunciado e não usa áudio/modelo/GPU para produzir transcrição.

## Resultado, revisão e publicação

A direção de UX após conclusão é:

```text
Processamento concluído
Resultado salvo localmente.
Nada foi publicado no TDA.

[ Revisar resultado ]
[ Comparar ]
[ Processar novamente ]
[ Publicar no TDA ]
```

O Slice 1 implementa a persistência/listagem local necessária para essa UX, mas **não habilita ainda esses controles editoriais na interface**.

Publicação futura deve consumir **resultado/revision aprovado**, não o evento terminal do worker.

Depois de publicado, o mesmo source continua podendo gerar novos runs. A revisão ativa no site permanece intacta até uma nova publicação/substituição ser confirmada.

## Sincronização

A UI atual continua mostrando **Sincronização não configurada.** Conclusão local não significa envio, importação, revisão, canon ou publicação.

O handoff futuro passa a ser explicitamente:

```text
run concluído
  -> revisão/comparação local
  -> ação Publicar
  -> identidade server-side
  -> autorização explícita
  -> persistência de revision completa
  -> receipt/readback
  -> ativação atômica da revision
```

A candidata histórica de transcript import contém primitives úteis de hash/idempotência/atomicidade, mas deve ser adaptada a esse lifecycle antes de ser ativada.

## Retenção e armazenamento

Neste Slice 1, runs concluídos e source/staging permanecem locais até ação futura explícita de cleanup. Não foi adicionada limpeza automática de runs.

Trash de 7 dias, archive e painel de armazenamento pertencem ao Slice 6. Quando entrarem, limpeza de source não poderá apagar transcrições concluídas implicitamente e deverá explicar quando novo processamento exigirá selecionar o ZIP Craig novamente.

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
- rollback/upgrade/preserve/purge quando o workflow correspondente for afetado;
- gates dos artifacts Whisper/Qwen e dependency freshness no SHA candidato.

Cobertura específica do Slice 1 inclui:

- dois runs do mesmo source coexistindo sem overwrite;
- retry/attempt com identidade distinta;
- mirror de compatibilidade mudando sem mutar run anterior;
- migração legada idempotente e não destrutiva;
- legado inválido sem promoção/delete implícito;
- tamper detectado por hash integral;
- listagem sanitizada sem transcript/path local;
- worker reprocessando sem criar falso run legado a partir do mirror;
- boundary HTTP de runs com autenticação/CORS estreitos.

Slices futuros devem acrescentar testes para:

- revisão sem mutar output bruto;
- comparação A/B por speaker/timeline;
- publish explícito/idempotente;
- substituição preservando anterior;
- restore/unpublish/delete conforme escopo;
- ausência de áudio bruto em payload cloud.

Esses testes automatizados não substituem o gate de qualidade/desempenho em GPU física. A aprovação física final dos perfis que a exigem deve registrar runtime/model revision, GPU/VRAM observada, elapsed/RTF e avaliação qualitativa adequada ao perfil.
