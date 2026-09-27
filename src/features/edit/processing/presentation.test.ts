import { describe, expect, it } from "vitest";
import {
	presentConnectionError,
	presentJobError,
	presentJobEvent,
	presentJobTitle,
	stageLabels,
} from "./presentation";

describe("processing presentation", () => {
	it("uses factual track-local window time and preserves legacy events", () => {
		const event = { seq: 1, attempt: null, code: "QWEN_WINDOW_TRANSCRIBED", at: "2026-09-27T00:00:00Z", level: "info", data: { track: 3, window: 205 } } as const;
		expect(presentJobEvent(event).detail).toBeUndefined();
		expect(presentJobEvent({ ...event, data: { ...event.data, speaker: "Alice", total_tracks: 4, start_seconds: 7860.125, end_seconds: 7890.75 } }).detail).toBe("Alice · 02:11:00–02:11:30 na faixa");
		expect(presentJobEvent({ ...event, data: { ...event.data, start_seconds: 20, end_seconds: 10 } }).detail).toBeUndefined();
	});
	it("separates version, API and browser-session compatibility diagnostics", () => {
		expect(
			presentConnectionError("version_incompatible", {
				detectedServiceVersion: "0.3.13",
				minimumServiceVersion: "0.3.14",
			}),
		).toContain("v0.3.13");
		expect(
			presentConnectionError("version_incompatible", {
				detectedServiceVersion: "0.3.13",
				minimumServiceVersion: "0.3.14",
			}),
		).toContain("v0.3.14");
		expect(
			presentConnectionError("api_incompatible", {
				detectedApiVersion: "2",
				requiredApiVersion: "1",
			}),
		).toContain("API v2");
		expect(presentConnectionError("session_incompatible")).toContain(
			"sessão automática",
		);
	});

	it("presents Craig transcription jobs as a session transcription", () => {
		expect(presentJobTitle({ kind: "transcription.craig" })).toBe(
			"Transcrição de sessão",
		);
	});

	it("keeps synthetic jobs friendly and unknown kinds explicit", () => {
		expect(presentJobTitle({ kind: "synthetic.fixture" })).toBe("Ensaio sintético");
		expect(presentJobTitle({ kind: "custom.kind" })).toBe("custom.kind");
	});

	it("explains non-retryable run failures without exposing raw codes", () => {
		expect(presentJobError("WORKER_RESULT_RUN_MISMATCH")).toContain(
			"não corresponde",
		);
		expect(presentJobError("TRANSCRIPTION_SOURCE_HASH_MISMATCH")).toContain(
			"fonte Craig",
		);
	});

	it("explains worker handshake, encoding and runtime failures", () => {
		expect(presentJobError("WORKER_STDOUT_ENCODING_INVALID")).toContain("codificação");
		expect(presentJobError("WORKER_READY_REQUIRED")).toContain("handshake");
		expect(presentJobError("WORKER_SEQUENCE_GAP")).toContain("sequência");
		expect(presentJobError("WORKER_RUNTIME_BOOTSTRAP_TIMEOUT")).toContain("inicialização");
		expect(presentJobError("QWEN_PHYSICAL_ACCEPTANCE_REQUIRED")).toContain(
			"validação física",
		);
		expect(presentJobError("WHISPER_RUNTIME_UNAVAILABLE")).toContain(
			"Whisper",
		);
	});

	it("explains physical ASR execution failures", () => {
		expect(presentJobError("QWEN_ALIGNMENT_REQUIRED")).toBe(
			"O alinhamento obrigatório falhou. Abra Diagnóstico para ver a faixa, a janela e a causa específica. Nenhum resultado parcial foi publicado.",
		);
		expect(presentJobError("QWEN_MODEL_NOT_GPU_RESIDENT")).toContain("GPU");
		expect(presentJobError("WHISPER_CUDA_UNAVAILABLE")).toContain("CUDA");
		expect(presentJobError("WHISPER_RUNTIME_NOT_INSTALLED")).toContain(
			"runtime Whisper",
		);
	});

	it("explains new integrity and worker-contract failures", () => {
		expect(presentJobError("AGENT_BUSY")).toContain("ocupado");
		expect(presentJobError("RESULT_ARTIFACT_UNAVAILABLE")).toContain(
			"não está mais disponível",
		);
		expect(presentJobError("WORKER_PROGRESS_GAP")).toContain("fora de ordem");
		expect(presentJobError("TRANSCRIPT_VALIDATION_FAILED")).toContain(
			"validação estrutural",
		);
		expect(presentJobError("CRAIG_MANIFEST_TRACK_METADATA_MISMATCH")).toContain(
			"reimporte",
		);
	});

	it("uses friendly worker diagnostics in the event history", () => {
		expect(
			presentJobEvent({
				seq: 20,
			attempt: null,
				code: "WORKER_READY_REQUIRED",
				at: "2026-09-19T12:00:00Z",
				level: "error",
				data: {},
			}).title,
		).toContain("handshake");
		expect(
			presentJobEvent({
				seq: 21,
			attempt: null,
				code: "WORKER_RESULT_TEARDOWN_FORCED",
				at: "2026-09-19T12:00:01Z",
				level: "warning",
				data: {},
			}).detail,
		).toContain("run imutável");
	});

	it("explains recovery and legacy mirror degradation", () => {
		expect(
			presentJobEvent({
				seq: 1,
			attempt: null,
				code: "SUCCEEDED_RECOVERED",
				at: "2026-09-19T12:00:00Z",
				level: "warning",
				data: {},
			}).title,
		).toContain("recuperado");
		expect(
			presentJobEvent({
				seq: 2,
			attempt: null,
				code: "COMPATIBILITY_MIRROR_WRITE_FAILED",
				at: "2026-09-19T12:00:01Z",
				level: "warning",
				data: {},
			}).detail,
		).toContain("fonte de verdade");
		expect(
			presentJobEvent({
				seq: 3,
			attempt: null,
				code: "INCOMPLETE_RUNS_CLEANED",
				at: "2026-09-19T12:00:02Z",
				level: "info",
				data: { count: 2 },
			}).title,
		).toContain("2 runs incompletos");
	});

	it("labels canonical processing stages", () => {
		expect(stageLabels.transcription).toBe("Transcrição");
		expect(stageLabels.runtime_bootstrap).toBe("Inicializando runtime local");
		expect(stageLabels.runtime_fingerprint).toBe("Confirmando identidade do runtime");
		expect(stageLabels.checkpoint_scan).toBe("Verificando checkpoints locais");
		expect(stageLabels.energy_analysis).toBe("Analisando energia entre faixas");
	});
});



