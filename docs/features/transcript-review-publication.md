# Transcrição — runs locais, revisão, comparação e publicação versionada

> Status: arquitetura aprovada; implementação pendente
> Owner: Edit / processamento local / transcript-sync
> Última revisão: 2026-09-15
> Fonte de verdade: esta spec, ADR-0016, `local-companion/tda_companion`, `src/features/transcript-sync` e contratos do Edit

## Objetivo

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