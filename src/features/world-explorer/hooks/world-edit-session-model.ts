export function worldPublishFailureMessage(reason: string): string {
	switch (reason) {
		case "unauthenticated":
			return "A publicação não aconteceu: sua sessão expirou. O rascunho continua preservado; entre novamente antes de publicar.";
		case "profile_unresolved":
			return "A publicação não aconteceu: sua conta ainda não está vinculada a um perfil autorizado. O rascunho continua preservado.";
		case "forbidden":
			return "A publicação não aconteceu: sua conta não possui permissão para esta edição. O rascunho continua preservado.";
		case "conflict":
			return "A publicação não aconteceu porque o Mundo publicado mudou desde o início desta edição. Seu rascunho foi preservado para reconciliação.";
		case "lease_lost":
			return "A publicação não aconteceu porque a sessão exclusiva expirou. Seu rascunho foi preservado; reabra a condução para recuperá-lo.";
		case "invalid_payload":
			return "A publicação não aconteceu porque existe um campo inválido no rascunho. Nada foi publicado e o rascunho continua preservado.";
		case "duplicate":
			return "A publicação não aconteceu porque ainda existe um nome, slug ou ligação incompatível/duplicada. Nada foi publicado e o rascunho continua preservado.";
		case "review_required":
			return "A publicação não aconteceu: há conteúdo marcado para campanha/web sem a revisão ou fonte canônica exigida. O rascunho continua preservado.";
		case "media_pending":
			return "A publicação não aconteceu porque uma imagem ainda não pôde ser verificada. O rascunho e a sessão foram preservados; tente novamente depois da verificação.";
		case "dependency_unavailable":
			return "Não foi possível confirmar o resultado da publicação por uma falha de servidor ou rede. O rascunho continua preservado; reabra o Mundo e confira a revisão publicada antes de tentar novamente.";
		default:
			return "Não foi possível confirmar o resultado da publicação. O rascunho continua preservado; confira a revisão publicada antes de tentar novamente.";
	}
}

export function worldDraftSaveFailureMessage(reason: string): string {
	switch (reason) {
		case "lease_lost":
			return "A sessão exclusiva expirou. O último rascunho confirmado continua preservado; reabra a condução antes de continuar.";
		case "conflict":
			return "O Mundo publicado mudou e este rascunho ficou desatualizado. Ele continua preservado e precisa ser reconciliado antes de publicar.";
		case "forbidden":
			return "Não foi possível salvar o rascunho porque sua permissão mudou. Mantenha esta aba aberta até recuperar a sessão.";
		case "invalid_payload":
			return "O rascunho contém um campo inválido e não pôde ser salvo. Corrija a alteração antes de sair desta página.";
		case "duplicate":
			return "O rascunho contém um conflito de nome, slug ou ligação e ainda não pôde ser salvo. Corrija-o antes de sair desta página.";
		default:
			return "Não foi possível confirmar o salvamento do rascunho. Mantenha esta aba aberta e tente novamente antes de sair.";
	}
}

export function worldEditFailureMessage(reason: string): string {
	switch (reason) {
		case "unauthenticated":
			return "Sua sessão expirou. Entre novamente antes de editar o Mundo.";
		case "profile_unresolved":
			return "Sua conta ainda não está vinculada a um perfil que possa editar o Mundo.";
		case "forbidden":
			return "Sua conta não possui permissão para esta edição do Mundo.";
		case "conflict":
			return "O Mundo publicado mudou enquanto este rascunho estava aberto. O rascunho foi preservado para reconciliação.";
		case "lease_lost":
			return "A sessão exclusiva de edição expirou. Seu rascunho confirmado continua preservado para recuperação.";
		case "invalid_payload":
			return "Há um campo inválido no rascunho. Corrija-o antes de continuar.";
		case "duplicate":
			return "Já existe um elemento, slug ou ligação incompatível com esta alteração.";
		case "review_required":
			return "Esta alteração precisa de revisão ou fonte canônica antes de poder ser publicada para essa audiência.";
		case "media_pending":
			return "A imagem ainda não pôde ser verificada. O rascunho e a sessão de edição foram preservados.";
		default:
			return "Não foi possível confirmar esta operação agora. O estado publicado não foi alterado.";
	}
}

export function worldLayoutPositionsEqual(
	left: Readonly<Record<string, Readonly<{ x: number; y: number }>>>,
	right: Readonly<Record<string, Readonly<{ x: number; y: number }>>>,
): boolean {
	const leftIds = Object.keys(left).sort();
	const rightIds = Object.keys(right).sort();
	if (leftIds.length !== rightIds.length) return false;
	return leftIds.every((id, index) => {
		if (id !== rightIds[index]) return false;
		return left[id]?.x === right[id]?.x && left[id]?.y === right[id]?.y;
	});
}
