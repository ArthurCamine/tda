# TDA Companion 0.3.3 — auditoria pesada de confiabilidade, segurança e release

> Status: auditoria concluída; 0.3.3 aposentada para certificação; remediação integrada na linha 0.3.4
> Owner: local-companion / processing / operations / security
> Última revisão: 2026-09-13

## Veredito

A auditoria revisou o candidato 0.3.3 associado ao source SHA `0307eee50a786b86c7baaa940dab0cc95a11fb75`, o artifact `10326455543` e o MSI SHA-256 `520481a800302337b14faa1a9bb9a897b09e9cab016afc786e06d73f20bac9a5`.

O candidato passou os gates automáticos existentes, mas a auditoria encontrou lacunas que impedem promovê-lo a stable. Por decisão operacional, o 0.3.3 permanece apenas como evidência histórica. A correção segue diretamente na linha que será promovida a Preview/main/Production como 0.3.4.

## Achados

| ID | Severidade | Área | Achado | Decisão |
| --- | --- | --- | --- | --- |
| A-001 | BLOCKER | aceite/release | receipt não vinculava EXE/helper instalados ao payload esperado do MSI | corrigir com payload manifest e comparação de hashes/tamanhos |
| A-002 | HIGH assurance | aceite | observações físicas eram autoatestadas por `PASS` | separar atestação humana de evidência medida |
| A-003 | HIGH assurance | Agent/aceite | recovery podia ser aceito sem PID inicial verificável | tornar gate fail-closed e medir PID antes/depois |
| A-004 | BLOCKER | segurança/manutenção | helper de manutenção podia enviar Bearer token a listener local que apenas respondesse HTTP 200 | remover segredo do fluxo de maintenance ou exigir identidade forte antes de qualquer auth |
| A-005 | HIGH | segurança local | handshake público do Agent era identidade declarativa, não prova criptográfica | documentar threat model e adicionar prova/peer validation quando necessário |
| A-006 | MEDIUM | API/recovery | retry automático de POST não exigia idempotência explícita | retry de mutation somente com idempotência conhecida/chave |
| A-007 | MEDIUM | BITS/network | BITS não permite a mesma inspeção de redirect-hop do fallback urllib | manter URL inicial estrita e SHA/tamanho como autoridade de integridade; não alegar paridade de hops |
| A-008 | MEDIUM assurance | BITS/aceite | gate físico não provava que o mesmo job BITS foi retomado | registrar evidência sanitizada de job/bytes/reuso |
| A-009 | BLOCKER release | CI/provenance | workflow de PR podia construir merge sintético e rotular artifact pelo head SHA | checkout explícito do source SHA e tree SHA no artifact/candidate manifest |
| A-010 | MEDIUM | diagnostics | probe de asset não era equivalente ao updater real | alinhar semântica ou rotular como reachability probe |
| A-011 | MEDIUM | testes | testes de release aceitavam hashes arbitrários de EXE/helper | testes negativos ligados ao payload manifest real |
| A-012 | HIGH | supply chain | EXE/helper/MSI sem Authenticode | assinar e verificar publisher/timestamp antes de stable |
| A-013 | MEDIUM/HIGH | supply chain | Actions críticas usavam tags móveis | pin por full commit SHA |
| A-014 | BLOCKER release | reproducibilidade | closure completa de dependências de packaging não estava travada | lock completo e verificação frozen do ambiente Windows |
| A-015 | MEDIUM/HIGH | operação | artifact expirava em 14 dias antes de RC formal | ampliar retenção e publicar RC antes do gate físico |
| A-016 | MEDIUM | diagnostics/proxy | DNS direto degradado podia bloquear receipt mesmo com HTTPS via proxy funcionando | readiness deve refletir caminho real configurado |
| A-017 | MEDIUM/R4 | modelos ASR | diagnóstico podia declarar modelo ready sem rehash do conteúdo | separar metadata-ready de integrity-verified |
| A-018 | HIGH | runtimes ASR | runtimes Whisper/Qwen podiam virar stable antes do gate GPU físico exato | aplicar RC -> GPU receipt -> same bytes stable |
| A-019 | HIGH/R4 | Qwen timeline | falha de alignment podia virar fallback temporal de janela e job seguir sucesso | expor precisão temporal e bloquear/avisar por limiar |
| A-020 | MEDIUM/R4 | memória | alignment Qwen materializava todas as windows de uma track | streaming/replay sequencial com teto de RAM |
| A-021 | HIGH/R4 | qualidade ASR | Qwen usava janelas duras não sobrepostas de 180 s | overlap/long-form strategy e corpus de fronteira |
| A-022 | MEDIUM | disponibilidade | manifest stable dependia de GitHub API sem índice first-party | stable index atômico ou cache/autenticação sem stale selection |
| A-023 | MEDIUM | promoção | ancestry por source SHA podia bloquear squash/rebase | usar conteúdo/tree equivalentes ou merge policy explícita |
| A-024 | MEDIUM | RC | criação de RC não era idempotente após sucesso parcial | validar/reutilizar RC existente se bytes forem idênticos |
| A-025 | LOW/MEDIUM | Craig/Windows | filenames do ZIP não cobriam toda semântica especial NTFS | filename físico canônico separado do speaker display name |

