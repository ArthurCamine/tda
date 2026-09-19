# TDA — Tem Dado Aqui
Base do reboot: uma aplicação para histórias, sessões e o futuro Edit integrado.

- [Documentação e roadmap](docs/README.md)
- [Arquitetura](docs/architecture.md)
- [Infraestrutura e estado](docs/infrastructure.md)
- [Publicação controlada](docs/releases.md)
- [Como contribuir](CONTRIBUTING.md)

Node indicado em .node-version, pnpm fixado no package.json. Instalar com `pnpm install --frozen-lockfile`; verificar com `pnpm check`, `pnpm build` e `pnpm test:e2e`. Executar `pnpm dev`.

Copiar `.env.example` para `.env.local` somente quando a tarefa precisar de integrações autenticadas. Desenvolvimento básico, testes e validação de mídia com `pnpm media:validate` não exigem credenciais R2. Contribuidores não precisam receber segredos de Production para preparar mídia: a publicação canônica ocorre pela Production CD com credenciais protegidas no GitHub Environment. Sem credenciais locais, o site mostra um estado de preparação; não inventa sessões. Leitura real é explícita e somente de sessões publicadas.
