# Transcrição — runs locais, revisão, comparação e publicação versionada

> Status: arquitetura aprovada; implementação pendente
> Owner: Edit / processamento local / transcript-sync
> Última revisão: 2026-09-22
> Fonte de verdade: esta spec, ADR-0016, `local-companion/tda_companion`, `src/features/transcript-sync` e contratos do Edit

## Rollout Production — estado operacional

A fundação física de revisões completas, receipts, current pointer e capability está aplicada em Production. O runtime continua separado do schema por `TDA_TRANSCRIPT_PUBLICATION_ENABLED`.

O rollout governado deve:

- habilitar a flag somente no artefato staged;
- provar em `/api/health` que `features.transcriptPublication=true`;
- promover exatamente o artefato testado;
- repetir a prova no domínio canônico;
- não publicar transcript automaticamente como parte do deploy;
- deixar o primeiro publish real dependente de revisão `approved_local`, confirmação humana e identidade/capability válidas.

Rollback lógico começa desligando a flag; revisões, receipts e eventos já persistidos não são apagados para simular rollback.

## Contratos de revisão validados em candidato — 2026-09-26

As correções de #664, #667, #670 e #652 preservam a identidade editorial:

- O Agent valida o conjunto por `(track_number, segment_id)` e reconstrói a ordem
  da base imutável ao salvar. Reordenar sem editar é um no-op: não muda bytes,
  revisão ou SHA. Drafts históricos mantêm a ordem e SHA reais na leitura; uma
  edição posterior passa a persistir na ordem da base, sem migração silenciosa.
- A publicação canonicaliza por `(track_number, start, end, segment_id)` antes do
  hash; o desempate do ID é lexical e independente de locale. Campos editoriais
  não participam da ordenação. A UI pode projetar outra ordem sem mudar o snapshot.
- `count_words_v1` conta sequências separadas pelo conjunto fixo Unicode
  White_Space: U+0009–000D, 0020, 0085, 00A0, 1680, 2000–200A, 2028, 2029, 202F,
  205F e 3000. U+001C–001F e FEFF não são separadores. Python, prévia Web e servidor
  usam a mesma regra e fixture `fixtures/transcript-review-words-v1.json`. Texto,
  normalização e limites editoriais não são alterados por essa contagem.
- O total de warnings deriva do transcript validado completo. A resposta limita
  a lista aos primeiros 1.000 e declara `warning_summary` com `total_count`,
  `displayed_count` e `truncated`. A Web mostra o total e no máximo 50 tipos. Sem
  essa metadata, o total histórico fica explicitamente não verificado. Publicação
  recebe o equivalente camelCase opcional, valida sua consistência e persiste
  somente a contagem factual; não adiciona o texto dos warnings ao payload cloud.
- Exceção de transporte, `dependency_unavailable`, JSON inválido ou receipt
  malformado no POST levam a uma consulta lookup-only com body byte-idêntico.
  Receipt ausente/indisponível mantém `unconfirmed`. Rejeições definitivas continuam
  definitivas e receipt de outra identidade é rejeitado. Sobrevivência da intenção
  ao reload permanece no escopo de #638.

Compatibilidade e publicação: implantar servidor/Web com suporte ao campo
opcional antes de liberar o Companion que o emite. Clientes anteriores sem o
campo continuam aceitos. Uma operação já iniciada não deve trocar de versão de
canonicalização no meio do replay; antes da promoção, reconciliar intenções
pendentes e preservar receipts existentes. Não há DDL, rewrite de histórico ou
publicação editorial como parte desta entrega. Rollback deve manter a leitura do
campo opcional enquanto houver Companions novos instalados; não remover receipts.

Evidência local: suíte Python 819 passed / 5 skipped; regressões compartilhadas de
Unicode, reorder sem escrita, totais 0/1/999/1000/1001/5000 e publicação ambígua.
Navegador desktop 1440px e mobile 390px: total 5.000, projeção limitada, fallback
histórico, contagem NEL, sem overflow horizontal ou erro de página. O estado aqui
é de candidato; merge e release exigem evidências independentes.

## Objetivo

### Preservação de legados e listagem — candidato #674

A classificação do `transcript.json` raiz ocorre na manutenção de startup e antes
de qualquer substituição pelo mirror, sob o mesmo lock de arquivo entre processos
Agent/worker. A transcrição válida é preservada byte a byte em `legacy-<sha>` antes
do overwrite. Um commit encontrado após interrupção tem conteúdo e política de
gravação reconfirmados; a limitação Windows descrita abaixo continua aplicável.
Legados inválidos ficam intactos no lugar, com diagnóstico
`COMPATIBILITY_MIRROR_LEGACY_PRESERVED`. O novo run imutável continua disponível.
O reparo de staging também copia e confere esses bytes; falha de cópia impede
substituir a source antiga. Não há correção editorial automática de um legado.

`root-transcript-state.json` é uma projeção pequena versionada com fingerprint de
metadata e referência ao run preservado. A API expõe somente a classificação.
Projeção ausente, corrompida ou desatualizada exige manutenção; nunca autoriza
descartar bytes. Mesmo uma projeção forjada não permite overwrite sem validar e
preservar o conteúdo atual. Startup seguinte ignora sources já classificadas.

`GET /sources/<source>/runs` lê manifests/estado e stats de arquivo, sem abrir ou
hashear transcripts, criar drafts ou executar migração. O teste de 100 sources
instrumenta cada abertura e permite apenas `run.json` e o pequeno estado de raiz:
zero bytes de conteúdo de transcript lidos. O N+1 de requests e a paginação seguem
no escopo de #661. O mirror permanece para consumidores legados; não se remove
nenhum consumidor nesta entrega. Rollback não deve reinstalar um writer que
sobrescreva raiz não preservada; manter o gate ou suspender atualização de mirrors.

### Política central de gravação — candidato #671

`atomic_storage.atomic_write` separa três classes versionadas. Os callers continuam
donos de confinement, schema, locks e CAS; o helper não transforma paths externos
em autorização de escrita.

| Classe | Uso | Fence e recuperação |
| --- | --- | --- |
| `authoritative` | transcript do run, `run.json`, draft/backup de reparo, publication target e futuros sidecars de approval/intent/tombstone | Conteúdo sincronizado antes de replace; política de namespace por plataforma. Falha depois de replace é inconclusiva. |
| `projection` | índice/summary/cache reconstruível | Visibilidade atômica, sem prometer durabilidade; ausente ou stale exige reconstrução. |
| `checkpoint` | opt-in para checkpoints que usam o helper | File sync + replace; um último checkpoint perdido exige refazer trabalho. Os codecs/validação ASR existentes continuam donos da retomada. |

