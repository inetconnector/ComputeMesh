/* ComputeMesh Portal Controller & Registration Manager
 * Provides B2B compliance, role-based form switching, and API credential generation.
 */
(function () {
  'use strict';

  const TERMS_VERSION = '2.1';

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
    } catch (error) {
      const prefix = lang === 'de' ? 'Registrierung fehlgeschlagen: ' : 'Registration failed: ';
      if (keyInput) keyInput.value = `${prefix}${String(error.message || error).slice(0, 160)}`;
    }
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
  }

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
