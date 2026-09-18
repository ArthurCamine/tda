import type {
	BridgeErrorCode,
	JobEvent,
	JobStatus,
} from "./protocol";

export const connectionHelp: Record<BridgeErrorCode, string> = {
	unreachable:
		"Não foi possível alcançar o serviço. Confira se ele está aberto neste computador e se este site tem permissão de acesso à rede local. O navegador não informa se a causa é conexão, origem ou permissão.",
	timeout:
		"O serviço não respondeu a tempo. Confira o aplicativo local e conecte novamente. Uma ação enviada pode ter sido recebida; verifique a fila antes de repetir.",
	unauthorized:
		"Pareamento recusado ou revogado. Copie um token válido do aplicativo local e conecte novamente.",
	forbidden:
		"O serviço recusou este acesso. Confira no aplicativo local se a origem exata deste site está autorizada.",
	incompatible:
		"Versão incompatível. Esta tela requer a API v1. Use uma versão compatível do serviço local.",
	invalid_response:
		"O serviço retornou dados inválidos para este contrato. Confira sua versão e consulte o suporte com o código invalid_response.",
	conflict:
		"O estado do trabalho mudou. Conecte novamente para consultar a fila antes de tentar outra ação.",
	service_error:
		"O serviço não concluiu a solicitação. Confira o diagnóstico no aplicativo local e conecte novamente.",
};
export const jobLabels: Record<JobStatus, string> = {
	queued: "Na fila",
	running: "Processando",
	succeeded: "Concluído",
	failed: "Falhou",
	cancelled: "Cancelado",
	interrupted: "Interrompido",
};
export const stageLabels: Record<string, string> = {
	queued: "Aguardando execução",
	fixture: "Ensaio sintético",
	checking_model: "Verificando modelo",
	downloading_model: "Baixando modelo",
	model_prepare: "Baixando/verificando modelo local",
	model_load: "Carregando modelo na GPU",
	alignment: "Alinhando palavras e timestamps",
	cross_track_dedup: "Removendo falas duplicadas",
	merge_timeline: "Montando linha do tempo",
	turn_building: "Organizando turnos de fala",
	result_prepare: "Gravando resultado local",
	loading_cpu: "Carregando modelo na CPU",
	loading_cuda: "Carregando modelo na GPU",
	loading_cuda_fallback: "Ajustando uso de VRAM",
	preparing: "Preparação",
	diarization: "Separação de falas",
	noise_cleanup: "Limpeza de ruído",
	resuming: "Retomando checkpoint",
	transcribing: "Transcrição",
	consolidating: "Consolidação",
	complete: "Resultado preparado",
	cancelled: "Cancelado",
	interrupted: "Execução interrompida",
};

const genericProgressJokes = [
	"O PC segue firme e ainda não pediu férias.",
	"Mais uma etapa domesticada sem sacrificar nenhum dado.",
	"O hamster da GPU continua correndo. Tudo sob controle.",
	"A máquina está trabalhando; a dignidade dela a gente avalia depois.",
] as const;

const transcriptionJokes = [
	(speaker: string) => `A voizinha de ${speaker} está rendendo serviço hoje 👀`,
	(speaker: string) => `Whisper e ${speaker} estão numa conversa séria agora.`,
	(speaker: string) => `Mais um pedaço de ${speaker} domesticado pela GPU.`,
] as const;

function textData(event: JobEvent, key: string): string | null {
	const value = event.data[key];
	return typeof value === "string" ? value : null;
}

