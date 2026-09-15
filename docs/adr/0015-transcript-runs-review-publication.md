# ADR-0015 — Runs locais imutáveis, revisão explícita e publicação versionada de transcrições

> Status: accepted
> Data: 2026-09-15
> Owner: Edit / processamento local / transcript-sync
> Relacionados: ADR-0003, ADR-0007, ADR-0013, `docs/features/local-processing.md`, `docs/features/transcript-review-publication.md`, `docs/integrations/transcript-import.md`

## Contexto

O TDA já decidiu em ADR-0003 que processamento pesado e áudio bruto permanecem locais, enquanto o produto e o conteúdo sincronizado vivem no cloud. ADR-0013 consolidou o TDA Companion como Agent local e definiu Qwen/Whisper como engines oficiais do pipeline ASR.

O pipeline atual produz um `transcript.json` local válido e não publica automaticamente. Isso é seguro, mas ainda trata o resultado concluído como um artefato único por source e não define a experiência completa para:

- reprocessar a mesma sessão com outro modelo/perfil;
- manter vários resultados simultaneamente;
- comparar Qwen/Whisper antes de decidir;
- revisar e corrigir sem destruir o output original;
- publicar conscientemente;
- substituir uma publicação sem perder a anterior;
- editar depois de publicar;
- restaurar ou remover publicação;
- excluir conteúdo local/cloud de forma previsível.

A candidata histórica de transcript import já possui propriedades valiosas de autorização, hashes, commit atômico, idempotência e receipt, mas foi desenhada em torno da importação de um bundle final, não de um workflow editorial com múltiplos runs/revisions.

O produto é uma ferramenta para memória de campanha de RPG. Precisa ser resistente a erro humano e falha de processamento, mas não necessita de retenção forense, WORM, multiaprovação ou controles equivalentes a sistemas financeiros/médicos.

## Decisão

### 1. Source e run são conceitos distintos

O source identifica a gravação Craig por conteúdo. Cada tentativa ASR gera um `run` próprio.

Repetir a mesma sessão, mesmo com configuração idêntica, cria um run novo. Runs concluídos não são sobrescritos.

### 2. Output bruto concluído é imutável

O transcript produzido pelo engine é preservado como evidência do run. Correção humana não altera esse arquivo lógico; cria uma revisão derivada.

### 3. Resultado parcial nunca é publicável

Run `running`, `interrupted`, `failed` ou `cancelled` não pode ser promovido como resultado final.

A promoção local de `.partial` para transcript final acontece somente após conclusão e validação.

### 4. Processar não publica

Nenhum job ASR envia/publica transcript automaticamente ao terminar.

Publicação exige ação humana explícita depois que o resultado local estiver disponível para revisão.

### 5. Comparação A/B faz parte do produto

Dois ou mais runs do mesmo source podem coexistir e ser comparados por speaker/track + timeline + similaridade textual.

O sistema pode apresentar métricas objetivas, mas não deve inventar uma nota absoluta que declare um modelo vencedor sem referência humana.

### 6. Edição cria revision derivada

Run bruto permanece intacto. Revisão humana local é um objeto separado com lineage para sua base.

Editar uma revision publicada também cria draft/revision nova; conteúdo visível não muda antes de um novo publish.

### 7. Publicação cloud é versionada

Uma sessão pode possuir múltiplas published revisions e no máximo uma revision ativa/current por vez.

Substituir significa criar/confirmar nova revision e trocar o ponteiro ativo de forma atômica, preservando a anterior.

### 8. Restore é suportado

Uma published revision anterior pode voltar a ser current sem reprocessar áudio.

A ativação/restauração é registrada como evento editorial leve.

### 9. Unpublish e delete são ações diferentes

`Remover publicação` deixa a sessão sem revision ativa, preservando revisions existentes.

Delete pode remover run/draft/revision conforme o escopo explícito. A current revision não sofre hard delete por uma ação genérica.

### 10. Lixeira local simples

Deletes locais comuns passam por Trash com retenção padrão de 7 dias. Isso é proteção de UX, não requisito de compliance.

