# R2 — segurança e custos

> Status: vigente
> Owner: integrations/media + infraestrutura/operação
> Última revisão: 2026-09-12

Credenciais ficam somente em ambientes autorizados; nunca em browser, Git, screenshots ou docs. Erro 403 é falha de autorização/configuração, não prova de ausência. Bucket privado nunca vira fallback público. Exposição acidental de conteúdo restrito é incidente de segurança.

Acesso temporário a objeto privado, se necessário, deve ser gerado server-side após autorização, com escopo e expiração mínimos. Em browser, CORS deve ser explícito.

Para upload direto do World, o contrato candidato usa presigned `PUT` SigV4 de curta duração para uma chave única sob `uploads/pending/world-entity/`. A assinatura vincula o `Content-Type`, mas não transforma MIME/hash/tamanho declarados pelo browser em evidência. O servidor precisa reautorizar o editor e a lease, ler os bytes do R2, validar magic bytes + SHA-256 + tamanho + dimensões e só então materializar a chave canônica imutável. O browser não recebe URL de escrita para `campaigns/.../portrait/{sha256}.{ext}`.

Pending keys não são apagadas sincronamente como garantia de segurança: uma presigned URL ainda válida pode recriar o objeto depois do delete. A retenção curta deve ser configurada por lifecycle explícito somente para `uploads/pending/`. O lifecycle não pode alcançar namespaces canônicos `campaigns/`, `site/`, `lore/`, masters ou evidências de recuperação. CORS do bucket de staging deve limitar origins, `PUT` e headers ao mínimo necessário, incluindo apenas `Content-Type` para este fluxo.

Usar R2 Standard como baseline. Infrequent Access e lifecycle automático exigem decisão explícita; a exceção planejada para `uploads/pending/` é lixo operacional efêmero e ainda precisa de configuração/revisão deliberada antes da ativação remota. Não criar delete automático em namespaces canônicos sem política de retenção.

Pricing consultado em 2026-09-11 para Standard: 10 GB-mês, 1 milhão de operações Class A e 10 milhões de Class B incluídos por mês; egress para Internet sem cobrança de bandwidth segundo o fornecedor. Conferir antes de decisões: <https://developers.cloudflare.com/r2/pricing/>.

O TDA prioriza franquias gratuitas, monitora storage/operações e não habilita produto pago por conveniência.
