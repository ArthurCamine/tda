# Processamento, jobs e áudio

> Status: processamento local real implementado; lifecycle editorial pós-ASR aprovado e em implementação futura
> Owner: processing/local-companion
> Última revisão: 2026-09-15
> Fonte de verdade: ADR-0003, ADR-0013, ADR-0015, `local-companion/tda_companion`, `docs/features/local-processing.md` e `docs/features/transcript-review-publication.md`

## Objetivo

Executar ingestão/transcrição e tarefas pesadas de forma rastreável, retomável e econômica sem tornar o site dependente do PC local ligado, preservando liberdade para experimentar com diferentes modelos antes de transformar um resultado em conteúdo editorial publicado.

## Decisão arquitetural

**Site/Edit em cloud; processamento pesado local.**

A cloud guarda somente conteúdo explicitamente publicado/sincronizado e metadados necessários ao produto. O Companion local executa trabalho pesado, mantém fontes/runs locais e só envia resultado quando houver uma ação editorial explícita.

Motivações:

- custo previsível;
- aproveitar hardware local;
- evitar retenção cloud desnecessária de áudio bruto;
- manter o produto web disponível independentemente do worker local;
- permitir Qwen/Whisper/retries sem risco de sobrescrever imediatamente a versão publicada;
- separar qualidade de ASR da decisão humana de publicação.

## Fonte, job, run e revision são conceitos diferentes

### Source

Identidade do material de origem. Para Craig, o Companion usa identidade baseada no conteúdo do ZIP e staging local reutilizável quando seguro.

### Job

Unidade operacional da fila: algo a executar, pausar/cancelar/repetir e observar.

### Run de transcrição

Execução concreta de ASR para um source e uma configuração. ADR-0015 determina que múltiplos runs do mesmo source podem coexistir e que um run concluído é imutável.

### Revision editorial

Versão derivada para revisão/edição/publicação. Não é o mesmo que um run e não é o mesmo que `transcript_segments.revision` usado para optimistic concurrency de linha.

## Processing job

O Companion atual possui fila local persistida e estados próprios. Conceitualmente:

```text
queued
  -> preparing
  -> running
  -> completed
  -> failed
  -> cancelled
  -> interrupted
```

`completed` é o único estado capaz de promover um output local final. `failed`, `cancelled` ou `interrupted` não produzem candidato publicável.

Retry precisa ser seguro. Quando houver checkpoint real do engine, resume pode continuar um run conforme contrato explícito; quando não houver, repetir cria nova tentativa/run em vez de fingir retomada exata.

## Job steps e eventos

Etapas/eventos existem para:

- progresso granular;
- diagnóstico;
- UI de monitoramento;
- telemetria factual;
- recuperação;
- evitar request web bloqueado por minutos.

Eventos técnicos/editoriais de job não são automaticamente audit trail de publicação. A revisão/publicação possui lifecycle próprio.

## Idempotência

Cada operação persistente deve definir a identidade apropriada.

Exemplos:

- source Craig por hash do ZIP;
- download de runtime/modelo por versão/hash;
- publicação por revision/candidate + transcript hash;
- retry de sync pelo mesmo receipt/identidade.

**Importante:** run de ASR não deve ser deduplicado de forma rígida apenas por `source + model + config`. O usuário pode querer rodar a mesma configuração novamente para comparar estabilidade, runtime novo ou simplesmente verificar um resultado duvidoso.

A UI pode avisar que já existe run equivalente, mas deve permitir processar novamente.

## Craig ingest

O pipeline canônico atual:

```text
Craig ZIP
  -> snapshot local
  -> SHA-256 / source_id
  -> validação ZIP/path/limites
  -> staging content-addressed
  -> tracks por participante
  -> job transcription.craig
```

O mesmo ZIP pode reutilizar staging validado. Caminho absoluto do usuário não é contrato cloud/browser.

Tracks Craig já carregam identidade de participante; diarização primária não é necessária quando a track é conhecida.

## Engines e perfis

Perfis atuais:

- `qwen-quality`;
- `qwen-fast`;
- `whisper-detailed`;
- `whisper-turbo`.

Modelos/runtimes pesados são gerenciados fora do MSI e possuem gates próprios de integridade/aceitação. Qualidade real continua dependente de evidência em áudio de campanha, não só unit tests.

## Runs locais e output imutável

Direção aprovada:

```text
source
  ├── run Qwen quality
  ├── run Qwen fast
  ├── run Whisper detailed
  └── run Whisper turbo
```

Cada run registra lineage suficiente para explicar sua origem: engine, modelo, model revision, profile, runtime, source hash, contexto/glossário, duração/RTF/warnings quando disponíveis.

Um output bruto concluído não é editado. Correções criam revision derivada.

O arquivo final só aparece após validação/escrita atômica; `.partial` e checkpoints não são resultados editoriais.

## Comparação e auditoria

O domínio de processamento fornece dados factuais necessários à revisão, mas a UX detalhada pertence a [transcript-review-publication.md](../features/transcript-review-publication.md).