### 11. Áudio bruto permanece local

Cloud recebe somente transcript aprovado e metadados necessários de lineage/publicação. Craig ZIP, FLACs, checkpoints, paths locais, pairing token e caches não fazem parte da publicação normal.

### 12. Sync reutiliza as garantias já construídas

A evolução do transcript import deve preservar:

- autorização server-side;
- hashes;
- limites de payload;
- atomicidade;
- idempotência;
- receipt/readback;
- conflito sem overwrite silencioso.

O que muda é o gatilho e o destino editorial: **resultado concluído não é importado automaticamente; publicação explícita cria/ativa revision**.

### 13. Segurança é proporcional ao TDA

Continuam obrigatórios autenticação/capability para writes cloud, validação de input, conflito explícito, atomicidade e confirmações destrutivas.

Não são requisitos assinatura criptográfica por edição, retenção legal, cadeia forense, MFA por publish/delete ou aprovação múltipla.

## Invariantes

- mesmo source pode ter vários runs;
- run concluído é imutável;
- run parcial não é publicável;
- edição nunca reescreve o output bruto do modelo;
- publish é explícito;
- published revision é imutável;
- substituir preserva a anterior;
- restore não exige ASR novo;
- retry de publish não duplica conteúdo quando a identidade/hash é a mesma;
- falha de publish não derruba a revision atual;
- áudio bruto não é requisito cloud;
- transcrição publicada continua fonte/evidência, não canon automático.

## Consequências positivas

- experimentar com Qwen/Whisper deixa de ser arriscado;
- comparação real pode orientar qual perfil funciona melhor para a campanha;
- um modelo ruim não destrói resultado bom;
- falha de worker não contamina publicação;
- revisão humana fica rastreável sem event sourcing excessivo;
- rollback de publicação fica barato;
- publicação passa a ser uma decisão editorial clara;
- o produto pode evoluir para benchmark pessoal sem mudar os fundamentos.

## Custos

- armazenamento local precisa indexar múltiplos runs;
- UI ganha biblioteca/histórico além da fila;
- transcript-sync precisa evoluir para revision completa;
- banco precisará separar concorrência de segmento de versionamento editorial da transcrição;
- comparação temporal/textual exige algoritmo e UI próprios;
- delete/restore/unpublish aumentam estados de produto a testar.

## Alternativas rejeitadas

### Sobrescrever `transcript.json` a cada reprocessamento

Simples, mas perde comparação, lineage e possibilidade de voltar a um resultado melhor.

### Publicar automaticamente ao concluir ASR

Economiza um clique, mas transforma falha de modelo em conteúdo cloud antes de revisão.

### Editar diretamente a published revision

Reduz objetos, mas impede rollback confiável e mistura estado público com draft em andamento.

### Guardar somente a revision atual

Reduz storage, mas força reprocessamento ou perda de histórico em caso de arrependimento.

### Event sourcing completo de cada alteração

Robusto demais para a necessidade do projeto e aumenta custo sem benefício proporcional.

## Relação com decisões anteriores

Este ADR **complementa**, não revoga:

- ADR-0003: processamento pesado local e produto cloud;
- ADR-0007: Edit como workbench administrativo;
- ADR-0013: Companion Agent/Desktop e pipeline ASR multi-engine.

Ele fecha a decisão que esses ADRs deixavam aberta: como resultados locais se tornam conteúdo editorial revisado/publicado ao longo do tempo.

## Não decisões

Este ADR não escolhe o schema SQL final, não aplica migration, não ativa transcript import produtivo e não define o algoritmo final de diff/alinhamento.

Esses detalhes devem seguir `docs/features/transcript-review-publication.md` e os documentos donos de banco/Edit quando os slices correspondentes forem implementados.

## Condição de revisão

Reavaliar somente se a experiência real mostrar que múltiplos runs/revisions trazem complexidade maior que o valor, ou se o produto deixar de usar processamento local/ASR como fonte principal de transcrição.
