/* ComputeMesh's per-browser model selector and P2P Local Node Auto-Router for the bundled AI Studio WebUI. */
(function () {
	'use strict';

	var STORAGE_KEY = 'cm_selected_model_id';
	var DRAFT_KEY = 'cm_model_switch_draft';
	var models = [];
	var selectedModel = null;
	var picker = null;
	var localNodeEndpoint = null;
	var meshEndpoints = [];
	var localNodeChecked = false;
	var localNodeCheckingPromise = null;
	var modelSelectionReady = null;
	var lastExecution = null;
	var modelInfoFallbackPromise = null;
	var modelInfoFallbackModelId = '';
	var agentSessions = [];
	var agentSessionId = '';
	var agentSessionCursor = 0;
	var agentSessionPollTimer = null;
	var agentSessionPollInFlight = false;
	var agentSessionPollBlocked = false;
	var agentSessionPanel = null;
	var agentSessionSelect = null;
	var agentSessionStatus = null;
	var agentSessionActivityPanel = null;
	var agentSessionActivity = [];
	var agentApprovalPanel = null;
	var agentTaskPrompt = null;
	var agentTaskCreateButton = null;
	var agentTaskContinueButton = null;
	var agentTaskPauseButton = null;
	var agentTaskResumeButton = null;
	var agentTaskCancelButton = null;
	var agentTaskActionMessage = null;
	var agentTaskBusy = false;
	var agentArtifactPanel = null;
	var agentArtifacts = [];
	var agentApprovals = [];
	var agentSessionLastEvent = '';
	var AGENT_SESSION_CACHE_KEY = 'cm_agent_sessions_cache_v1';

	var agentControlLabels = {
		de: { pause: 'Pausieren', resume: 'Fortsetzen', cancel: 'Abbrechen', controlError: 'Steuerung konnte nicht gespeichert werden', controlQueued: 'Steuerung angefordert' },
		en: { pause: 'Pause', resume: 'Resume', cancel: 'Cancel', controlError: 'Control request was not saved', controlQueued: 'Control request accepted' },
		fr: { pause: 'Pause', resume: 'Reprendre', cancel: 'Annuler', controlError: 'La commande n’a pas été enregistrée', controlQueued: 'Commande acceptée' },
		es: { pause: 'Pausar', resume: 'Continuar', cancel: 'Cancelar', controlError: 'No se guardó el control', controlQueued: 'Control aceptado' },
		it: { pause: 'Pausa', resume: 'Riprendi', cancel: 'Annulla', controlError: 'Controllo non salvato', controlQueued: 'Controllo accettato' },
		'pt-BR': { pause: 'Pausar', resume: 'Retomar', cancel: 'Cancelar', controlError: 'O controle não foi salvo', controlQueued: 'Controle aceito' },
		nl: { pause: 'Pauzeren', resume: 'Hervatten', cancel: 'Annuleren', controlError: 'Besturing niet opgeslagen', controlQueued: 'Besturing geaccepteerd' },
		pl: { pause: 'Wstrzymaj', resume: 'Wznów', cancel: 'Anuluj', controlError: 'Nie zapisano sterowania', controlQueued: 'Sterowanie przyjęte' },
		tr: { pause: 'Duraklat', resume: 'Sürdür', cancel: 'İptal', controlError: 'Denetim kaydedilmedi', controlQueued: 'Denetim kabul edildi' }
	};

	var agentArtifactLabels = {
		de: { title: 'Artefakte', empty: 'Keine Artefakte', download: 'Herunterladen' },
		en: { title: 'Artifacts', empty: 'No artifacts', download: 'Download' },
		fr: { title: 'Artefacts', empty: 'Aucun artefact', download: 'Télécharger' },
		es: { title: 'Artefactos', empty: 'No hay artefactos', download: 'Descargar' },
		it: { title: 'Artefatti', empty: 'Nessun artefatto', download: 'Scarica' },
		'pt-BR': { title: 'Artefatos', empty: 'Nenhum artefato', download: 'Baixar' },
		nl: { title: 'Artefacten', empty: 'Geen artefacten', download: 'Downloaden' },
		pl: { title: 'Artefakty', empty: 'Brak artefaktów', download: 'Pobierz' },
		tr: { title: 'Yapay eserler', empty: 'Yapay eser yok', download: 'İndir' }
	};
	var executionStatusLabels = {
		de: { last: 'Letzte Ausführung', unknown: 'unbekannt', unspecified: 'nicht angegeben', evidence: 'Ausführungsnachweis des letzten Laufs', id: 'Ausführungs-ID' },
		en: { last: 'Last execution', unknown: 'unknown', unspecified: 'not specified', evidence: 'Execution evidence for the last run', id: 'Execution ID' },
		fr: { last: 'Dernière exécution', unknown: 'inconnu', unspecified: 'non indiqué', evidence: 'Preuve de la dernière exécution', id: 'ID d’exécution' },
		es: { last: 'Última ejecución', unknown: 'desconocido', unspecified: 'no indicado', evidence: 'Evidencia de la última ejecución', id: 'ID de ejecución' },
		it: { last: 'Ultima esecuzione', unknown: 'sconosciuto', unspecified: 'non indicato', evidence: 'Prova dell’ultima esecuzione', id: 'ID esecuzione' },
		'pt-BR': { last: 'Última execução', unknown: 'desconhecido', unspecified: 'não especificado', evidence: 'Evidência da última execução', id: 'ID da execução' },
		nl: { last: 'Laatste uitvoering', unknown: 'onbekend', unspecified: 'niet opgegeven', evidence: 'Uitvoeringsbewijs van de laatste run', id: 'Uitvoerings-ID' },
		pl: { last: 'Ostatnie wykonanie', unknown: 'nieznane', unspecified: 'nie podano', evidence: 'Dowód ostatniego wykonania', id: 'Identyfikator wykonania' },
		tr: { last: 'Son çalıştırma', unknown: 'bilinmiyor', unspecified: 'belirtilmedi', evidence: 'Son çalıştırmanın kanıtı', id: 'Çalıştırma kimliği' }
	};

	function executionStatusText(key) {
		var raw = String(document.documentElement.lang || navigator.language || 'en').replace('_', '-');
		var locale = Object.prototype.hasOwnProperty.call(executionStatusLabels, raw) ? raw : raw.split('-')[0];
		var labels = executionStatusLabels[locale] || executionStatusLabels.en;
		return labels[key] || executionStatusLabels.en[key];
	}

	var agentSessionLabels = {
		de: { title: 'Agent-Sitzungen', select: 'Agent-Sitzung auswählen', prompt: 'Aufgabe für den Agenten …', create: 'Neue Aufgabe', continueTask: 'Fortsetzen', taskCreated: 'Aufgabe gestartet', turnQueued: 'Nächster Turn eingereiht', taskError: 'Aufgabe konnte nicht gestartet werden', noModel: 'Kein Modell verfügbar', waiting: 'Warte auf Fortschritt …', unavailable: 'Sitzung nicht erreichbar', idle: 'Bereit', approvals: 'Offene Freigaben', approve: 'Freigeben', reject: 'Ablehnen', noApprovals: 'Keine offenen Freigaben', approvalError: 'Freigabe nicht gespeichert' },
		en: { title: 'Agent sessions', select: 'Select agent session', prompt: 'Task for the agent …', create: 'New task', continueTask: 'Continue', taskCreated: 'Task started', turnQueued: 'Next turn queued', taskError: 'Task could not be started', noModel: 'No model available', waiting: 'Waiting for progress …', unavailable: 'Session unavailable', idle: 'Ready', approvals: 'Pending approvals', approve: 'Approve', reject: 'Reject', noApprovals: 'No pending approvals', approvalError: 'Approval was not saved' },
		fr: { title: 'Sessions agent', select: 'Sélectionner une session agent', prompt: 'Tâche pour l’agent …', create: 'Nouvelle tâche', continueTask: 'Continuer', taskCreated: 'Tâche démarrée', turnQueued: 'Tour suivant en file', taskError: 'Impossible de démarrer la tâche', noModel: 'Aucun modèle disponible', waiting: 'En attente de progression …', unavailable: 'Session indisponible', idle: 'Prête', approvals: 'Approbations en attente', approve: 'Approuver', reject: 'Refuser', noApprovals: 'Aucune approbation en attente', approvalError: 'Approbation non enregistrée' },
		es: { title: 'Sesiones de agente', select: 'Seleccionar sesión de agente', prompt: 'Tarea para el agente …', create: 'Nueva tarea', continueTask: 'Continuar', taskCreated: 'Tarea iniciada', turnQueued: 'Siguiente turno en cola', taskError: 'No se pudo iniciar la tarea', noModel: 'No hay ningún modelo disponible', waiting: 'Esperando progreso …', unavailable: 'Sesión no disponible', idle: 'Lista', approvals: 'Aprobaciones pendientes', approve: 'Aprobar', reject: 'Rechazar', noApprovals: 'No hay aprobaciones pendientes', approvalError: 'No se guardó la aprobación' },
		it: { title: 'Sessioni agente', select: 'Seleziona sessione agente', prompt: 'Attività per l’agente …', create: 'Nuova attività', continueTask: 'Continua', taskCreated: 'Attività avviata', turnQueued: 'Turno successivo in coda', taskError: 'Impossibile avviare l’attività', noModel: 'Nessun modello disponibile', waiting: 'In attesa di progressi …', unavailable: 'Sessione non disponibile', idle: 'Pronta', approvals: 'Approvazioni in sospeso', approve: 'Approva', reject: 'Rifiuta', noApprovals: 'Nessuna approvazione in sospeso', approvalError: 'Approvazione non salvata' },
		'pt-BR': { title: 'Sessões do agente', select: 'Selecionar sessão do agente', prompt: 'Tarefa para o agente …', create: 'Nova tarefa', continueTask: 'Continuar', taskCreated: 'Tarefa iniciada', turnQueued: 'Próximo turno na fila', taskError: 'Não foi possível iniciar a tarefa', noModel: 'Nenhum modelo disponível', waiting: 'Aguardando progresso …', unavailable: 'Sessão indisponível', idle: 'Pronta', approvals: 'Aprovações pendentes', approve: 'Aprovar', reject: 'Rejeitar', noApprovals: 'Nenhuma aprovação pendente', approvalError: 'A aprovação não foi salva' },
		nl: { title: 'Agentsessies', select: 'Agentsessie selecteren', prompt: 'Taak voor de agent …', create: 'Nieuwe taak', continueTask: 'Doorgaan', taskCreated: 'Taak gestart', turnQueued: 'Volgende beurt in wachtrij', taskError: 'Taak kon niet worden gestart', noModel: 'Geen model beschikbaar', waiting: 'Wachten op voortgang …', unavailable: 'Sessie niet beschikbaar', idle: 'Gereed', approvals: 'Openstaande goedkeuringen', approve: 'Goedkeuren', reject: 'Afwijzen', noApprovals: 'Geen openstaande goedkeuringen', approvalError: 'Goedkeuring niet opgeslagen' },
		pl: { title: 'Sesje agenta', select: 'Wybierz sesję agenta', prompt: 'Zadanie dla agenta …', create: 'Nowe zadanie', continueTask: 'Kontynuuj', taskCreated: 'Zadanie uruchomione', turnQueued: 'Następna tura w kolejce', taskError: 'Nie udało się uruchomić zadania', noModel: 'Brak dostępnego modelu', waiting: 'Oczekiwanie na postęp …', unavailable: 'Sesja niedostępna', idle: 'Gotowe', approvals: 'Oczekujące zgody', approve: 'Zatwierdź', reject: 'Odrzuć', noApprovals: 'Brak oczekujących zgód', approvalError: 'Nie zapisano decyzji' },
		tr: { title: 'Aracı oturumları', select: 'Aracı oturumu seç', prompt: 'Aracı için görev …', create: 'Yeni görev', continueTask: 'Sürdür', taskCreated: 'Görev başlatıldı', turnQueued: 'Sonraki tur sıraya alındı', taskError: 'Görev başlatılamadı', noModel: 'Kullanılabilir model yok', waiting: 'İlerleme bekleniyor …', unavailable: 'Oturum kullanılamıyor', idle: 'Hazır', approvals: 'Bekleyen onaylar', approve: 'Onayla', reject: 'Reddet', noApprovals: 'Bekleyen onay yok', approvalError: 'Onay kaydedilmedi' }
	};
	var agentSessionActivityLabels = {
		de: { title: 'Aktivität', empty: 'Noch keine Aktivität' },
		en: { title: 'Activity', empty: 'No activity yet' },
		fr: { title: 'Activité', empty: 'Aucune activité' },
		es: { title: 'Actividad', empty: 'Aún no hay actividad' },
		it: { title: 'Attività', empty: 'Nessuna attività' },
		'pt-BR': { title: 'Atividade', empty: 'Ainda não há atividade' },
		nl: { title: 'Activiteit', empty: 'Nog geen activiteit' },
		pl: { title: 'Aktywność', empty: 'Brak aktywności' },
		tr: { title: 'Etkinlik', empty: 'Henüz etkinlik yok' }
	};

	function agentSessionActivityText(key) {
		var locale = agentSessionLocale();
		var labels = agentSessionActivityLabels[locale] || agentSessionActivityLabels.en;
		return labels[key] || agentSessionActivityLabels.en[key];
	}

	function agentSessionLocale() {
		var raw = String(document.documentElement.lang || navigator.language || 'en').replace('_', '-');
		if (Object.prototype.hasOwnProperty.call(agentSessionLabels, raw)) return raw;
		var base = raw.split('-')[0];
		return Object.prototype.hasOwnProperty.call(agentSessionLabels, base) ? base : 'en';
	}

	function agentSessionText(key) {
		return agentSessionLabels[agentSessionLocale()][key] || agentSessionLabels.en[key];
	}

	function agentControlText(key) {
		var labels = agentControlLabels[agentSessionLocale()] || agentControlLabels.en;
		return labels[key] || agentControlLabels.en[key];
	}

	function agentArtifactText(key) {
		var locale = agentSessionLocale();
		var labels = agentArtifactLabels[locale] || agentArtifactLabels.en;
		return labels[key] || agentArtifactLabels.en[key];
	}

	var agentSessionStatuses = {
		creating: { de: 'Wird erstellt', en: 'Creating', fr: 'Création', es: 'Creando', it: 'Creazione', 'pt-BR': 'Criando', nl: 'Wordt gemaakt', pl: 'Tworzenie', tr: 'Oluşturuluyor' },
		ready: { de: 'Bereit', en: 'Ready', fr: 'Prête', es: 'Lista', it: 'Pronta', 'pt-BR': 'Pronta', nl: 'Gereed', pl: 'Gotowe', tr: 'Hazır' },
		running: { de: 'Läuft', en: 'Running', fr: 'En cours', es: 'En ejecución', it: 'In esecuzione', 'pt-BR': 'Em execução', nl: 'Actief', pl: 'W toku', tr: 'Çalışıyor' },
		waiting_for_tool: { de: 'Wartet auf Tool', en: 'Waiting for tool', fr: 'En attente d’un outil', es: 'Esperando una herramienta', it: 'In attesa di uno strumento', 'pt-BR': 'Aguardando uma ferramenta', nl: 'Wacht op tool', pl: 'Oczekiwanie na narzędzie', tr: 'Araç bekleniyor' },
		waiting_for_approval: { de: 'Wartet auf Freigabe', en: 'Waiting for approval', fr: 'En attente d’approbation', es: 'Esperando aprobación', it: 'In attesa di approvazione', 'pt-BR': 'Aguardando aprovação', nl: 'Wacht op goedkeuring', pl: 'Oczekiwanie na zgodę', tr: 'Onay bekleniyor' },
		waiting_for_subagents: { de: 'Wartet auf Subagenten', en: 'Waiting for subagents', fr: 'En attente de sous-agents', es: 'Esperando subagentes', it: 'In attesa dei subagenti', 'pt-BR': 'Aguardando subagentes', nl: 'Wacht op subagents', pl: 'Oczekiwanie na podagentów', tr: 'Alt aracılar bekleniyor' },
		compacting: { de: 'Kontext wird verdichtet', en: 'Compacting context', fr: 'Condensation du contexte', es: 'Compactando contexto', it: 'Compattazione del contesto', 'pt-BR': 'Compactando contexto', nl: 'Context comprimeren', pl: 'Kompaktowanie kontekstu', tr: 'Bağlam sıkıştırılıyor' },
		paused: { de: 'Pausiert', en: 'Paused', fr: 'En pause', es: 'En pausa', it: 'In pausa', 'pt-BR': 'Pausada', nl: 'Gepauzeerd', pl: 'Wstrzymana', tr: 'Duraklatıldı' },
		resuming: { de: 'Wird fortgesetzt', en: 'Resuming', fr: 'Reprise', es: 'Reanudando', it: 'Ripresa', 'pt-BR': 'Retomando', nl: 'Hervatten', pl: 'Wznawianie', tr: 'Sürdürülüyor' },
		completed: { de: 'Abgeschlossen', en: 'Completed', fr: 'Terminée', es: 'Completada', it: 'Completata', 'pt-BR': 'Concluída', nl: 'Voltooid', pl: 'Ukończona', tr: 'Tamamlandı' },
		failed: { de: 'Fehlgeschlagen', en: 'Failed', fr: 'Échec', es: 'Fallida', it: 'Fallita', 'pt-BR': 'Falhou', nl: 'Mislukt', pl: 'Nieudana', tr: 'Başarısız' },
		cancelled: { de: 'Abgebrochen', en: 'Cancelled', fr: 'Annulée', es: 'Cancelada', it: 'Annullata', 'pt-BR': 'Cancelada', nl: 'Geannuleerd', pl: 'Anulowana', tr: 'İptal edildi' },
		expired: { de: 'Abgelaufen', en: 'Expired', fr: 'Expirée', es: 'Expirada', it: 'Scaduta', 'pt-BR': 'Expirada', nl: 'Verlopen', pl: 'Wygasła', tr: 'Süresi doldu' }
	};

	function agentSessionStatusText(status) {
		var entry = agentSessionStatuses[String(status || '').toLowerCase()];
		if (!entry) return agentSessionText('idle');
		return entry[agentSessionLocale()] || entry.en;
	}

	function agentSessionTerminal(status) {
		return ['completed', 'failed', 'cancelled', 'expired'].includes(String(status || '').toLowerCase());
	}

	function agentStorageGet(key) {
		try {
			var persistent = localStorage.getItem(key);
			if (persistent !== null) return persistent;
		} catch (_) {}
		try { return sessionStorage.getItem(key); } catch (_) { return null; }
	}

	function agentStorageSet(key, value) {
		try {
			localStorage.setItem(key, value);
			return;
		} catch (_) {}
		try { sessionStorage.setItem(key, value); } catch (_) {}
	}

	function agentStorageRemove(key) {
		try { localStorage.removeItem(key); } catch (_) {}
		try { sessionStorage.removeItem(key); } catch (_) {}
	}

	function saveAgentSessionCache() {
		try {
			var safe = agentSessions.slice(0, 50).map(function (session) {
				return {
					session_id: String(session.session_id || ''),
					agent_id: String(session.agent_id || ''),
					agent_version: String(session.agent_version || ''),
					status: String(session.status || ''),
					environment_type: String(session.environment_type || ''),
					version: Number(session.version || 0),
					created_at: Number(session.created_at || 0),
					updated_at: Number(session.updated_at || 0)
				};
			}).filter(function (session) { return session.session_id && session.agent_id; });
			agentStorageSet(AGENT_SESSION_CACHE_KEY, JSON.stringify(safe));
		} catch (_) {}
	}

	function restoreAgentSessionCache() {
		try {
			var raw = agentStorageGet(AGENT_SESSION_CACHE_KEY);
			var parsed = raw ? JSON.parse(raw) : [];
			if (!Array.isArray(parsed)) return [];
			return parsed.slice(0, 50).filter(function (session) {
				return session && typeof session === 'object' && String(session.session_id || '').length <= 160 && String(session.agent_id || '').length <= 160;
			});
		} catch (_) { return []; }
	}

	function agentSessionStorageKey(id) {
		return 'cm_agent_session_cursor_' + String(id || '').replace(/[^a-zA-Z0-9_.-]/g, '_');
	}

	function restoreAgentSessionCursor(id) {
		agentSessionCursor = 0;
		try {
			var stored = Number(agentStorageGet(agentSessionStorageKey(id)) || 0);
			if (Number.isFinite(stored) && stored >= 0) agentSessionCursor = Math.floor(stored);
		} catch (_) {}
	}

	function saveAgentSessionCursor() {
		agentStorageSet(agentSessionStorageKey(agentSessionId), String(agentSessionCursor));
	}

	// Image bytes become base64 in the chat JSON; keep their combined binary size
	// near 5 MiB to leave room for base64 expansion and the rest of the request.
	var uploadLimitBytes = 5 * 1024 * 1024;
	var maxChatRequestBytes = 9 * 1024 * 1024;
	var gatewayRequestLimitBytes = 10 * 1024 * 1024;
	var maxImageEdge = 1600;
	var replayingFileInputs = new WeakSet();

	var localizedMeshNotices = {
		de: 'LAN-Node erkannt, aber er verlangt eine manuelle Kopplung. Öffne Setup und hinterlege den Owner-Key oder scanne den Einmal-QR-Code.',
		en: 'LAN node detected, but it requires manual pairing. Open Setup and enter the owner key or scan the one-time QR code.',
		fr: 'Nœud LAN détecté, mais il nécessite un appairage manuel. Ouvrez Setup et saisissez la clé propriétaire ou scannez le QR code à usage unique.',
		es: 'Nodo LAN detectado, pero requiere vinculación manual. Abre Setup e introduce la clave del propietario o escanea el código QR de un solo uso.',
		it: 'Nodo LAN rilevato, ma richiede un abbinamento manuale. Apri Setup e inserisci la chiave del proprietario oppure scansiona il codice QR monouso.',
		'pt-BR': 'Nó LAN detectado, mas ele exige pareamento manual. Abra Setup e informe a chave do proprietário ou escaneie o código QR de uso único.',
		nl: 'LAN-node gevonden, maar handmatig koppelen is vereist. Open Setup en voer de eigenaarsleutel in of scan de eenmalige QR-code.',
		pl: 'Wykryto węzeł LAN, ale wymaga on ręcznego parowania. Otwórz Setup i podaj klucz właściciela albo zeskanuj jednorazowy kod QR.',
		tr: 'LAN düğümü algılandı, ancak manuel eşleştirme gerekiyor. Setup bölümünü açıp sahip anahtarını girin veya tek kullanımlık QR kodunu tarayın.'
	};

	function localizedMeshNotice(code) {
		if (code !== 'local_node_auth_required') return '';
		var raw = String(document.documentElement.lang || navigator.language || 'en').replace('_', '-');
		var exact = Object.prototype.hasOwnProperty.call(localizedMeshNotices, raw) ? raw : raw.split('-')[0];
		return localizedMeshNotices[exact] || localizedMeshNotices.en;
	}

	function rewriteMeshNoticePayload(payload) {
		if (!payload || typeof payload !== 'object') return payload;
		var notice = payload.compute_mesh_notice || (payload.error && payload.error.compute_mesh_notice);
		var message = localizedMeshNotice(notice && notice.code);
		if (!message) return payload;
		var rewritten = Object.assign({}, payload);
		if (rewritten.error && typeof rewritten.error === 'object') {
			rewritten.error = Object.assign({}, rewritten.error, { message: message });
		}
		if (Array.isArray(rewritten.choices)) {
			rewritten.choices = rewritten.choices.map(function (choice) {
				var next = Object.assign({}, choice);
				if (next.delta) next.delta = Object.assign({}, next.delta, { content: message });
				if (next.message) next.message = Object.assign({}, next.message, { content: message });
				return next;
			});
		}
		return rewritten;
	}

	function rewriteMeshNoticeSseLine(line) {
		if (!line.startsWith('data: ')) return line;
		var raw = line.slice(6).trim();
		if (!raw || raw === '[DONE]') return line;
		try {
			var parsed = JSON.parse(raw);
			var rewritten = rewriteMeshNoticePayload(parsed);
			return rewritten === parsed ? line : 'data: ' + JSON.stringify(rewritten);
		} catch (_) { return line; }
	}

	async function localizeMeshNoticeResponse(response) {
		var contentType = response.headers.get('content-type') || '';
		if (contentType.includes('application/json')) {
			try {
				var payload = await response.clone().json();
				var rewritten = rewriteMeshNoticePayload(payload);
				if (rewritten === payload) return response;
				var headers = new Headers(response.headers);
				['content-length', 'content-encoding', 'content-md5', 'etag'].forEach(function (name) { headers.delete(name); });
				return new Response(JSON.stringify(rewritten), { status: response.status, statusText: response.statusText, headers: headers });
			} catch (_) { return response; }
		}
		if (!contentType.includes('text/event-stream') || !response.body || typeof ReadableStream === 'undefined') return response;
		var reader = response.body.getReader();
		var decoder = new TextDecoder();
		var encoder = new TextEncoder();
		var carry = '';
		var stream = new ReadableStream({
			async pull(controller) {
				var part = await reader.read();
				if (part.done) {
					carry += decoder.decode();
					if (carry) controller.enqueue(encoder.encode(rewriteMeshNoticeSseLine(carry)));
					controller.close();
					return;
				}
				carry += decoder.decode(part.value, { stream: true });
				var lines = carry.split(/\n/);
				carry = lines.pop() || '';
				controller.enqueue(encoder.encode(lines.map(rewriteMeshNoticeSseLine).join('\n') + (lines.length ? '\n' : '')));
			}
		});
		return new Response(stream, { status: response.status, statusText: response.statusText, headers: response.headers });
	}

	// A stored id is only a hint. Validate it against the live catalog before
	// allowing it to rewrite a completion request.
	var originalFetch = window.fetch.bind(window);

	function addMeshEndpoint(value) {
		if (!value) return;
		try {
			var endpoint = new URL(String(value), window.location.origin).href.replace(/\/$/, '');
			if (!/^https?:$/i.test(new URL(endpoint).protocol)) return;
			if (!meshEndpoints.includes(endpoint)) meshEndpoints.push(endpoint);
		} catch (_) {}
	}

	async function fetchDiscoveryJson(url, credentials) {
		var controller = new AbortController();
		var timer = setTimeout(function () { controller.abort(); }, 2000);
		try {
			var response = await originalFetch(url, { credentials: credentials, cache: 'no-store', signal: controller.signal });
			return response.ok ? await response.json() : null;
		} finally {
			clearTimeout(timer);
		}
	}

	async function discoverFleetEndpoints() {
		var paths = ['/api/v1/mesh/fleet', '/api/portal/fleet'];
		for (var i = 0; i < paths.length; i++) {
			try {
				var payload = await fetchDiscoveryJson(paths[i], 'include');
				var nodes = Array.isArray(payload && payload.nodes) ? payload.nodes : [];
				nodes.forEach(function (node) {
					if (!node || node.is_online === false || node.status === 'offline') return;
					addMeshEndpoint(node.remote_url || node.endpoint || node.node_url || node.url);
				});
			} catch (_) {}
		}
	}

	async function mapWithConcurrency(items, limit, mapper) {
		var results = new Array(items.length);
		var nextIndex = 0;
		async function worker() {
			while (nextIndex < items.length) {
				var index = nextIndex++;
				results[index] = await mapper(items[index], index);
			}
		}
		var workerCount = Math.min(Math.max(1, limit), items.length);
		await Promise.all(Array.from({ length: workerCount }, worker));
		return results;
	}

	async function probeLocalNode() {
		if (localNodeChecked) return localNodeEndpoint;
		if (localNodeCheckingPromise) return localNodeCheckingPromise;

		localNodeCheckingPromise = (async function () {
			var isLocalHost = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
			if (isLocalHost) {
				localNodeEndpoint = window.location.origin;
				addMeshEndpoint(localNodeEndpoint);
				localNodeChecked = true;
				return localNodeEndpoint;
			}

			// Probe local appliance on port 8080 (Zero router configuration required - loopback P2P)
			var candidates = ['http://127.0.0.1:8080', 'http://localhost:8080'];
			for (var i = 0; i < candidates.length; i++) {
				var candidate = candidates[i];
				try {
					var controller = new AbortController();
					var timer = setTimeout(function () { controller.abort(); }, 600);
					var resp = await originalFetch(candidate + '/webui/props', {
						signal: controller.signal,
						mode: 'cors',
						cache: 'no-store'
					});
					clearTimeout(timer);
					if (resp.ok) {
						localNodeEndpoint = candidate;
						addMeshEndpoint(candidate);
						console.log('[ComputeMesh] Auto-discovered local GPU node at ' + candidate + ' (P2P direct loopback mode)');
						break;
					}
				} catch (_) {}
			}
			await discoverFleetEndpoints();
			localNodeChecked = true;
			return localNodeEndpoint;
		})();

		return localNodeCheckingPromise;
	}

	function modalitiesFor(model) {
		if (model && Array.isArray(model.modalities)) return model.modalities;
		var id = String(model && model.id || '').toLowerCase();
		var modalities = ['text'];
		if (/(^|[-_./])(vl|vision)([-_./]|$)|llava|moondream/.test(id)) modalities.push('vision');
		if (/audio|omni|whisper/.test(id)) modalities.push('audio');
		if (/video/.test(id)) modalities.push('video');
		return modalities;
	}

	function modelParameterBillions(model) {
		var values = [
			model && model.parameter_size,
			model && model.details && model.details.parameter_size,
			model && model.meta && model.meta.parameter_size,
			model && model.id
		];
		var best = 0;
		values.forEach(function (value) {
			var match = String(value || '').match(/(\d+(?:\.\d+)?)\s*b(?:illion)?\b/i);
			if (match) best = Math.max(best, Number(match[1]) || 0);
		});
		return best;
	}

	function compareModels(left, right) {
		function score(model) {
			var status = String(model && model.status && (model.status.value || model.status) || model && model.availability || '').toLowerCase();
			var capabilities = Array.isArray(model && model.capabilities) ? model.capabilities : [];
			return modelParameterBillions(model) * 1000 +
				(status === 'loaded' || status === 'available_warm' ? 100 : 0) +
				(capabilities.includes('tools') || capabilities.includes('tool_calling') ? 10 : 0);
		}
		return score(right) - score(left) || String(left.id).localeCompare(String(right.id));
	}

	function applyCapabilities(model) {
		var modalities = modalitiesFor(model);
		var root = document.documentElement;
		root.classList.toggle('cm-model-no-vision', !modalities.includes('vision'));
		root.classList.toggle('cm-model-no-audio', !modalities.includes('audio'));
		root.classList.toggle('cm-model-no-video', !modalities.includes('video'));
		return modalities;
	}

	function currentModel() {
		return selectedModel;
	}

	function isCompletionUrl(input) {
		var rawUrl = typeof input === 'string' ? input : input && input.url;
		if (!rawUrl) return false;
		try {
			var path = new URL(rawUrl, window.location.href).pathname.replace(/\/$/, '');
			return /(?:^|\/)(?:v1\/)?(?:chat\/completions|completions|completion)$/.test(path);
		} catch (_) {
			return false;
		}
	}

	function isPropsUrl(input) {
		var rawUrl = typeof input === 'string' ? input : input && input.url;
		if (!rawUrl) return false;
		try {
			return /(?:^|\/)(?:webui\/)?(?:api\/)?(?:v1\/)?props$/.test(new URL(rawUrl, window.location.href).pathname.replace(/\/$/, ''));
		} catch (_) {
			return false;
		}
	}

	var modelInfoLabels = {
		de: { model: 'Modell', path: 'Dateipfad', context: 'Kontextgroesse', training: 'Trainingskontext', size: 'Modellgroesse', parameters: 'Parameter', embedding: 'Embedding-Groesse', vocabulary: 'Vokabulargroesse', vocabType: 'Vokabulartyp', slots: 'Parallele Slots', modalities: 'Modalitaeten', build: 'Build-Info' },
		en: { model: 'Model', path: 'File path', context: 'Context size', training: 'Training context', size: 'Model size', parameters: 'Parameters', embedding: 'Embedding size', vocabulary: 'Vocabulary size', vocabType: 'Vocabulary type', slots: 'Parallel slots', modalities: 'Modalities', build: 'Build info' },
		fr: { model: 'Modèle', path: 'Chemin du fichier', context: 'Taille du contexte', training: 'Contexte d\'entraînement', size: 'Taille du modèle', parameters: 'Paramètres', embedding: 'Taille de l\'embedding', vocabulary: 'Taille du vocabulaire', vocabType: 'Type de vocabulaire', slots: 'Emplacements parallèles', modalities: 'Modalités', build: 'Informations de build' },
		es: { model: 'Modelo', path: 'Ruta del archivo', context: 'Tamaño del contexto', training: 'Contexto de entrenamiento', size: 'Tamaño del modelo', parameters: 'Parámetros', embedding: 'Tamaño del embedding', vocabulary: 'Tamaño del vocabulario', vocabType: 'Tipo de vocabulario', slots: 'Slots paralelos', modalities: 'Modalidades', build: 'Información de compilación' },
		it: { model: 'Modello', path: 'Percorso file', context: 'Dimensione contesto', training: 'Contesto di addestramento', size: 'Dimensione modello', parameters: 'Parametri', embedding: 'Dimensione embedding', vocabulary: 'Dimensione vocabolario', vocabType: 'Tipo di vocabolario', slots: 'Slot paralleli', modalities: 'Modalità', build: 'Informazioni build' },
		'pt-BR': { model: 'Modelo', path: 'Caminho do arquivo', context: 'Tamanho do contexto', training: 'Contexto de treinamento', size: 'Tamanho do modelo', parameters: 'Parâmetros', embedding: 'Tamanho do embedding', vocabulary: 'Tamanho do vocabulário', vocabType: 'Tipo de vocabulário', slots: 'Slots paralelos', modalities: 'Modalidades', build: 'Informações da compilação' },
		nl: { model: 'Model', path: 'Bestandspad', context: 'Contextgrootte', training: 'Trainingscontext', size: 'Modelgrootte', parameters: 'Parameters', embedding: 'Embeddinggrootte', vocabulary: 'Woorden­schatgrootte', vocabType: 'Woorden­schattype', slots: 'Parallelle slots', modalities: 'Modaliteiten', build: 'Buildinformatie' },
		pl: { model: 'Model', path: 'Sciezka pliku', context: 'Rozmiar kontekstu', training: 'Kontekst treningowy', size: 'Rozmiar modelu', parameters: 'Parametry', embedding: 'Rozmiar embeddingu', vocabulary: 'Rozmiar slownika', vocabType: 'Typ slownika', slots: 'Sloty równolegle', modalities: 'Modalnosci', build: 'Informacje o kompilacji' },
		tr: { model: 'Model', path: 'Dosya yolu', context: 'Baglam boyutu', training: 'Egitim baglami', size: 'Model boyutu', parameters: 'Parametreler', embedding: 'Embedding boyutu', vocabulary: 'Kelime dagarcigi boyutu', vocabType: 'Kelime dagarcigi türü', slots: 'Paralel yuvalar', modalities: 'Modaliteler', build: 'Derleme bilgisi' }
	};

	function modelInfoLocale() {
		var raw = String(document.documentElement.lang || navigator.language || 'en').replace('_', '-');
		return modelInfoLabels[raw] || modelInfoLabels[raw.split('-')[0]] || modelInfoLabels.en;
	}

	function findModelInfoDialog() {
		var headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"], body *'));
		var title = headings.find(function (node) {
			var text = (node.textContent || '').trim();
			return node.children.length === 0 && /^(current model details and capabilities|model information)$/i.test(text);
		});
		if (!title) return null;
		return title.closest('[role="dialog"]') || title.parentElement && title.parentElement.parentElement && title.parentElement.parentElement.parentElement || title.parentElement;
	}

	function modelInfoModel() {
		if (selectedModel) return selectedModel;
		if (models.length) return models[0];
		var id = '';
		try { id = localStorage.getItem(STORAGE_KEY) || ''; } catch (_) {}
		return { id: id || 'qwen2.5:3b', name: id || 'qwen2.5:3b' };
	}

	function repairModelInfoDialogLayout(dialog) {
		// Android WebView can resolve the bundled 80dvh utility to 0px. Use the
		// actual viewport height and keep the dialog itself scrollable instead.
		var maxHeight = Math.max(240, (window.innerHeight || 660) - 24);
		dialog.style.setProperty('max-height', maxHeight + 'px', 'important');
		dialog.style.setProperty('height', 'auto', 'important');
		dialog.style.setProperty('overflow-y', 'auto', 'important');
		dialog.style.setProperty('overflow-x', 'hidden', 'important');
		dialog.style.setProperty('min-width', '0', 'important');
		dialog.style.setProperty('box-sizing', 'border-box', 'important');
		if (!dialog.dataset.cmInitialScrollReset) {
			dialog.dataset.cmInitialScrollReset = 'true';
			dialog.scrollTop = 0;
		}

		Array.from(dialog.querySelectorAll('table')).forEach(function (table) {
			table.style.tableLayout = 'fixed';
			table.style.width = '100%';
			table.style.maxWidth = '100%';
		});
		Array.from(dialog.querySelectorAll('th, td')).forEach(function (cell) {
			cell.style.minWidth = '0';
			cell.style.maxWidth = '100%';
			cell.style.whiteSpace = 'normal';
			cell.style.overflowWrap = 'anywhere';
			cell.style.wordBreak = 'break-word';
		});
		Array.from(dialog.querySelectorAll('th:first-child, td:first-child')).forEach(function (cell) {
			cell.style.width = '42%';
		});
		Array.from(dialog.querySelectorAll('th:nth-child(2), td:nth-child(2)')).forEach(function (cell) {
			cell.style.width = '58%';
		});
		Array.from(dialog.querySelectorAll('pre, code')).forEach(function (code) {
			code.style.display = 'block';
			code.style.width = '100%';
			code.style.maxWidth = '100%';
			code.style.maxHeight = '220px';
			code.style.boxSizing = 'border-box';
			code.style.whiteSpace = 'pre-wrap';
			code.style.overflowWrap = 'anywhere';
			code.style.overflowX = 'auto';
			code.style.fontSize = '11px';
		});
	}

	function modelInfoValue(props, key) {
		if (props && props[key] !== undefined && props[key] !== null && String(props[key]).trim() !== '') return props[key];
		return '';
	}

	function formatModelBytes(value) {
		var bytes = Number(value);
		if (!Number.isFinite(bytes) || bytes <= 0) return '';
		var units = ['B', 'KB', 'MB', 'GB', 'TB'];
		var unit = 0;
		while (bytes >= 1024 && unit < units.length - 1) { bytes /= 1024; unit++; }
		return (unit === 0 ? Math.round(bytes) : bytes.toFixed(1)) + ' ' + units[unit];
	}

	function formatModelParameters(value) {
		var parameters = Number(value);
		if (!Number.isFinite(parameters) || parameters <= 0) return '';
		if (parameters >= 1000000000) return (parameters / 1000000000).toFixed(parameters >= 10000000000 ? 0 : 1).replace('.0', '') + 'B';
		if (parameters >= 1000000) return (parameters / 1000000).toFixed(1).replace('.0', '') + 'M';
		return String(parameters);
	}

	function appendModelInfoRow(container, label, value) {
		if (value === '' || value === null || value === undefined) return;
		var row = document.createElement('div');
		row.style.cssText = 'display:flex;gap:16px;justify-content:space-between;align-items:flex-start;padding:8px 0;border-bottom:1px solid rgba(148,163,184,.14);font-size:13px;line-height:1.35;';
		var name = document.createElement('span');
		name.style.cssText = 'font-weight:600;color:rgba(226,232,240,.78);flex:0 0 42%;';
		name.textContent = label;
		var detail = document.createElement('span');
		detail.style.cssText = 'color:rgba(241,245,249,.96);text-align:right;overflow-wrap:anywhere;';
		detail.textContent = String(value);
		row.append(name, detail);
		container.append(row);
	}

	async function renderModelInfoFallback() {
		var dialog = findModelInfoDialog();
		if (!dialog) return;
		repairModelInfoDialogLayout(dialog);
		var fallback = dialog.querySelector('#cm-model-info-fallback');
		if (/file path|context size|dateipfad|kontextgroesse/i.test(dialog.textContent || '') && !fallback) return;
		var model = modelInfoModel();
		if (!model) return;
		var modelId = String(model.id || '').trim();
		if (!modelId) return;
		if (fallback) return;
		if (modelInfoFallbackPromise && modelInfoFallbackModelId === modelId) return;
		modelInfoFallbackModelId = modelId;
		modelInfoFallbackPromise = (async function () {
			try {
				var endpoint = model.__sourceEndpoint && model.__sourceEndpoint !== window.location.origin ? model.__sourceEndpoint : window.location.origin;
				var propsResponse = await originalFetch(endpoint + '/props?model=' + encodeURIComponent(modelId), { credentials: 'include', cache: 'no-store' });
				if (!propsResponse.ok) return;
				var props = await propsResponse.json();
				var labels = modelInfoLocale();
				var rows = document.createElement('div');
				rows.id = 'cm-model-info-fallback';
				rows.style.cssText = 'margin-top:12px;max-height:58vh;overflow:auto;padding:4px 16px 12px;background:rgba(15,23,42,.42);border-radius:8px;';
				appendModelInfoRow(rows, labels.model, props.model_alias || model.name || modelId);
				appendModelInfoRow(rows, labels.path, modelInfoValue(props, 'model_path') || modelId);
				appendModelInfoRow(rows, labels.context, modelInfoValue(props.default_generation_settings, 'n_ctx') ? props.default_generation_settings.n_ctx + ' tokens' : '');
				appendModelInfoRow(rows, labels.training, modelInfoValue(props, 'n_ctx_train') ? props.n_ctx_train + ' tokens' : '');
				appendModelInfoRow(rows, labels.size, formatModelBytes(props.size));
				appendModelInfoRow(rows, labels.parameters, formatModelParameters(props.n_params) || (model.meta && model.meta.parameter_size) || '');
				appendModelInfoRow(rows, labels.embedding, modelInfoValue(props, 'n_embd'));
				appendModelInfoRow(rows, labels.vocabulary, modelInfoValue(props, 'n_vocab') ? props.n_vocab + ' tokens' : '');
				appendModelInfoRow(rows, labels.vocabType, modelInfoValue(props, 'vocab_type'));
				appendModelInfoRow(rows, labels.slots, modelInfoValue(props, 'total_slots'));
				var modalities = props.modalities || model.modalities;
				if (modalities && typeof modalities === 'object') {
					var modalityNames = Object.keys(modalities).filter(function (key) { return modalities[key]; }).map(function (key) { return key; });
					appendModelInfoRow(rows, labels.modalities, modalityNames.join(', '));
				}
				appendModelInfoRow(rows, labels.build, modelInfoValue(props, 'build_info'));
				if (!dialog.querySelector('#cm-model-info-fallback')) dialog.append(rows);
			} catch (_) {}
		})().finally(function () { modelInfoFallbackPromise = null; });
		await modelInfoFallbackPromise;
	}

	function updateExecutionStatus(metadata) {
		if (!metadata || typeof metadata !== 'object') return;
		lastExecution = metadata;
		var status = document.getElementById('cm-execution-status');
		if (!status && document.body) {
			status = document.createElement('div');
			status.id = 'cm-execution-status';
			status.setAttribute('aria-live', 'polite');
			status.style.cssText = 'position: fixed; right: 16px; top: max(64px, env(safe-area-inset-top, 0px)); bottom: auto; z-index: 40; max-width: min(420px, calc(100vw - 32px)); padding: 6px 10px; border: 1px solid rgba(161, 161, 170, 0.24); border-radius: 6px; background: rgba(24, 24, 27, 0.94); color: #a1a1aa; font-size: 11px; overflow-wrap: anywhere; pointer-events: none;';
			document.body.append(status);
		}
		if (!status) return;
		var model = String(metadata.model_id || metadata.model || '').trim();
		var nodeIds = Array.isArray(metadata.provider_node_ids) ? metadata.provider_node_ids.filter(Boolean) : [];
		var nodeLabel = nodeIds.length ? nodeIds.join(', ') : executionStatusText('unspecified');
		status.textContent = executionStatusText('last') + ': ' + (model || executionStatusText('unknown')) + ' · Node: ' + nodeLabel;
		status.title = metadata.execution_id ? executionStatusText('id') + ': ' + metadata.execution_id : executionStatusText('evidence');
		status.hidden = false;
	}

	function ensureAgentSessionPanel() {
		if (agentSessionPanel || !document.body) return;
		agentSessionPanel = document.createElement('section');
		agentSessionPanel.id = 'cm-agent-session-panel';
		agentSessionPanel.setAttribute('aria-live', 'polite');
		agentSessionPanel.style.cssText = 'position:fixed;right:16px;top:max(104px,calc(env(safe-area-inset-top, 0px) + 104px));z-index:39;width:min(360px,calc(100vw - 32px));max-height:min(72vh,560px);overflow:auto;box-sizing:border-box;padding:8px 10px;border:1px solid rgba(56,189,248,.28);border-radius:8px;background:rgba(15,23,42,.96);color:#cbd5e1;box-shadow:0 8px 28px rgba(0,0,0,.28);font-size:11px;pointer-events:auto;';
		var title = document.createElement('div');
		title.textContent = agentSessionText('title');
		title.style.cssText = 'font-weight:600;margin-bottom:5px;overflow-wrap:anywhere;';
		agentSessionSelect = document.createElement('select');
		agentSessionSelect.setAttribute('aria-label', agentSessionText('select'));
		agentSessionSelect.style.cssText = 'display:block;width:100%;min-width:0;height:32px;box-sizing:border-box;padding:0 8px;border:1px solid rgba(148,163,184,.35);border-radius:6px;background:#111827;color:#f8fafc;font-size:12px;';
		agentSessionSelect.addEventListener('change', function () {
			agentSessionId = agentSessionSelect.value;
			agentSessionPollBlocked = false;
			restoreAgentSessionCursor(agentSessionId);
			agentSessionLastEvent = '';
			agentSessionActivity = [];
			agentArtifacts = [];
			renderAgentSessionPanel();
			refreshAgentArtifacts();
			pollAgentSessionEvents();
		});
		agentTaskPrompt = document.createElement('textarea');
		agentTaskPrompt.rows = 2;
		agentTaskPrompt.setAttribute('aria-label', agentSessionText('prompt'));
		agentTaskPrompt.placeholder = agentSessionText('prompt');
		agentTaskPrompt.style.cssText = 'display:block;width:100%;min-height:54px;box-sizing:border-box;margin-top:7px;padding:7px 8px;border:1px solid rgba(148,163,184,.35);border-radius:6px;background:#111827;color:#f8fafc;font:inherit;line-height:1.35;resize:vertical;';
		agentTaskPrompt.addEventListener('input', renderAgentTaskControls);
		var actionRow = document.createElement('div');
		actionRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;margin-top:6px;';
		agentTaskCreateButton = document.createElement('button');
		agentTaskCreateButton.type = 'button';
		agentTaskCreateButton.textContent = '+ ' + agentSessionText('create');
		agentTaskCreateButton.style.cssText = 'flex:1 1 140px;min-height:30px;padding:5px 8px;border:1px solid rgba(56,189,248,.45);border-radius:6px;background:#0e7490;color:#f8fafc;font-size:11px;cursor:pointer;';
		agentTaskCreateButton.addEventListener('click', function () { submitAgentTask('create'); });
		agentTaskContinueButton = document.createElement('button');
		agentTaskContinueButton.type = 'button';
		agentTaskContinueButton.textContent = '↻ ' + agentSessionText('continueTask');
		agentTaskContinueButton.style.cssText = 'flex:1 1 110px;min-height:30px;padding:5px 8px;border:1px solid rgba(148,163,184,.35);border-radius:6px;background:#1f2937;color:#f8fafc;font-size:11px;cursor:pointer;';
		agentTaskContinueButton.addEventListener('click', function () { submitAgentTask('continue'); });
		actionRow.append(agentTaskCreateButton, agentTaskContinueButton);
		var controlRow = document.createElement('div');
		controlRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;margin-top:5px;';
		agentTaskPauseButton = document.createElement('button');
		agentTaskPauseButton.type = 'button';
		agentTaskPauseButton.textContent = '⏸ ' + agentControlText('pause');
		agentTaskPauseButton.setAttribute('aria-label', agentControlText('pause'));
		agentTaskPauseButton.style.cssText = 'flex:1 1 90px;min-height:30px;padding:5px 8px;border:1px solid rgba(245,158,11,.45);border-radius:6px;background:#422006;color:#fde68a;font-size:11px;cursor:pointer;';
		agentTaskPauseButton.addEventListener('click', function () { controlAgentSession('pause'); });
		agentTaskResumeButton = document.createElement('button');
		agentTaskResumeButton.type = 'button';
		agentTaskResumeButton.textContent = '▶ ' + agentControlText('resume');
		agentTaskResumeButton.setAttribute('aria-label', agentControlText('resume'));
		agentTaskResumeButton.style.cssText = 'flex:1 1 90px;min-height:30px;padding:5px 8px;border:1px solid rgba(34,197,94,.45);border-radius:6px;background:#14532d;color:#bbf7d0;font-size:11px;cursor:pointer;';
		agentTaskResumeButton.addEventListener('click', function () { controlAgentSession('resume'); });
		agentTaskCancelButton = document.createElement('button');
		agentTaskCancelButton.type = 'button';
		agentTaskCancelButton.textContent = '× ' + agentControlText('cancel');
		agentTaskCancelButton.setAttribute('aria-label', agentControlText('cancel'));
		agentTaskCancelButton.style.cssText = 'flex:1 1 90px;min-height:30px;padding:5px 8px;border:1px solid rgba(248,113,113,.45);border-radius:6px;background:#450a0a;color:#fecaca;font-size:11px;cursor:pointer;';
		agentTaskCancelButton.addEventListener('click', function () { controlAgentSession('cancel'); });
		controlRow.append(agentTaskPauseButton, agentTaskResumeButton, agentTaskCancelButton);
		agentTaskActionMessage = document.createElement('div');
		agentTaskActionMessage.style.cssText = 'display:none;margin-top:5px;line-height:1.35;overflow-wrap:anywhere;';
		agentSessionStatus = document.createElement('div');
		agentSessionStatus.style.cssText = 'margin-top:5px;line-height:1.35;overflow-wrap:anywhere;';
		agentSessionActivityPanel = document.createElement('div');
		agentSessionActivityPanel.style.cssText = 'margin-top:8px;padding-top:7px;border-top:1px solid rgba(148,163,184,.2);max-height:132px;overflow:auto;';
		agentApprovalPanel = document.createElement('div');
		agentApprovalPanel.style.cssText = 'margin-top:8px;padding-top:7px;border-top:1px solid rgba(148,163,184,.2);';
		agentArtifactPanel = document.createElement('div');
		agentArtifactPanel.style.cssText = 'margin-top:8px;padding-top:7px;border-top:1px solid rgba(148,163,184,.2);';
		agentSessionPanel.append(title, agentSessionSelect, agentTaskPrompt, actionRow, controlRow, agentTaskActionMessage, agentSessionStatus, agentSessionActivityPanel, agentApprovalPanel, agentArtifactPanel);
		document.body.appendChild(agentSessionPanel);
	}

	function renderAgentArtifacts() {
		if (!agentArtifactPanel) return;
		agentArtifactPanel.replaceChildren();
		var heading = document.createElement('div');
		heading.textContent = agentArtifactText('title');
		heading.style.cssText = 'font-weight:600;margin-bottom:5px;overflow-wrap:anywhere;';
		agentArtifactPanel.appendChild(heading);
		if (!agentArtifacts.length) {
			var empty = document.createElement('div');
			empty.textContent = agentArtifactText('empty');
			empty.style.cssText = 'opacity:.72;line-height:1.35;';
			agentArtifactPanel.appendChild(empty);
			return;
		}
		agentArtifacts.forEach(function (artifact) {
			var row = document.createElement('div');
			row.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:5px;';
			var name = document.createElement('span');
			name.textContent = String(artifact.name || artifact.ref_id || 'artifact');
			name.style.cssText = 'flex:1 1 130px;min-width:0;overflow-wrap:anywhere;';
			var link = document.createElement('a');
			link.href = '/v1/agents/artifacts/' + encodeURIComponent(String(artifact.ref_id || ''));
			link.download = String(artifact.name || 'artifact');
			link.textContent = agentArtifactText('download');
			link.setAttribute('aria-label', agentArtifactText('download') + ' ' + name.textContent);
			link.style.cssText = 'min-height:28px;box-sizing:border-box;padding:5px 8px;border:1px solid rgba(56,189,248,.4);border-radius:6px;color:#67e8f9;text-decoration:none;font-size:11px;';
			row.append(name, link);
			agentArtifactPanel.appendChild(row);
		});
	}

	async function refreshAgentArtifacts() {
		if (!agentSessionId) return;
		try {
			var response = await originalFetch('/v1/agents/sessions/' + encodeURIComponent(agentSessionId) + '/artifacts', { credentials: 'include', cache: 'no-store' });
			if (!response.ok) return;
			var payload = await response.json();
			agentArtifacts = Array.isArray(payload && payload.artifacts) ? payload.artifacts : [];
			renderAgentArtifacts();
		} catch (_) {}
	}

	function renderAgentTaskControls() {
		if (!agentTaskPrompt || !agentTaskCreateButton || !agentTaskContinueButton || !agentTaskPauseButton || !agentTaskResumeButton || !agentTaskCancelButton) return;
		var hasPrompt = Boolean(String(agentTaskPrompt.value || '').trim());
		var selected = agentSessions.find(function (session) { return String(session.session_id) === agentSessionId; });
		var status = String(selected && selected.status || '').toLowerCase();
		var canContinue = Boolean(selected && status === 'ready');
		agentTaskCreateButton.disabled = agentTaskBusy || !hasPrompt || !selectedModel;
		agentTaskContinueButton.disabled = agentTaskBusy || !hasPrompt || !canContinue;
		var canPause = Boolean(selected && ['creating', 'ready', 'running', 'waiting_for_tool', 'waiting_for_approval', 'waiting_for_subagents', 'compacting', 'resuming'].includes(status));
		var canResume = Boolean(selected && ['paused', 'failed'].includes(status));
		var canCancel = Boolean(selected && !agentSessionTerminal(status) && status !== 'paused');
		agentTaskPauseButton.hidden = !canPause;
		agentTaskResumeButton.hidden = !canResume;
		agentTaskCancelButton.hidden = !canCancel;
		agentTaskPauseButton.disabled = agentTaskBusy;
		agentTaskResumeButton.disabled = agentTaskBusy;
		agentTaskCancelButton.disabled = agentTaskBusy;
		agentTaskCreateButton.style.opacity = agentTaskCreateButton.disabled ? '.55' : '1';
		agentTaskContinueButton.style.opacity = agentTaskContinueButton.disabled ? '.55' : '1';
	}

	function setAgentTaskMessage(text, isError) {
		if (!agentTaskActionMessage) return;
		agentTaskActionMessage.textContent = String(text || '');
		agentTaskActionMessage.style.display = text ? 'block' : 'none';
		agentTaskActionMessage.style.color = isError ? '#fca5a5' : '#67e8f9';
	}

	async function submitAgentTask(mode) {
		if (agentTaskBusy || !agentTaskPrompt || !selectedModel) return;
		var prompt = String(agentTaskPrompt.value || '').trim();
		if (!prompt) return;
		var selected = agentSessions.find(function (session) { return String(session.session_id) === agentSessionId; });
		if (mode === 'continue' && (!selected || String(selected.status || '').toLowerCase() !== 'ready')) return;
		agentTaskBusy = true;
		setAgentTaskMessage('', false);
		renderAgentTaskControls();
		try {
			var endpoint = mode === 'continue'
				? '/v1/agents/sessions/' + encodeURIComponent(agentSessionId) + '/turns'
				: '/v1/agents/sessions';
			var body = mode === 'continue'
				? { input: prompt }
				: { agent_id: 'computemesh.agent', agent_version: '1', model: String(selectedModel.id), input: prompt, environment_type: 'mesh' };
			var response = await originalFetch(endpoint, {
				method: 'POST',
				credentials: 'include',
				cache: 'no-store',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});
			var payload = {};
			try { payload = await response.json(); } catch (_) {}
			if (!response.ok) throw new Error((payload.error && payload.error.message) || agentSessionText('taskError'));
			if (mode === 'create' && payload.session && payload.session.session_id) {
				agentSessionId = String(payload.session.session_id);
				agentStorageSet('cm_agent_session_id', agentSessionId);
				restoreAgentSessionCursor(agentSessionId);
			}
			agentTaskPrompt.value = '';
			setAgentTaskMessage(agentSessionText(mode === 'create' ? 'taskCreated' : 'turnQueued'), false);
			await initializeAgentSessions();
		} catch (error) {
			setAgentTaskMessage(error && error.message ? error.message : agentSessionText('taskError'), true);
		} finally {
			agentTaskBusy = false;
			renderAgentTaskControls();
		}
	}

	async function controlAgentSession(action) {
		if (agentTaskBusy || !agentSessionId) return;
		agentTaskBusy = true;
		setAgentTaskMessage('', false);
		renderAgentTaskControls();
		try {
			var response = await originalFetch('/v1/agents/sessions/' + encodeURIComponent(agentSessionId) + '/control', {
				method: 'POST',
				credentials: 'include',
				cache: 'no-store',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ action: action })
			});
			var payload = {};
			try { payload = await response.json(); } catch (_) {}
			if (!response.ok) throw new Error((payload.error && payload.error.message) || agentControlLabels[agentSessionLocale()].controlError);
			setAgentTaskMessage(agentControlText('controlQueued'), false);
			await initializeAgentSessions();
		} catch (error) {
			setAgentTaskMessage(error && error.message ? error.message : agentControlText('controlError'), true);
		} finally {
			agentTaskBusy = false;
			renderAgentTaskControls();
		}
	}

	async function resolveAgentApproval(approvalId, decision) {
		try {
			var response = await originalFetch('/v1/agents/approvals/' + encodeURIComponent(String(approvalId)), {
				method: 'POST',
				credentials: 'include',
				cache: 'no-store',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ decision: decision })
			});
			if (!response.ok) throw new Error('approval request failed');
			await refreshAgentApprovals();
		} catch (_) {
			agentSessionLastEvent = agentSessionText('approvalError');
			renderAgentSessionPanel();
		}
	}

	function renderAgentSessionActivity() {
		if (!agentSessionActivityPanel) return;
		agentSessionActivityPanel.replaceChildren();
		var heading = document.createElement('div');
		heading.textContent = agentSessionActivityText('title');
		heading.style.cssText = 'font-weight:600;margin-bottom:5px;overflow-wrap:anywhere;';
		agentSessionActivityPanel.appendChild(heading);
		if (!agentSessionActivity.length) {
			var empty = document.createElement('div');
			empty.textContent = agentSessionActivityText('empty');
			empty.style.cssText = 'opacity:.72;line-height:1.35;';
			agentSessionActivityPanel.appendChild(empty);
			return;
		}
		agentSessionActivity.slice().reverse().forEach(function (entry) {
			var row = document.createElement('div');
			row.textContent = entry.label;
			row.style.cssText = 'padding:3px 0;line-height:1.3;overflow-wrap:anywhere;';
			agentSessionActivityPanel.appendChild(row);
		});
	}

	function renderAgentApprovals() {
		if (!agentApprovalPanel) return;
		agentApprovalPanel.replaceChildren();
		var heading = document.createElement('div');
		heading.textContent = agentSessionText('approvals');
		heading.style.cssText = 'font-weight:600;margin-bottom:5px;overflow-wrap:anywhere;';
		agentApprovalPanel.appendChild(heading);
		if (!agentApprovals.length) {
			var empty = document.createElement('div');
			empty.textContent = agentSessionText('noApprovals');
			empty.style.cssText = 'opacity:.72;line-height:1.35;';
			agentApprovalPanel.appendChild(empty);
			return;
		}
		agentApprovals.forEach(function (approval) {
			var row = document.createElement('div');
			row.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;align-items:center;margin-top:5px;';
			var label = document.createElement('span');
			label.textContent = String(approval.tool_id || approval.call_id || 'Tool') + ' · ' + String(approval.status || 'pending');
			label.style.cssText = 'flex:1 1 130px;min-width:0;overflow-wrap:anywhere;';
			row.appendChild(label);
			if (String(approval.status) === 'pending') {
				['approved', 'rejected'].forEach(function (decision) {
					var button = document.createElement('button');
					button.type = 'button';
					button.textContent = decision === 'approved' ? '✓ ' + agentSessionText('approve') : '× ' + agentSessionText('reject');
					button.setAttribute('aria-label', button.textContent);
					button.style.cssText = 'min-height:30px;padding:5px 8px;border:1px solid rgba(148,163,184,.35);border-radius:6px;background:#1f2937;color:#f8fafc;font-size:11px;cursor:pointer;';
					button.addEventListener('click', function () { button.disabled = true; resolveAgentApproval(approval.approval_id, decision); });
					row.appendChild(button);
				});
			}
			agentApprovalPanel.appendChild(row);
		});
	}

	function renderAgentSessionPanel() {
		ensureAgentSessionPanel();
		if (!agentSessionPanel || !agentSessionSelect || !agentSessionStatus) return;
		agentSessionPanel.hidden = false;
		agentSessionSelect.replaceChildren();
		if (!agentSessions.length) {
			agentSessionSelect.hidden = true;
			agentSessionStatus.textContent = agentSessionText('idle');
			renderAgentSessionActivity();
			renderAgentApprovals();
			agentArtifacts = [];
			renderAgentArtifacts();
			renderAgentTaskControls();
			return;
		}
		agentSessionSelect.hidden = false;
		agentSessions.forEach(function (session) {
			var option = document.createElement('option');
			option.value = String(session.session_id || '');
			option.textContent = String(session.agent_id || session.session_id || 'Agent') + ' · ' + agentSessionStatusText(session.status);
			agentSessionSelect.appendChild(option);
		});
		agentSessionSelect.value = agentSessionId;
		if (agentSessionSelect.value !== agentSessionId && agentSessionSelect.options.length) {
			agentSessionId = agentSessionSelect.options[0].value;
			restoreAgentSessionCursor(agentSessionId);
		}
		var selected = agentSessions.find(function (session) { return String(session.session_id) === agentSessionId; });
		var status = selected ? agentSessionStatusText(selected.status) : agentSessionText('unavailable');
		agentSessionStatus.textContent = agentSessionLastEvent ? status + ' · ' + agentSessionLastEvent : status;
		renderAgentSessionActivity();
		renderAgentApprovals();
		renderAgentArtifacts();
		renderAgentTaskControls();
	}

	async function refreshAgentApprovals() {
		try {
			var response = await originalFetch('/v1/agents/approvals?status=pending&limit=20', { credentials: 'include', cache: 'no-store' });
			if (!response.ok) return;
			var payload = await response.json();
			agentApprovals = Array.isArray(payload && payload.approvals) ? payload.approvals : [];
			renderAgentSessionPanel();
		} catch (_) {}
	}

	function describeAgentSessionEvent(event) {
		var type = String(event && event.event_type || '').toLowerCase();
		var payload = event && event.payload && typeof event.payload === 'object' ? event.payload : {};
		if (type === 'session.status_changed' && payload.to) return agentSessionStatusText(payload.to);
		if (type === 'approval.required') return agentSessionStatusText('waiting_for_approval');
		if (type.includes('tool.started') || type.includes('inference.started')) return agentSessionStatusText('running');
		if (type.includes('completed')) return agentSessionStatusText('completed');
		if (type.includes('failed')) return agentSessionStatusText('failed');
		return agentSessionText('waiting');
	}

	async function pollAgentSessionEvents() {
		if (!agentSessionId || agentSessionPollInFlight || agentSessionPollBlocked) return;
		var selected = agentSessions.find(function (session) { return String(session.session_id) === agentSessionId; });
		if (selected && agentSessionTerminal(selected.status) && agentSessionLastEvent) return;
		agentSessionPollInFlight = true;
		try {
			var endpoint = '/v1/agents/sessions/' + encodeURIComponent(agentSessionId) + '/events?after_sequence=' + encodeURIComponent(String(agentSessionCursor)) + '&limit=100&wait_seconds=5';
			var response = await originalFetch(endpoint, { credentials: 'include', cache: 'no-store' });
			if (!response.ok) {
				if (response.status === 401 || response.status === 403 || response.status === 404) {
					agentSessionPollBlocked = true;
					agentSessionLastEvent = agentSessionText('unavailable');
					renderAgentSessionPanel();
				}
				return;
			}
			var payload = await response.json();
			var events = Array.isArray(payload && payload.events) ? payload.events : [];
			if (payload && payload.session) {
				var index = agentSessions.findIndex(function (session) { return String(session.session_id) === agentSessionId; });
				if (index >= 0) agentSessions[index] = Object.assign({}, agentSessions[index], payload.session);
				saveAgentSessionCache();
			}
			if (events.length) {
				agentSessionLastEvent = describeAgentSessionEvent(events[events.length - 1]);
				events.forEach(function (event) {
					agentSessionActivity.push({ label: describeAgentSessionEvent(event) });
				});
				agentSessionActivity = agentSessionActivity.slice(-12);
			}
			if (payload && Number.isFinite(Number(payload.next_sequence))) {
				agentSessionCursor = Math.max(agentSessionCursor, Number(payload.next_sequence));
				saveAgentSessionCursor();
			}
			await refreshAgentApprovals();
			await refreshAgentArtifacts();
			renderAgentSessionPanel();
		} catch (_) {
			agentSessionLastEvent = agentSessionText('unavailable');
			renderAgentSessionPanel();
		} finally {
			agentSessionPollInFlight = false;
			var current = agentSessions.find(function (session) { return String(session.session_id) === agentSessionId; });
			if (agentSessionId && (!current || !agentSessionTerminal(current.status))) {
				clearTimeout(agentSessionPollTimer);
				agentSessionPollTimer = setTimeout(pollAgentSessionEvents, 1500);
			}
		}
	}

	async function initializeAgentSessions() {
		ensureAgentSessionPanel();
		var cachedSessions = restoreAgentSessionCache();
		if (!agentSessions.length && cachedSessions.length) {
			agentSessions = cachedSessions;
			var cachedId = String(agentStorageGet('cm_agent_session_id') || '');
			var cachedPreferred = cachedSessions.find(function (session) { return String(session.session_id) === cachedId; }) || cachedSessions.find(function (session) { return !agentSessionTerminal(session.status); }) || cachedSessions[0];
			agentSessionId = String(cachedPreferred.session_id || '');
			restoreAgentSessionCursor(agentSessionId);
			renderAgentSessionPanel();
			pollAgentSessionEvents();
		}
		renderAgentSessionPanel();
		try {
			var response = await originalFetch('/v1/agents/sessions?limit=50', { credentials: 'include', cache: 'no-store' });
			if (!response.ok) {
				if (response.status === 401 || response.status === 403) {
					agentSessions = [];
					agentSessionId = '';
					agentStorageRemove(AGENT_SESSION_CACHE_KEY);
					renderAgentSessionPanel();
				}
				return;
			}
			var payload = await response.json();
			var sessions = Array.isArray(payload && payload.sessions) ? payload.sessions : [];
			if (!sessions.length) {
				agentSessions = [];
				agentStorageRemove(AGENT_SESSION_CACHE_KEY);
				renderAgentSessionPanel();
				return;
			}
			agentSessions = sessions;
			saveAgentSessionCache();
			agentSessionPollBlocked = false;
			var storedId = '';
			storedId = String(agentStorageGet('cm_agent_session_id') || '');
			var preferred = sessions.find(function (session) { return String(session.session_id) === storedId; }) || sessions.find(function (session) { return !agentSessionTerminal(session.status); }) || sessions[0];
			agentSessionId = String(preferred.session_id || '');
			agentStorageSet('cm_agent_session_id', agentSessionId);
			restoreAgentSessionCursor(agentSessionId);
			renderAgentSessionPanel();
			refreshAgentApprovals();
			pollAgentSessionEvents();
		} catch (_) {
			// Agent sessions are optional; the legacy chat UI remains unchanged.
		}
	}

	function observeExecutionPayload(payload) {
		if (payload && typeof payload === 'object' && payload.compute_mesh_execution) {
			updateExecutionStatus(payload.compute_mesh_execution);
		}
	}

	function observeExecutionResponse(response) {
		try {
			var contentType = response.headers.get('content-type') || '';
			if (contentType.includes('application/json')) {
				response.clone().json().then(observeExecutionPayload).catch(function () {});
			} else if (contentType.includes('text/event-stream')) {
				response.clone().text().then(function (text) {
					text.split(/\r?\n/).forEach(function (line) {
						if (!line.startsWith('data: ') || line === 'data: [DONE]') return;
						try { observeExecutionPayload(JSON.parse(line.slice(6))); } catch (_) {}
					});
				}).catch(function () {});
			}
		} catch (_) {}
	}

	function findImageDataUrls(value, found) {
		if (!value || typeof value !== 'object') return;
		Object.keys(value).forEach(function (key) {
			if (typeof value[key] === 'string' && /^data:image\//i.test(value[key])) {
				found.push({ parent: value, key: key, value: value[key] });
			} else {
				findImageDataUrls(value[key], found);
			}
		});
	}

	async function dataUrlToFile(dataUrl, index) {
		var response = await originalFetch(dataUrl);
		var blob = await response.blob();
		var type = blob.type || 'image/jpeg';
		var extension = type === 'image/png' ? '.png' : '.jpg';
		return new File([blob], 'chat-image-' + index + extension, { type: type });
	}

	function fileToDataUrl(file) {
		return new Promise(function (resolve, reject) {
			var reader = new FileReader();
			reader.onload = function () { resolve(String(reader.result || '')); };
			reader.onerror = function () { reject(reader.error || new Error('Unable to read optimized image')); };
			reader.readAsDataURL(file);
		});
	}

	async function fitChatBody(body) {
		var serialized = JSON.stringify(body);
		if (new Blob([serialized]).size <= maxChatRequestBytes) return serialized;

		var imageRefs = [];
		findImageDataUrls(body, imageRefs);
		if (!imageRefs.length) return serialized;

		var encodedImagesSize = imageRefs.reduce(function (total, ref) { return total + ref.value.length; }, 0);
		var nonImageSize = new Blob([serialized]).size - encodedImagesSize;
		if (nonImageSize >= gatewayRequestLimitBytes) {
			throw new Error('The message and conversation history alone exceed the gateway size limit. Shorten the prompt or remove older messages.');
		}
		if (new Blob([serialized]).size <= gatewayRequestLimitBytes && nonImageSize >= maxChatRequestBytes) return serialized;
		var availableEncodedSize = maxChatRequestBytes - nonImageSize - imageRefs.length * 128;
		var perImageBudget = Math.floor(Math.max(0, availableEncodedSize) * 0.74 / imageRefs.length);
		for (var attempt = 0; attempt < 5; attempt++) {
			if (perImageBudget < 32768) break;
			for (var index = 0; index < imageRefs.length; index++) {
				var ref = imageRefs[index];
				var sourceFile = await dataUrlToFile(ref.value, index);
				var optimized = await optimizeImageFile(sourceFile, perImageBudget);
				ref.parent[ref.key] = await fileToDataUrl(optimized);
			}
			serialized = JSON.stringify(body);
			if (new Blob([serialized]).size <= maxChatRequestBytes) return serialized;
			perImageBudget = Math.floor(perImageBudget * 0.72);
		}
		if (new Blob([serialized]).size <= gatewayRequestLimitBytes) return serialized;
		throw new Error('The images could not be reduced enough for this request. Remove an image or use a smaller photo.');
	}

	async function withSelectedModel(bodyText) {
		if (!selectedModel || !bodyText) return null;
		var body;
		try {
			body = JSON.parse(bodyText);
		} catch (_) {
			return null;
		}
		if (!body || typeof body !== 'object' || (!Array.isArray(body.messages) && typeof body.prompt !== 'string')) return null;
		body.model = selectedModel.id;
		return await fitChatBody(body);
	}

	window.fetch = async function (input, init) {
		await probeLocalNode();
		if (isCompletionUrl(input) && modelSelectionReady) await modelSelectionReady;

		if (isPropsUrl(input) && selectedModel) {
			var propsResponse = await originalFetch(input, init);
			if (!propsResponse.ok) return propsResponse;
			try {
				var props = await propsResponse.clone().json();
				props.default_generation_settings = props.default_generation_settings || {};
				props.default_generation_settings.model = selectedModel.id;
				props.model_path = selectedModel.id;
				props.model_alias = displayName(selectedModel);
				var supportedModalities = modalitiesFor(selectedModel);
				props.modalities = {
					vision: supportedModalities.includes('vision'),
					audio: supportedModalities.includes('audio'),
					video: supportedModalities.includes('video')
				};
				var headers = new Headers(propsResponse.headers);
				['content-length', 'content-encoding', 'content-md5', 'etag'].forEach(function (name) { headers.delete(name); });
				return new Response(JSON.stringify(props), {
					status: propsResponse.status,
					statusText: propsResponse.statusText,
					headers: headers
				});
			} catch (_) {
				return propsResponse;
			}
		}

		if (!isCompletionUrl(input)) return originalFetch(input, init);

		var isCrossRouting = Boolean(localNodeEndpoint && window.location.origin !== localNodeEndpoint);
		var targetUrl = isCrossRouting ? (localNodeEndpoint + '/webui/chat/completions') : input;
		var fetchOptions = init ? Object.assign({}, init) : {};

		if (typeof fetchOptions.body === 'string') {
			var rewrittenBody = await withSelectedModel(fetchOptions.body);
			if (rewrittenBody) fetchOptions.body = rewrittenBody;
		} else if (input instanceof Request) {
			var cloned = input.clone();
			var requestBody = await cloned.text();
			var rewritten = await withSelectedModel(requestBody);
			if (rewritten) {
				var h = new Headers(input.headers);
				h.delete('content-length');
				fetchOptions = Object.assign({}, fetchOptions, {
					method: input.method,
					headers: h,
					body: rewritten
				});
			}
		}

		try {
			var response = await originalFetch(targetUrl, fetchOptions);
			response = await localizeMeshNoticeResponse(response);
			observeExecutionResponse(response);

			if (isCrossRouting && response.ok) {
				var contentType = response.headers.get('content-type') || '';
				if (contentType.includes('application/json')) {
					var rawJson = await response.json();
					var stringified = JSON.stringify(rawJson);
					var rewrittenJson = stringified.replace(/(\/generated\/image_[a-zA-Z0-9_-]+\.(?:png|jpg|jpeg|webp))/g, localNodeEndpoint + '$1');
					var outHeaders = new Headers(response.headers);
					outHeaders.delete('content-length');
					observeExecutionPayload(rawJson);
					return new Response(rewrittenJson, {
						status: response.status,
						statusText: response.statusText,
						headers: outHeaders
					});
				} else if (contentType.includes('text/event-stream') && response.body) {
					var reader = response.body.getReader();
					var decoder = new TextDecoder();
					var encoder = new TextEncoder();
					var transformedStream = new ReadableStream({
						async start(controller) {
							while (true) {
								var chunk = await reader.read();
								if (chunk.done) {
									controller.close();
									break;
								}
								var text = decoder.decode(chunk.value, { stream: true });
								var rewrittenText = text.replace(/(\/generated\/image_[a-zA-Z0-9_-]+\.(?:png|jpg|jpeg|webp))/g, localNodeEndpoint + '$1');
								controller.enqueue(encoder.encode(rewrittenText));
							}
						}
					});
					return new Response(transformedStream, {
						status: response.status,
						statusText: response.statusText,
						headers: response.headers
					});
				}
			}
			return response;
		} catch (err) {
			if (isCrossRouting) {
				console.warn('[ComputeMesh] Local node unreachable, falling back to cloud gateway:', err);
				localNodeEndpoint = null;
				var gatewayModel = models.find(function (model) { return model.__sourceEndpoint === window.location.origin; });
				if (!gatewayModel) throw err;
				selectedModel = gatewayModel;
				applyCapabilities(selectedModel);
				try { localStorage.setItem(STORAGE_KEY, selectedModel.id); } catch (_) {}
				var fallbackBody = await withSelectedModel(fetchOptions.body);
				if (fallbackBody) fetchOptions.body = fallbackBody;
				return originalFetch(input, fetchOptions);
			}
			throw err;
		}
	};

	function displayName(model) {
		return String(model.name || model.id || '').replace(/^[^/]+\//, '').replace(/[-_]/g, ' ');
	}

	function canvasBlob(canvas, type, quality) {
		return new Promise(function (resolve) { canvas.toBlob(resolve, type, quality); });
	}

	async function optimizeImageFile(file, maxOutputBytes) {
		if (!file.type || !file.type.startsWith('image/') || /image\/(gif|svg\+xml)/i.test(file.type)) return file;
		if (typeof createImageBitmap !== 'function') return file;

		var bitmap;
		try { bitmap = await createImageBitmap(file); } catch (_) { return file; }
		try {
			var longestEdge = Math.max(bitmap.width, bitmap.height);
			if (longestEdge <= maxImageEdge && file.size <= maxOutputBytes) return file;

			var scale = Math.min(1, maxImageEdge / longestEdge);
			var width = Math.max(1, Math.round(bitmap.width * scale));
			var height = Math.max(1, Math.round(bitmap.height * scale));
			var canvas = document.createElement('canvas');
			var context = canvas.getContext('2d', { alpha: file.type === 'image/png' });
			if (!context) return file;
			var outputType = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
			var quality = 0.84;
			var blob = null;

			for (var attempt = 0; attempt < 12; attempt++) {
				canvas.width = width;
				canvas.height = height;
				context.drawImage(bitmap, 0, 0, width, height);
				blob = await canvasBlob(canvas, outputType, outputType === 'image/jpeg' ? quality : undefined);
				if (!blob || blob.size <= maxOutputBytes) break;

				if (outputType === 'image/jpeg' && quality > 0.56) {
					quality = Math.max(0.56, quality - 0.1);
				} else {
					width = Math.max(1, Math.round(width * 0.78));
					height = Math.max(1, Math.round(height * 0.78));
					quality = 0.82;
				}
			}

			if (!blob || blob.size > maxOutputBytes) return file;
			var extension = outputType === 'image/png' ? '.png' : '.jpg';
			var baseName = file.name.replace(/\.[^.]+$/, '');
			return new File([blob], baseName + extension, {
				type: outputType,
				lastModified: file.lastModified
			});
		} finally {
			if (bitmap && typeof bitmap.close === 'function') bitmap.close();
		}
	}

	function installImageUploadOptimization() {
		document.addEventListener('change', function (event) {
			var input = event.target;
			if (!input || input.type !== 'file') return;
			if (replayingFileInputs.has(input)) {
				replayingFileInputs.delete(input);
				return;
			}
			var originalFiles = Array.from(input.files || []);
			if (!originalFiles.some(function (file) { return file.type && file.type.startsWith('image/'); })) return;

			event.preventDefault();
			event.stopImmediatePropagation();
			(async function () {
				try {
					var compressibleImages = originalFiles.filter(function (file) {
						return file.type && file.type.startsWith('image/') && !/image\/(gif|svg\+xml)/i.test(file.type);
					});
					var perImageBudget = Math.floor(uploadLimitBytes / Math.max(1, compressibleImages.length));
					var optimizedFiles = await Promise.all(originalFiles.map(function (file) {
						return compressibleImages.includes(file) ? optimizeImageFile(file, perImageBudget) : file;
					}));
					var transfer = new DataTransfer();
					optimizedFiles.forEach(function (file) { transfer.items.add(file); });
					input.files = transfer.files;
				} catch (_) {
					// If this browser cannot replace FileList, let the normal uploader try the originals.
				}
				replayingFileInputs.add(input);
				input.dispatchEvent(new Event('change', { bubbles: true }));
			})();
		}, true);
	}

	function renderOptions(select) {
		select.replaceChildren();
		models.forEach(function (model) {
			var option = document.createElement('option');
			var modalities = modalitiesFor(model);
			option.value = model.id;
			option.textContent = displayName(model) + (modalities.includes('vision') ? ' · Bilder' : ' · Text');
			select.appendChild(option);
		});
		select.value = selectedModel ? selectedModel.id : '';
	}

	function findModelInfoValueCell() {
		var headings = Array.from(document.querySelectorAll('h1, h2, h3, [role="heading"]'));
		var title = headings.find(function (node) {
			return /model information/i.test(node.textContent || '');
		});
		if (!title) return null;

		var panel = title;
		for (var depth = 0; panel && depth < 9; depth++, panel = panel.parentElement) {
			var text = panel.textContent || '';
			if (/file path/i.test(text)) break;
		}
		if (!panel || !/file path/i.test(panel.textContent || '')) return null;

		var modelLabel = Array.from(panel.querySelectorAll('*')).find(function (node) {
			return node.children.length === 0 && (node.textContent || '').trim() === 'Model';
		});
		if (!modelLabel) return null;

		var branch = modelLabel;
		for (var level = 0; branch && branch.parentElement && level < 5; level++, branch = branch.parentElement) {
			var siblings = Array.from(branch.parentElement.children).filter(function (node) {
				return node !== branch && (node.textContent || '').trim();
			});
			if (siblings.length) return siblings[0];
		}
		return modelLabel.parentElement;
	}

	function mountPicker() {
		renderModelInfoFallback();
		if (!models.length) return;
		var valueCell = findModelInfoValueCell();
		if (!valueCell) {
			if (picker && picker.parentElement) picker.remove();
			return;
		}

		if (!picker) {
			picker = document.createElement('div');
			picker.className = 'cm-model-picker';
			picker.style.cssText = 'display:flex;flex-direction:column;gap:6px;width:100%;min-width:0;max-width:100%;box-sizing:border-box;';
			var select = document.createElement('select');
			select.id = 'cm-model-select';
			select.setAttribute('aria-label', 'Model');
			select.style.cssText = 'display:block;width:100%;min-width:0;max-width:100%;height:40px;box-sizing:border-box;padding:0 34px 0 12px;border:1px solid rgba(56,189,248,.55);border-radius:8px;background:#111827;color:#f8fafc;font-size:14px;line-height:1.2;white-space:nowrap;text-overflow:ellipsis;overflow:hidden;';
			select.addEventListener('change', function () {
				selectedModel = models.find(function (model) { return model.id === select.value; }) || null;
				if (!selectedModel) return;
				localNodeEndpoint = selectedModel.__sourceEndpoint && selectedModel.__sourceEndpoint !== window.location.origin
					? selectedModel.__sourceEndpoint
					: null;
				try { localStorage.setItem(STORAGE_KEY, selectedModel.id); } catch (_) {}
				try {
					var draft = document.querySelector('textarea');
					if (draft && draft.value) sessionStorage.setItem(DRAFT_KEY, draft.value);
				} catch (_) {}
				applyCapabilities(selectedModel);
				window.dispatchEvent(new CustomEvent('cm:model-selection-change', { detail: { model: selectedModel } }));
				window.location.reload();
			});
			picker.append(select);

			// Append node status pill
			var badge = document.createElement('div');
			badge.id = 'cm-node-status-badge';
			badge.style.cssText = 'width:100%;max-width:100%;box-sizing:border-box;margin-top:0;font-size:11px;line-height:1.25;padding:4px 8px;border-radius:6px;display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-weight:500;';
			if (localNodeEndpoint) {
				badge.style.background = 'rgba(16, 185, 129, 0.15)';
				badge.style.color = '#10b981';
				badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
				badge.innerHTML = '<span>🟢</span> <span>Lokale GPU-Node aktiv (P2P · Zero-Config)</span>';
				badge.title = 'Inferenz und Bildgenerierung laufen direkt ueber deine lokale GPU-Node ohne Router-Konfiguration.';
			} else {
				badge.style.background = 'rgba(99, 102, 241, 0.12)';
				badge.style.color = '#818cf8';
				badge.style.border = '1px solid rgba(99, 102, 241, 0.25)';
				badge.innerHTML = '<span>☁️</span> <span>ComputeMesh Cloud-Gateway</span>';
				badge.title = 'Verbindung zum dezentralen ComputeMesh Netzwerk.';
			}
			picker.append(badge);
			var executionStatus = document.getElementById('cm-execution-status') || document.createElement('div');
			executionStatus.id = 'cm-execution-status';
			executionStatus.hidden = true;
			executionStatus.style.cssText = 'position: static; margin-top: 5px; font-size: 11px; color: #a1a1aa; max-width: 320px; overflow-wrap: anywhere; pointer-events: none;';
			picker.append(executionStatus);
		}
		updateExecutionStatus(lastExecution);
		if (picker.parentElement === valueCell) return;
		valueCell.style.minWidth = '0';
		valueCell.style.width = '58%';
		valueCell.style.maxWidth = '100%';
		valueCell.style.boxSizing = 'border-box';
		valueCell.replaceChildren(picker);
		var select = picker.querySelector('select');
		renderOptions(select);
		restoreDraft(document.querySelector('textarea'));
	}

	function restoreDraft(textarea) {
		try {
			var draft = sessionStorage.getItem(DRAFT_KEY);
			if (draft === null) return;
			sessionStorage.removeItem(DRAFT_KEY);
			textarea.value = draft;
			textarea.dispatchEvent(new Event('input', { bubbles: true }));
			textarea.dispatchEvent(new Event('change', { bubbles: true }));
		} catch (_) {}
	}

	// Rewrites any image elements pointing to relative /generated/ to the local node when cross-routing
	function installImageTagRewriter() {
		var observer = new MutationObserver(function (mutations) {
			if (!localNodeEndpoint || window.location.origin === localNodeEndpoint) return;
			var imgs = document.querySelectorAll('img[src^="/generated/"]');
			for (var i = 0; i < imgs.length; i++) {
				var img = imgs[i];
				var currentSrc = img.getAttribute('src');
				if (currentSrc && currentSrc.startsWith('/generated/')) {
					img.src = localNodeEndpoint + currentSrc;
				}
			}
		});
		observer.observe(document.documentElement, { childList: true, subtree: true });
	}

	async function initialize() {
		try {
			await probeLocalNode();

			// Peer discovery must never hide the authenticated gateway's catalog.
			var catalogEndpoints = [window.location.origin].concat(meshEndpoints.filter(function (endpoint) {
				return endpoint !== window.location.origin;
			}));
			var catalogResults = await mapWithConcurrency(catalogEndpoints, 8, async function (endpoint) {
				try {
					var result = await fetchDiscoveryJson(endpoint + '/v1/models', 'include');
					return (result && Array.isArray(result.data) ? result.data : []).filter(function (model) {
						return model && model.id && model.available !== false &&
							(!model.availability || ['catalogued', 'available', 'available_cold', 'available_warm'].includes(model.availability));
					}).map(function (model) {
						return Object.assign({}, model, { __sourceEndpoint: endpoint });
					});
				} catch (_) {
					return [];
				}
			});
			var byModelId = new Map();
			catalogResults.flat().forEach(function (model) {
				var existing = byModelId.get(model.id);
				if (!existing || compareModels(model, existing) < 0) byModelId.set(model.id, model);
			});
			models = Array.from(byModelId.values()).sort(compareModels);
			if (!models.length) throw new Error('No selectable models');

			var savedId = '';
			try { savedId = localStorage.getItem(STORAGE_KEY) || ''; } catch (_) {}
			selectedModel = models.find(function (model) { return model.id === savedId; }) || null;
			if (!selectedModel) {
				selectedModel = models[0];
				try {
					var slots = await fetchDiscoveryJson('/slots', 'same-origin');
					var activeId = Array.isArray(slots) && slots[0] && slots[0].model;
					selectedModel = models.find(function (model) { return model.id === activeId; }) || selectedModel;
				} catch (_) {}
				try { localStorage.setItem(STORAGE_KEY, selectedModel.id); } catch (_) {}
			}
			localNodeEndpoint = selectedModel.__sourceEndpoint && selectedModel.__sourceEndpoint !== window.location.origin
				? selectedModel.__sourceEndpoint
				: null;
			applyCapabilities(selectedModel);
			mountPicker();
			new MutationObserver(mountPicker).observe(document.documentElement, { childList: true, subtree: true });
			initializeAgentSessions();
		} catch (error) {
			applyCapabilities(null);
			initializeAgentSessions();
		}
	}

	window.ComputeMeshModelSelector = { getSelectedModel: currentModel, modalitiesFor: modalitiesFor, probeLocalNode: probeLocalNode };
	window.ComputeMeshAgentSessions = { refresh: initializeAgentSessions, poll: pollAgentSessionEvents, refreshApprovals: refreshAgentApprovals };
	installImageUploadOptimization();
	installImageTagRewriter();
	setInterval(renderModelInfoFallback, 500);
	modelSelectionReady = document.readyState === 'loading'
		? new Promise(function (resolve) {
			document.addEventListener('DOMContentLoaded', function () { initialize().finally(resolve); }, { once: true });
		})
		: initialize();
})();
