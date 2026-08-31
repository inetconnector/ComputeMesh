/* ComputeMesh Portal Registration & Compliance Controller
 * Integrates B2B, Terms v2.1, and Privacy Policy consent for account registration
 * without interfering with marketing, UI localization, or playground streaming.
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
      terms: (ver) => `I accept the <a href="/terms" target="_blank" rel="noopener">Terms of Service v${ver}</a>.`,
      privacy: 'I acknowledge the <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.',
      countryLabel: 'Provider Operating Country (EEA Region)',
      selectCountry: 'Select Country…',
      providerData: 'I accept the provider data-processing terms (zero prompt retention/extraction).',
      providerLogs: 'I attest that node systems will not persist or log plaintext prompts or responses.',
      consumerRole: 'Developer API (Run AI Inference)',
      providerRole: 'Hardware Provider (Monetize GPUs)',
      errBusiness: 'Please accept the Business User confirmation, Terms of Service, and Privacy Policy.',
      errProvider: 'Please select an operating country and accept provider compliance obligations.',
      registering: 'Generating API credentials…',
      registered: '✓ Account created successfully! Use your API key in the OpenAI SDK or provider daemon.',
      regFailed: 'Registration failed: '
    },
    de: {
      business: 'Ich bestätige meine Registrierung als <strong>Gewerbekunde/Unternehmer (B2B)</strong>, nicht als Verbraucher.',
      terms: (ver) => `Ich akzeptiere die <a href="/terms" target="_blank" rel="noopener">Nutzungsbedingungen v${ver}</a>.`,
      privacy: 'Ich habe die <a href="/privacy" target="_blank" rel="noopener">Datenschutzerklärung</a> zur Kenntnis genommen.',
      countryLabel: 'Provider-Betriebsland (EWR/EEA-Region)',
      selectCountry: 'Land auswählen…',
      providerData: 'Ich akzeptiere die Auftragsverarbeitungs-Bedingungen (keine Speicherung oder Weitergabe von Kundendaten).',
      providerLogs: 'Ich versichere, dass keine Klartext-Prompts oder Antworten protokolliert werden.',
      consumerRole: 'Developer-API nutzen (KI-Inferenz ausführen)',
      providerRole: 'Hardware-Provider werden (GPUs monetarisieren)',
      errBusiness: 'Bitte bestätige den Geschäftskundenstatus, die AGB und die Datenschutzerklärung.',
      errProvider: 'Bitte wähle dein Betriebsland und bestätige die Provider-Sicherheitsrichtlinien.',
      registering: 'Zugangsdaten werden generiert…',
      registered: '✓ Konto erfolgreich erstellt! Nutze deinen API-Key im OpenAI SDK oder im Provider-Daemon.',
      regFailed: 'Registrierung fehlgeschlagen: '
    }
  };

  function getLang() {
    return (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de' || (!localStorage.getItem('cm_portal_lang') && (navigator.language || '').startsWith('de'))) ? 'de' : 'en';
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
    row.style.cssText = 'display:flex;gap:0.5rem;align-items:flex-start;font-size:0.82rem;line-height:1.4;margin-top:0.5rem;cursor:pointer;';
    const input = el('input', { id, type: 'checkbox' });
    input.style.marginTop = '0.2rem';
    const span = el('span');
    span.innerHTML = htmlText;
    row.append(input, span);
    container.appendChild(row);
  }

  function ensureComplianceControls() {
    const form = document.getElementById('registration-form');
    if (!form || document.getElementById('cm-compliance-box')) return;

    const box = el('div', { id: 'cm-compliance-box' });
    box.style.cssText = 'margin-top: 1rem; border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.08)); padding-top: 0.8rem;';

    addCheckbox(box, 'cm-business-user', COMPLIANCE_I18N.en.business);
    addCheckbox(box, 'cm-terms', COMPLIANCE_I18N.en.terms(TERMS_VERSION));
    addCheckbox(box, 'cm-privacy', COMPLIANCE_I18N.en.privacy);

    const providerBox = el('div', { id: 'cm-provider-compliance' });
    providerBox.style.cssText = 'display: none; flex-direction: column; gap: 0.5rem; margin-top: 0.8rem; padding: 0.8rem; background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: var(--radius-sm, 8px);';

    const countryGroup = el('div', { class: 'form-group' });
    countryGroup.style.marginBottom = '0.5rem';
    const countryLabel = el('label', { for: 'cm-provider-country' }, COMPLIANCE_I18N.en.countryLabel);
    countryLabel.style.cssText = 'font-size: 0.82rem; color: var(--text-muted); display: block; margin-bottom: 0.3rem;';
    const select = el('select', { id: 'cm-provider-country', class: 'form-control' });
    select.style.cursor = 'pointer';
    select.appendChild(el('option', { value: '' }, COMPLIANCE_I18N.en.selectCountry));
    EEA.forEach(([code, name]) => {
      select.appendChild(el('option', { value: code }, `${name} (${code})`));
    });
    countryGroup.append(countryLabel, select);
    providerBox.appendChild(countryGroup);

    addCheckbox(providerBox, 'cm-provider-data-terms', COMPLIANCE_I18N.en.providerData);
    addCheckbox(providerBox, 'cm-provider-no-logs', COMPLIANCE_I18N.en.providerLogs);

    box.appendChild(providerBox);

    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) form.insertBefore(box, submitBtn);
    else form.appendChild(box);

    const role = document.getElementById('modal-role');
    if (role) {
      role.addEventListener('change', syncProviderControls);
    }
    syncProviderControls();
  }

  function syncProviderControls() {
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const provider = document.getElementById('cm-provider-compliance');
    if (provider) provider.style.display = role === 'provider' ? 'flex' : 'none';
  }

  function checked(id, fallbackId) {
    if (document.getElementById(id)?.checked === true) return true;
    if (fallbackId && document.getElementById(fallbackId)?.checked === true) return true;
    return false;
  }

  function syncComplianceLanguage(lang) {
    const l = (lang === 'de' || lang === 'en') ? lang : getLang();
    const t = COMPLIANCE_I18N[l];

    const spanBiz = document.querySelector('label[for="cm-business-user"] span') || document.querySelector('label[for="business-user-confirm"] span');
    if (spanBiz) spanBiz.innerHTML = t.business;
    const spanTerms = document.querySelector('label[for="cm-terms"] span') || document.querySelector('label[for="terms-confirm"] span');
    if (spanTerms) spanTerms.innerHTML = t.terms(TERMS_VERSION);
    const spanPriv = document.querySelector('label[for="cm-privacy"] span') || document.querySelector('label[for="privacy-confirm"] span');
    if (spanPriv) spanPriv.innerHTML = t.privacy;

    const countryLabel = document.querySelector('label[for="cm-provider-country"]');
    if (countryLabel) countryLabel.textContent = t.countryLabel;
    const countryFirstOpt = document.querySelector('#cm-provider-country option[value=""]');
    if (countryFirstOpt) countryFirstOpt.textContent = t.selectCountry;

    const spanData = document.querySelector('label[for="cm-provider-data-terms"] span');
    if (spanData) spanData.innerHTML = t.providerData;
    const spanLogs = document.querySelector('label[for="cm-provider-no-logs"] span');
    if (spanLogs) spanLogs.innerHTML = t.providerLogs;

    const role = document.getElementById('modal-role');
    if (role) {
      const optConsumer = role.querySelector('option[value="consumer"]');
      const optProvider = role.querySelector('option[value="provider"]');
      if (optConsumer) optConsumer.textContent = t.consumerRole;
      if (optProvider) optProvider.textContent = t.providerRole;
    }
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
    const walletInput = form.querySelector('input[placeholder*="0x"]');
    const wallet = walletInput ? walletInput.value.trim() : '';

    if (!checked('cm-business-user', 'business-user-confirm') || !checked('cm-terms', 'terms-confirm') || !checked('cm-privacy', 'privacy-confirm')) {
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
          wallet: wallet || '',
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
        note.style.cssText = 'font-size:.82rem;color:var(--accent-emerald, #10b981);margin-top:.75rem;';
        note.textContent = t.registered;
        resBox.appendChild(note);
      }
    } catch (error) {
      if (keyInput) keyInput.value = `${t.regFailed}${String(error.message || error).slice(0, 160)}`;
    }
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
