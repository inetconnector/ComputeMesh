/* ComputeMesh's per-browser model selector for the bundled AI Studio WebUI. */
(function () {
	'use strict';

	var STORAGE_KEY = 'cm_selected_model_id';
	var DRAFT_KEY = 'cm_model_switch_draft';
	var models = [];
	var selectedModel = null;
	var picker = null;
	try {
		var savedModelId = localStorage.getItem(STORAGE_KEY);
		if (savedModelId) selectedModel = { id: savedModelId };
	} catch (_) {}
	var originalFetch = window.fetch.bind(window);

	function modalitiesFor(model) {
		if (model && Array.isArray(model.modalities)) return model.modalities;
		var id = String(model && model.id || '').toLowerCase();
		var modalities = ['text'];
		if (/(^|[-_./])(vl|vision)([-_./]|$)|llava|moondream/.test(id)) modalities.push('vision');
		if (/audio|omni|whisper/.test(id)) modalities.push('audio');
		if (/video/.test(id)) modalities.push('video');
		return modalities;
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

	function withSelectedModel(bodyText) {
		if (!selectedModel || !bodyText) return null;
		try {
			var body = JSON.parse(bodyText);
			if (!body || typeof body !== 'object' || (!Array.isArray(body.messages) && typeof body.prompt !== 'string')) return null;
			body.model = selectedModel.id;
			return JSON.stringify(body);
		} catch (_) {
			return null;
		}
	}

	window.fetch = async function (input, init) {
		if (isPropsUrl(input) && selectedModel) {
			var propsResponse = await originalFetch(input, init);
			if (!propsResponse.ok) return propsResponse;
			try {
				var props = await propsResponse.clone().json();
				props.default_generation_settings = props.default_generation_settings || {};
				props.default_generation_settings.model = selectedModel.id;
				props.model_path = selectedModel.id;
				props.model_alias = displayName(selectedModel);
				props.modalities = modalitiesFor(selectedModel);
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

		if (init && typeof init.body === 'string') {
			var rewrittenBody = withSelectedModel(init.body);
			if (rewrittenBody) init = Object.assign({}, init, { body: rewrittenBody });
			return originalFetch(input, init);
		}

		if (input instanceof Request) {
			var cloned = input.clone();
			var requestBody = await cloned.text();
			var rewritten = withSelectedModel(requestBody);
			if (rewritten) {
				var headers = new Headers(input.headers);
				headers.delete('content-length');
				return originalFetch(new Request(input, { body: rewritten, headers: headers }));
			}
		}
		return originalFetch(input, init);
	};

	function displayName(model) {
		return String(model.name || model.id || '').replace(/^[^/]+\//, '').replace(/[-_]/g, ' ');
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
		if (!models.length) return;
		var valueCell = findModelInfoValueCell();
		if (!valueCell) {
			if (picker && picker.parentElement) picker.remove();
			return;
		}

		if (!picker) {
			picker = document.createElement('div');
			picker.className = 'cm-model-picker';
			var select = document.createElement('select');
			select.id = 'cm-model-select';
			select.setAttribute('aria-label', 'Model');
			select.addEventListener('change', function () {
				selectedModel = models.find(function (model) { return model.id === select.value; }) || null;
				if (!selectedModel) return;
				try { localStorage.setItem(STORAGE_KEY, selectedModel.id); } catch (_) {}
				try {
					var draft = document.querySelector('textarea');
					if (draft && draft.value) sessionStorage.setItem(DRAFT_KEY, draft.value);
				} catch (_) {}
				applyCapabilities(selectedModel);
				window.dispatchEvent(new CustomEvent('cm:model-selection-change', { detail: { model: selectedModel } }));
				// Reload so the bundled WebUI refreshes its internal modality checks from /props.
				window.location.reload();
			});
			picker.append(select);
		}
		if (picker.parentElement === valueCell) return;
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

	async function initialize() {
		try {
			var response = await originalFetch('/v1/models', { credentials: 'same-origin', cache: 'no-store' });
			if (!response.ok) throw new Error('Model list unavailable');
			var result = await response.json();
			models = Array.isArray(result.data) ? result.data.filter(function (model) {
				return model && model.id && model.available !== false &&
					(!model.availability || ['catalogued', 'available', 'available_cold', 'available_warm'].includes(model.availability));
			}) : [];
			if (!models.length) throw new Error('No selectable models');

			var savedId = '';
			try { savedId = localStorage.getItem(STORAGE_KEY) || ''; } catch (_) {}
			selectedModel = models.find(function (model) { return model.id === savedId; }) || null;
			if (!selectedModel) {
				var slotResponse = await originalFetch('/slots', { credentials: 'same-origin', cache: 'no-store' });
				var slots = slotResponse.ok ? await slotResponse.json() : [];
				var activeId = Array.isArray(slots) && slots[0] && slots[0].model;
				selectedModel = models.find(function (model) { return model.id === activeId; }) || models[0];
				try { localStorage.setItem(STORAGE_KEY, selectedModel.id); } catch (_) {}
			}
			applyCapabilities(selectedModel);
			mountPicker();
			new MutationObserver(mountPicker).observe(document.documentElement, { childList: true, subtree: true });
		} catch (error) {
			// No model metadata means media actions stay hidden and no misleading switcher is shown.
			applyCapabilities(null);
		}
	}

	window.ComputeMeshModelSelector = { getSelectedModel: currentModel, modalitiesFor: modalitiesFor };
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true });
	else initialize();
})();