Comparação deve priorizar:

- mesmo source;
- speaker/track;
- tempo sobreposto;
- similaridade textual;
- warnings e métricas objetivas.

O sistema não deve inventar uma nota absoluta de qualidade. A escolha final é humana.

## Áudio

Três conceitos históricos continuam úteis para distinguir responsabilidade:

### Recording/source file

Arquivo fonte da gravação/sessão.

### Chunk / speech slice / janela

Unidade técnica temporária para processamento ou gate.

### Audio artifact

Artefato derivado com lifecycle/retention específico.

No reboot, **áudio bruto não integra retenção cloud obrigatória**. Craig ZIP, FLACs extraídos e janelas de aceitação permanecem locais salvo decisão futura explícita.

## Retenção local

Defaults aprovados pelo lifecycle editorial:

- runs concluídos: manter até ação do usuário;
- revisions locais: manter até ação do usuário;
- source/staging: manter por default para permitir reprocessamento/comparação;
- falhos/interrompidos: manter enquanto úteis para retry/diagnóstico, com limpeza disponível;
- Trash local: 7 dias;
- modelos/runtimes: lifecycle próprio;
- logs: política própria do Companion.

Limpeza de source deve explicar que novo processamento pode exigir importar o ZIP novamente.

## Cleanup

Nunca limpar source/raw apenas porque um job possui status genérico `completed/succeeded`.

Antes de remover dados compartilhados, considerar:

- runs que dependem do source;
- possibilidade de reprocessamento;
- revisions locais;
- conteúdo publicado cloud independente;
- existência do ZIP original fora do TDA;
- escolha explícita do usuário.

Delete comum de run/draft passa por lixeira local. Hard delete total é ação distinta.

## Cache

Cache técnico pode ser reutilizado quando source + configuração + runtime realmente equivalem e o artefato for seguro para reuse.

Cache não substitui o conceito de run histórico. Mesmo quando inferência reutiliza resultado/cache, a experiência pode registrar uma nova tentativa lógica com lineage apropriado.

Mudança de modelo/prompt/language/revision pode invalidar reuse sem apagar respostas históricas.

## Observabilidade e métricas

Registrar quando factual e disponível:

- job/run status;
- started/completed/elapsed;
- error code explícito;
- source/model/runtime identity;
- track/segment/word counts;
- RTF;
- device/GPU/VRAM quando mensurável;
- warnings;
- hashes relevantes;
- cache/reuse.

Métrica ausente fica desconhecida. Não preencher com estimativa para deixar a UI mais bonita.

## Sincronização e publicação cloud

Companion **não deve sincronizar automaticamente ao concluir ASR**.

Fluxo alvo:

```text
run completed
  -> review/compare/edit local
  -> explicit Publish
  -> server-side auth/capability
  -> validated revision payload
  -> atomic commit + receipt
  -> readback
  -> activate current revision
```

Requisitos:

- protocolo/versionamento;
- idempotency key;
- auth com capability mínima;
- checksum/hash;
- confirmação server-side;
- retry após perda de resposta;
- conflito explícito;
- sem service key irrestrita em cliente local;
- sem áudio bruto no payload normal.

A candidata existente de transcript import é fundação técnica, não fluxo produtivo final, e deve ser reconciliada com ADR-0015 antes de ativação.

## Falhas

### ZIP inválido

Não criar source utilizável como se ingest tivesse sido confiável.

### Track faltando/corrompida

Falhar ou avisar conforme contrato do pacote; nunca remapear silenciosamente para outro participante.

### Transcrição falha

Preservar source e runs concluídos anteriores. O run novo falha/interrompe sem substituir resultado existente.

### Resultado ruim

Não é falha técnica obrigatória. O usuário pode comparar, arquivar, excluir ou reprocessar e escolher outro run para publicação.

### Sync/publicação falha

Resultado local continua disponível. A revision cloud atual permanece intacta quando o novo commit não foi confirmado.

### Resposta perdida depois do commit

Consultar receipt/readback antes de repetir; retry coerente não cria duplicata.

### Disco cheio

Não promover `.partial`; preservar resultados já concluídos e orientar limpeza explícita.

## Segurança proporcional

O domínio mantém segurança básica: loopback protegido, payload limitado, hashes, auth/capability em writes cloud, atomicidade e conflitos explícitos.

Não é objetivo adicionar controles financeiros/médicos, retenção legal ou trilha criptográfica por tecla.

## Próximas evoluções

1. múltiplos runs locais imutáveis;
2. biblioteca/histórico de resultados;
3. revisão local e marcação de trechos;
4. comparação A/B temporal por speaker;
5. publicação revisionada com receipt/readback;
6. edit/substitute/restore/unpublish;
7. delete/archive/storage polish;
8. benchmark pessoal baseado em escolhas reais, sem autoeleger modelo vencedor.

A especificação dona desse lifecycle é [Transcrição — runs locais, revisão, comparação e publicação versionada](../features/transcript-review-publication.md).
