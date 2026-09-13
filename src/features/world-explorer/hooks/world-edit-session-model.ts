export function worldEditFailureMessage(reason: string): string {
	switch (reason) {
		case "unauthenticated":
			return "Sua sessão expirou. Entre novamente antes de editar o Mundo.";
		case "profile_unresolved":
			return "Sua conta ainda não está vinculada a um perfil que possa editar o Mundo.";
		case "forbidden":
			return "Sua conta não possui permissão para esta edição do Mundo.";
		case "conflict":
			return "O Mundo publicado mudou enquanto este rascunho estava aberto. O rascunho foi preservado; recarregue antes de publicar.";
		case "lease_lost":
			return "A sessão exclusiva de edição expirou. Seu rascunho foi preservado para recuperação, mas precisa de uma nova sessão antes de publicar.";
		case "invalid_payload":
			return "Há um campo inválido no rascunho. Corrija-o antes de publicar.";
		case "duplicate":
			return "Já existe um elemento, slug ou ligação incompatível com esta alteração. Ajuste o rascunho e tente novamente.";
		case "media_pending":
			return "A imagem ainda não pôde ser verificada para publicação. O rascunho e a sessão de edição foram preservados; tente publicar novamente.";
		default:
			return "Não foi possível confirmar a edição agora. Nenhuma alteração foi publicada.";
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
