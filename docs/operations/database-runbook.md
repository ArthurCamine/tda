# Runbook operacional do banco / Supabase

> Status: vigente
> Owner: dados/Supabase
> Última revisão: 2026-09-07
> Banco canônico: Supabase `dmrqnbdvbkfqzctcerbx`

Este runbook define como inspecionar, alterar, validar e recuperar o banco do TDA. O objetivo é que uma mudança de banco seja reproduzível e auditável sem depender de chat, memória ou histórico de terminal.

## Regra principal

Uma mudança de banco só é considerada concluída quando existem, quando aplicável:

1. contrato/objetivo documentado;
2. migration versionada;
3. impacto e compatibilidade avaliados;
4. aplicação controlada;
5. validação pós-migration;
6. migration history conferida;
7. documentação atualizada;
8. evidência registrada em `docs/database/verification-log.md`.

Alteração manual no dashboard não substitui migration. Se uma intervenção emergencial for inevitável, ela deve ser documentada e reconciliada com o repositório imediatamente depois.

## Fonte de verdade

- banco físico: Supabase `dmrqnbdvbkfqzctcerbx`;
- schema principal de aplicação: `public`;
- migrations do reboot: `supabase/migrations`;
- contrato físico: `docs/database/schema-catalog.md`;
- domínio: `docs/data-model.md`;
- segurança: `docs/database/security.md`;
- evolução: `docs/database/migrations.md`;
- fotografias/auditorias: `docs/database-audit.md` e `docs/database/verification-log.md`.

O histórico anterior ao reboot continua no próprio Supabase e no legado `Faysk/dnd-scribe`. O TDA não deve fabricar migrations históricas retroativas.

## Classificação de risco

### Baixo

- índice novo não destrutivo;
- comentário/documentação de schema;
- coluna nullable sem consumidor obrigatório;
- backfill idempotente e determinístico já validado.

### Médio

- nova FK/constraint;
- coluna `NOT NULL`;
- alteração de enum/check;
- backfill de volume relevante;
- mudança de query path que exige índice;
- nova tabela exposta a API/RLS.

### Alto

- `DROP`, truncate ou perda potencial de dados;
- alteração de RLS/grant;
- `SECURITY DEFINER`/`SECURITY INVOKER`;
- mudança de identidade/autorização;
- remoção de coluna/constraint usada pelo legado;
- alteração incompatível com aplicação já publicada;
- migration que mistura grande DDL, backfill e mudança de auth.

Mudanças de alto risco exigem mapear consumidores e estratégia de recuperação antes da aplicação.

## Auditoria read-only antes de mexer

Antes de qualquer etapa grande de banco:

1. confirmar que o projeto correto é `dmrqnbdvbkfqzctcerbx`;
2. confirmar estado saudável do projeto;
3. conferir migration history remoto;
4. conferir objetos que serão afetados no schema real;
5. medir linhas/duplicatas/nulls relevantes;
6. conferir consumidores no TDA e no legado;
7. executar advisors de segurança e performance;
8. registrar divergências antes de escrever DDL.

Nunca assumir que documentação antiga representa perfeitamente o banco atual.

## Fluxo de mudança

```text
1. definir contrato e invariantes
2. inspecionar banco real e consumidores
3. desenhar mudança mínima
4. revisar compatibilidade com legado
5. revisar RLS/grants/RPCs/indexes
6. criar migration versionada
7. aplicar de forma controlada
8. validar invariantes com SQL read-only
9. conferir migration history
10. rodar advisors
11. atualizar docs
12. registrar verificação
13. CI/PR/release conforme necessário
```

### Invariantes típicos

Dependendo da mudança, validar explicitamente:

- contagem antes/depois;
- duplicatas inesperadas;
- nulls inesperados;
- FK/constraint/index realmente existentes;
- cardinalidade de relacionamentos;
- RLS/policies/grants;
- RPCs ainda autorizam e negam quem devem;
- consumidores legados continuam operando;
- nenhum candidato/evidência virou canon sem aprovação;
- migration remota possui o mesmo ID/nome do arquivo do repositório.

## Backfills

Todo backfill deve declarar:

- fonte do dado;
- regra de matching;
- por que o matching é seguro;
- ambiguidades não resolvidas;
- condição para rerun/idempotência;
- como identificar as linhas afetadas;
- validação de resultado.

