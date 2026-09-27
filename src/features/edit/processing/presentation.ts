import type {
	BridgeErrorCode,
	BridgeErrorDetails,
	JobEvent,
	JobStatus,
	LocalJob,
} from "./protocol";

export const connectionHelp: Record<BridgeErrorCode, string> = {
	unreachable:
		"Não foi possível alcançar o serviço. Confira se ele está aberto neste computador e se este site tem permissão de acesso à rede local. O navegador não informa se a causa é conexão, origem ou permissão.",
	timeout:
		"O serviço local não respondeu a tempo. Confira o Companion e tente novamente. Uma ação enviada pode ter sido recebida; verifique a fila antes de repetir.",
	unauthorized:
		"A sessão local expirou ou foi recusada. O TDA tentará criar uma nova sessão automaticamente; se necessário, abra o Companion e tente novamente.",
	forbidden:
		"O serviço recusou este acesso. Confira no aplicativo local se a origem exata deste site está autorizada.",
	api_incompatible:
		"A API do Companion não é compatível com esta tela. Atualize o aplicativo local.",
	version_incompatible:
		"A versão do Companion é antiga demais para a conexão automática desta tela. Atualize o aplicativo local.",
	session_incompatible:
		"O Companion não oferece o contrato de sessão automática esperado por esta tela. Atualize o aplicativo local.",
	incompatible:
		"O Companion não suporta o contrato exigido por esta tela. Atualize o aplicativo local.",
	invalid_response:
		"O serviço retornou dados inválidos para este contrato. Confira sua versão e consulte o suporte com o código invalid_response.",
	payload_too_large:
		"A solicitação local excede o orçamento UTF-8 aceito pelo Companion. Reduza o texto antes de tentar novamente.",
	conflict:
		"O estado local mudou e esta ação não pôde ser aplicada. A conexão continua ativa; atualize a fila e confira o trabalho antes de repetir.",
	service_error:
		"O Companion não concluiu esta solicitação. A conexão continua ativa; confira os eventos/diagnóstico local antes de repetir.",
};

export function presentConnectionError(
	code: BridgeErrorCode,
	details: BridgeErrorDetails | null = null,
): string {
	if (code === "version_incompatible") {
		const detected = details?.detectedServiceVersion;
		const minimum = details?.minimumServiceVersion;
		if (detected && minimum)
			return `TDA Companion v${detected} detectado. Esta tela requer v${minimum} ou mais recente para conexão automática. Atualize o aplicativo local.`;
	}
	if (code === "api_incompatible") {
		const detected = details?.detectedApiVersion;
		const required = details?.requiredApiVersion;
		if (detected && required)
			return `API v${detected} detectada. Esta tela requer API v${required}. Atualize o TDA Companion.`;
	}
	return connectionHelp[code];
}

export function presentJobTitle(job: Pick<LocalJob, "kind">): string {
	if (job.kind === "synthetic.fixture") return "Ensaio sintético";
	if (job.kind === "transcription.craig") return "Transcrição de sessão";
	return job.kind;
}

