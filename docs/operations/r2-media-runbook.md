# R2 e mídia — runbook operacional

> Status: vigente
> Owner: integrations/media + operations
> Última revisão: 2026-09-19

Fluxo obrigatório: confirmar identidade/role/audience; validar provenance; escolher o master/fonte de maior fidelidade; calcular SHA-256, MIME, bytes e dimensões; decidir se o consumidor precisa do master, de variante dinâmica ou de derivado físico; validar qualidade/resolução; escolher bucket/key; verificar colisão; fazer upload somente quando autorizado; executar read-back; para mídia pública, validar URL HTTPS anônima e decode; registrar evidência; só então promover referência e validar frontend/social.

O [fluxo único de mídia](../integrations/r2/media-pipeline.md) é o contrato dos gates e responsabilidades. A referência é integrada primeiro no candidato e só promovida para produção depois da validação do consumidor. Autorização já dada para o escopo não precisa ser solicitada novamente; não ampliar escopo para apagar arquivos, publicar conteúdo privado ou ativar serviços pagos.

## Acesso de contribuidores

Há dois caminhos distintos e eles não devem ser misturados:

- **contribuição normal de mídia/código:** não precisa de credenciais R2. O contribuidor adiciona a fonte em `media/sources/`, mantém o manifesto em `media/manifests/` e executa `pnpm media:validate`/`pnpm check`. A publicação canônica é responsabilidade da Production CD;
- **operação R2 local/autorizada:** somente quando a tarefa exige leitura/escrita direta no storage. Nesse caso, usar `.env.local` ignorado pelo Git com credencial própria de desenvolvimento/preview e escopo mínimo. Nunca distribuir o par de Production para destravar uma contribuição comum.

A Production CD usa os secrets `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY` protegidos no GitHub Environment `production`; `R2_PUBLIC_BUCKET` é fixado no workflow. O publisher canônico só roda quando o plano de release detecta alteração de mídia e publica os manifests alterados por `tools/ci/publish-production-media.sh`.

Para conteúdo versionado, o contribuidor não deve executar `pnpm media:publish` contra Production a partir da máquina local. O fluxo esperado é PR -> CI -> merge -> Production CD -> publicação/read-back -> smoke. Isso mantém os segredos fora da estação do contribuidor e deixa receipt auditável.

O runtime do World/Edit é outro boundary: credenciais permanecem server-only; o browser recebe apenas presigned PUT curto para uma pending key quando autorizado. Staging usa `tda-media-preview` fora de Production e `tda-media-private` em Production antes da promoção pública.

## Antes de executar

- Identificar fonte íntegra, consumidor, ambiente, visibilidade e referência anterior.
- Conferir conta/endpoint, bucket e credencial restrita sem mostrar valores em logs; falhar explicitamente se indisponível ou inválida.
- Preservar master na cloud privada com read-back antes de depender apenas do derivado público.
- Usar o tooling existente quando cobre o caso. O script histórico de sessões abaixo não é um uploader genérico de lores; lacunas devem virar implementação compartilhada com testes, não comandos fictícios.
- Fazer pré-flight sem escrita; listar arquivos, destino, tamanho e validações pendentes. Upload aditivo e publicação são etapas distintas.

## Diagnóstico por sintoma

Evidência histórica de recuperação: [manifesto de D, Seika e Pipipi em 2026-09-12](../integrations/evidence/lore-media-recovery-2026-09-12.json). O estado de consumidor incompleto registrado nessa recuperação foi corrigido: D/Seika foram publicados pelas PRs #223/#224, commit `ed9201c9911a600918ef742c9c212aa1d18315c8`; Pipipi pelas PRs #225/#226, commit `8fa6cb53096a68c0f9865bc6f61ab29cc9514a4f`. A execução Production CD 34698087655 terminou com sucesso e `/api/version` confirmou esta última versão em 2026-09-12. Consultar [fidelidade dos pacotes](../features/lore-pack-fidelity.md) e [Pipipi](../features/pipipi-lore.md) para escopo e evidências. Masters/pacotes foram preservados no R2 privado; não repetir upload com base no diagnóstico histórico.

Para pacotes completos, seguir [ZIP à produção](zip-to-production.md), incluindo todas as referências HTML/CSS/JS, e preencher o [modelo de entrega](../templates/lore-pack-delivery.md).