POSIX (`posix_file_and_namespace_sync_v1`): temp exclusivo no diretório de destino,
write completo, flush/fsync do arquivo, replace e fsync de cada diretório ancestral
até a raiz. Isso cobre também uma cadeia criada nessa operação ou deixada por uma
tentativa anterior. Erro de directory sync, inclusive `EINVAL` em filesystem sem
suporte, não é ignorado. Não há fallback silencioso para uma garantia menor.

Windows (`windows_file_sync_write_through_v1`): file fsync seguido de
`MoveFileExW(REPLACE_EXISTING | WRITE_THROUGH)` no mesmo diretório/volume. Não usa
copy/delete, move no reboot, flush de volume nem privilégio administrativo. A API
[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)
descreve write-through, com garantia explícita de flush para copy/delete; isso não
estabelece aqui um equivalente geral a directory fsync para rename/criação de
ancestrais. Portanto o baseline local NTFS tem conteúdo sincronizado e replace
solicitado com write-through, **sem afirmação de confirmação plena após power loss**.
Não se usa um erro ignorado de
[FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)
em diretório para fingir essa garantia. Network shares, FAT/exFAT e falhas de
controladora não têm garantia adicional implícita.

O helper retorna o nome da política, nunca um booleano genérico `durable=true`.
Um erro contém somente stage/código sanitizado e `ambiguous`. Antes do replace,
destino antigo permanece intacto. Após replace/fence inconclusivo, não há write
compensatório nem remoção do destino; partial temporário nunca é promovido por
recovery. O Agent retorna `LOCAL_REVIEW_WRITE_UNCONFIRMED`, preserva a cópia editada
na tela e exige readback/conferência antes de retry. SHA/revision CAS evita que um
retry obsoleto apague um save que já aconteceu. Readback prova bytes/schema visíveis,
não retroativamente a durabilidade diante de falha elétrica.

Ordenação de run: transcript completa sua política antes de `run.json`. Falha
inconclusiva preserva evidência incompleta; um diretório sem marker não aparece
como completed. Um marker presente é relido com validação de SHA/schema. Cleanup
posterior de diretório comprovadamente incompleto continua uma ação do lifecycle,
nunca compensação imediata de um write incerto. O worker emite código estável
`LOCAL_WRITE_UNCONFIRMED` e não declara sucesso do job sem a confirmação.
Fences de cancel/commit mantêm O_EXCL e file sync; acrescentam o fence POSIX de
namespace, preservando o marcador em erro posterior. Replays sincronizam antes de
retornar. No Windows, essa criação exclusiva permanece explicitamente sob a
garantia mais fraca de file sync, sem directory fence.

Medição/validação: faults de temp-write, file-sync, replace e fence pós-replace;
ordem completa POSIX simulada no Windows e teste real condicionado a runner POSIX; native
write-through/readback local em NTFS. Teste físico de corte de energia/reboot
abrupto **não foi realizado** e não é pré-condição para alegar uma garantia que
esta entrega deliberadamente não oferece no Windows. Telemetria/eventos não
recebem fsync por frame; checkpoints ASR existentes não foram reescritos.

Rollout exige build dos runtimes porque transcript/run writers são compartilhados.
Rollback de código não apaga destinos/partials para simular sucesso; reabrir,
verificar integridade e manter a mesma identidade de operação. Novos sidecars
autoritativos devem usar essa política e registrar a garantia efetivamente obtida.

### Strings editoriais — candidato #668

`review_string_rules_v1` mede comprimento por valores escalares Unicode: texto
até 100.000, participante até 160. Surrogates isolados são inválidos. A verificação
de conteúdo não vazio usa exatamente White_Space de `count_words_v1`; não remove
espaços nem normaliza NFC/NFKC. Texto permite TAB/LF/CR e rejeita os outros controles
C0 e DEL. Participante rejeita todos os C0 e DEL. O mesmo fixture versionado
`fixtures/transcript-review-strings-v1.json` alimenta Agent, parser Web e contrato
cloud, incluindo limites ASCII/BMP/emoji, NEL, BOM, combinantes e controles.

O Agent aplica o contrato à vista da base e valida mutações antes de persistir.
A Web verifica antes do save e não usa o limite UTF-16 nativo como regra editorial:
os campos comportam até o dobro de unidades UTF-16 e a validação decide o limite
real. Strings aceitas preservam cada caractere no save, reopen e payload cloud.

**Reparo explícito de revisão antiga:** uma string incompatível num draft existente
retorna somente `LOCAL_REVIEW_LEGACY_STRING_REPAIR_REQUIRED`, sem o texto privado
no diagnóstico. A leitura não modifica o arquivo. Para reparar:

1. Fechar o Companion e preservar o data root. Abrir localmente o `draft.json`
   afetado, registrar sua revisão e SHA-256 exato; não enviar esse arquivo ao GitHub.
2. Preparar um JSON local com `{"segments": [...]}` contendo o conjunto completo
   de segmentos corrigidos. Manter identidades e timestamps; escolher explicitamente
   cada correção. Não apagar ou normalizar caracteres automaticamente.
3. No ambiente Python do Companion, executar
   `python tools/repair_local_review.py --data-root <root> --package-root <root/staging/source> --run-id <run> --expected-revision <n> --expected-sha256 <sha> --replacement-file <json-local>`.
   O comando exige package dentro do staging informado, adquire `RootLock` e recusa
   um Companion ativo. CAS e validação acontecem antes de qualquer substituição.
4. Conferir o resultado (somente revision/SHA/status), reabrir e revisar. A cópia
   `draft-before-repair-<sha>.json` preserva **os bytes originais** antes da troca.
   O reparo gera nova revisão em status `draft`, nunca herda aprovação.

