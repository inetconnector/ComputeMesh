/* ComputeMesh's per-browser model selector and P2P Local Node Auto-Router for the bundled AI Studio WebUI. */
(function () {
	'use strict';

	var STORAGE_KEY = 'cm_selected_model_id';
	var DRAFT_KEY = 'cm_model_switch_draft';
	var models = [];
	var selectedModel = null;
	var picker = null;
	var localNodeEndpoint = null;
	var localNodeChecked = false;
	var localNodeCheckingPromise = null;

	// Image bytes become base64 in the chat JSON; keep their combined binary size
	// near 5 MiB to leave room for base64 expansion and the rest of the request.
	var uploadLimitBytes = 5 * 1024 * 1024;
	var maxChatRequestBytes = 9 * 1024 * 1024;
	var gatewayRequestLimitBytes = 10 * 1024 * 1024;
	var maxImageEdge = 1600;
	var replayingFileInputs = new WeakSet();

	try {
		var savedModelId = localStorage.getItem(STORAGE_KEY);
		if (savedModelId) selectedModel = { id: savedModelId };
	} catch (_) {}
	var originalFetch = window.fetch.bind(window);

	async function probeLocalNode() {
		if (localNodeChecked) return localNodeEndpoint;
		if (localNodeCheckingPromise) return localNodeCheckingPromise;

		localNodeCheckingPromise = (async function () {
			var isLocalHost = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
			if (isLocalHost) {
				localNodeEndpoint = window.location.origin;
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
						console.log('[ComputeMesh] Auto-discovered local GPU node at ' + candidate + ' (P2P direct loopback mode)');
						break;
					}
				} catch (_) {}
			}
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

			if (isCrossRouting && response.ok) {
				var contentType = response.headers.get('content-type') || '';
				if (contentType.includes('application/json')) {
					var rawJson = await response.json();
					var stringified = JSON.stringify(rawJson);
					var rewrittenJson = stringified.replace(/(\/generated\/image_[a-zA-Z0-9_-]+\.(?:png|jpg|jpeg|webp))/g, localNodeEndpoint + '$1');
					var outHeaders = new Headers(response.headers);
					outHeaders.delete('content-length');
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
				return originalFetch(input, init);
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
				window.location.reload();
			});
			picker.append(select);

			// Append node status pill
			var badge = document.createElement('div');
			badge.id = 'cm-node-status-badge';
			badge.style.cssText = 'margin-top: 6px; font-size: 11px; padding: 3px 8px; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; font-weight: 500;';
			if (localNodeEndpoint) {
				badge.style.background = 'rgba(16, 185, 129, 0.15)';
				badge.style.color = '#10b981';
				badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
				badge.innerHTML = '<span>🟢</span> <span>Lokale GPU-Node aktiv (P2P · Zero-Config)</span>';
				badge.title = 'Inferenz & Bildgenerierung laufen direkt über deine lokale RTX 3080 ohne Router-Konfiguration.';
			} else {
				badge.style.background = 'rgba(99, 102, 241, 0.12)';
				badge.style.color = '#818cf8';
				badge.style.border = '1px solid rgba(99, 102, 241, 0.25)';
				badge.innerHTML = '<span>☁️</span> <span>ComputeMesh Cloud-Gateway</span>';
				badge.title = 'Verbindung zum dezentralen ComputeMesh Netzwerk.';
			}
			picker.append(badge);
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
			applyCapabilities(null);
		}
	}

	window.ComputeMeshModelSelector = { getSelectedModel: currentModel, modalitiesFor: modalitiesFor, probeLocalNode: probeLocalNode };
	installImageUploadOptimization();
	installImageTagRewriter();
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true });
	else initialize();
})();