## Evidência do candidato auditado

| Campo | Valor |
| --- | --- |
| Versão | `0.3.3` |
| Source SHA declarado | `0307eee50a786b86c7baaa940dab0cc95a11fb75` |
| Merge sintético observado no run PR | `77550391a72067fc6f359956a38c93d3d80d6d81` |
| Tree comum naquele candidato | `e0964b3f0c3676eec4f5e384b81f6f755cdc5030` |
| Workflow run | `34784373249` |
| Artifact id | `10326455543` |
| Artifact archive SHA-256 | `f42b639915589e1764c157288b58de91b7f1141c60446d4399389c8bf6077b1f` |
| MSI SHA-256 | `520481a800302337b14faa1a9bb9a897b09e9cab016afc786e06d73f20bac9a5` |
| Portable ZIP SHA-256 | `15ca793ae67da7c1869313eb89e531a95753ebe2d366c8975acde7468c09bec5` |
| Decisão | `RETIRED_FROM_CERTIFICATION` |

O merge sintético e o source SHA possuíam a mesma tree neste candidato específico; portanto A-009 não prova divergência de conteúdo do MSI 0.3.3. O problema é estrutural: sem checkout explícito, um run futuro pode rotular bytes de outra tree.

## Pontos que resistiram bem à auditoria

- Agent preso a `127.0.0.1`, Host guard e Origin guard.
- Bearer comparado com `hmac.compare_digest` no Agent.
- pairing token com ACL restritiva no Windows.
- Craig com defesa contra absoluto, `..`, subpastas, symlink, nomes duplicados, excesso de entries, tamanho total/per-track e compression ratio.
- update com manifest versionado, tamanho/SHA-256, `.partial` e `os.replace`.
- BITS preservando transferências pendentes e concluindo `Transferred` antes de promover o arquivo.
- WiX rollback probe forçando falha após `RemoveExistingProducts` e exercitando rollback/upgrade/preserve/purge.
- RC/promotion desenhados para promover os mesmos bytes, sem rebuild após aceite.

## Claims proibidos até remediação

Não usar como afirmação de release:

- “o mesmo MSI foi provado fisicamente” sem payload binding completo;
- “Bearer nunca chega a listener estranho” enquanto houver qualquer caminho de maintenance não verificado;
- “source SHA do run é necessariamente o checkout que gerou os bytes” sem source identity explícita;
- “rebuild do mesmo SHA é byte-equivalente” sem lock completo;
- “BITS inspeciona a mesma cadeia de redirects do urllib”; 
- “diagnóstico ready prova integridade criptográfica do modelo”; 
- “Qwen possui timeline precisa” quando houve fallback de alignment; 
- “runtime stable significa GPU fisicamente homologada” sem receipt do artifact exato.

## Ordem de remediação

### P0 — antes do próximo build de produção

1. A-004 — remover vazamento de token no maintenance;
2. A-001/A-011 — payload manifest e tests negativos;
3. A-009 — checkout/source/tree únicos;
4. A-014 — lock completo e verificação da closure;
5. A-003 — recovery fail-closed;
6. A-002 — separar atestação e medição.

### P1 — antes de declarar stable confiável

A-005, A-006, A-008, A-012, A-013, A-015, A-016, A-018, A-023 e A-024.

### R4 — qualidade real

A-017, A-019, A-020 e A-021, além de corpus com cross-talk, fronteiras de janela, silêncio, nomes próprios, WER/CER, erro temporal e teto de RAM.

### Hardening adicional

A-007, A-010, A-022 e A-025.

## Gate do próximo candidato

O próximo candidato só pode ser publicado para teste pesado real quando:

- source SHA e source tree do build forem explícitos;
- ambiente packaging estiver travado e verificado;
- payload manifest incluir EXE/helper/scripts e for validado após instalação;
- maintenance não puder transmitir segredo a listener estranho;
- RC for imutável e referenciar exatamente os artifacts do run verde;
- receipts distinguirem atestação humana de evidência medida;
- CI Linux/Windows, MSI install/uninstall, rollback, upgrade, preserve/purge e web/E2E estiverem verdes no mesmo source.

Depois disso o plano operacional é integrar a mudança em Preview, promover Preview -> main e executar os testes pesados contra Production real.

## Estado da remediação 0.3.4

A linha 0.3.4 já incorporou parte dos achados enquanto esta auditoria era consolidada: source checkout explícito, Actions pinadas por SHA, lock de dependências ampliado/verificado, retenção maior, payload evidence v2 e RC idempotente. O documento continua sendo a lista canônica dos achados originais; o status final de cada item deve ser atualizado somente após teste que prove a correção.