| Sintoma | Como distinguir a causa | Próxima ação |
| --- | --- | --- |
| Credencial rejeitada | Validar configuração do ambiente e tipo de credencial, sem imprimir o segredo | Corrigir o par S3 e escopo; não repetir uploads às cegas |
| URL pública 404 | Conferir objeto pela API autenticada, key exata, domínio vinculado e cache da resposta | Recuperar/upload do objeto se ausente; corrigir caminho/domínio se presente; verificar novamente pelo domínio |
| 401/403 | Conferir autorização e visibilidade | Corrigir acesso; não tornar bucket privado público |
| HTTP 200 com HTML | Inspecionar MIME real e decodificação | Corrigir rota/fallback; não aceitar como imagem |
| Read-back diverge | Comparar bytes com o artefato enviado, não com outro derivado | Bloquear promoção e recuperar fonte/upload íntegros |
| Objeto abre, página falha | Inspecionar URL efetivamente requisitada, proxy/otimizador, CSP e CORS quando relevante | Corrigir consumidor e revalidar, sem recomprimir por tentativa |
| Imagem aparece borrada ou cortada | Conferir arquivo selecionado, tamanho natural, slot, DPR, crop e compressão | Ajustar variante/apresentação a partir do master e comparar visualmente |
| Nova imagem não aparece | Conferir referência promovida, release e cache | Corrigir referência/cache específico; preservar objeto anterior |

404 público não prova sozinho ausência no bucket. Não mascarar falha de origem adicionando um proxy. Mudança de DNS/domínio ou purge só após identificar o caminho afetado.

## Execução recuperável

Registrar resultado por arquivo a cada fase. Após interrupção, revalidar os objetos já enviados e retomar apenas o que falta; não sobrescrever por nome. Colisão ou hash divergente interrompe o item. Manter fonte, master e referência anterior até o aceite.

Relatório de entrega deve conter os campos e checks do [fluxo único](../integrations/r2/media-pipeline.md). Upload/read-back, teste no navegador e publicação possuem estados distintos. Uma implementação futura deve automatizar os gates técnicos; a revisão perceptiva continua explícita.

## Preparação de imagem

1. partir sempre do master ou da melhor fonte conhecida;
2. nunca gerar um novo lossy a partir de um lossy menor se o master estiver disponível;
3. registrar dimensão natural, role e superfície-alvo;
4. calcular `upscaleRatio = tamanho_exibido / tamanho_natural` no eixo limitante;
5. se `upscaleRatio > 1.50`, interromper: obter master melhor ou limitar o slot;
6. entre 1.15 e 1.50, exigir exceção e inspeção visual explícita;
7. escolher formato/encoder pela imagem real: AVIF para fotografia/ilustração opaca quando adequado; AVIF ou WebP para alpha após teste de borda; PNG quando lossless for necessário;
8. ajustar compressão procurando o menor arquivo visualmente indistinguível ou quase indistinguível do master na superfície-alvo;
9. revisar em 100% de zoom e nos viewports reais antes de considerar o derivado apto.

PSNR/SSIM e tamanho de arquivo podem ser registrados como apoio, mas não aprovam a imagem sozinhos. Rostos, cabelo, bordas transparentes, texto, gradientes e textura fina exigem inspeção humana.

## Next/Image e derivados já otimizados

`next/image` é entrega, não restauração. Ele não transforma uma fonte pequena em master de alta resolução.

Quando um asset local já é um AVIF/WebP final, pequeno e aprovado, evitar segunda compressão lossy se a economia marginal não compensar perda visual. `unoptimized` é aceitável para esses casos quando o arquivo já tem peso adequado e não há necessidade de variantes responsivas adicionais.

Quando o otimizador for necessário, a fonte entregue a ele deve ter resolução suficiente para a maior variante pedida. `sizes` precisa refletir a largura real do slot para evitar download maior do que o necessário.

## Cenas cinematográficas

Uma cena achatada/static só substitui background + subject se a variante final passar o gate de qualidade do fullscreen. Static de baixa resolução não deve ser esticado para preservar composição.

Se o static falhar:

1. manter o master registrado;
2. voltar temporariamente para layers com maior detalhe útil;
3. limitar cada subject à sua resolução natural quando necessário;
4. documentar a necessidade de flattened master hi-res;
5. reativar static somente após nova inspeção visual.

## Imagem temporariamente abaixo do gate

Se ainda não existe master melhor, qualidade tem prioridade sobre tamanho aparente: limitar o CSS ao detalhe natural do raster é preferível a ampliá-lo 2×. A limitação deve ser claramente temporária e removida quando o master hi-res for publicado.

## Publicação R2

Para as imagens históricas de sessão, o tooling existente é `tools/migrate-session-media-r2.mjs`. O modo padrão recupera/valida sem escrever no R2; `--verify-db --check-r2` faz verificações adicionais. Upload real exige autorização explícita e `--upload`.

Por objeto, registrar URL, HTTP status, Content-Type, bytes, SHA-256, dimensões, decode e horário, sem credenciais ou dados privados. Para derivados, registrar também master/provenance, role, encoder/parâmetros relevantes e superfície-alvo.

## Validação pós-publicação

Verificar:

- GET real e decode;
- dimensões recebidas;
- crop/focal point;
- desktop e mobile;
- 100% de zoom;
- ausência de upscale acima do gate;
- alpha/halo/banding;
- request/bytes finais;
- fallback e estado de erro;
- social/crawler quando aplicável.

Rollback preserva a referência anterior e aborta se houver edição concorrente. Upload aditivo não exige apagar o objeto para desfazer o consumo.