Se a validação ou backup falhar, não há substituição do draft. Uma cópia preservada
não é prova de publicação nem de tolerância a falha elétrica (#671). Recuperação
manual mantém o original e a revisão reparada; não deve apagar a evidência.
Base imutável inválida continua recusada sem ser reescrita pelo reparador de draft.

Compatibilidade: promover Web/cloud com suporte aos limites escalares antes do
Companion novo. Reverter parsers para UTF-16 pode tornar revisões válidas ilegíveis;
manter leitores compatíveis no rollback, sem reescrever dados para ajustá-los.
Esta entrega não publica revisões, não migra o banco e não altera saída ASR.

### Snapshot e primeiro save — candidato #669 / #672

A resposta de revisão anuncia `snapshot_contract=tda_local_review_cas_v1`.
Sem arquivo de draft, GET retorna `persistence=ephemeral_base`, revisão/SHA/datas
nulos, status `draft` como estado editável da vista, e nenhum diretório/arquivo de
revisão é criado. A Web apresenta **Sem revisão salva**. Consultas repetidas
retornam a mesma vista sem atualizar timestamps ou resumo editorial persistente.

O primeiro POST explícito envia `expected={persistence: ephemeral_base,
base_transcript_sha256}`; sob os locks existentes, o Agent exige ausência real de
draft e base idêntica, valida o candidato e grava a primeira revisão **1**. Um save
explícito idêntico à base materializa o draft; a UI mantém Save desabilitado até
uma intenção editorial (editar, marcar revisão ou selecionar estado). Aprovar
localmente sem editar texto também exige esse save explícito. Approval independente
e vinculada ao SHA permanece no escopo de #660.

Para drafts persistidos, POST exige `expected={persistence: persisted,
draft_revision, draft_sha256}`. O SHA deriva dos mesmos bytes limitados por tamanho
que foram parseados. Revision ou SHA divergentes geram
`LOCAL_REVIEW_DRAFT_CONFLICT`, sem write. A Web transporta o baseline que originou
a cópia editada e verifica identidade source/run/base/revision/SHA antes do envio.
O primeiro save de uma segunda aba com precondition de ausência também conflita.
Draft histórico r0 continua **persistido**, com seu SHA real, sem migração na leitura.

Compatibilidade: ausência ou versão desconhecida do contrato nunca é wildcard.
Cliente antigo que envia somente revision recebe
`LOCAL_REVIEW_SNAPSHOT_CONTRACT_REQUIRED` (422). Web nova lê Agent anterior em
modo somente leitura, com instrução de atualização. Publicar uma vista ephemeral
é rejeitado no cliente. Promover Web compatível antes do Companion e pedir refresh
das abas antigas; não liberar o Companion antes dessa entrega coordenada.
Rollback exige manter o CAS até todas as versões que dependem dele serem retiradas;
reverter para revision-only afrouxa a proteção e não é um rollback transparente.
Nenhum draft histórico é removido e nenhum conteúdo é publicado nesta mudança.

Regressões sintéticas cobrem GET puro, save explícito sem edição, duas primeiras
escritas concorrentes, SHA alterado com revision igual, revisão zero histórica,
preconditions ausentes/inválidas, falha de replace e separação de runs. Os testes
de navegador verificam os estados ephemeral/persistido e Agent antigo sem edição.

### Integridade local validada em candidato — 2026-09-26

As correções de [#666](https://github.com/Faysk/tda/issues/666) e
[#673](https://github.com/Faysk/tda/issues/673) usam um snapshot único por operação
de revisão: leitura bounded, comparação de tamanho/SHA, parse dos mesmos bytes e
validação semântica completa. `save_review` reutiliza esse snapshot dentro da
ordem de locks existente (`RootLock` do Agent → `source_gate` → lock da revisão),
sem chamar a fachada de GET para carregar a base novamente.

`TranscriptDocument.from_dict` reconstrói o schema persistido sem coercionar IDs,
normalizar strings ou aceitar aliases dos workers. Valida engine, timestamps com
timezone, tracks, words, turns/referências, contagens e warnings. Campos opcionais
de v1 continuam usando os defaults declarados nos dataclasses; identidade, tracks,
engine, stats e demais campos obrigatórios não são inventados. Unicode inválido e
NUL são rejeitados. A regra editorial unificada entre Python/Web continua sendo
trabalho de [#668](https://github.com/Faysk/tda/issues/668).

Migração aceita somente documentos válidos e copia **os bytes originais** para o
run legado. Input inválido fica preservado no root, sem commit marker. Um run
histórico com conteúdo semanticamente inválido não abre revisão nem cria draft.
Metadata malformada é isolada na listagem: `runs` contém os summaries válidos e
`invalid_runs` traz somente `run_id`, `integrity=invalid` e reason code sanitizado.
Esse diagnóstico também cobre artefatos já promovidos por versões anteriores.
Não há repair/rewrite automático de arquivos históricos.

O probe sintético reproduzível está em
[`benchmark_review_snapshot.py`](../../local-companion/tools/benchmark_review_snapshot.py).
Medição local Windows/Python 3.12, comparada com `1550f438`, sem áudio/modelos:

| Segmentos | Bytes do transcript | Leituras antes/depois | Bytes lidos antes/depois | Save antes/depois | Crescimento RSS amostrado antes/depois |
| --- | --- | --- | --- | --- | --- |
| 7.500 | 1.688.052 | 4 / 1 | 6.752.208 / 1.688.052 | 0,094 s / 0,132 s | 9,6 MB / 8,8 MB |
| 100.000 | 23.223.058 | 4 / 1 | 92.892.232 / 23.223.058 | 1,361 s / 2,035 s | 139,9 MB / 137,7 MB |

Os tempos medem o save local completo, inclusive validação e escrita, que executa
sob o gate HTTP; não são uma medição de latência de rede ou contention real. RSS
é amostrado a cada 10 ms. Houve redução de I/O, **não speedup total demonstrado**:
a validação semântica nova custa CPU. Buffers são limitados ao tamanho observado
do arquivo + 1 byte para detectar crescimento, sem alocar o teto de 512 MiB em
cada read. O SHA deriva do buffer realmente parseado, nunca de outra abertura.

Estado: código e regressões no candidato; merge, release do Companion e uso em
Production precisam de evidências próprias. Esta alteração não publica conteúdo.

O TDA deve tratar transcrição como um **fluxo editorial revisável**, e não como um arquivo que se torna definitivo quando um modelo termina de processar.

A unidade de trabalho correta é:

```text
fonte Craig
  -> processamento local
  -> resultado local imutável
  -> revisão/comparação
  -> candidato aprovado
  -> publicação explícita
  -> revisão publicada versionada
```

O objetivo de produto é permitir experimentar com Qwen/Whisper, repetir o processamento com configurações diferentes, comparar resultados, corrigir trechos e decidir conscientemente o que merece ser publicado. Publicar não elimina a possibilidade de edição, substituição, restauração, remoção ou nova comparação posterior.

Este é um sistema para memória de campanha de RPG, não um sistema bancário. A robustez desejada é **proporcional ao projeto**: evitar perda de trabalho, estados parciais, sobrescrita acidental e ambiguidade entre local/publicado, sem introduzir infraestrutura de compliance que não agrega valor ao TDA.

## Estado atual e limite desta spec

Na `main` vigente nesta revisão:

- o Companion já faz ingest Craig local content-addressed;
- os perfis `qwen-quality`, `qwen-fast`, `whisper-detailed` e `whisper-turbo` existem no pipeline local;
- o worker grava `transcript.json` local somente ao terminar e usa escrita atômica;
- o resultado atual declara `sync.status = "not_configured"`;
- o endpoint cloud de importação continua deliberadamente negado em produção;
- concluir um job **não publica** e não envia transcript integral como efeito colateral;
- existe fundação server-side para leitura/edição de segmentos e existe uma candidata de importação atômica, mas ela não está ativada como fluxo produtivo.

Esta spec define o **contrato-alvo aprovado** para evoluir esse estado. Ela não declara que runs versionados, comparação A/B, revisions cloud ou lixeira já estão implementados. Nenhuma migration é autorizada apenas por este documento.

## Princípios de produto

### 1. Processar não é publicar

O fim de um job local significa apenas:

> processamento concluído; resultado disponível para revisão local.

Nunca significa automaticamente:

- sincronizado;
- importado;
- revisado;
- aprovado;
- publicado;
- canonizado.

A UI deve usar linguagem explícita, por exemplo:

```text
Processamento concluído
Resultado salvo localmente.
Nada foi publicado no TDA.
```

### 2. Resultado bruto de modelo é evidência, não documento editável

O output bruto de uma execução concluída é imutável. Se o usuário corrigir texto, speaker, timestamp ou outra informação editorial, nasce uma **revisão derivada**.

Isso preserva a resposta para perguntas simples e úteis:

- o que o Qwen realmente produziu?
- o que o Whisper realmente produziu?
- o que foi alterado manualmente?
- qual versão foi publicada?

### 3. Reprocessamento nunca destrói um resultado anterior

Rodar o mesmo Craig novamente, inclusive com o mesmo perfil, cria um novo `run`.

Exemplo:

```text
source craig-<sha>
  run A — qwen-quality — concluído
  run B — whisper-detailed — concluído
  run C — qwen-quality com outro contexto — concluído
  run D — qwen-fast — interrompido
```

Nenhum deles sobrescreve outro.

### 4. Publicação é uma escolha humana explícita

Somente uma ação intencional como **Publicar no TDA** pode criar ou ativar uma revisão cloud.

Warnings e revisão incompleta podem gerar confirmação, mas não precisam bloquear rigidamente a publicação: o produto é editorial e humano, não regulatório.

### 5. Publicado também pode evoluir

Após publicar, continuam válidas as ações:

- editar;
- criar nova revisão;
- reprocessar localmente;
- comparar com outro modelo;
- substituir a revisão atual;
- restaurar uma revisão anterior;
- remover publicação;
- excluir conteúdo quando apropriado.

Publicação não transforma a transcrição em objeto irreversível.

## Vocabulário canônico

### Source

Identidade do material de origem local. Para Craig, deriva do conteúdo do ZIP e permanece content-addressed.

Um `source` representa **a mesma gravação**, não uma tentativa de ASR.

### Run

Uma execução local específica do pipeline ASR.

Um run registra pelo menos:

- `run_id`;
- `source_id` / `source_sha256`;
- engine/família;
- profile;
- modelo e revision;
- runtime version;
- device/compute mode quando aplicável;
- contexto/glossário usados ou seus hashes;
- timestamps de início/fim;
- tempo de processamento;
- RTF quando mensurável;
- warnings;
- status terminal;
- hash do transcript final quando concluído.

O run é imutável depois de `completed`, `failed`, `cancelled` ou `interrupted` terminalizado.

### Local result

O `transcript.json` validado produzido por um run concluído.

É publicável somente se:

- o run terminou como `completed`;
- o schema é suportado;
- o transcript passa validação estrutural;
- o hash armazenado corresponde aos bytes finais;
- não é arquivo `.partial`;
- a origem ainda corresponde ao source esperado.

### Draft revision

Versão editorial local derivada de um local result ou de outra revision.

Pode conter:

- correções manuais;
- marcações de revisão;
- substituições de speaker;
- ajustes de texto/timestamp permitidos;
- notas locais de revisão;
- referência de lineage à base.

### Published revision

Versão persistida no cloud e elegível para ser a transcrição visível/ativa da sessão.

Conteúdo publicado é imutável. Uma edição posterior cria outra revision.

### Current revision

Revision cloud apontada como versão atualmente visível/ativa da sessão.

A sessão pode temporariamente ter `current_revision = null` quando a publicação for removida, preservando histórico conforme a operação escolhida.

### Publication event

Evento leve que registra mudança de estado de publicação, por exemplo:

- primeira publicação;
- ativação de nova revision;
- restauração de revision anterior;
- remoção de publicação;
- exclusão de revision inativa.

Não precisa formar uma cadeia criptográfica. Deve apenas permitir entender a sequência editorial relevante.

## Modelo de estados local

### Source

```text
preparing
  -> ready
  -> invalid
  -> deleted
```

### Run

```text
queued
  -> preparing
  -> running
  -> completed
  -> failed
  -> cancelled
  -> interrupted
```

`completed` é o único estado que pode produzir resultado publicável.

`interrupted` pode ser retomável somente quando o engine/checkpoint realmente suportar retomada segura. A UI não deve prometer resume exato quando houver apenas retry completo.

### Draft/revisão local

```text
draft
  -> reviewed
  -> approved_local
  -> published
  -> archived
  -> trashed
```

`approved_local` é útil como marcador humano, mas não é requisito rígido para publicar. Se a revisão não estiver marcada como aprovada, a UI pode pedir confirmação adicional.

## Armazenamento local alvo

O layout exato pode evoluir, mas deve manter a separação conceitual:

```text
%LOCALAPPDATA%\TDA\Data\transcriptions\
  sources\
    craig-<source_sha256>\
      source.json
      tracks\...
      runs\
        <run_id>\
          run.json
          transcript.json
          checkpoints\...
        <run_id>\
          run.json
          transcript.json.partial
      revisions\
        <revision_id>\
          revision.json
  trash\
```

Regras:

- source/tracks podem ser reutilizados entre runs;
- runs concluídos não são sobrescritos;
- um run em execução grava somente arquivos temporários/checkpoints próprios;
- transcript final usa rename/replace atômico após validação;
- `.partial` nunca é mostrado como resultado concluído;
- excluir um run não implica excluir automaticamente o source compartilhado;
- limpeza de source só ocorre quando não houver dependência que exija seus arquivos ou quando o usuário confirmar regenerabilidade/perda.

SQLite local pode manter o índice, estados, lineage e referências. O transcript completo continua adequado como arquivo versionado local; não é necessário colocar todo o texto no SQLite apenas para indexação.

## Identidade e deduplicação

O `source_id` permanece content-addressed. Selecionar exatamente o mesmo ZIP deve reutilizar a fonte/staging seguro.

A identidade de run **não** deve ser deduplicada apenas por source+profile. Duas execuções iguais ainda podem ser desejadas para:

- comparar regressão entre runtime/model revision;
- repetir após atualização de driver/runtime;
- testar mudanças no contexto;
- observar instabilidade;
- simplesmente tentar novamente uma transcrição que pareceu ruim.

A UI pode detectar configuração idêntica e avisar:

> Já existe um resultado concluído com esta configuração.

mas deve permitir **Processar novamente**.

## Configuração reproduzível por run

Cada run deve guardar informação suficiente para explicar o resultado sem armazenar segredos desnecessários:

```text
profile_id
engine
model
model_revision
runtime_id/runtime_version
alignment
language
compute mode
glossary/context ou hash + snapshot editorial apropriado
source_sha256
Companion version
```

Para contexto e glossário, o objetivo é reproduzir decisões editoriais. Como são textos de campanha e não secrets técnicos, podem ser preservados localmente junto ao run. Se houver razão de privacidade futura, a UI pode permitir omitir o texto e manter somente hash, mas isso não é requisito agora.

## Biblioteca local de resultados

A tela de Processamento deve evoluir de uma fila operacional para também possuir uma área de **Resultados locais**.

Exemplo:

| Resultado | Perfil | Estado | Tempo | Palavras | Warnings | Publicado |
| --- | --- | --- | ---: | ---: | ---: | --- |
| A | Qwen · melhor precisão | concluído | 38m | 18.432 | 7 | não |
| B | Whisper · detalhado | concluído | 29m | 18.201 | 16 | não |
| C | Qwen · rápido | interrompido 63% | 14m | — | — | não |

Ações por run concluído:

- Revisar;
- Comparar;
- Usar como base;
- Processar novamente;
- Duplicar configuração;
- Publicar;
- Arquivar;
- Excluir.

Ações por run incompleto:

- Retomar, quando comprovadamente suportado;
- Repetir;
- Ver erro/log;
- Excluir.

## Auditoria antes de publicar

A revisão deve otimizar o tempo humano. O usuário não deve ser obrigado a reler duas horas de sessão linearmente se o sistema consegue apontar áreas de atenção.

### Resumo factual

Mostrar quando disponível:

- duração da sessão;
- participantes/tracks;
- palavras;
- segmentos/turnos;
- engine/model/profile;
- model revision/runtime;
- tempo de processamento;
- RTF;
- device/GPU;
- warnings produzidos pelo pipeline;
- quantidade de trechos marcados como revisados.

Ausência de uma métrica deve aparecer como desconhecida, nunca inventada.

### Pontos de atenção

Quando os dados permitirem, destacar:

- baixa confiança;
- gaps temporais anormais;
- overlaps de speakers;
- segmentos sem palavras/timestamp esperado;
- termos do glossário com grafias divergentes;
- trechos sem correspondência em comparação A/B;
- diferenças grandes entre duas execuções;
- warnings do engine/alignment.

Esses itens são **atalhos de revisão**, não prova automática de erro.

### Progresso de revisão humana

Segmentos/turnos podem ter marcador local `reviewed`.

Exemplo:

```text
Revisão: 1.612 / 2.184 segmentos — 74%
Warnings não revisados: 7
```

A publicação pode continuar com revisão incompleta após confirmação explícita.

## Comparação entre modelos/runs

Comparação A/B é parte de primeira classe do produto.

### Alinhamento

Não usar diff textual puro como mecanismo principal. O TDA possui informação temporal e speaker por track.

A comparação deve alinhar preferencialmente por:

1. source idêntico;
2. speaker/track correspondente;
3. janela temporal sobreposta;
4. similaridade textual para resolver correspondências próximas.

Assim frases reordenadas ou segmentadas de maneira diferente não explodem artificialmente o diff.

### Modos de comparação

A UI deve oferecer pelo menos:

- lado a lado;
- somente divergências;
- navegação `anterior / próxima diferença`;
- filtro por participante;
- filtro por warning;
- faixa temporal.

### Métricas objetivas

Pode mostrar:

- palavras/segmentos por run;
- tempo/RTF;
- quantidade de warnings;
- percentual aproximado de trechos equivalentes/divergentes;
- número de regiões sem correspondência;
- termos do glossário reconhecidos/variantes, quando mensurável.

Não criar uma nota arbitrária do tipo `Qwen 93/100` como verdade de qualidade. O usuário decide qual resultado é melhor.

### Escolha de base

No primeiro corte, a decisão editorial deve escolher **um run inteiro como base** e permitir correções humanas.

Misturar automaticamente trechos de engines diferentes é fase posterior. Quando existir, deve gerar uma revisão derivada nova e registrar lineage, nunca alterar os runs A/B originais.

## Edição local

Editar um resultado cria uma revision local derivada.

Exemplo:

```text
run qwen-quality #A (imutável)
  -> draft #1
     -> draft #2 após correções
```

Não é necessário materializar uma revision nova a cada tecla. O editor pode manter undo/redo normal durante a sessão e criar checkpoints/revisions em ações significativas como:

- Salvar revisão;
- Marcar como revisado;
- Preparar para publicação.

O contrato de persistência deve continuar evitando writes parciais/corrompidos.

## Publicação cloud

### Primeiro publish

Ação explícita:

```text
Publicar no TDA
```

Confirmação deve resumir:

- sessão;
- run/revision de origem;
- modelo/perfil;
- percentual revisado;
- warnings ainda abertos;
- quantidade de segmentos/palavras.

Depois do commit confirmado, o resultado recebe referência ao receipt/revision cloud.

### Substituir publicação existente

Nunca usar semântica destrutiva de "delete tudo e reinsere" como experiência de produto.

Substituir significa:

1. criar uma nova published revision completa;
2. validar o commit;
3. trocar `current_revision_id` atomicamente;
4. preservar a revision anterior.

Se qualquer etapa falhar, a revision atual continua ativa.

### Editar depois de publicado

Abrir **Editar transcrição** cria draft baseado na revision ativa.

Enquanto o draft não for publicado, consumidores continuam vendo a revision atual anterior.

Publicar as alterações cria nova revision e atualiza o ponteiro ativo.

### Restaurar

Uma revision anterior pode ser reativada sem reprocessar áudio.

A restauração deve registrar um publication event. Não é necessário duplicar todo o conteúdo em uma nova revision apenas para representar o clique de restore; o histórico de ativação pode indicar que a revision antiga voltou a ser current.

Se futuramente a UI exigir numeração linear estrita para cada ativação, essa regra pode ser revisitada sem mudar a imutabilidade do conteúdo.

### Remover publicação

**Remover publicação** significa tornar a sessão sem transcrição pública/ativa, preservando revisions existentes para restauração futura.

É diferente de excluir definitivamente uma revision.

## Modelo cloud conceitual

Esta seção descreve intenção, **não DDL aprovada**.

A evolução física deve preservar o schema atual e ser definida em migration própria quando a implementação começar.

Conceitualmente são necessários:

```text
transcript_revisions
  id
  campaign_id
  session_id
  revision_number ou ordem editorial
  source_id/source_sha256
  run lineage/model metadata
  transcript_sha256
  segment_count
  created_by
  created_at
  status

session.current_transcript_revision_id

publication_events
  session_id
  revision_id opcional
  action
  actor
  created_at
```

Os segmentos podem ser materializados por revision ou projetados por uma estrutura equivalente. A decisão física deve considerar custo de leitura, compatibilidade com `transcript_segments`, edição por segmento e volume real antes de criar tabela nova.

O objetivo do modelo não é duplicar banco sem necessidade; é garantir que substituir/publicar/restaurar sejam operações claras e recuperáveis.

## Relação com `transcript_segments` e Edit atual

O Edit atual já possui `revision` por segmento para optimistic concurrency. Isso resolve concorrência de **edição de uma versão**, mas não é o mesmo conceito que `published revision` desta spec.

Não reutilizar o mesmo número/campo para os dois significados.

- `transcript_segments.revision`: concorrência/edição da linha;
- `published revision`: versão editorial completa da transcrição da sessão.

A implementação deve nomear esses conceitos de forma inequívoca.

## Relação com o importador atual

A candidata de `transcript-import` já fornece propriedades úteis:

- validação do bundle;
- hashes;
- autorização server-side;
- commit atômico;
- receipt idempotente;
- readback;
- conflito sem sobrescrever revisão humana.

Essas propriedades devem ser **reutilizadas**, não descartadas.

Porém a ativação futura deve ser adaptada ao novo contrato:

```text
processamento concluído
  != importação automática

resultado aprovado/publicar
  -> import/publish revision
```

A importação não deve continuar assumindo que o primeiro transcript recebido se torna diretamente o conteúdo editorial definitivo da sessão.

## Atomicidade e idempotência

### Upload/publicação

Retry da mesma operação, com mesma identidade e hashes, deve retornar o mesmo resultado/receipt quando seguro.

Payload diferente para a mesma identidade de commit não pode sobrescrever silenciosamente o vencedor.

### Troca da revision ativa

A nova revision e a troca de `current_revision_id` devem ser confirmadas na mesma operação lógica ou em protocolo que garanta rollback seguro.

Nunca deixar a sessão com mistura parcial de duas revisions.

### Perda de resposta

Se o servidor comitou mas a resposta se perdeu:

1. cliente mantém estado `publication_pending_confirmation`;
2. consulta receipt/readback;
3. confirma a revision exata por identidade/hash;
4. somente então marca localmente como `published`.

## Offline e retry

Ficar sem internet durante processamento não é problema: processamento/revisão continuam locais.

Se cair durante publish:

- manter resultado local intacto;
- não assumir sucesso;
- consultar receipt quando a conexão voltar;
- permitir retry idempotente.

O usuário nunca deve precisar reprocessar áudio só porque a publicação falhou.

## Delete, archive e lixeira

Delete precisa existir, mas cada ação deve explicar o seu alcance.

### Excluir run local

Remove aquele run e suas revisões locais dependentes que o usuário escolher remover.

Default:

- mover para lixeira local;
- retenção padrão de 7 dias;
- permitir Restaurar;
- apagar definitivamente após prazo ou ação **Esvaziar lixeira**.

Runs publicados não devem ser apagados localmente sem aviso de que a cópia cloud permanecerá disponível.

### Excluir draft local

Remove apenas revision/draft ainda não publicado.

### Arquivar

Arquivar esconde da visão principal sem apagar bytes.

Útil para sessões antigas ou experimentos que o usuário quer manter.

### Remover publicação

Define `current_revision = null` ou estado equivalente, mantendo revisions cloud para restauração.

### Excluir revision cloud inativa

Permitido com confirmação quando não for a current revision.

Pode apagar conteúdo pesado da revision e manter somente evento/tombstone mínimo se a implementação achar útil para histórico. Não é necessário retenção legal/audit trail permanente.

### Excluir revision atual

A UI deve oferecer escolhas explícitas:

```text
Esta é a revisão atualmente publicada.

[ Restaurar anterior ]
[ Remover publicação ]
[ Cancelar ]
```

Hard delete da current revision não deve acontecer como efeito colateral de um clique genérico.

### Excluir tudo da sessão

Ação destrutiva separada, com confirmação forte como digitar `EXCLUIR`.

Deve informar exatamente se inclui:

- runs locais;
- drafts;
- revisions cloud;
- source/staging local.

O áudio original externo escolhido pelo usuário não é propriedade do TDA e não deve ser apagado.

## Política de retenção local

Defaults aprovados:

- runs concluídos: manter até ação do usuário;
- revisions locais: manter até ação do usuário;
- source/staging Craig: manter por default para permitir reprocessamento/comparação;
- runs falhos/interrompidos: manter enquanto úteis para retry/diagnóstico; UI pode oferecer limpeza em lote;
- lixeira: 7 dias;
- modelos/runtimes: gerenciados separadamente;
- logs: seguem política própria do Companion.

Configurações futuras podem oferecer limpeza automática, mas não devem remover um resultado não publicado sem comunicar claramente a política.

## Gestão de armazenamento

A UI deve separar consumo por categoria quando mensurável:

```text
Modelos/runtimes
Fontes/faixas de áudio locais
Runs/transcrições
Revisões locais
Cache
Lixeira
```

Ação útil:

**Limpar áudio/source de sessões processadas**

só deve ser oferecida quando as consequências estiverem claras: resultados continuam disponíveis, mas reprocessar pode exigir selecionar/importar o ZIP Craig novamente.

## Dados permitidos no cloud

O cloud pode receber, após publicação explícita:

- transcript aprovado;
- speaker/track/timestamps necessários;
- metadata de lineage do processamento;
- model/profile/revision suficientes para entender origem;
- hashes;
- estatísticas editoriais úteis;
- ator/data da publicação;
- revision/publication state.

Não enviar como parte normal do sync:

- áudio Craig bruto;
- FLACs extraídos;
- caminho absoluto local;
- pairing token;
- logs técnicos integrais;
- checkpoints do worker;
- caches/model files.

## Segurança proporcional ao projeto

O TDA continua exigindo fronteiras básicas sensatas:

- publicação cloud requer identidade autenticada e capability/scope apropriado;
- token loopback não vira credencial administrativa cloud;
- payload é validado e limitado;
- hashes evitam confundir bytes/resultado;
- writes importantes são atômicos;
- conflito não sobrescreve silenciosamente;
- delete destrutivo pede confirmação.

Não são objetivos:

- assinatura criptográfica de cada edição de texto;
- WORM storage;
- retenção legal;
- aprovação por múltiplas pessoas;
- MFA específico por publish/delete;
- cadeia forense de auditoria;
- criptografia custom além da infraestrutura normal do produto.

Se o projeto mudar de natureza, essa decisão pode ser revista.

## UX alvo no Processamento

Depois de concluir:

```text
Processamento concluído
Qwen3-ASR · Melhor precisão

Resultado salvo localmente.
Nada foi publicado no TDA.

[ Revisar resultado ]
[ Comparar ]
[ Processar novamente ]
[ Publicar no TDA ]
```

Na presença de vários runs:

```text
Resultados locais (3)

Qwen Quality       concluído
Whisper Detailed   concluído
Qwen Fast          interrompido

[ Comparar selecionados ]
```

A UI não deve misturar fila de jobs ativos com histórico editorial de forma que um run antigo pareça ainda estar processando.

## UX alvo na sessão publicada

Para operador autorizado:

```text
Transcrição atual — revisão 4

[ Editar ]
[ Ver histórico ]
[ Substituir ]
[ Remover publicação ]
```

Histórico:

```text
r4 · atual · Whisper + correções
r3 · Whisper original
r2 · Qwen + correções
r1 · Qwen original
```

Ações de revisão antiga:

- Visualizar;
- Comparar com atual;
- Restaurar;
- Criar edição a partir desta;
- Excluir, se inativa e permitido.

## Edição e publicação de trechos

Primeiro corte aprovado:

- uma revision tem um transcript completo coerente;
- edição humana altera a revision derivada;
- publish troca a revision completa.

Não implementar inicialmente publicação parcial por trecho ou uma sessão com alguns segmentos apontando para Qwen e outros para Whisper em tabelas independentes. Isso aumenta muito a complexidade de lineage e rollback.

A mistura seletiva de trechos pode existir depois como **composição local de uma nova revision completa**.

## Failure modes obrigatórios

### Worker trava no meio

- run vira interrupted/failed;
- nenhum resultado parcial é publicável;
- resultado concluído anterior permanece intacto;
- retry/resume depende da capacidade real do engine.

### Modelo produz resultado ruim

- resultado continua local;
- usuário pode manter, arquivar, excluir ou comparar;
- novo run não toca no publicado.

### Publish falha antes do commit

- cloud atual permanece inalterado;
- local continua pronto para retry.

### Publish comita e resposta se perde

- estado local fica pendente;
- readback confirma receipt/revision;
- não criar segunda revision duplicada no retry coerente.

### Nova revision cloud falha parcialmente

- transação/protocolo deve abortar;
- revision atual anterior continua current.

### Edição concorrente

- usar optimistic concurrency já adotada pelo Edit;
- conflito é mostrado e reconciliado;
- não usar last-write-wins silencioso.

### Delete acidental

- local vai para Trash por default;
- current cloud exige ação específica;
- exclusão total possui confirmação forte.

### Disco cheio

- run falha fechado antes de promover `.partial`;
- resultados concluídos existentes não são removidos automaticamente;
- UI mostra storage/ação de limpeza.

## Provenance e auditoria razoáveis

Guardar o suficiente para entender decisões:

```text
source
run/model/profile
base revision
quantidade de alterações
created_at/updated_at
ator cloud quando publicado/editado
publication events
hashes relevantes
```

Não é necessário registrar cada tecla ou produzir event sourcing completo.

## Relação com canon e memória narrativa

Transcrição publicada continua sendo **fonte**, não canon automático.

Revisar/publicar uma transcrição não:

- cria `canon_entries` automaticamente;
- transforma inferência em fato;
- publica segredo para audience indevida;
- cria entities/relations por conveniência.

Os pipelines de evidence/canon continuam separados.

## Fases de implementação recomendadas

### Slice 1 — runs locais imutáveis

- diretório/index de runs;
- migrar `transcript.json` único para identidade de run;
- preservar resultado anterior;
- listar runs;
- reprocessar sem overwrite;
- cleanup/trash local básico.

### Slice 2 — revisão local

- abrir transcript;
- marcar reviewed;
- editar em revision derivada;
- warnings/review summary;
- salvar draft de forma segura.

### Slice 3 — comparação A/B

- selecionar dois runs do mesmo source;
- alinhar por track/speaker/tempo;
- lado a lado;
- somente divergências;
- métricas objetivas.

### Slice 4 — publicação revisionada

- adaptar transcript-sync atual;
- schema/migration de revision completa;
- primeira publicação;
- receipt/readback;
- `current_revision`;
- publicação atômica/idempotente.

### Slice 5 — pós-publicação

- editar publicado criando draft;
- substituir;
- histórico;
- restore;
- unpublish.

### Slice 6 — delete/storage polish

- Trash local 7 dias;
- archive;
- delete revision inativa;
- excluir tudo;
- painel de armazenamento/limpeza.

Não misturar todos esses slices em uma migration/PR gigante.

## Migração do estado local atual

Quando runs versionados forem implementados, um `transcript.json` legado existente e válido pode ser importado como um run histórico local com metadata conhecida.

Não inventar engine/model/revision que não puder ser comprovada. Campos desconhecidos ficam `unknown`/null conforme o schema alvo permitir.

A migração deve:

- preservar o transcript existente;
- calcular hash real;
- não marcar como publicado sem receipt cloud real;
- não apagar o arquivo original antes de confirmar a nova estrutura.

## Critérios de aceite do contrato completo

A feature só pode ser chamada de completa quando for possível demonstrar:

1. o mesmo Craig possui dois runs concluídos simultaneamente sem overwrite;
2. run interrompido não corrompe run concluído;
3. Qwen e Whisper podem ser comparados lado a lado;
4. revisão humana não altera o output bruto do modelo;
5. publicar exige ação explícita;
6. falha/retry de publish é idempotente;
7. substituir preserva revision anterior;
8. restore volta uma revision anterior sem reprocessar áudio;
9. editar publicado não muda a versão visível antes de novo publish;
10. remover publicação não exige apagar histórico;
11. delete local passa por Trash por default;
12. current revision cloud não é hard-deletada por ação genérica;
13. nenhuma operação normal envia áudio bruto ao cloud;
14. conflito concorrente não usa last-write-wins silencioso;
15. storage pode ser entendido e limpo sem destruir resultados de forma implícita.

## Não objetivos

- editor profissional de áudio;
- DAW;
- treinamento/fine-tuning automático a partir das correções;
- escolha automática definitiva do "melhor modelo";
- publicação automática ao concluir ASR;
- merge automático de engines na primeira versão;
- versionar áudio bruto na nuvem;
- transformar transcrição revisada em canon automaticamente;
- segurança/compliance de ambiente financeiro ou médico.

## Decisões futuras permitidas sem quebrar o contrato

Podem evoluir depois:

- forma física exata das tabelas de published revisions;
- algoritmo de alinhamento A/B;
- políticas opcionais de limpeza automática;
- retenção de revision cloud antiga;
- composição de trechos de runs diferentes;
- benchmark pessoal baseado em escolhas históricas do usuário;
- sugestão de modelo default com base em resultados reais.

Essas evoluções devem preservar os invariantes principais: **run bruto imutável, revisão derivada, publicação explícita, revisão cloud substituível/restaurável e áudio bruto local**.

## Projeção leve da revisão — #625 / PR #626

`GET /sources/:source/runs` inclui `review` aditivo: status, revisão, percentual
e timestamp. Ausência de draft retorna null (sem revisão persistida); sidecar
ausente, incompatível, inválido ou stale retorna unknown com os demais campos
null. GET de revisão continua efêmero quando não há draft e não cria nem atualiza
projeções. O save autoritativo e o repair explícito atualizam `summary.json` no
namespace de revisão usando a política central `projection`, atômica e descartável.
Falha da projeção não desfaz nem transforma em erro um save já confirmado.

O sidecar `tda_local_review_summary_v1` tem no máximo 8 KiB, não contém segmentos
ou paths e é vinculado a source/run/base SHA e fingerprint do draft (tamanho,
mtime/ctime, file ID e volume). O leitor valida arquivo regular, recusa links e
junctions no namespace e limita o read a 8193 bytes; nunca abre o draft/transcript.
Fingerprint é detecção barata de stale, não prova criptográfica dos bytes atuais.
O badge não autoriza save/publicação, que continuam validando o snapshot completo.

Revisões antigas sem projeção permanecem unknown até novo save ou reconstrução
deliberada, com Companion parado:

```text
python local-companion/tools/rebuild_review_summary.py --data-root <Data> --package-root <Data/staging/source> --run-id <run>
```

A ferramenta detém o RootLock do Agent, valida run e draft completos e recria
apenas o sidecar; não altera bytes, hash ou revisão editorial. Saída sanitizada
unknown termina com código 2. Rollback: leitores antigos ignoram o campo/arquivo;
o draft e os runs permanecem no formato anterior. Nenhuma migration de banco.

Validação sintética: catálogo de 100 runs sem abrir payloads editoriais, identidade
incorreta, metadata não finita, stale/missing/corrupt, arquivos não regulares, falha
de disco da projeção, GET sem efeitos e rebuild preservando bytes do draft.


## Recuperação do vínculo de publicação — candidato #637

O vínculo derivado `publication-target.json` tem uma origem redundante mínima,
`publication-origin.json`, persistida atomicamente antes do binding. Ambos contêm
somente campaign/session/source/run/job/attempt/hash e versão, sem texto ou paths.
A origem permanece após exclusão do job da fila e deve acompanhar o run no backup.
Runs existentes não são reescritos: a origem é estabelecida ao verificar o vínculo
completo antes da limpeza da fila ou em reparo explícito de um job succeeded.

A revisão distingue `valid`, `invalid` e `unbound`. Ausência de target com origem
presente é dano (`invalid`), não prova de que nunca houve vínculo. A capability aditiva `transcription.target.repair` habilita o botão
**Reparar vínculo original** usa POST autenticado no Agent e só fica disponível
sem edição pendente. O Agent verifica os bytes do run e a origem redundante; se
o job existe, exige também succeeded, attempt, source/hash, profile, context e
glossary hashes, track count e result receipt compatíveis. Nenhuma sessão é
escolhida por nome ou pela última seleção. Sem prova, retorna erro explícito e
preserva o resultado revisável com publicação indisponível. Rebind humano para
outro destino não faz parte deste contrato.

Binding e reparo compartilham lock entre processos. Um target válido divergente,
origem divergente ou symlink falha fechado. A limpeza de um job succeeded Craig
verifica/preserva a origem antes de remover a linha operacional; falha bloqueia
cleanup com `PUBLICATION_TARGET_CLEANUP_BLOCKED`. A listagem continua metadata-only,
sem repair automático nem hash de transcript a cada polling.

Compatibilidade: campos de estado são aditivos; clientes anteriores continuam
lendo o target. Servidor anterior ignora a origem adicional, mas não oferece
reparo e não protege a última origem no cleanup. Rollback deve manter os sidecars
e evitar limpeza da fila pelo Agent anterior. Sem DDL, publicação editorial ou
deploy neste candidato; integração e rollout precisam de evidências separadas.


Evidência local do candidato: suíte Companion 986 passed / 12 skipped; regressões
focadas finais 21 passed, incluindo limpeza da fila e reparo autenticado. `pnpm
check` passou (659 testes Web, validações de docs/design/media/database) e build
Production local passou. Playwright: 12 casos desktop/mobile, com screenshots
inspecionados e edição pendente bloqueando reparo. Fixtures são sintéticas.


## Renomeio de participante em lote — candidato #662

Gerenciar participantes identifica cada grupo por `(trackNumber, speaker atual)`.
O operador escolhe explicitamente a track e o nome de origem, informa o novo nome
e confirma um preview das identidades afetadas. Nomes divergentes na mesma track
são exceções preservadas e têm contagem/consulta próprias; tracks diferentes com
nomes iguais nunca são fundidas. Se o conjunto mudar após o preview, a interface
exige nova conferência antes de aplicar.

Aplicar transforma o working draft uma única vez em O(n), sem request, sem mudar
IDs, timestamps, texto, reviewed ou ordem. O mesmo contrato Unicode do draft
rejeita nomes vazios, controles e mais de 160 escalares. Busca usa imediatamente
os nomes novos. Aplicar/cancelar devolve foco ao seletor sem forçar scroll.

A edição marca dirty e invalida aprovação em memória. O único Salvar revisão
persiste o snapshot completo com o CAS existente; conflito mantém o renomeio local.
Run bruto não é alterado e publicação exige salvamento e aprovação nova explícita.

Validação: sete testes de estado, incluindo 7.500 segmentos/3.000 alterações;
fluxos desktop/mobile de preview, cancelar, exceções, tracks homônimas, aprovação
invalidada, um único save e conflito sem perda. Integração e release são etapas
separadas. Rollback da Web mantém os drafts compatíveis, sem migração de dados.