it("presents ownership-safe Qwen alignment overflow without hiding fail-closed semantics", () => {
	expect(
		presentJobEvent({
			seq: 40,
			attempt: null,
			code: "QWEN_ALIGNMENT_TRAILING_OVERFLOW_IGNORED",
			at: "2026-09-23T00:00:00.000Z",
			level: "info",
			data: { track: 2, window: 88, count: 1, stage: "alignment" },
		}),
	).toEqual({
		title: "Um timestamp extrapolado no overlap vizinho foi ignorado com segurança.",
		detail: "Esse trecho pertence à janela vizinha; palavras da janela atual continuam sob validação estrita.",
	});
});


it("presents actionable terminal copy for Qwen runtime failures", () => {
	expect(presentJobError("QWEN_CUDA_DRIVER_INCOMPATIBLE")).toBe(
		"O driver NVIDIA/CUDA não é compatível com este runtime Qwen.",
	);
	expect(presentJobError("QWEN_ASR_RUNTIME_API_FAILED")).toBe(
		"O runtime Qwen encontrou uma falha interna ao executar a API de inferência/alinhamento.",
	);
});


it("explains checkpoint durability and retry cost honestly", () => {
	expect(
		presentJobEvent({
			seq: 44,
			attempt: null,
			code: "ASR_TEXT_CHECKPOINT_SAVED",
			at: "2026-09-25T00:00:03.000Z",
			level: "info",
			data: { track: 1, stage: "transcription" },
		}),
	).toEqual({
		title: "Texto Qwen pré-alinhamento salvo em checkpoint.",
		detail:
			"Se o alinhamento falhar, uma nova tentativa compatível pode evitar retranscrever esta faixa.",
	});
	expect(
		presentJobEvent({
			seq: 45,
			attempt: null,
			code: "ASR_TEXT_CHECKPOINT_WRITE_SKIPPED",
			at: "2026-09-25T00:00:04.000Z",
			level: "warning",
			data: { track: 1, stage: "transcription" },
		}),
	).toEqual({
		title: "Não foi possível salvar o checkpoint de texto desta faixa.",
		detail:
			"A execução atual continua, mas uma nova tentativa pode precisar retranscrever esta faixa.",
	});
	expect(
		presentJobEvent({
			seq: 46,
			attempt: null,
			code: "ASR_CHECKPOINT_WRITE_SKIPPED",
			at: "2026-09-25T00:00:05.000Z",
			level: "warning",
			data: { track: 1, stage: "alignment" },
		}),
	).toEqual({
		title: "Não foi possível salvar o checkpoint final desta faixa.",
		detail:
			"A faixa continua nesta execução, mas uma nova tentativa pode precisar refazer este trabalho.",
	});
});

