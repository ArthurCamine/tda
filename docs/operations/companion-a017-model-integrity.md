# TDA Companion — A-017 integridade dos modelos ASR

> Status: implementado em candidato; integração condicionada aos gates automáticos e ao aceite físico
> Owner: local-companion / processing / operations / security
> Última revisão: 2026-09-14

## Objetivo

Fechar o achado A-017 sem transformar o diagnóstico cotidiano do Companion em rehash de vários GiB.

O contrato separa duas afirmações que não podem ser tratadas como equivalentes:

- **metadata-ready**: diretório, arquivos obrigatórios, identidade do modelo, revisão e marker local são coerentes; é a checagem barata usada no diagnóstico cotidiano;
- **integrity-verified**: o conteúdo completo do modelo foi relido e comparado por SHA-256 com o hash registrado no marker; é obrigatório no gate físico que produz evidência de aceite.

## Whisper

O aceite físico Whisper agora executa `inspect_model_install(..., verify_hash=True)` depois da preparação do modelo e antes de carregar o modelo na GPU. Se o rehash falhar, o aceite termina em `ACCEPTANCE_MODEL_INTEGRITY_FAILED` e nenhuma inferência é usada como evidência.

O receipt inclui:

- `model_content_sha256`;
- `model_integrity = sha256-full`;
- modelo e revisão já pinados pelo perfil.

## Qwen

O gate físico Qwen já fazia rehash completo tanto do modelo ASR quanto do Forced Aligner ao registrar o gate. A remediação A-017 preserva esse comportamento e torna a distinção explícita no diagnóstico: o check diário de modelo é apenas metadata-ready, enquanto o gate aceito informa que SHA-256 completo foi verificado no momento do aceite.

## Diagnóstico cotidiano

O diagnóstico não relê vários GiB a cada abertura. Um modelo com marker/identidade coerentes é reportado como instalado com metadados coerentes e recebe detalhe `integrity=metadata-only`.

Isso **não** é evidência suficiente para promoção stable. A evidência criptográfica pertence ao gate físico e ao receipt correspondente.

## Claims permitidos

- “modelo instalado / metadata-ready” quando somente o diagnóstico barato passou;
- “integridade SHA-256 completa verificada no aceite físico” somente quando o gate físico correspondente foi produzido com sucesso.

## Claims proibidos

- chamar metadata-ready de integridade criptográfica verificada;
- usar o diagnóstico cotidiano como substituto do receipt físico;
- promover runtime/modelo com base apenas em marker, nomes de arquivos ou revisão declarada.

## Testes

A suíte cobre:

- adulteração do conteúdo Whisper depois da criação do marker;
- falha fechada do aceite Whisper quando a integridade não valida;
- garantia de que o diagnóstico diário chama a inspeção com `verify_hash=False`;
- mensagem explícita de metadata-only;
- exposição do vínculo de integridade do gate Qwen como verificado no aceite.