export function presentJobError(code: string): string {
	const known: Record<string, string> = {
		AGENT_BUSY: "O Companion está ocupado com um processamento ou preparação local; aguarde a operação atual terminar.",
		PROCESS_INTERRUPTED: "Execução interrompida pelo encerramento ou reinício do Agent.",
		WORKER_START_TIMEOUT: "O worker local não iniciou dentro do tempo esperado.",
		WORKER_RUNTIME_BOOTSTRAP_TIMEOUT: "O runtime local não concluiu a inicialização pesada dentro do limite esperado.",
		WORKER_RUNTIME_BOOTSTRAP_FAILED: "O runtime local falhou durante a inicialização antes do processamento.",
		WORKER_HEARTBEAT_TIMEOUT: "O worker local parou de responder.",
		WORKER_EXECUTION_FAILED: "O worker local encontrou uma falha inesperada.",
		WORKER_COMMAND_INVALID: "O Companion não conseguiu iniciar o worker com um comando local válido.",
		WORKER_EXITED_WITHOUT_RESULT: "O worker local encerrou sem informar resultado, cancelamento ou erro.",
		WORKER_EXIT_TIMEOUT: "O processo do worker não encerrou corretamente dentro do limite esperado.",
		WORKER_NONZERO_EXIT: "O worker informou o resultado, mas o processo encerrou de forma anormal; o TDA verificará se existe um run íntegro para recuperar.",
		WORKER_PROTOCOL_INVALID: "O worker local enviou uma mensagem inválida para o Companion.",
		WORKER_LINE_SIZE_INVALID: "O worker local enviou uma mensagem maior que o limite seguro do protocolo.",
		WORKER_STDOUT_ENCODING_INVALID: "O worker local enviou dados de saída corrompidos ou com codificação inválida.",
		WORKER_READY_REQUIRED: "O worker local não completou o handshake obrigatório antes de enviar dados de processamento.",
		WORKER_READY_REPLAY: "O worker local repetiu o handshake de inicialização de forma inválida.",
		WORKER_SEQUENCE_GAP: "O worker local perdeu uma mensagem na sequência; a execução foi interrompida para proteger o estado.",
		WORKER_ASR_ROOTS_UNCONFIGURED: "O worker local não recebeu os diretórios seguros de dados e modelos.",
		WHISPER_RUNTIME_UNAVAILABLE: "O runtime Whisper local não está disponível ou não passou pela verificação.",
		WHISPER_RUNTIME_UNCONFIGURED: "O runtime Whisper ainda não está configurado neste Companion.",
		QWEN_RUNTIME_UNAVAILABLE: "O runtime Qwen local não está disponível ou não passou pela verificação.",
		QWEN_RUNTIME_UNCONFIGURED: "O runtime Qwen ainda não está configurado neste Companion.",
		QWEN_PHYSICAL_ACCEPTANCE_REQUIRED: "O Qwen precisa concluir novamente a validação física de runtime, modelo e GPU antes de processar.",
		WORKER_RESULT_RUN_INVALID: "O run local falhou na validação de integridade.",
		WORKER_RESULT_RUN_MISMATCH: "O run local não corresponde a este job e tentativa.",
		WORKER_RESULT_INCOMPLETE: "O worker terminou sem concluir todas as unidades exigidas pela fila.",
		WORKER_PROGRESS_GAP: "O worker informou progresso fora de ordem; o job foi interrompido para proteger o estado local.",
		TRANSCRIPT_VALIDATION_FAILED: "O engine produziu uma transcrição que não passou pela validação estrutural.",
		TRANSCRIPTION_SOURCE_HASH_MISMATCH: "A transcrição não corresponde à fonte Craig esperada.",
		RESULT_ARTIFACT_UNAVAILABLE: "O run concluído está registrado, mas o artefato imutável não está mais disponível no disco.",
		RESULT_ARTIFACT_MISMATCH: "O artefato local não corresponde mais à identidade registrada para este resultado.",
		CRAIG_MANIFEST_INVALID: "A fonte Craig local está inválida; reimporte o ZIP original.",
		CRAIG_MANIFEST_TRACK_HASH_MISMATCH: "Uma faixa Craig foi alterada; reimporte o ZIP original.",
		CRAIG_MANIFEST_TRACK_SIZE_MISMATCH: "Uma faixa Craig mudou de tamanho; reimporte o ZIP original.",
		CRAIG_MANIFEST_TRACK_METADATA_MISMATCH: "Uma faixa Craig mudou no disco; reimporte o ZIP original para reparar a fonte local.",
		CRAIG_STAGING_REPAIR_FAILED: "O TDA tentou reparar a fonte Craig local, mas não conseguiu concluir a troca segura.",
		QWEN_CUDA_DRIVER_INCOMPATIBLE: "O driver NVIDIA/CUDA não é compatível com este runtime Qwen.",
		QWEN_ASR_GPU_MEMORY_EXHAUSTED: "O Qwen ficou sem VRAM durante a execução.",
		QWEN_ASR_CUDA_FAILED: "O Qwen encontrou uma falha CUDA durante a execução.",
		QWEN_ASR_RUNTIME_API_FAILED: "O runtime Qwen encontrou uma falha interna ao executar a API de inferência/alinhamento.",
		QWEN_ASR_INFERENCE_FAILED: "O Qwen não conseguiu concluir a inferência desta faixa.",
		QWEN_ALIGNMENT_REQUIRED: "O alinhamento obrigatório falhou. Abra Diagnóstico para ver a faixa, a janela e a causa específica. Nenhum resultado parcial foi publicado.",
		QWEN_ALIGNMENT_FAILED: "O alinhador do Qwen falhou ao sincronizar as palavras com o áudio.",
		QWEN_AUDIO_DECODE_FAILED: "O Qwen não conseguiu decodificar uma das faixas de áudio.",
		QWEN_AUDIO_EMPTY: "Uma das faixas chegou vazia ao pipeline de áudio do Qwen.",
		QWEN_MODEL_NOT_GPU_RESIDENT: "O modelo Qwen não permaneceu carregado corretamente na GPU.",
		QWEN_ALIGNER_NOT_GPU_RESIDENT: "O alinhador do Qwen não permaneceu carregado corretamente na GPU.",
		QWEN_RUNTIME_NOT_INSTALLED: "O runtime Qwen necessário para esta execução não está instalado.",
		QWEN_TRACK_PROGRESS_INCOMPLETE: "O Qwen encerrou uma faixa sem concluir todas as janelas esperadas.",
		QWEN_WINDOW_REPLAY_MISMATCH: "Um checkpoint do Qwen não corresponde ao replay esperado; a execução foi interrompida para proteger o resultado.",
		WHISPER_MODEL_LOAD_FAILED: "O Whisper não conseguiu carregar o modelo local.",
		WHISPER_MODEL_NOT_LOADED: "O Whisper não manteve o modelo carregado para iniciar a transcrição.",
		WHISPER_RUNTIME_NOT_INSTALLED: "O runtime Whisper necessário para esta execução não está instalado.",
		WHISPER_CUDA_UNAVAILABLE: "O Whisper não encontrou CUDA disponível nesta máquina.",
		WHISPER_CUDA_COMPUTE_UNSUPPORTED: "A GPU foi detectada, mas o runtime Whisper não oferece um modo de cálculo CUDA compatível.",
	};
	return known[code] ?? code.replaceAll("_", " ").toLocaleLowerCase("pt-BR");
}

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
	runtime_validation: "Validando runtime e gate físico",
	runtime_bootstrap: "Inicializando runtime local",
	runtime_fingerprint: "Confirmando identidade do runtime",
	checkpoint_scan: "Verificando checkpoints locais",
	source_validation: "Validando sessão local",
	fixture: "Ensaio sintético",
	checking_model: "Verificando modelo",
	downloading_model: "Baixando modelo",
	model_prepare: "Baixando/verificando modelo local",
	model_load: "Carregando modelo na GPU",
	alignment: "Alinhando palavras e timestamps",
	energy_analysis: "Analisando energia entre faixas",
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
	transcription: "Transcrição",
	consolidating: "Consolidação",
	complete: "Resultado preparado",
	failed: "Falha na execução",
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
		case "QWEN_RUNTIME_FINGERPRINT_READY": {
			const runtimeVersion = textData(event, "runtime_version");
			const workerSha = textData(event, "worker_sha256");
			return {
				title: runtimeVersion
					? `Runtime Qwen ${runtimeVersion} identificado e validado.`
					: "Identidade do runtime Qwen confirmada.",
				detail: workerSha
					? `Worker selado · SHA-256 ${workerSha}`
					: undefined,
			};
		}
		case "QWEN_WINDOW_TRANSCRIBED": {
			const track = numberData(event, "track");
			const window = numberData(event, "window");
			const speaker = textData(event, "speaker");
			const start = numberData(event, "start_seconds");
			const end = numberData(event, "end_seconds");
			const timestamp = (seconds: number) => [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, Math.floor(seconds) % 60].map(value => String(value).padStart(2, "0")).join(":");
			const range = start !== null && end !== null && start >= 0 && end >= start
				? `${timestamp(start)}–${timestamp(end)} na faixa` : null;
			return {
				title: `Qwen concluiu uma janela de áudio${track !== null ? ` da faixa ${track}` : ""}${window !== null ? ` · janela ${window}` : ""}.`,
				detail: [speaker, range].filter(Boolean).join(" · ") || undefined,
			};
		}
		case "QWEN_ALIGNMENT_TRAILING_OVERFLOW_IGNORED": {
			const count = numberData(event, "count");
			return {
				title:
					count === 1
						? "Um timestamp extrapolado no overlap vizinho foi ignorado com segurança."
						: count !== null
							? `${count} timestamps extrapolados no overlap vizinho foram ignorados com segurança.`
							: "Timestamps extrapolados no overlap vizinho foram ignorados com segurança.",
				detail: "Esse trecho pertence à janela vizinha; palavras da janela atual continuam sob validação estrita.",
			};
		}
		case "QWEN_ALIGNMENT_WINDOW_FAILED": {
			const failureClass = textData(event, "failure_class");
			const track = numberData(event, "track");
			const window = numberData(event, "window");
			const runtimeVersion = textData(event, "runtime_version");
			const workerSha = textData(event, "worker_sha256");
			const details: Record<string, string> = {
				QWEN_ALIGNMENT_FAILED: "O Forced Aligner não conseguiu sincronizar esta janela.",
				QWEN_ALIGNMENT_EMPTY: "O Forced Aligner não retornou palavras utilizáveis nesta janela.",
				QWEN_ALIGNMENT_TIMESTAMP_PARSE_INVALID: "O alinhador retornou um timestamp que não pôde ser interpretado.",
				QWEN_ALIGNMENT_TIMESTAMP_NONFINITE: "O alinhador retornou um timestamp não finito.",
				QWEN_ALIGNMENT_TIMESTAMP_NEGATIVE_START: "O alinhador retornou uma palavra antes do início permitido da janela.",
				QWEN_ALIGNMENT_TIMESTAMP_REVERSED: "O alinhador retornou um intervalo de palavra invertido.",
				QWEN_ALIGNMENT_TIMESTAMP_OUTSIDE_WINDOW: "O alinhador posicionou uma palavra completamente fora da janela de áudio.",
				QWEN_ALIGNMENT_TIMESTAMPS_INVALID: "O alinhador retornou timestamps inválidos que não puderam ser classificados com segurança.",
				QWEN_ALIGNMENT_TIMESTAMP_NON_MONOTONIC: "Os timestamps retornados ficaram fora de ordem.",
				QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW: "Uma palavra extrapolou a janela ainda dentro da região que esta janela precisa proteger.",
				QWEN_ALIGNMENT_NO_OWNED_WORDS: "O alinhamento não deixou nenhuma palavra pertencente a esta janela.",
				QWEN_ALIGNMENT_NO_SEGMENTS: "As palavras alinhadas não formaram nenhum segmento válido.",
				QWEN_CUDA_DRIVER_INCOMPATIBLE: "O alinhador encontrou um driver CUDA incompatível nesta janela.",
				QWEN_ASR_GPU_MEMORY_EXHAUSTED: "A GPU ficou sem VRAM enquanto o alinhador processava esta janela.",
				QWEN_ASR_CUDA_FAILED: "O alinhador encontrou uma falha CUDA nesta janela.",
				QWEN_ASR_RUNTIME_API_FAILED: "O runtime Qwen falhou ao executar a API de alinhamento desta janela.",
			};
			const cause =
				(failureClass ? details[failureClass] : undefined) ??
				"O TDA interrompeu esta janela sem publicar resultado parcial. Uma nova tentativa compatível reutilizará o texto pré-alinhamento se o checkpoint estiver disponível.";
			const runtimeIdentity = runtimeVersion
				? ` Identidade da execução: runtime ${runtimeVersion}${workerSha ? ` · worker SHA-256 ${workerSha}` : ""}.`
				: workerSha
					? ` Identidade da execução: worker SHA-256 ${workerSha}.`
					: "";
			return {
				title: `Falha de alinhamento Qwen${track !== null ? ` · faixa ${track}` : ""}${window !== null ? ` · janela ${window}` : ""}.`,
				detail: `${cause}${runtimeIdentity}`,
			};
		}
		case "ASR_CHECKPOINT_FAST_PATH":
			return {
				title: "Todas as faixas foram recuperadas de checkpoints compatíveis.",
				detail: "O modelo não precisou ser carregado novamente.",
			};
		case "ASR_CHECKPOINT_REUSED":
			return { title: "Checkpoint local reutilizado; esta faixa não precisa ser refeita." };
		case "ASR_TEXT_CHECKPOINT_COMPAT_REUSED": {
			const sourceRuntime = textData(event, "source_runtime_version");
			return {
				title: sourceRuntime
					? `Texto Qwen do runtime ${sourceRuntime} reutilizado com validação de integridade.`
					: "Texto Qwen da versão anterior reutilizado com validação de integridade.",
				detail: "A transcrição compatível não rodou de novo; o processamento retomou a partir do alinhamento.",
			};
		}
		case "ASR_TEXT_CHECKPOINT_SAVED":
			return {
				title: "Texto Qwen pré-alinhamento salvo em checkpoint.",
				detail: "Se o alinhamento falhar, uma nova tentativa compatível pode evitar retranscrever esta faixa.",
			};
		case "ASR_TEXT_CHECKPOINT_WRITE_SKIPPED":
			return {
				title: "Não foi possível salvar o checkpoint de texto desta faixa.",
				detail: "A execução atual continua, mas uma nova tentativa pode precisar retranscrever esta faixa.",
			};
		case "ASR_CHECKPOINT_SAVED":
			return { title: "Checkpoint da faixa salvo com sucesso." };
		case "ASR_CHECKPOINT_WRITE_SKIPPED":
			return {
				title: "Não foi possível salvar o checkpoint final desta faixa.",
				detail: "A faixa continua nesta execução, mas uma nova tentativa pode precisar refazer este trabalho.",
			};
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
		case "SOURCE_VALIDATED":
			return {
				title: "Sessão local validada.",
				detail: "Manifesto, faixas e tamanhos conferidos; iniciando o pipeline de ASR.",
			};
		case "WORKER_DISPATCH_PREPARING":
			return {
				title: "Runtime local validado; preparando o worker.",
				detail: "O gate físico selado foi conferido sem reler gigabytes do modelo.",
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
		case "TRACK_ALIGNMENT_STARTED":
			return {
				title:
					track !== null && totalTracks !== null
						? `Alinhando arquivo ${track} de ${totalTracks}${speaker ? ` — ${speaker}` : ""}.`
						: `Alinhando timestamps${speaker ? ` — ${speaker}` : ""}.`,
			};
		case "TRACK_ENERGY_STARTED":
			return {
				title:
					track !== null && totalTracks !== null
						? `Analisando energia do arquivo ${track} de ${totalTracks}${speaker ? ` — ${speaker}` : ""}.`
						: `Analisando energia da faixa${speaker ? ` — ${speaker}` : ""}.`,
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
		case "SUCCEEDED_RECOVERED":
		case "JOB_RECOVERED_FROM_IMMUTABLE_RUN":
			return {
				title: "Resultado completo recuperado após reinício do Agent.",
				detail: "O run imutável já estava íntegro no disco; nenhuma retranscrição foi necessária.",
			};
		case "COMPATIBILITY_MIRROR_WRITE_FAILED":
			return {
				title: "Run concluído; o espelho legado não pôde ser atualizado.",
				detail: "O resultado imutável continua válido e é a fonte de verdade.",
			};
		case "WORKER_RESULT_TEARDOWN_FORCED":
			return {
				title: "O worker terminou o trabalho, mas precisou ser encerrado à força.",
				detail: "O TDA ainda valida o run imutável antes de concluir o job.",
			};
		case "INCOMPLETE_RUNS_CLEANED": {
			const count = numberData(event, "count");
			return {
				title:
					count === 1
						? "Um run incompleto de uma execução interrompida foi limpo."
						: count !== null
							? `${count} runs incompletos de execuções interrompidas foram limpos.`
							: "Runs incompletos de uma execução interrompida foram limpos.",
				detail: "Runs com commit válido nunca são removidos por esta limpeza.",
			};
		}
		case "WORKER_RESULT_RUN_INVALID":
		case "WORKER_RESULT_RUN_MISMATCH":
		case "TRANSCRIPTION_SOURCE_HASH_MISMATCH":
			return { title: presentJobError(event.code) };
		case "CANCELLED":
			return { title: "Processamento cancelado pelo operador." };
		case "INTERRUPTED":
		case "PROCESS_INTERRUPTED":
			return { title: "Execução interrompida; o trabalho pode ser repetido." };
		case "FIXTURE_EXECUTION_FAILED":
			return { title: "O ensaio sintético encontrou uma falha." };
		default:
			return { title: presentJobError(event.code) };
	}
}
