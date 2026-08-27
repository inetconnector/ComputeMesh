/* ComputeMesh compliance wrapper.
 *
 * The historical portal implementation is preserved byte-for-byte as portal-core.js.
 * This wrapper loads it, then applies the production-facing B2B/AI/provider policy
 * without deleting playground, calculator, billing, translation or other UI logic.
 */
(function () {
  'use strict';

  const TERMS_VERSION = '2.1';
  const EEA = [
    ['AT','Austria / Österreich'],['BE','Belgium / Belgien'],['BG','Bulgaria / Bulgarien'],['HR','Croatia / Kroatien'],['CY','Cyprus / Zypern'],
    ['CZ','Czechia / Tschechien'],['DE','Germany / Deutschland'],['DK','Denmark / Dänemark'],['EE','Estonia / Estland'],['ES','Spain / Spanien'],
    ['FI','Finland / Finnland'],['FR','France / Frankreich'],['GR','Greece / Griechenland'],['HU','Hungary / Ungarn'],['IE','Ireland / Irland'],
    ['IS','Iceland / Island'],['IT','Italy / Italien'],['LI','Liechtenstein'],['LT','Lithuania / Litauen'],
    ['LU','Luxembourg / Luxemburg'],['LV','Latvia / Lettland'],['MT','Malta'],['NL','Netherlands / Niederlande'],['NO','Norway / Norwegen'],
    ['PL','Poland / Polen'],['PT','Portugal'],['RO','Romania / Rumänien'],['SE','Sweden / Schweden'],['SI','Slovenia / Slowenien'],['SK','Slovakia / Slowakei']
  ];

  const COMPLIANCE_I18N = {
    en: {
      business: 'I confirm that I register as an <strong>entrepreneur/business user</strong>, not as a consumer.',
      terms: (ver) => `I accept the <a href="/terms" target="_blank" rel="noopener">Terms v${ver}</a>.`,
      privacy: 'I acknowledge the <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.',
      countryLabel: 'Provider operating country (EEA production pool)',
      selectCountry: 'Select EEA country…',
      providerData: 'I accept the provider confidentiality/data-processing obligations: no independent use, extraction or retention of customer workload data.',
      providerLogs: 'I attest that provider systems will not persist or log plaintext prompts or responses and will follow the approved operational security policy.',
      providerPayout: 'Production provider payouts are onboarded separately through the approved payment provider (currently Stripe Connect). Registration does not guarantee node admission, workloads or earnings.',
      consumerRole: 'Use third-party AI models through ComputeMesh infrastructure',
      providerRole: 'Provide EEA compute capacity as a business',
      errBusiness: 'Business status, Terms and Privacy acknowledgement are required.',
      errProvider: 'EEA country and provider data/security obligations are required.',
      registering: 'Registering…',
      registered: 'Account created. Production node admission remains pending operator verification and server-side compliance enrollment.',
      regFailed: 'Registration failed: '
    },
    de: {
      business: 'Ich bestätige meine Registrierung als <strong>Gewerbekunde/Unternehmer (B2B)</strong>, nicht als Verbraucher.',
      terms: (ver) => `Ich akzeptiere die <a href="/terms" target="_blank" rel="noopener">AGB v${ver}</a>.`,
      privacy: 'Ich habe die <a href="/privacy" target="_blank" rel="noopener">Datenschutzerklärung</a> zur Kenntnis genommen.',
      countryLabel: 'Provider-Betriebsland (EWR/EEA-Produktionspool)',
      selectCountry: 'EWR-Land auswählen…',
      providerData: 'Ich akzeptiere die Vertraulichkeits- und Auftragsverarbeitungs-Bedingungen: keine Speicherung, Weitergabe oder Zweckentfremdung von Kundendaten.',
      providerLogs: 'Ich versichere, dass keine Klartext-Prompts oder Antworten protokolliert werden und die Sicherheitsrichtlinien eingehalten werden.',
      providerPayout: 'Auszahlungen für Provider werden separat über den zugelassenen Zahlungsdienstleister (Stripe Connect) abgewickelt. Eine Registrierung garantiert keine automatische Zulassung oder Auslastung.',
      consumerRole: 'KI-Inferenzmodelle über ComputeMesh nutzen (Kunde)',
      providerRole: 'EWR-Rechenleistung als gewerblicher Provider bereitstellen',
      errBusiness: 'Bestätigung als Gewerbekunde, AGB und Datenschutz sind erforderlich.',
      errProvider: 'EWR-Land und Provider-Sicherheitsverpflichtungen sind erforderlich.',
      registering: 'Registrierung läuft…',
      registered: 'Konto erstellt. Die produktive Node-Zulassung erfolgt nach Prüfung und Compliance-Aktivierung.',
      regFailed: 'Registrierung fehlgeschlagen: '
    }
  };

  function getLang() {
    return (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de') ? 'de' : 'en';
  }

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === 'class') node.className = value;
      else if (key === 'for') node.htmlFor = value;
      else if (key === 'checked') node.checked = Boolean(value);
      else node.setAttribute(key, value);
    });
    if (text != null) node.textContent = text;
    return node;
  }

  function addCheckbox(container, id, htmlText) {
    const row = el('label', { class: 'compliance-check', for: id });
    const input = el('input', { id, type: 'checkbox' });
    const span = el('span');
    span.innerHTML = htmlText;
    row.append(input, span);
    container.appendChild(row);
  }

  function syncComplianceLanguage(lang) {
    const l = (lang === 'de' || lang === 'en') ? lang : getLang();
    const t = COMPLIANCE_I18N[l];

    const spanBiz = document.querySelector('label[for="cm-business-user"] span');
    if (spanBiz) spanBiz.innerHTML = t.business;
    const spanTerms = document.querySelector('label[for="cm-terms"] span');
    if (spanTerms) spanTerms.innerHTML = t.terms(TERMS_VERSION);
    const spanPriv = document.querySelector('label[for="cm-privacy"] span');
    if (spanPriv) spanPriv.innerHTML = t.privacy;

    const countryLabel = document.querySelector('label[for="cm-provider-country"]');
    if (countryLabel) countryLabel.textContent = t.countryLabel;
    const countryFirstOpt = document.querySelector('#cm-provider-country option[value=""]');
    if (countryFirstOpt) countryFirstOpt.textContent = t.selectCountry;

    const spanData = document.querySelector('label[for="cm-provider-data-terms"] span');
    if (spanData) spanData.innerHTML = t.providerData;
    const spanLogs = document.querySelector('label[for="cm-provider-no-logs"] span');
    if (spanLogs) spanLogs.innerHTML = t.providerLogs;

    const payoutP = document.querySelector('#cm-provider-compliance p');
    if (payoutP) payoutP.textContent = t.providerPayout;

    const role = document.getElementById('modal-role');
    if (role) {
      const consumerOption = role.querySelector('option[value="consumer"]');
      const providerOption = role.querySelector('option[value="provider"]');
      if (consumerOption) consumerOption.textContent = t.consumerRole;
      if (providerOption) providerOption.textContent = t.providerRole;
    }
  }
  window.syncComplianceLanguage = syncComplianceLanguage;

  function ensureComplianceControls() {
    const modal = document.getElementById('register-modal');
    const form = modal?.querySelector('form');
    if (!form || document.getElementById('cm-compliance-controls')) return;

    const lang = getLang();
    const t = COMPLIANCE_I18N[lang];

    const box = el('div', { id: 'cm-compliance-controls', class: 'form-group' });
    box.style.cssText = 'display:flex;flex-direction:column;gap:.75rem;padding:1rem;border:1px solid var(--border-subtle);border-radius:10px;background:rgba(17,24,39,.45);';
    addCheckbox(box, 'cm-business-user', t.business);
    addCheckbox(box, 'cm-terms', t.terms(TERMS_VERSION));
    addCheckbox(box, 'cm-privacy', t.privacy);

    const provider = el('div', { id: 'cm-provider-compliance' });
    provider.style.cssText = 'display:none;flex-direction:column;gap:.75rem;margin-top:.5rem;';
    const countryLabel = el('label', { for: 'cm-provider-country' }, t.countryLabel);
    const country = el('select', { id: 'cm-provider-country', class: 'form-control' });
    country.appendChild(el('option', { value: '' }, t.selectCountry));
    EEA.forEach(([code, name]) => country.appendChild(el('option', { value: code }, `${name} (${code})`)));
    provider.append(countryLabel, country);
    addCheckbox(provider, 'cm-provider-data-terms', t.providerData);
    addCheckbox(provider, 'cm-provider-no-logs', t.providerLogs);
    const payout = el('p', {});
    payout.style.cssText = 'font-size:.8rem;color:var(--text-muted);margin:0;';
    payout.textContent = t.providerPayout;
    provider.appendChild(payout);
    box.appendChild(provider);

    const submit = form.querySelector('button[type="submit"]');
    if (submit) form.insertBefore(box, submit);
    else form.appendChild(box);

    const wallet = form.querySelector('input[data-i18n="modal_wallet_placeholder"]');
    if (wallet) {
      wallet.value = '';
      const group = wallet.closest('.form-group');
      if (group) group.style.display = 'none';
    }

    const role = document.getElementById('modal-role');
    if (role) {
      const consumerOption = role.querySelector('option[value="consumer"]');
      const providerOption = role.querySelector('option[value="provider"]');
      if (consumerOption) consumerOption.textContent = t.consumerRole;
      if (providerOption) providerOption.textContent = t.providerRole;
      role.addEventListener('change', syncProviderControls);
    }
    syncProviderControls();
  }

  function syncProviderControls() {
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const provider = document.getElementById('cm-provider-compliance');
    if (provider) provider.style.display = role === 'provider' ? 'flex' : 'none';
  }

  function checked(id) {
    return document.getElementById(id)?.checked === true;
  }

  async function compliantRegistration(event) {
    event.preventDefault();
    ensureComplianceControls();
    const lang = getLang();
    const t = COMPLIANCE_I18N[lang];

    const form = event.currentTarget;
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const email = form.querySelector('input[type="email"]')?.value?.trim() || '';
    const keyInput = document.getElementById('generated-key-val');
    const resBox = document.getElementById('modal-result-box');
    const country = document.getElementById('cm-provider-country')?.value || '';

    if (!checked('cm-business-user') || !checked('cm-terms') || !checked('cm-privacy')) {
      if (keyInput) keyInput.value = t.errBusiness;
      if (resBox) resBox.style.display = 'block';
      return;
    }
    if (role === 'provider' && (!country || !checked('cm-provider-data-terms') || !checked('cm-provider-no-logs'))) {
      if (keyInput) keyInput.value = t.errProvider;
      if (resBox) resBox.style.display = 'block';
      return;
    }

    if (keyInput) keyInput.value = t.registering;
    if (resBox) resBox.style.display = 'block';
    try {
      const response = await fetch('/api/v1/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          role,
          wallet: '',
          country_code: role === 'provider' ? country : '',
          terms_version: TERMS_VERSION,
          accepted_terms: true,
          privacy_acknowledged: true,
          business_user: true,
          provider_data_processing_terms_accepted: role === 'provider' ? true : false,
          no_prompt_logging_attested: role === 'provider' ? true : false
        })
      });
      const data = await response.json();
      if (!response.ok || !data.api_key) throw new Error(data.error || 'registration_failed');
      if (keyInput) keyInput.value = data.api_key;
      if (role === 'provider' && resBox) {
        const note = el('p', {});
        note.style.cssText = 'font-size:.8rem;color:var(--text-muted);margin-top:.75rem;';
        note.textContent = t.registered;
        resBox.appendChild(note);
      }
    } catch (error) {
      if (keyInput) keyInput.value = `${t.regFailed}${String(error.message || error).slice(0, 160)}`;
    }
  }

  function applyLegalPositioning() {
    document.querySelectorAll('.chat-author').forEach((node) => {
      if (node.textContent.includes('ComputeMesh AI')) {
        node.childNodes[0].textContent = 'Configured third-party model via ComputeMesh ';
      }
    });
    window.applyQuickPrompt = function (key) {
      const safe = {
        explain_mesh: 'In 2 concise sentences, explain ComputeMesh as distributed compute/orchestration infrastructure and distinguish it from the third-party AI models it executes.',
        python_fastapi: 'Write a high-performance Python FastAPI endpoint that forwards requests to an OpenAI-compatible /v1/chat/completions gateway with streaming.',
        gpu_sharding: 'Explain the engineering trade-offs of pipeline layer sharding across multiple GPUs without assuming a universal speedup.',
        compare_costs: 'Explain the variables that determine distributed inference cost. Do not invent savings, prices, SLAs or benchmark results.'
      };
      const input = document.getElementById('playground-prompt-input');
      if (input && safe[key]) {
        input.value = safe[key];
        input.focus();
      }
    };
  }

  function installOverrides() {
    const coreOpenModal = window.openModal;
    window.openModal = function (role = 'consumer') {
      if (typeof coreOpenModal === 'function') coreOpenModal(role);
      ensureComplianceControls();
      const select = document.getElementById('modal-role');
      if (select) select.value = role;
      syncProviderControls();
      syncComplianceLanguage(getLang());
    };
    window.handleRegistration = compliantRegistration;
    ensureComplianceControls();
    applyLegalPositioning();
    syncComplianceLanguage(getLang());
  }

  const core = document.createElement('script');
  core.src = 'portal-core.js';
  core.async = false;
  core.onload = installOverrides;
  core.onerror = function () {
    const fallback = document.createElement('script');
    fallback.src = '/portal-core.js';
    fallback.async = false;
    fallback.onload = installOverrides;
    fallback.onerror = function () {
      console.error('ComputeMesh portal core failed to load');
    };
    document.head.appendChild(fallback);
  };
  document.head.appendChild(core);
})();
