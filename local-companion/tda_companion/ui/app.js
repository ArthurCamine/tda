(() => {
  const $ = (id) => document.getElementById(id);
  let api = null;
  let lastSnapshot = null;
  let allLogs = [];
  let refreshTimer = null;
  let selectedSession = null;
  let profileState = [];
  let selectedProfileId = null;
  let processBusy = false;
  let submittedJobId = null;
  let lastConnectionState = null;

  const FRIENDLY_ERRORS = {
    CRAIG_FILE_PICKER_UNAVAILABLE: "O seletor de arquivos do Windows não está disponível.",
    CRAIG_ZIP_REQUIRED: "Selecione o ZIP original do Craig.",
    CRAIG_ARCHIVE_INVALID: "O arquivo selecionado não é um ZIP Craig válido.",
    CRAIG_ARCHIVE_NO_TRACKS: "O ZIP não contém faixas FLAC do Craig.",
    CRAIG_SOURCE_CHANGED: "O arquivo mudou enquanto era lido. Selecione-o novamente.",
    CRAIG_UPLOAD_SIZE_LIMIT: "A sessão excede o limite local de tamanho.",
    TRANSCRIPTION_PREPARATION_BLOCKED_BY_RUNNING_JOB: "Espere o trabalho atual terminar antes de preparar outro perfil.",
    RUNTIME_UPDATE_BLOCKED_BY_RUNNING_JOB: "O runtime não pode ser alterado enquanto há um trabalho em execução.",
    QWEN_RUNTIME_UNAVAILABLE: "O runtime Qwen ainda não está disponível.",
    QWEN_RUNTIME_LONG_GATE_REQUIRED: "O runtime Qwen instalado é antigo e precisa ser atualizado.",
    QWEN_CUDA_UNAVAILABLE: "O Qwen não encontrou CUDA disponível nesta máquina.",
    QWEN_ACCEPTANCE_AUDIO_TOO_SHORT: "Nenhuma faixa possui 180 segundos úteis para validar o Qwen.",
    QWEN_ACCEPTANCE_NO_SPEECH_RECOGNIZED: "A amostra escolhida não teve fala suficiente. Tente outra sessão.",
    QWEN_MODEL_DOWNLOAD_FAILED: "Não foi possível baixar o modelo Qwen.",
    QWEN_MODEL_REPAIR_REQUIRED: "O modelo Qwen local precisa de reparo.",
    QWEN_ALIGNER_REPAIR_REQUIRED: "O alinhador Qwen local precisa de reparo.",
    QWEN_MODEL_NOT_GPU_RESIDENT: "O modelo Qwen não coube integralmente na GPU.",
    QWEN_ALIGNER_NOT_GPU_RESIDENT: "O alinhador Qwen não coube integralmente na GPU.",
    QWEN_ACCEPTANCE_GPU_NAME_MISMATCH: "O gate físico não foi executado na RTX 4070 esperada.",
    AGENT_CONNECTION_REFUSED: "O Agent local não está respondendo.",
    AGENT_CONNECTION_TIMEOUT: "O Agent local demorou demais para responder.",
    AGENT_CONNECTION_FAILED: "Não foi possível conectar ao Agent local.",
    AGENT_RECONNECT_BACKOFF: "O Agent continua indisponível. Uma nova tentativa será feita automaticamente.",
    AGENT_RECOVERY_FAILED: "O Agent não voltou após a tentativa de recuperação.",
    AGENT_START_FAILED: "O Agent local não pôde ser iniciado.",
    AGENT_STOPPED_BY_USER: "O Agent foi parado deliberadamente neste computador.",
    AGENT_PORT_CONFLICT: "A porta local 8765 está sendo usada por outro processo. O Companion não enviou seu token para ele.",
    AGENT_API_INCOMPATIBLE: "O Agent em execução usa uma API incompatível com esta interface.",
    AGENT_VERSION_MISMATCH: "A interface e o Agent são de versões diferentes. Reinicie o Agent antes de alterar o estado local.",
    AGENT_RESTART_VERSION_MISMATCH: "O Agent reiniciado ainda não corresponde à versão desta interface.",
    AGENT_RESTART_FAILED: "O Agent não voltou corretamente após o reinício.",
    AGENT_SHUTDOWN_TIMEOUT: "O Agent não encerrou dentro do tempo esperado.",
  };

  function errorText(error) {
    const raw = String(error || "Erro desconhecido");
    const code = raw.replace(/^Error:\s*/, "").trim();
    return FRIENDLY_ERRORS[code] || code;
  }

  function toast(message, error = false) {
    const node = $("toast");
    node.textContent = String(message || "Concluído");
    node.classList.toggle("error", error);
    node.classList.add("show");
    window.clearTimeout(node._timer);
    node._timer = window.setTimeout(() => node.classList.remove("show"), 3600);
  }

  function formatBytes(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let amount = value;
    let unit = 0;
    while (amount >= 1024 && unit < units.length - 1) {
      amount /= 1024;
      unit += 1;
    }
    const digits = unit >= 3 ? 1 : 0;
    return `${amount.toFixed(digits)} ${units[unit]}`;
  }

  function timeOnly(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function duration(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds)) return "—";
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (hours) return `${hours}h ${minutes}min`;
    return `${minutes}min`;
  }

  function showView(name) {
    document.querySelectorAll(".view").forEach((node) => {
      node.classList.toggle("active", node.id === `view-${name}`);
    });
    document.querySelectorAll(".nav-item").forEach((node) => {
      node.classList.toggle("active", node.dataset.view === name);
    });
    if (name === "logs") refreshLogs(false);
  }

  function setProcessStatus(title, detail, state = "waiting") {
    $("process-status-title").textContent = title;
    $("process-status-detail").textContent = detail;
    const pill = $("process-state-pill");
    pill.classList.remove("success", "warning");
    if (state === "success") pill.classList.add("success");
    if (state === "warning" || state === "busy") pill.classList.add("warning");
    pill.textContent = state === "success" ? "Pronto" : state === "busy" ? "Processando" : state === "warning" ? "Atenção" : "Aguardando sessão";
  }

  function renderLogRows(target, rows, compact = false) {
    target.replaceChildren();
    const query = ($("log-search")?.value || "").trim().toLocaleLowerCase("pt-BR");
    const visible = compact
      ? rows.slice(-8)
      : rows.filter((row) => {
          if (!query) return true;
          return `${row.code || ""} ${row.component || ""} ${row.message || ""}`
            .toLocaleLowerCase("pt-BR")
            .includes(query);
        });
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "log-row";
      const text = document.createElement("span");
      text.className = "log-message";
      text.textContent = "Nenhum log para mostrar.";
      empty.append(text);
      target.append(empty);
      return;
    }
    visible.forEach((row) => {
      const line = document.createElement("div");
      line.className = "log-row";
      const stamp = document.createElement("span");
      stamp.className = "log-time";
      stamp.textContent = timeOnly(row.at);
      const level = document.createElement("span");
      level.className = `log-level ${row.level || "info"}`;
      level.textContent = row.level || "info";
      const component = document.createElement("span");
      component.className = "log-component";
      component.textContent = row.component || "agent";
      const message = document.createElement("span");
      message.className = "log-message";
      message.textContent = row.message || row.code || "Evento";
      line.append(stamp, level, component, message);
      target.append(line);
    });
    if (!compact) target.scrollTop = target.scrollHeight;
  }

  function renderLogsUnavailable(result) {
    allLogs = [];
    const message = `Logs indisponíveis enquanto o Agent não responde. ${errorText(result?.error || "AGENT_CONNECTION_FAILED")}`;
    [$("full-logs"), $("overview-logs")].forEach((target) => {
      target.replaceChildren();
      const row = document.createElement("div");
      row.className = "log-row";
      const level = document.createElement("span");
      level.className = "log-level warning";
      level.textContent = "warning";
      const component = document.createElement("span");
      component.className = "log-component";
      component.textContent = "agent";
      const text = document.createElement("span");
      text.className = "log-message";
      text.textContent = message;
      row.append(level, component, text);
      target.append(row);
    });
  }

  function renderWhisperRuntime(result, checkedRemote = false) {
    const status = result?.status || "missing";
    const current = result?.current_version || result?.version || null;
    const detail = $("whisper-runtime-detail");
    const feedback = $("whisper-runtime-feedback");
    const install = $("install-whisper-runtime");

    if (status === "ready") detail.textContent = `Whisper runtime${current ? ` v${current}` : ""} instalado e íntegro.`;
    else if (status === "corrupt") detail.textContent = `Runtime Whisper${current ? ` v${current}` : ""} precisa de reparo.`;
    else detail.textContent = "Runtime Whisper ainda não instalado.";

    if (!checkedRemote) {
      install.classList.add("hidden");
      feedback.textContent = "Runtime isolado; não altera o PATH global.";
      return;
    }

    const available = Boolean(result?.available);
    install.classList.toggle("hidden", !available);
    if (available) {
      install.textContent = status === "ready" ? `Atualizar para ${result.version}` : `Instalar ${result.version}`;
      feedback.textContent = `Pacote verificado · ${formatBytes(result.size)} · v${result.version}`;
    } else {
      feedback.textContent = status === "ready" ? "Whisper já está na versão estável mais recente." : "Nenhum runtime Whisper estável disponível.";
    }
  }

  function renderQwenRuntime(result, checkedRemote = false) {
    const status = result?.status || "missing";
    const current = result?.current_version || result?.installed_version || result?.version || null;
    const detail = $("qwen-runtime-detail");
    const feedback = $("qwen-runtime-feedback");
    const install = $("install-qwen-runtime");

    if (status === "ready") detail.textContent = `Qwen runtime${current ? ` v${current}` : ""} instalado e íntegro.`;
    else if (status === "corrupt") detail.textContent = `Runtime Qwen${current ? ` v${current}` : ""} precisa de reparo.`;
    else detail.textContent = "Runtime Qwen ainda não instalado.";

    if (!checkedRemote) {
      install.classList.add("hidden");
      feedback.textContent = "O gate físico e os modelos são preparados quando você escolher um perfil Qwen.";
      return;
    }

    const available = Boolean(result?.available);
    install.classList.toggle("hidden", !available);
    if (available) {
      install.textContent = status === "ready" ? `Atualizar para ${result.version}` : `Instalar ${result.version}`;
      const parts = typeof result.part_count === "number" ? ` · ${result.part_count} parte(s)` : "";
      feedback.textContent = `Pacote verificado · ${formatBytes(result.size)}${parts} · v${result.version}`;
    } else {
      feedback.textContent = status === "ready" ? "Qwen já está na versão estável mais recente." : "Nenhum runtime Qwen estável disponível.";
    }
  }

  function profileById(profileId) {
    return profileState.find((profile) => profile.id === profileId) || null;
  }

  function updateProcessControls() {
    const button = $("start-processing");
    if (!selectedSession) {
      button.disabled = true;
      button.textContent = "Preparar e processar";
      if (!processBusy) setProcessStatus("Selecione uma sessão para começar.", "O arquivo é processado localmente neste computador.");
      return;
    }
    const profile = profileById(selectedProfileId);
    if (!profile) {
      button.disabled = true;
      button.textContent = "Escolha a qualidade";
      if (!processBusy) setProcessStatus("Escolha a qualidade da transcrição.", "O perfil recomendado prioriza precisão para sessões importantes.");
      return;
    }
    button.disabled = processBusy;
    button.textContent = profile.ready ? "Processar sessão" : "Preparar e processar";
    if (!processBusy && !submittedJobId) {
      if (profile.ready) setProcessStatus("Tudo pronto para processar.", `${profile.label} está disponível nesta máquina.`, "success");
      else setProcessStatus("O perfil será preparado no primeiro uso.", "Runtime, modelo e validações necessárias serão executados antes do job.", "warning");
    }
  }

  function renderSession(session) {
    selectedSession = session;
    submittedJobId = null;
    const empty = $("source-empty");
    const summary = $("session-summary");
    const tracks = $("track-list");
    tracks.replaceChildren();

    if (!session) {
      empty.classList.remove("hidden");
      summary.classList.add("hidden");
      profileState = [];
      selectedProfileId = null;
      $("profile-list").innerHTML = '<div class="profile-loading">Selecione uma sessão para verificar os perfis disponíveis.</div>';
      updateProcessControls();
      return;
    }

    empty.classList.add("hidden");
    summary.classList.remove("hidden");
    $("session-name").textContent = session.source_name || "Sessão Craig";
    const metadata = [formatBytes(session.size_bytes), session.guild, session.channel, session.recording_id ? `gravação ${session.recording_id}` : null].filter(Boolean);
    $("session-meta").textContent = metadata.join(" · ") || "ZIP Craig validado";
    $("session-track-count").textContent = `${session.track_count || 0} faixa(s)`;

    (Array.isArray(session.tracks) ? session.tracks : []).forEach((track) => {
      const row = document.createElement("li");
      row.className = "track-row";
      const number = document.createElement("span");
      number.className = "track-number";
      number.textContent = `#${track.number ?? "—"}`;
      const speaker = document.createElement("span");
      speaker.className = "track-speaker";
      speaker.textContent = track.speaker || "Participante";
      const size = document.createElement("span");
      size.className = "track-size";
      size.textContent = formatBytes(track.size_bytes);
      row.append(number, speaker, size);
      tracks.append(row);
    });
    setProcessStatus("Sessão validada.", `${session.track_count || 0} faixa(s) encontradas. Verificando perfis disponíveis…`, "busy");
  }

  function renderProfiles(result) {
    profileState = Array.isArray(result?.profiles) ? result.profiles : [];
    const target = $("profile-list");
    target.replaceChildren();
    if (result?.unavailable) {
      const unavailable = document.createElement("div");
      unavailable.className = "profile-loading";
      unavailable.textContent = `Sessão validada. ${errorText(result.error || "AGENT_CONNECTION_FAILED")} Os perfis serão verificados após a reconexão.`;
      target.append(unavailable);
      selectedProfileId = null;
      updateProcessControls();
      setProcessStatus(
        "Sessão validada.",
        `O ZIP continua pronto. ${errorText(result.error || "AGENT_CONNECTION_FAILED")}`,
        "warning",
      );
      return;
    }
    if (!profileState.length) {
      const empty = document.createElement("div");
      empty.className = "profile-loading";
      empty.textContent = "Nenhum perfil de transcrição disponível.";
      target.append(empty);
      selectedProfileId = null;
      updateProcessControls();
      return;
    }

    const preferred = profileState.some((profile) => profile.id === selectedProfileId)
      ? selectedProfileId
      : result?.recommended || profileState[0].id;
    selectedProfileId = preferred;

    profileState.forEach((profile) => {
      const label = document.createElement("label");
      label.className = "profile-option";
      label.classList.toggle("selected", profile.id === selectedProfileId);

      const input = document.createElement("input");
      input.type = "radio";
      input.name = "transcription-profile";
      input.value = profile.id;
      input.checked = profile.id === selectedProfileId;
      input.addEventListener("change", () => {
        selectedProfileId = profile.id;
        document.querySelectorAll(".profile-option").forEach((node) => {
          node.classList.remove("selected");
        });
        label.classList.add("selected");
        submittedJobId = null;
        updateProcessControls();
      });

      const copy = document.createElement("div");
      copy.className = "profile-copy";
      const title = document.createElement("strong");
      title.textContent = profile.label || profile.id;
      if (profile.recommended) {
        const tag = document.createElement("em");
        tag.className = "recommended-tag";
        tag.textContent = "Recomendado";
        title.append(tag);
      }
      const description = document.createElement("span");
      description.textContent = profile.description || "Perfil local de transcrição.";
      copy.append(title, description);

      const readiness = document.createElement("span");
      readiness.className = `profile-readiness${profile.ready ? "" : " prepare"}`;
      readiness.textContent = profile.ready ? "Pronto" : "Preparar no primeiro uso";
      label.append(input, copy, readiness);
      target.append(label);
    });
    updateProcessControls();
  }

  async function refreshProfiles() {
    if (!api || !selectedSession) return null;
    const result = await api.transcription_profiles();
    renderProfiles(result);
    return result;
  }

  async function selectCraigSession() {
    if (!api || processBusy) return;
    const button = $("select-craig");
    button.disabled = true;
    button.textContent = "Validando…";
    setProcessStatus("Validando sessão…", "O Companion está conferindo o ZIP e as faixas localmente.", "busy");
    let result = null;
    try {
      result = await api.select_craig_session();
    } catch (error) {
      setProcessStatus("Não foi possível validar esse ZIP.", errorText(error), "warning");
      toast(`Sessão rejeitada: ${errorText(error)}`, true);
      button.disabled = false;
      button.textContent = selectedSession ? "Trocar ZIP" : "Selecionar ZIP";
      return;
    }

    try {
      if (!result?.selected) {
        if (!selectedSession) setProcessStatus("Nenhuma sessão selecionada.", "Escolha o ZIP multitrack original do Craig.");
        return;
      }
      renderSession(result);
      try {
        const profiles = await refreshProfiles();
        if (profiles?.unavailable) {
          toast(`${result.source_name || "Sessão"} validada; aguardando o Agent para verificar os perfis.`);
        } else {
          toast(`${result.source_name || "Sessão"} pronta para configurar.`);
        }
      } catch (error) {
        renderProfiles({ profiles: [], unavailable: true, error: String(error || "AGENT_CONNECTION_FAILED").replace(/^Error:\s*/, "") });
        toast(`${result.source_name || "Sessão"} foi validada, mas o Agent ainda não respondeu.`, true);
      }
    } finally {
      button.disabled = false;
      button.textContent = selectedSession ? "Trocar ZIP" : "Selecionar ZIP";
    }
  }

  async function startProcessing() {
    if (!api || processBusy || !selectedSession || !selectedProfileId) return;
    processBusy = true;
    submittedJobId = null;
    updateProcessControls();
    const profileId = selectedProfileId;
    let profile = profileById(profileId);
    try {
      if (!profile?.ready) {
        setProcessStatus(`Preparando ${profile?.label || profileId}…`, profile?.engine === "qwen3" ? "O primeiro uso pode baixar vários GB e executará um gate real de 180 s na GPU." : "O runtime será baixado e verificado antes de criar o job.", "busy");
        const prepared = await api.prepare_transcription_profile(selectedSession.source_id, profileId);
        const gpuDetail = prepared?.gpu_name ? ` Gate aprovado em ${prepared.gpu_name}.` : "";
        setProcessStatus("Preparação concluída.", `Perfil validado.${gpuDetail}`, "success");
        await refreshProfiles();
        profile = profileById(profileId);
        if (!profile?.ready) throw new Error("TRANSCRIPTION_PROFILE_NOT_READY");
      }

      setProcessStatus("Enviando para a fila local…", "Criando o job canônico do Agent.", "busy");
      const result = await api.start_craig_transcription(
        selectedSession.source_id,
        profileId,
        $("session-glossary").value || "",
        $("session-context").value || "",
      );
      submittedJobId = result?.id || null;
      const status = result?.status || "queued";
      setProcessStatus(
        status === "running" ? "Transcrição iniciada." : "Sessão adicionada à fila.",
        submittedJobId ? `Job ${submittedJobId} · ${profile?.label || profileId}` : `${profile?.label || profileId} · aguardando o Agent`,
        "busy",
      );
      toast("Sessão entregue ao processamento local.");
      await refreshSnapshot();
    } catch (error) {
      submittedJobId = null;
      setProcessStatus("Não foi possível iniciar o processamento.", errorText(error), "warning");
      toast(`Processamento não iniciado: ${errorText(error)}`, true);
    } finally {
      processBusy = false;
      updateProcessControls();
    }
  }

  function renderSubmittedJob(snapshot) {
    if (!submittedJobId || processBusy) return;
    const job = (snapshot.jobs || []).find((item) => item.id === submittedJobId);
    if (!job) return;
    const progress = job.progress || {};
    if (job.status === "queued") {
      setProcessStatus("Sessão na fila local.", "O Agent iniciará assim que o slot de processamento estiver livre.", "busy");
      return;
    }
    if (job.status === "running") {
      const detail = typeof progress.completed === "number"
        ? `${progress.completed} de ${progress.total ?? "—"} ${progress.unit || "itens"}`
        : "O worker está processando as faixas da sessão.";
      setProcessStatus("Transcrição em andamento.", detail, "busy");
      return;
    }
    if (job.status === "succeeded") {
      setProcessStatus("Transcrição concluída.", "O resultado local está pronto para o fluxo seguinte do TDA.", "success");
      return;
    }
    if (job.status === "failed" || job.status === "interrupted") {
      setProcessStatus("O processamento precisa de atenção.", job.error?.code || "Consulte os logs técnicos para detalhes.", "warning");
    }
  }

  function connectionFamily(state) {
    if (state === "ready") return "ready";
    if (state === "reconnecting" || state === "unavailable" || state === "starting") return "recovering";
    if (state === "stopped_by_user") return "stopped";
    if (state === "port_conflict" || state === "incompatible") return "blocked";
    return "unknown";
  }

  function announceConnectionTransition(connection) {
    const state = connection?.state || "ready";
    if (lastConnectionState === null) {
      lastConnectionState = state;
      return;
    }
    const previousFamily = connectionFamily(lastConnectionState);
    const nextFamily = connectionFamily(state);
    lastConnectionState = state;
    if (previousFamily === nextFamily) return;
    if (nextFamily === "ready") {
      toast("Agent local recuperado.");
      return;
    }
    if (nextFamily === "recovering") {
      toast("Agent local indisponível. O Companion está tentando recuperar a conexão.", true);
      return;
    }
    if (nextFamily === "stopped") {
      toast("Agent local está parado e não será reiniciado automaticamente.", true);
      return;
    }
    if (nextFamily === "blocked") {
      toast(errorText(connection?.error || "AGENT_PORT_CONFLICT"), true);
    }
  }

  function renderSnapshot(value) {
    lastSnapshot = value;
    const version = value.version || "—";
    $("rail-version").textContent = `v${version}`;
    $("head-version").textContent = `v${version}`;
    $("settings-version").textContent = `TDA Companion ${version}`;

    const agent = value.agent || {};
    const connection = value.connection || { state: agent.lifecycle || "ready" };
    const connectionState = connection.state || "ready";
    const lifecycle = agent.lifecycle || connectionState || "starting";
    const queuePaused = connectionState === "ready" && lifecycle === "paused";
    const labels = {
      ready: ["● Agente local ativo", "Online"],
      starting: ["● Iniciando Agent", "Iniciando"],
      reconnecting: ["● Reconectando Agent", "Reconectando"],
      unavailable: ["● Agent indisponível", "Indisponível"],
      stopped_by_user: ["● Agent parado", "Parado"],
      port_conflict: ["● Conflito na porta local", "Conflito"],
      incompatible: ["● Agent incompatível", "Incompatível"],
    };
    const [pillText, machineText] = queuePaused
      ? ["● Fila pausada", "Pausado"]
      : labels[connectionState] || labels.starting;
    $("agent-pill").textContent = pillText;
    $("agent-pill").classList.toggle("warning", connectionState !== "ready" || queuePaused);
    $("machine-state").textContent = machineText;
    $("machine-state").classList.toggle("warning", connectionState !== "ready" || queuePaused);

    if (connectionState === "ready") {
      const mismatch = connection.compatibility === "compatible" ? ` · Agent v${connection.service_version || "?"} precisa ser reiniciado` : "";
      $("agent-detail").textContent = `TDA local · API v${agent.api_version || "1"} · 127.0.0.1:${agent.port || 8765} · ativo há ${duration(agent.uptime_seconds)}${mismatch}`;
    } else {
      const retry = Number(connection.retry_after_seconds || 0);
      const retryText = retry > 0 ? ` · nova tentativa em ${retry.toFixed(0)} s` : "";
      $("agent-detail").textContent = `${errorText(connection.error || agent.error || "AGENT_CONNECTION_FAILED")}${retryText}`;
    }
    announceConnectionTransition(connection);

    const system = value.system || {};
    const host = system.host || {};
    const gpu = Array.isArray(system.gpus) && system.gpus.length ? system.gpus[0] : null;
    const cpu = system.cpu || {};
    const memory = system.memory || {};
    $("machine-description").textContent = [host.os, host.cpu, gpu?.name].filter(Boolean).join(" · ") || "Sistema local";
    $("gpu-value").textContent = gpu && typeof gpu.utilization_percent === "number" ? `${gpu.utilization_percent}%` : "—";
    $("vram-value").textContent = gpu ? `VRAM ${formatBytes(gpu.memory_used_bytes)} / ${formatBytes(gpu.memory_total_bytes)}` : "GPU NVIDIA indisponível";
    $("cpu-value").textContent = typeof cpu.utilization_percent === "number" ? `${cpu.utilization_percent}%` : "—";
    $("cpu-name").textContent = host.cpu || "CPU local";
    $("ram-value").textContent = typeof memory.percent === "number" ? `${memory.percent}%` : "—";
    $("ram-detail").textContent = `${formatBytes(memory.used_bytes)} / ${formatBytes(memory.total_bytes)}`;

    const storage = value.storage || {};
    $("storage-value").textContent = storage.free_bytes == null ? "—" : `${formatBytes(storage.free_bytes)} livres`;
    $("storage-detail").textContent = storage.total_bytes == null ? "Volume local" : `de ${formatBytes(storage.total_bytes)}`;

    const counts = value.counts || {};
    $("count-processing").textContent = counts.processing ?? 0;
    $("count-queued").textContent = counts.queued ?? 0;
    $("count-completed").textContent = counts.completed ?? 0;
    $("count-attention").textContent = counts.attention ?? 0;
    $("last-update").textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    $("toggle-queue").textContent = queuePaused ? "Retomar fila" : "Pausar fila";
    $("toggle-queue").disabled = connectionState !== "ready";
    $("restart-agent").disabled = connectionState === "port_conflict" || connectionState === "incompatible";

    const active = (value.jobs || []).find((job) => job.status === "running");
    const summary = $("work-summary");
    if (active) {
      summary.querySelector("h3").textContent = "Processamento em andamento";
      const progress = active.progress || {};
      summary.querySelector("p").textContent = `${active.kind || "Trabalho local"} · ${progress.completed ?? 0} de ${progress.total ?? "—"} ${progress.unit || "itens"}`;
    } else if (connectionState !== "ready") {
      summary.querySelector("h3").textContent = "Agent local indisponível.";
      summary.querySelector("p").textContent = "A interface continua ativa. O Companion tentará recuperar o Agent sem descartar a sessão Craig já selecionada.";
    } else {
      summary.querySelector("h3").textContent = "Nenhum processamento em andamento.";
      summary.querySelector("p").textContent = counts.queued ? `${counts.queued} trabalho(s) aguardando na fila.` : "A fila está livre. Selecione um ZIP do Craig para iniciar uma transcrição local.";
    }

    const settings = value.settings || {};
    $("setting-startup").checked = Boolean(settings.start_with_windows);
    $("setting-tray").checked = Boolean(settings.show_tray);
    $("setting-updates").checked = Boolean(settings.check_updates);
    $("setting-theme").value = settings.theme || "system";
    $("setting-close").value = settings.close_behavior || "hide";
    renderWhisperRuntime(value.whisper_runtime || { status: "missing" }, false);
    renderQwenRuntime(value.qwen_runtime || { status: "missing" }, false);
    renderSubmittedJob(value);
  }

  async function refreshSnapshot() {
    if (!api) return;
    const previousState = lastConnectionState;
    try {
      const snapshot = await api.snapshot();
      renderSnapshot(snapshot);
      const currentState = snapshot?.connection?.state || snapshot?.agent?.lifecycle || "ready";
      if (previousState && previousState !== "ready" && currentState === "ready" && selectedSession) {
        try {
          await refreshProfiles();
        } catch {
          // The next background cycle will retry; do not turn recovery into toast spam.
        }
      }
    } catch {
      $("agent-pill").textContent = "● Agent indisponível";
      $("agent-pill").classList.add("warning");
    }
  }

  async function refreshLogs(announce = false) {
    if (!api) return;
    try {
      const level = $("log-level")?.value || null;
      const result = await api.logs(level, null, 300);
      if (result?.unavailable) {
        renderLogsUnavailable(result);
        if (announce) toast(`Logs indisponíveis: ${errorText(result.error)}`, true);
        return;
      }
      allLogs = Array.isArray(result.logs) ? result.logs : [];
      renderLogRows($("full-logs"), allLogs, false);
      renderLogRows($("overview-logs"), allLogs, true);
    } catch (error) {
      if (announce) toast(`Não foi possível ler os logs: ${errorText(error)}`, true);
    }
  }

  function renderUpdate(result) {
    const available = Boolean(result?.available);
    $("update-banner").classList.toggle("hidden", !available);
    $("update-version").textContent = available ? `· v${result.version}` : "";
    $("install-update").classList.toggle("hidden", !available);
    if (available) $("install-update").textContent = `Atualizar para ${result.version}`;
  }

  async function checkUpdate(announce = false) {
    if (!api) return;
    try {
      const result = await api.check_update();
      renderUpdate(result);
      if (announce) toast(result.available ? `TDA Companion ${result.version} disponível.` : "Você já está na versão mais recente.");
    } catch (error) {
      if (announce) toast(`Não foi possível verificar atualização: ${errorText(error)}`, true);
    }
  }

  async function checkWhisperRuntime(announce = false) {
    const button = $("check-whisper-runtime");
    button.disabled = true;
    try {
      const result = await api.check_whisper_runtime();
      renderWhisperRuntime(result, true);
      if (announce) toast(result.available ? `Whisper runtime ${result.version} disponível.` : "Runtime Whisper já está atualizado.");
    } catch (error) {
      if (announce) toast(`Não foi possível verificar o Whisper: ${errorText(error)}`, true);
    } finally {
      button.disabled = false;
    }
  }

  async function installWhisperRuntime() {
    if (!window.confirm("Baixar e instalar o runtime Whisper isolado?")) return;
    const button = $("install-whisper-runtime");
    button.disabled = true;
    button.textContent = "Baixando e verificando…";
    try {
      const result = await api.install_whisper_runtime();
      toast(result.accepted ? `Whisper runtime ${result.version} instalado e verificado.` : "Runtime Whisper já está atualizado.");
      await refreshSnapshot();
      await checkWhisperRuntime(false);
    } catch (error) {
      toast(`O runtime Whisper não foi instalado: ${errorText(error)}`, true);
    } finally {
      button.disabled = false;
    }
  }

  async function checkQwenRuntime(announce = false) {
    const button = $("check-qwen-runtime");
    button.disabled = true;
    try {
      const result = await api.check_qwen_runtime();
      renderQwenRuntime(result, true);
      if (announce) toast(result.available ? `Qwen runtime ${result.version} disponível.` : "Runtime Qwen já está atualizado.");
    } catch (error) {
      if (announce) toast(`Não foi possível verificar o Qwen: ${errorText(error)}`, true);
    } finally {
      button.disabled = false;
    }
  }

  async function installQwenRuntime() {
    if (!window.confirm("Baixar e instalar o runtime Qwen isolado? Os modelos e o gate físico serão preparados somente ao processar uma sessão.")) return;
    const button = $("install-qwen-runtime");
    button.disabled = true;
    button.textContent = "Baixando e verificando…";
    try {
      const result = await api.install_qwen_runtime();
      toast(result.accepted ? `Qwen runtime ${result.version} instalado e verificado.` : "Runtime Qwen já está atualizado.");
      await refreshSnapshot();
      await checkQwenRuntime(false);
      if (selectedSession) await refreshProfiles();
    } catch (error) {
      toast(`O runtime Qwen não foi instalado: ${errorText(error)}`, true);
    } finally {
      button.disabled = false;
    }
  }

  function renderDiagnostics(result) {
    $("diagnostic-overall").textContent = result.overall === "pass" ? "Tudo certo" : result.overall === "warning" ? "Atenção recomendada" : "Problema encontrado";
    $("diagnostic-time").textContent = result.generated_at ? new Date(result.generated_at).toLocaleString("pt-BR") : "—";
    const target = $("diagnostic-list");
    target.replaceChildren();
    (result.checks || []).forEach((check) => {
      const row = document.createElement("div");
      row.className = "diagnostic-row";
      const dot = document.createElement("i");
      dot.className = `diagnostic-status ${check.status || ""}`;
      const code = document.createElement("b");
      code.textContent = check.code || "check";
      const message = document.createElement("span");
      message.textContent = check.message || "—";
      const detail = document.createElement("small");
      detail.textContent = check.detail || check.status || "—";
      row.append(dot, code, message, detail);
      target.append(row);
    });
  }

  async function runDiagnostics() {
    try {
      renderDiagnostics(await api.diagnostics());
    } catch (error) {
      toast(`Diagnóstico falhou: ${errorText(error)}`, true);
    }
  }

  async function updateSetting(key, value) {
    try {
      await api.update_settings({ [key]: value });
      await refreshSnapshot();
    } catch (error) {
      toast(`Não foi possível salvar: ${errorText(error)}`, true);
    }
  }

  async function installUpdate() {
    if (!window.confirm("Baixar, verificar e instalar a atualização agora? O Agent só será reiniciado se não houver trabalho em execução.")) return;
    const button = $("install-update");
    button.disabled = true;
    button.textContent = "Preparando atualização…";
    try {
      const result = await api.install_update();
      if (!result.accepted) {
        renderUpdate(result);
        toast("Você já está na versão mais recente.");
        return;
      }
      toast(`Atualizando para ${result.version}…`);
      await api.close_desktop();
    } catch (error) {
      toast(`A atualização não foi iniciada: ${errorText(error)}`, true);
      button.disabled = false;
      await checkUpdate(false);
    }
  }

  async function uninstall(purge) {
    const message = purge
      ? "Remover completamente o TDA Companion, fila, resultados, modelos, logs e configurações locais deste usuário? Esta ação não pode ser desfeita."
      : "Desinstalar o TDA Companion e manter seus dados locais para uma futura reinstalação?";
    if (!window.confirm(message)) return;
    if (purge && !window.confirm("Confirma a remoção COMPLETA dos dados locais do TDA neste computador?")) return;
    try {
      const result = await api.uninstall(Boolean(purge));
      if (result.accepted) {
        toast(purge ? "Removendo completamente o TDA Companion…" : "Desinstalando o TDA Companion…");
        await api.close_desktop();
      }
    } catch (error) {
      toast(`A desinstalação não foi iniciada: ${errorText(error)}`, true);
    }
  }

  function bindEvents() {
    document.querySelectorAll(".nav-item").forEach((node) => {
      node.addEventListener("click", () => showView(node.dataset.view));
    });
    document.querySelectorAll("[data-go]").forEach((node) => {
      node.addEventListener("click", () => showView(node.dataset.go));
    });
    $("new-session").addEventListener("click", () => showView("process"));
    $("select-craig").addEventListener("click", selectCraigSession);
    $("start-processing").addEventListener("click", startProcessing);
    $("open-tda").addEventListener("click", () => api.open_tda());
    $("open-local").addEventListener("click", () => api.open_local_folder());
    $("open-logs").addEventListener("click", () => api.open_logs_folder());
    $("toggle-queue").addEventListener("click", async () => {
      try {
        await api.set_queue_paused(lastSnapshot?.agent?.lifecycle !== "paused");
        await refreshSnapshot();
      } catch (error) {
        toast(`Não foi possível alterar a fila: ${errorText(error)}`, true);
      }
    });
    $("restart-agent").addEventListener("click", async () => {
      if (!window.confirm("Reiniciar o Agent local? A ação é bloqueada se houver trabalho em execução.")) return;
      try {
        await api.restart_agent();
        toast("Agent reiniciado.");
        await refreshSnapshot();
      } catch (error) {
        toast(`Não foi possível reiniciar: ${errorText(error)}`, true);
      }
    });
    $("quick-diagnostics").addEventListener("click", () => {
      showView("diagnostics");
      runDiagnostics();
    });
    $("run-diagnostics").addEventListener("click", runDiagnostics);
    $("export-diagnostics").addEventListener("click", async () => {
      try {
        const path = await api.export_diagnostics();
        toast(`Diagnóstico exportado: ${path}`);
      } catch (error) {
        toast(`Export falhou: ${errorText(error)}`, true);
      }
    });
    $("refresh-logs").addEventListener("click", () => refreshLogs(true));
    $("log-level").addEventListener("change", () => refreshLogs(true));
    $("log-search").addEventListener("input", () => renderLogRows($("full-logs"), allLogs, false));
    $("setting-startup").addEventListener("change", (event) => updateSetting("start_with_windows", event.target.checked));
    $("setting-tray").addEventListener("change", (event) => updateSetting("show_tray", event.target.checked));
    $("setting-updates").addEventListener("change", (event) => updateSetting("check_updates", event.target.checked));
    $("setting-theme").addEventListener("change", (event) => updateSetting("theme", event.target.value));
    $("setting-close").addEventListener("change", (event) => updateSetting("close_behavior", event.target.value));
    $("copy-token").addEventListener("click", async () => {
      try {
        const token = await api.pairing_token();
        await navigator.clipboard.writeText(token);
        $("token-feedback").textContent = "Token copiado";
        window.setTimeout(() => {
          $("token-feedback").textContent = "";
        }, 2200);
      } catch (error) {
        toast(`Não foi possível copiar o token: ${errorText(error)}`, true);
      }
    });
    $("check-whisper-runtime").addEventListener("click", () => checkWhisperRuntime(true));
    $("install-whisper-runtime").addEventListener("click", installWhisperRuntime);
    $("check-qwen-runtime").addEventListener("click", () => checkQwenRuntime(true));
    $("install-qwen-runtime").addEventListener("click", installQwenRuntime);
    $("check-update").addEventListener("click", () => checkUpdate(true));
    $("install-update").addEventListener("click", installUpdate);
    $("update-banner").addEventListener("click", () => {
      showView("settings");
      checkUpdate(true);
    });
    $("uninstall-keep").addEventListener("click", () => uninstall(false));
    $("uninstall-purge").addEventListener("click", () => uninstall(true));
  }

  async function boot() {
    api = window.pywebview?.api;
    if (!api) return;
    bindEvents();
    renderSession(null);
    await refreshSnapshot();
    await refreshLogs(false);
    if (lastSnapshot?.settings?.check_updates) {
      checkUpdate(false);
      checkWhisperRuntime(false);
      checkQwenRuntime(false);
    }
    refreshTimer = window.setInterval(async () => {
      await refreshSnapshot();
      if (document.visibilityState === "visible") await refreshLogs(false);
    }, 3000);
  }

  window.addEventListener("pywebviewready", boot, { once: true });
  window.addEventListener("beforeunload", () => {
    if (refreshTimer) window.clearInterval(refreshTimer);
  });
})();