function numberData(event: JobEvent, key: string): number | null {
	const value = event.data[key];
	return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function eventBytes(value: number): string {
	const mib = value / 1024 ** 2;
	if (mib < 1024) return `${mib.toFixed(mib >= 100 ? 0 : 1)} MB`;
	const gib = mib / 1024;
	return `${gib.toFixed(gib >= 10 ? 1 : 2)} GB`;
}

function choose<T>(values: readonly T[], seed: number): T {
	return values[Math.abs(seed) % values.length];
}

export type PresentedJobEvent = Readonly<{
	title: string;
	detail?: string;
}>;

export function presentJobEvent(event: JobEvent): PresentedJobEvent {
	const completed = numberData(event, "completed");
	const total = numberData(event, "total");
	const percent = numberData(event, "percent");
	const speaker = textData(event, "speaker");
	const track = numberData(event, "track");
	const totalTracks = numberData(event, "total_tracks");

	switch (event.code) {
		case "DUPLICATE_SUBMISSION_REUSED":
			return {
				title: "A mesma transcrição já estava ativa; o TDA reutilizou o trabalho existente.",
				detail: "Nenhuma cópia extra foi adicionada à fila.",
			};
		case "MODEL_DOWNLOAD_PROGRESS": {
			const downloaded = numberData(event, "downloaded_bytes");
			return {
				title: downloaded !== null
					? `Modelo local sendo baixado/verificado · ${eventBytes(downloaded)}.`
					: "Modelo local sendo baixado/verificado.",
				detail: "A GPU pode ficar em 0% enquanto os arquivos chegam ao disco.",
			};
		}
		case "QWEN_WINDOW_TRANSCRIBED": {
			const track = numberData(event, "track");
			const window = numberData(event, "window");
			return {
				title: `Qwen concluiu uma janela de áudio${track !== null ? ` da faixa ${track}` : ""}${window !== null ? ` · janela ${window}` : ""}.`,
			};
		}
		case "ASR_CHECKPOINT_REUSED":
			return { title: "Checkpoint local reutilizado; esta faixa não precisa ser refeita." };
		case "ASR_CHECKPOINT_SAVED":
			return { title: "Checkpoint da faixa salvo com sucesso." };
		case "QUEUED":
			return { title: "Trabalho adicionado à fila." };
		case "RUNNING":
			return {
				title: "Processamento iniciado.",
				detail: "A máquina acordou. Agora vai.",
			};
		case "UNIT_COMMITTED":
			return {
				title:
					completed !== null && total !== null
						? `Unidade ${completed} de ${total} concluída.`
						: "Unidade de trabalho concluída.",
				detail: choose(genericProgressJokes, event.seq),
			};
		case "MODEL_LOADING":
			return {
				title: "Carregando modelo de transcrição na GPU.",
				detail: "A VRAM recebeu visita. Esperamos que ela tenha arrumado a casa.",
			};
		case "TRACK_STARTED":
			return {
				title:
					track !== null && totalTracks !== null
						? `Arquivo ${track} de ${totalTracks}${speaker ? ` — ${speaker}` : ""}.`
						: `Transcrição iniciada${speaker ? ` — ${speaker}` : ""}.`,
			};
		case "TRACK_PROGRESS":
			return {
				title: `${speaker ? `Processando voz — ${speaker}` : "Transcrevendo áudio"}${percent !== null ? ` · ${Math.round(percent)}%` : ""}.`,
				detail: speaker
					? choose(transcriptionJokes, event.seq)(speaker)
					: choose(genericProgressJokes, event.seq),
			};
		case "NOISE_REDUCTION_PROGRESS":
			return {
				title: `Reduzindo ruído de fundo${speaker ? ` — ${speaker}` : ""}${percent !== null ? ` · ${Math.round(percent)}%` : ""}.`,
				detail: speaker
					? `Separando os chiados de ${speaker} sem julgar ninguém ✨`
					: "Separando o que é voz do que claramente queria virar podcast de ventilador.",
			};
		case "BACKGROUND_SPEECH_DETECTED":
			return {
				title: "Fala de fundo detectada.",
				detail: "A família decidiu participar da sessão também.",
			};
		case "DOG_BARK_IGNORED":
			return {
				title: "Latido identificado e ignorado.",
				detail: "O cachorro tentou entrar no canon. Pedido negado.",
			};
		case "TRACK_COMPLETED":
			return {
				title: `Arquivo concluído${speaker ? ` — ${speaker}` : ""}.`,
				detail: "Uma voz a menos para a GPU interrogar.",
			};
		case "SUCCEEDED":
			return {
				title: "Processamento concluído com sucesso.",
				detail: "Sobreviveu todo mundo. Inclusive o PC.",
			};
		case "CANCELLED":
			return { title: "Processamento cancelado pelo operador." };
		case "INTERRUPTED":
		case "PROCESS_INTERRUPTED":
			return { title: "Execução interrompida; o trabalho pode ser repetido." };
		case "FIXTURE_EXECUTION_FAILED":
			return { title: "O ensaio sintético encontrou uma falha." };
		default:
			return { title: event.code.replaceAll("_", " ").toLocaleLowerCase("pt-BR") };
	}
}