Nunca preencher identidade humana ausente por inferência narrativa. Exemplo: `participant.profile_id` histórico pode continuar nulo enquanto `character_entity_id` é recuperado com evidência suficiente.

## Segurança

Para qualquer alteração em RLS, grants, Auth ou RPC:

- revisar `docs/database/security.md`;
- testar acesso positivo e negativo;
- não abrir policy apenas para silenciar linter;
- não usar service/secret key no browser;
- tratar toda função `SECURITY DEFINER` como boundary privilegiado;
- conferir `EXECUTE` e autorização interna da função;
- evitar `SECURITY DEFINER` como correção rápida de erro de permissão.

Warnings existentes devem ser classificados por impacto, não apagados cosmeticamente.

## Performance

Não criar nem remover índices em massa apenas para satisfazer advisor.

Priorizar:

1. queries reais do TDA;
2. caminhos de autorização;
3. busca/paginação de transcrições;
4. joins/FKs comprovadamente quentes;
5. jobs operacionais consultados com frequência.

Índice novo precisa ter hipótese de uso. Índice aparentemente não utilizado pode corresponder a feature ainda não ativada.

## Drift

Drift existe quando banco, migrations e documentação deixam de contar a mesma história.

Sinais:

- migration remota sem arquivo correspondente do reboot;
- arquivo do reboot não aplicado em produção;
- objeto físico diferente do documentado;
- mudança feita manualmente no dashboard;
- versão/nome divergente;
- código depende de constraint/policy não documentada.

Ao encontrar drift:

1. parar novas mudanças relacionadas;
2. registrar estado real;
3. identificar origem e consumidores;
4. decidir qual estado é canônico;
5. reconciliar via migration/documentação, sem reescrever silenciosamente história já aplicada;
6. validar novamente.

## Rollback e recuperação

Rollback de banco não significa automaticamente executar um `DOWN`.

Classificar a recuperação:

- **DDL reversível:** retirar objeto novo ainda sem dependência;
- **compatibilidade:** manter caminho antigo e desativar o novo;
- **backfill:** reverter apenas se as linhas afetadas puderem ser identificadas com segurança;
- **perda potencial de dados:** antes de aplicar, confirmar estratégia real de backup/restore/PITR disponível para o projeto e documentar o ponto de recuperação.

Nunca apagar dados para fazer o schema “voltar a caber”.

## Incidente de banco

Se uma mudança causar erro em produção:

1. interromper novas migrations/deploys relacionados;
2. identificar SHA da aplicação e migration mais recente;
3. verificar saúde do Supabase;
4. medir impacto sem fazer writes exploratórios;
5. preservar evidência/logs;
6. preferir restauração de compatibilidade a remoção destrutiva;
7. validar a correção com queries read-only e smoke test da aplicação;
8. registrar causa, impacto, correção e prevenção;
9. atualizar docs/ADR quando o incidente revelar uma regra arquitetural nova.

## Registro de verificação

`docs/database/verification-log.md` é append-only por intenção. Cada entrada deve registrar:

- data/hora ou janela da verificação;
- projeto verificado;
- migration head relevante;
- invariantes verificadas;
- advisors executados;
- divergências encontradas;
- ação tomada ou decisão de não agir.

Não colocar secrets, dumps privados, tokens, hashes sensíveis ou PII no log.

## Checklist de fechamento

Antes de declarar “banco pronto” para uma etapa:

- [ ] projeto correto e saudável;
- [ ] migration history sem drift conhecido;
- [ ] invariantes da mudança validadas;
- [ ] RLS/grants/RPCs revisados se afetados;
- [ ] advisors revisados;
- [ ] compatibilidade legada conhecida;
- [ ] rollback/recuperação adequado ao risco;
- [ ] documentação atualizada;
- [ ] verificação registrada;
- [ ] nenhum dado sensível foi documentado ou exposto.

### Publicação com CAS (#636, candidata)

Para `20260926220608_transcript_publication_current_cas`: manter publicação desativada durante a troca; identificar scripts que invocam restore/unpublish e migrar da assinatura de seis para sete UUIDs, lendo e congelando o current antes da confirmação. Verificar após migration que a assinatura antiga não existe, anon/authenticated não têm EXECUTE, service_role tem EXECUTE na nova assinatura, e a flag só é reativada com Web compatível e aceites #430. Não executar smoke destrutivo em sessão real. Em falha, desativar publicação e corrigir adiante, preservando revisions e receipts. Não reintroduzir writes sem expectativa como rollback.
