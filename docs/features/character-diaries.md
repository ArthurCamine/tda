# Diários dos personagens

> Status: implementado em branch local; publicação pendente
> Owner: narrativa / frontend
> Última revisão: 2026-09-18

## Contrato

Diários são obras independentes em `/diario/<slug>`, com catálogo próprio em `/diario`. O diário de Astel não substitui nem implementa sua futura lore. Hospedar um diário não cria entity, relation, canon entry nem vínculo novo no banco. O conteúdo narrativo é a escrita do personagem, sem promoção automática a verdade canônica.

A decisão do autor nesta entrega autoriza a integração dos onze capítulos fornecidos e a preservação da experiência em livro. Planejamento, continuidade e guia de estilo são material local de trabalho e não entram nos arquivos públicos nem no Git.

Cada diário pode preservar sua composição editorial independente. O catálogo usa o Design System do TDA; o leitor estático abre por navegação de documento completo, com CSS/JS isolados do shell React. Por decisão editorial, o catálogo fica acessível pela URL direta `/diario` e pelo rodapé do leitor, sem link no layout compartilhado ou alteração na página principal. A integração com a navegação do site será definida em entrega posterior.

## Estrutura e atualização

- `src/features/diary/catalog.json`: slug, título, autor e descrição dos diários incluídos deliberadamente.
- `content/diaries/<slug>/*.md`: única fonte editorial versionada dos capítulos autorizados.
- `public/diario/<slug>/`: documento estático, estilos, comportamento e favicon técnico.
- `tools/diary/generate.mjs`: produz `capitulos.js`, `leitura.html` e metadata do livro a partir das fontes.
- `next.config.ts`: rewrites explícitos derivados do catálogo; slug desconhecido continua 404.

Após editar capítulos, executar `pnpm diary:generate`. O formato aceito preserva parágrafos de prosa e `***` como separador de cena; outras marcações Markdown não são convertidas. Títulos seguem `# Capítulo N: Título`, arquivos `NN_titulo.md`, numeração sequencial. O gerador escapa HTML e valida numeração/slug. `pnpm diary:check`, incluído em `pnpm check`, bloqueia cópias geradas divergentes. Para acrescentar um autor, criar fontes e documento próprios, cadastrar a entrada e validar sua experiência antes de publicar.

Não copiar diretórios de trabalho inteiros para `public`. Não criar CMS, banco, upload ou sistema de contas para este catálogo.

## Astel — entrega local

- Fonte: pasta fornecida pelo usuário em `.local/livro-astel`, preservada sem alteração; sem ZIP recebido.
- URL: `/diario/astel`; listagem apenas no catálogo de diários.
- 11 capítulos, de “Coisas Pequenas” a “Uma Resposta”.
- Identidade aprovada: capa e livro em CSS/SVG, cores, tipografia, páginas duplas em desktop e simples em mobile do pacote recebido.
- Sem imagens editoriais, fontes externas, áudio ou vídeo. Os SVGs são pequenos assets técnicos revisados; não há operação R2 nesta entrega. Mídia editorial futura segue a pipeline compartilhada.
- Marcador mantido no localStorage (`diario_astel_leitura_v1`); não é sincronizado entre aparelhos. Edição do texto pode deslocar uma posição anterior.
- Adaptações: caminhos absolutos, XI e demais numerais romanos, links para catálogo e leitura contínua, fallback de paginação, semântica acessível e metadata específica. Largura mínima do body/capa ajustada para não gerar rolagem horizontal em 320px com scrollbar.
- `leitura.html` contém os mesmos capítulos, com âncoras, texto selecionável, impressão e funcionamento sem JavaScript. Canonical aponta para o livro para evitar duplicar a identidade da obra.
- Compartilhamento usa título/descrição próprios e o fallback de marca `/og/default`, pois não foi fornecida arte social dedicada.
- Indexação permitida nesta versão pública candidata, seguindo o comportamento padrão do site; não há controle de acesso ou `noindex` implícito.

## Validação e publicação

Verificar fidelidade de texto, paginação, fonte, retomada, navegação por sumário, URLs com e sem barra, metadata no HTML, leitura sem JavaScript, mobile/desktop e movimento reduzido. Testes da superfície: `tests/diary.spec.ts`.

Evidências locais em 2026-09-18, branch `arthur/livro-astel`:

- `pnpm check`: passou; 434 testes Vitest passaram, 7 skips preexistentes, 40 testes Node passaram; lint sem erros, com warnings. Gates de mídia, Design System, documentação e banco passaram.
- `pnpm build`: passou, incluindo o catálogo `/diario` estático.
- `pnpm diary:check`: 11 capítulos sincronizados; o check normaliza CRLF/LF para funcionar após checkout no Windows.
- Playwright direcionado a `tests/diary.spec.ts`: 9/9 passaram, nos projetos 1920×1080, 2560×1440 e 390×844; verifica também 320×740, movimento reduzido e igualdade de todos os parágrafos da leitura contínua com os Markdown.
- Os testes de navegador finais usaram override local de configuração para o servidor do build já em execução em `127.0.0.1:4178`, sem fixtures de Auth desnecessárias. A suíte E2E completa do restante do produto não foi executada.
- Inspeção visual no navegador: capa e livro em desktop, catálogo/leitor em 390px, livro em 320px após correção de overflow. Sem chamada ao Supabase de produção para validar estas superfícies.
- Runtime disponível nesta máquina: Node 24.19.0 e shim pnpm 11.19.0; dependências do app instaladas pelo lockfile sem alteração. Os pins do repositório continuam Node 24.20.0/pnpm 12.3.4; a CI deve revalidar no runtime fixado antes de qualquer publicação.

Limitações deliberadas: marcador apenas local; texto depende de regeneração após edição; arte social usa fallback de marca. O total de páginas varia com fonte e viewport.

Nenhum upload, PR, merge ou deploy faz parte desta integração local. O fluxo remoto deve seguir [CI/CD vigente](../operations/ci-cd.md); criar PR já pode gerar Preview, e merge aprovado em main pode publicar Production. Publicado exige evidência do domínio/SHA, não apenas build local.

Rollback: reverter a entrega de catálogo, rewrite, leitor e fontes pelo fluxo de release; não há migration ou objetos R2 a desfazer. O material original local permanece disponível.
