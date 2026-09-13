# Supabase do TDA

Projeto canônico existente: `dmrqnbdvbkfqzctcerbx`.

Este diretório versiona mudanças do reboot TDA a partir do momento em que o novo repositório passou a assumir mudanças revisadas de schema. O histórico anterior continua registrado no próprio Supabase e no legado `Faysk/dnd-scribe`; ele não deve ser copiado para cá fingindo que foi criado pelo reboot.

## Diretórios

- `supabase/migrations/`: **somente migrations autorizadas para aplicação remota**. O Production CD usa estes arquivos como conjunto autoritativo do TDA dentro de um overlay efêmero que também contém o migration history legado já aplicado.
- `supabase/candidates/`: SQL candidato ainda não autorizado para Production. Pode ser executado somente em ensaios scratch explicitamente preparados para esse candidato; o Supabase CLI não o considera no fluxo automático de Production.
- `supabase/tests/`: fixtures e verificações SQL sintéticas.

Ao promover um candidato, a migration deployável final precisa existir em `supabase/migrations/` com timestamp/nome revisados contra o schema vigente e com a autorização registrada na documentação/PR correspondente. O arquivo candidato original pode ser arquivado ou removido deliberadamente depois da promoção. Depois que uma migration deployável for aplicada remotamente, não editar seu SQL para corrigir history; usar migration corretiva.

## Regras

- Production data não é resetável por conveniência de desenvolvimento.
- Toda DDL autorizada para Production entra em `supabase/migrations` e deve corresponder ao nome/versão registrada no Supabase após aplicação.
- SQL ainda aguardando decisão operacional fica em `supabase/candidates` e deve estar explicitamente documentado como não aplicado.
- Migration deployável já integrada não é editada, renomeada ou removida para corrigir history; criar migration corretiva.
- Migrations de transição devem preservar o legado enquanto ele ainda estiver operacional.
- Não remover tabelas, columns, scopes ou grants legados sem comprovar independência do TDA.
- RLS e grants são mudanças de contrato de segurança; revisar consumidores antes de alterar.
- Dados narrativos derivados não viram canon por migration automática.
- Identidade de entity deve convergir para UUID/slug; nomes são apresentação e busca. A constraint histórica `(campaign_id, name)` permanece apenas enquanto o consolidator legado usar esse `ON CONFLICT`.

## Boundary e overlay de Production

O primeiro timestamp de migration pertencente ao reboot TDA é `20260906210333`. Esse valor é o boundary operacional versionado no workflow de Production.

O banco canônico possui migration history anterior a esse boundary que não pertence a este repositório. Como `supabase db push` compara o histórico remoto completo com os arquivos locais, executar o comando diretamente sobre `supabase/migrations` produziria um falso drift de migrations legadas ausentes.

Por isso o Production CD usa um **overlay efêmero e descartável no runner**:

1. cria um workdir Supabase temporário;
2. liga explicitamente ao projeto canônico `dmrqnbdvbkfqzctcerbx`;
3. busca, em modo somente leitura para o banco, o migration history remoto para esse workdir;
4. exige que qualquer entrada remota a partir do boundary TDA exista com o mesmo filename em `supabase/migrations`;
5. copia os arquivos autoritativos de `supabase/migrations` sobre o overlay, preservando o histórico legado apenas como contexto local;
6. executa `db push --dry-run --skip-vault` e só depois `db push --skip-vault`;
7. busca novamente o migration history e exige igualdade exata entre o conjunto TDA remoto e `supabase/migrations` antes do smoke/promotion.

O overlay nunca é commitado, não executa `migration repair`, não reescreve o migration history remoto e não transforma migrations legadas em arquivos de autoria do TDA. Qualquer entrada remota nova a partir do boundary que não exista no repo faz o release falhar fechado e exige reconciliação deliberada.

## Primeiras migrations do reboot

- `20260906210333_align_tda_domain_identity.sql`: cria o scope canônico `tda` em paralelo ao legado e liga PCs à registry de entities.
- `20260906210427_backfill_narrative_entity_links.sql`: recupera links de participantes históricos para PCs e adiciona índices do domínio narrativo.
- `20260906211040_relax_reboot_entity_name_lookup.sql`: remove apenas a unicidade case-insensitive adicionada pelo reboot, mantém lookup case-insensitive e preserva a constraint exata exigida pelo consolidator legado.

## Migrations autorizadas aguardando Production CD

- `migrations/20260912214500_world_entity_media_foundation_v2.sql` — identidade first-class de assets do World, vínculo entity → portrait e wrapper transacional de publicação. Autorizada para rollout controlado pela #271; ainda não aplicada no Supabase Production até a execução do Production CD da promoção `Preview -> main`.

## Candidatos atuais

Estes SQL permanecem deliberadamente fora de Production:

- `candidates/20260907193704_transcript_import_capability.sql`;
- `candidates/20260907193705_transcript_import_atomic.sql`;
- `candidates/20260908231000_backfill_screacky_historical_alias.sql`.

Os contratos e gates de ativação continuam em `docs/integrations/transcript-import.md`, `docs/features/world-entity-media-foundation.md` e `docs/database/migrations.md`.