it("presents sealed Qwen runtime identity without local paths", () => {
	expect(
		presentJobEvent({
			seq: 40,
			attempt: null,
			code: "QWEN_RUNTIME_FINGERPRINT_READY",
			at: "2026-09-25T00:00:00.000Z",
			level: "info",
			data: {
				runtime_version: "1.0.11",
				worker_sha256: "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
			},
		}),
	).toEqual({
		title: "Runtime Qwen 1.0.11 identificado e validado.",
		detail:
			"Worker selado · SHA-256 abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
	});
});


it("presents sanitized Qwen alignment failure context", () => {
	expect(
		presentJobEvent({
			seq: 41,
			attempt: null,
			code: "QWEN_ALIGNMENT_WINDOW_FAILED",
			at: "2026-09-25T00:00:00.000Z",
			level: "error",
			data: {
				track: 1,
				window: 89,
				failure_class: "QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW",
				runtime_version: "1.0.11",
				worker_sha256: "a".repeat(64),
			},
		}),
	).toEqual({
		title: "Falha de alinhamento Qwen · faixa 1 · janela 89.",
		detail:
			"Uma palavra extrapolou a janela ainda dentro da região que esta janela precisa proteger. Identidade da execução: runtime 1.0.11 · worker SHA-256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.",
	});
});

it("presents an alignment VRAM failure as a runtime problem, not transcript corruption", () => {
	expect(
		presentJobEvent({
			seq: 43,
			attempt: null,
			code: "QWEN_ALIGNMENT_WINDOW_FAILED",
			at: "2026-09-25T00:00:02.000Z",
			level: "error",
			data: {
				track: 2,
				window: 17,
				failure_class: "QWEN_ASR_GPU_MEMORY_EXHAUSTED",
			},
		}),
	).toEqual({
		title: "Falha de alinhamento Qwen · faixa 2 · janela 17.",
		detail: "A GPU ficou sem VRAM enquanto o alinhador processava esta janela.",
	});
});


it("explains compatibility reuse without implying a completed run", () => {
	expect(
		presentJobEvent({
			seq: 42,
			attempt: null,
			code: "ASR_TEXT_CHECKPOINT_COMPAT_REUSED",
			at: "2026-09-25T00:00:01.000Z",
			level: "info",
			data: { track: 1, total_tracks: 4, source_runtime_version: "1.0.10" },
		}),
	).toEqual({
		title: "Texto Qwen do runtime 1.0.10 reutilizado com validação de integridade.",
		detail:
			"A transcrição compatível não rodou de novo; o processamento retomou a partir do alinhamento.",
	});
});


it("presents Qwen post-ASR track context truthfully", () => {
	expect(
		presentJobEvent({
			seq: 41,
			attempt: null,
			code: "TRACK_ALIGNMENT_STARTED",
			at: "2026-09-19T00:00:00.000Z",
			level: "info",
			data: { track: 1, total_tracks: 4, speaker: "Alice", stage: "alignment" },
		}),
	).toEqual({ title: "Alinhando arquivo 1 de 4 — Alice." });

	expect(
		presentJobEvent({
			seq: 42,
			attempt: null,
			code: "TRACK_ENERGY_STARTED",
			at: "2026-09-19T00:00:01.000Z",
			level: "info",
			data: { track: 2, total_tracks: 4, speaker: "Bob", stage: "energy_analysis" },
		}),
	).toEqual({ title: "Analisando energia do arquivo 2 de 4 — Bob." });
});
