# Companion — política de versões e dependências

> Status: requisito de release
> Owner: local-companion / processing
> Última revisão: 2026-09-11

## Regra

O TDA Companion deve usar a versão **estável mais recente e compatível** das dependências que fazem parte do runtime, build, empacotamento e ASR.

"Mais recente" não significa atualizar cegamente um major incompatível. Uma versão só pode virar baseline quando:

- é release estável, não preview/RC/dev;
- oferece artefato suportado para Windows x64 quando necessário;
- é compatível com a família de Python/runtime escolhida;
- passa testes Windows e Linux aplicáveis;
- passa build do bundle e MSI;
- passa smoke do runtime isolado;
- para GPU/ASR, passa teste físico na RTX 4070 8 GB antes de ser declarada suportada;
- não exige alterar Python, CUDA ou PATH global do computador do usuário.

Os pins continuam exatos para tornar cada release reproduzível. Antes de publicar uma nova release, os pins devem ser auditados contra os upstreams atuais.

Dependências transitivas do lock não são comparadas cegamente com o maior número publicado no PyPI: a versão correta é a resolvida pela versão atual das dependências diretas. O gate de freshness exige que os **pins diretos/runtime** estejam atuais e que o lock continue compatível com esses pins.

## Modelos ASR

Modelos também fazem parte deste requisito.

- cada modelo/aligner usado pelo Companion tem `revision` imutável de 40 caracteres;
- nunca usamos `main` flutuante em job de produção;
- o gate diário compara a revision pinada com a revision atual do upstream Hugging Face;
- se o upstream mudar, a release fica pendente de auditoria mesmo quando a mudança for apenas README/metadata;
- depois de revisar a mudança, atualizamos o pin e repetimos os gates aplicáveis;
- o conteúdo instalado continua recebendo hash próprio no marker local.

Isso permite simultaneamente saber qual upstream estamos acompanhando e reproduzir exatamente uma execução passada.

## Automação

- Dependabot monitora diariamente Python/pip do `local-companion` e GitHub Actions.
- O workflow de freshness verifica pins diretos Python/PyPI, Python 3.12, runtimes Whisper/Qwen e revisions dos modelos/aligner contra os upstreams atuais.
- Os workflows do Companion, Whisper e Qwen precisam usar o mesmo pin de `uv`.
- Mudança detectada não é auto-publicada: primeiro atualizamos o pin e executamos os gates novamente.

## CUDA

Whisper e Qwen têm runtimes isolados e podem usar famílias CUDA diferentes quando seus upstreams exigirem isso.

### Whisper / CTranslate2

Para Faster-Whisper/CTranslate2, o TDA segue a família CUDA suportada pelo upstream. Enquanto CTranslate2 exigir CUDA 12.x para os wheels usados pelo Companion, **CUDA 13 não substitui a baseline Whisper só por ser numericamente mais nova**.

Dentro da família CUDA 12.x, usamos os releases estáveis mais recentes de runtime/cuBLAS/cuDNN que passem o build, o probe e o teste físico.

### Qwen / PyTorch

Qwen3 usa runtime PyTorch/Transformers separado. O runtime 1.0.5 adota temporariamente o wheel oficial **PyTorch 2.13.0 + CUDA 12.6** como exceção explícita de compatibilidade. O motivo é operacional: CUDA 13.x exige driver NVIDIA da família 580 ou superior para minor-version compatibility, enquanto o Companion não instala nem altera driver NVIDIA automaticamente.

A exceção fica declarada no próprio manifest Qwen em `dependency_freshness_exceptions` e só é aceita pelo gate quando nome e versão coincidem exatamente com o pin efetivo. Trocar o pin invalida a exceção. O caminho de remoção da exceção é repetir o aceite físico numa baseline de driver compatível com CUDA 13.x e então voltar ao PyTorch estável mais recente.

Além da descoberta da GPU, o runtime Qwen deve executar uma operação CUDA real de smoke antes de qualquer modelo ser aceito. `torch.cuda.is_available()` isoladamente não constitui prova suficiente de compatibilidade driver/runtime.

O fato de Qwen poder usar CUDA 13.x não autoriza migrar o runtime Whisper para CUDA 13 enquanto CTranslate2 não suportar essa família.

## Exceções

Toda exceção precisa ser explícita e ter justificativa técnica ou legal. Exceções de dependência runtime devem ser machine-readable no manifest correspondente, vinculadas à versão pinada e rejeitadas automaticamente quando o pin divergir.

### WiX Toolset

O MSI permanece temporariamente em WiX 5.0.2. WiX 6/7 introduzem mudança major e requisitos de licenciamento/OSMF que precisam ser avaliados antes de adotarmos a versão mais nova no pipeline. Essa retenção não autoriza deixar as demais dependências desatualizadas.

A migração de WiX deve ser testada isoladamente e só entra quando o contrato/licenciamento e os smokes de install/upgrade/uninstall/purge estiverem aprovados.

## Fontes de verdade

- Dependências Python do Companion: `local-companion/pyproject.toml`
- Lock dos testes: `local-companion/requirements-test.lock`
- Runtime Whisper Windows: `local-companion/runtime/whisper-windows-x64.json`
- Runtime Qwen Windows: `local-companion/runtime/qwen-windows-x64.json`
- Perfis e revisions ASR: `local-companion/tda_companion/asr_models.py`
- Workflow do Companion: `.github/workflows/companion.yml`
- Workflow do runtime Whisper: `.github/workflows/whisper-runtime.yml`
- Workflow candidato Qwen: `.github/workflows/qwen-runtime.yml`
- Gate de versões: `.github/workflows/companion-dependency-freshness.yml`

Uma release não deve ser promovida para produção se a auditoria de versões estiver pendente ou se uma exceção necessária não estiver documentada.
