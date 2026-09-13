/* ComputeMesh Portal Controller & Registration Manager
 * Provides B2B compliance, role-based form switching, and API credential generation.
 */
(function () {
  'use strict';

  const TERMS_VERSION = '2.1';
  const ANDROID_APK_URL = 'https://mesh.inetconnector.com/downloads/ComputeMesh-Android.apk';

  function getLang() {
    return (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de' || (!localStorage.getItem('cm_portal_lang') && (navigator.language || '').startsWith('de'))) ? 'de' : 'en';
  }

  function syncProviderControls() {
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const providerFields = document.getElementById('provider-extra-fields');
    const submitBtn = document.getElementById('modal-submit-btn');
    const lang = getLang();

    if (providerFields) {
      providerFields.style.display = role === 'provider' ? 'flex' : 'none';
    }
    if (submitBtn) {
      if (role === 'provider') {
        submitBtn.textContent = lang === 'de' ? '⚡ GPU-Node registrieren' : '⚡ Register GPU Node';
      } else {
        submitBtn.textContent = lang === 'de' ? '🚀 API-Key generieren' : '🚀 Generate API Key';
      }
    }
  }

  async function compliantRegistration(event) {
    if (event && event.preventDefault) event.preventDefault();
    const form = document.getElementById('registration-form');
    const submitBtn = document.getElementById('modal-submit-btn');
    if (form?.dataset.registrationBusy === '1') return;
    const lang = getLang();
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const email = document.getElementById('modal-email')?.value?.trim() || '';
    const country = document.getElementById('cm-provider-country')?.value || '';
    const wallet = document.getElementById('modal-wallet')?.value?.trim() || '';
    const bizCheck = document.getElementById('business-user-confirm');
    const keyInput = document.getElementById('generated-key-val');
    const resBox = document.getElementById('modal-result-box');

    if (!bizCheck || !bizCheck.checked) {
      const msg = lang === 'de'
        ? 'Bitte akzeptiere die Nutzungsbedingungen und bestätige die geschäftliche Nutzung (B2B).'
        : 'Please accept the Terms of Service & Privacy Policy and confirm business (B2B) use.';
      if (keyInput) keyInput.value = msg;
      if (resBox) resBox.style.display = 'block';
      return;
    }

    if (role === 'provider' && !country) {
      const msg = lang === 'de' ? 'Bitte wähle dein Betriebsland (EWR/EU).' : 'Please select your operating country.';
      if (keyInput) keyInput.value = msg;
      if (resBox) resBox.style.display = 'block';
      return;
    }

    if (form) form.dataset.registrationBusy = '1';
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.setAttribute('aria-busy', 'true');
    }

    if (keyInput) keyInput.value = lang === 'de' ? 'Zugangsdaten werden generiert…' : 'Generating API credentials…';
    if (resBox) resBox.style.display = 'block';

    try {
      const response = await fetch('/api/v1/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          role,
          wallet: role === 'provider' ? wallet : '',
          country_code: role === 'provider' ? country : '',
          terms_version: TERMS_VERSION,
          accepted_terms: true,
          privacy_acknowledged: true,
          business_user: true,
          provider_data_processing_terms_accepted: role === 'provider',
          no_prompt_logging_attested: role === 'provider'
        })
      });
      const data = await response.json();
      if (!response.ok || !data.api_key) throw new Error(data.error || 'registration_failed');
      if (keyInput) keyInput.value = data.api_key;
      try { localStorage.setItem('cm_api_key', data.api_key); } catch (e) {}
      if (typeof window.updateCodeSnippetsWithKey === 'function') {
        window.updateCodeSnippetsWithKey(data.api_key);
      }
    } catch (error) {
      const prefix = lang === 'de' ? 'Registrierung fehlgeschlagen: ' : 'Registration failed: ';
      if (keyInput) keyInput.value = `${prefix}${String(error.message || error).slice(0, 160)}`;
    } finally {
      if (form) delete form.dataset.registrationBusy;
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.removeAttribute('aria-busy');
      }
    }
  }

  function clarifyVisionCapabilities() {
    const select = document.getElementById('playground-model-select');
    if (!select) return;
    const option = Array.from(select.options).find(o => o.value === 'qwen2.5-vl:7b');
    if (option) {
      option.textContent = getLang() === 'de'
        ? 'Qwen 2.5 VL 7B (Vision / Bildanalyse – keine Bildgenerierung)'
        : 'Qwen 2.5 VL 7B (Vision / image analysis – not image generation)';
    }
  }

  function installImageSafetyNotice() {
    const studio = document.querySelector('.playground-studio');
    if (!studio || document.getElementById('cm-image-safety-notice')) return;
    const note = document.createElement('div');
    note.id = 'cm-image-safety-notice';
    note.style.cssText = 'margin-top:1rem;padding:0.85rem 1rem;border:1px solid rgba(56,189,248,.24);border-radius:10px;background:rgba(15,23,42,.55);font-size:.82rem;line-height:1.5;color:#94a3b8;';
    note.innerHTML = getLang() === 'de'
      ? '🛡️ <strong style="color:#cbd5e1">Bild-KI Sicherheit:</strong> Vision-Modelle analysieren Bilder, erzeugen aber keine. Eine separate Bildgenerierung wird nur mit verpflichtender Prompt- und Output-Moderation, Minderjährigenschutz, Deepfake-Schutz und KI-Herkunftskennzeichnung freigeschaltet.'
      : '🛡️ <strong style="color:#cbd5e1">Image AI safety:</strong> Vision models analyze images; they do not render images. Separate image generation is enabled only with mandatory prompt/output moderation, minor protection, deepfake safeguards and AI-origin provenance.';
    studio.appendChild(note);
  }

  function installAndroidDownloadLink() {
    const links = Array.from(document.querySelectorAll('a[href*="ComputeMesh-Android.apk"]'));
    links.forEach(link => {
      link.href = ANDROID_APK_URL;
      link.setAttribute('rel', 'noopener');
    });

    const androidButton = links.find(link => link.hasAttribute('download') || link.dataset.i18n === 'dl_android_btn');
    const card = androidButton?.closest('.download-card');
    if (!card || card.querySelector('.cm-android-direct-link')) return;

    const direct = document.createElement('a');
    direct.className = 'cm-android-direct-link';
    direct.href = ANDROID_APK_URL;
    direct.rel = 'noopener';
    direct.textContent = ANDROID_APK_URL;
    direct.style.cssText = 'display:block;margin-top:.6rem;font-size:.72rem;overflow-wrap:anywhere;color:var(--accent-cyan);text-align:center;';
    card.appendChild(direct);
  }

  function setupModalHooks() {
    const roleSelect = document.getElementById('modal-role');
    if (roleSelect) {
      roleSelect.addEventListener('change', syncProviderControls);
    }
    const form = document.getElementById('registration-form');
    if (form) {
      form.onsubmit = compliantRegistration;
    }

    const coreOpenModal = window.openModal;
    window.openModal = function (role = 'consumer') {
      if (typeof coreOpenModal === 'function') coreOpenModal(role);
      if (roleSelect) roleSelect.value = role;
      syncProviderControls();
    };
    window.handleRegistration = compliantRegistration;
    window.compliantRegistration = compliantRegistration;
    syncProviderControls();
    clarifyVisionCapabilities();
    installImageSafetyNotice();
    installAndroidDownloadLink();
  }

  const QUICK_PROMPTS_FALLBACK = {
    de: {
      explain_mesh: "Was macht ComputeMesh einzigartig und wie funktioniert die dezentrale GPU-Inferenz?",
      python_fastapi: "Schreibe einen performanten Python-FastAPI-Endpunkt, der Requests an das OpenAI-kompatible /v1/chat/completions Gateway mit Streaming weiterleitet.",
      gpu_sharding: "Erkläre wie Pipeline-Layer-Sharding große KI-Modelle effizient über mehrere GPUs aufteilt.",
      compare_costs: "Wie viel Geld kann ich mit ComputeMesh im Vergleich zu AWS oder Azure sparen?"
    },
    en: {
      explain_mesh: "What makes ComputeMesh unique and how does decentralized GPU inference work?",
      python_fastapi: "Write a high-performance Python-FastAPI streaming endpoint using the OpenAI-compatible /v1/chat/completions gateway.",
      gpu_sharding: "Explain how pipeline layer sharding efficiently distributes large AI models across multiple GPUs.",
      compare_costs: "How much money can I save with ComputeMesh compared to AWS or Azure?"
    }
  };

  window.applyQuickPrompt = function (promptKey) {
    const lang = (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de' || (!localStorage.getItem('cm_portal_lang') && (navigator.language || '').startsWith('de'))) ? 'de' : 'en';
    const dict = (window.QUICK_PROMPTS && typeof window.QUICK_PROMPTS === 'object') ? window.QUICK_PROMPTS : QUICK_PROMPTS_FALLBACK;
    const prompt = (dict[lang] && dict[lang][promptKey]) || (dict.en && dict.en[promptKey]) || '';
    const inputEl = document.getElementById('playground-prompt-input');
    if (prompt && inputEl) {
      inputEl.value = prompt;
      inputEl.style.height = 'auto';
      inputEl.style.height = Math.min(Math.max(inputEl.scrollHeight, 60), 140) + 'px';
      inputEl.focus();
      inputEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  };

  const core = document.createElement('script');
  core.src = 'portal-core.js';
  core.async = false;
  core.onload = setupModalHooks;
  core.onerror = function () {
    const fallback = document.createElement('script');
    fallback.src = '/portal-core.js';
    fallback.async = false;
    fallback.onload = setupModalHooks;
    fallback.onerror = function () {
      console.error('ComputeMesh portal core failed to load');
    };
    document.head.appendChild(fallback);
  };
  document.head.appendChild(core);
})();
