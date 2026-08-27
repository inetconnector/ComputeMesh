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
    ['AT','Austria'],['BE','Belgium'],['BG','Bulgaria'],['HR','Croatia'],['CY','Cyprus'],
    ['CZ','Czechia'],['DE','Germany'],['DK','Denmark'],['EE','Estonia'],['ES','Spain'],
    ['FI','Finland'],['FR','France'],['GR','Greece'],['HU','Hungary'],['IE','Ireland'],
    ['IS','Iceland'],['IT','Italy'],['LI','Liechtenstein'],['LT','Lithuania'],
    ['LU','Luxembourg'],['LV','Latvia'],['MT','Malta'],['NL','Netherlands'],['NO','Norway'],
    ['PL','Poland'],['PT','Portugal'],['RO','Romania'],['SE','Sweden'],['SI','Slovenia'],['SK','Slovakia']
  ];

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

  function ensureComplianceControls() {
    const modal = document.getElementById('register-modal');
    const form = modal?.querySelector('form');
    if (!form || document.getElementById('cm-compliance-controls')) return;

    const box = el('div', { id: 'cm-compliance-controls', class: 'form-group' });
    box.style.cssText = 'display:flex;flex-direction:column;gap:.75rem;padding:1rem;border:1px solid var(--border-subtle);border-radius:10px;background:rgba(17,24,39,.45);';
    addCheckbox(box, 'cm-business-user', 'I confirm that I register as an <strong>entrepreneur/business user</strong>, not as a consumer.');
    addCheckbox(box, 'cm-terms', `I accept the <a href="/terms" target="_blank" rel="noopener">Terms v${TERMS_VERSION}</a>.`);
    addCheckbox(box, 'cm-privacy', 'I acknowledge the <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.');

    const provider = el('div', { id: 'cm-provider-compliance' });
    provider.style.cssText = 'display:none;flex-direction:column;gap:.75rem;margin-top:.5rem;';
    const countryLabel = el('label', { for: 'cm-provider-country' }, 'Provider operating country (EEA production pool)');
    const country = el('select', { id: 'cm-provider-country', class: 'form-control' });
    country.appendChild(el('option', { value: '' }, 'Select EEA country…'));
    EEA.forEach(([code, name]) => country.appendChild(el('option', { value: code }, `${name} (${code})`)));
    provider.append(countryLabel, country);
    addCheckbox(provider, 'cm-provider-data-terms', 'I accept the provider confidentiality/data-processing obligations: no independent use, extraction or retention of customer workload data.');
    addCheckbox(provider, 'cm-provider-no-logs', 'I attest that provider systems will not persist or log plaintext prompts or responses and will follow the approved operational security policy.');
    const payout = el('p', {});
    payout.style.cssText = 'font-size:.8rem;color:var(--text-muted);margin:0;';
    payout.textContent = 'Production provider payouts are onboarded separately through the approved payment provider (currently Stripe Connect). Registration does not guarantee node admission, workloads or earnings.';
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
      if (consumerOption) consumerOption.textContent = 'Use third-party AI models through ComputeMesh infrastructure';
      if (providerOption) providerOption.textContent = 'Provide EEA compute capacity as a business';
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
    const form = event.currentTarget;
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const email = form.querySelector('input[type="email"]')?.value?.trim() || '';
    const keyInput = document.getElementById('generated-key-val');
    const resBox = document.getElementById('modal-result-box');
    const country = document.getElementById('cm-provider-country')?.value || '';

    if (!checked('cm-business-user') || !checked('cm-terms') || !checked('cm-privacy')) {
      if (keyInput) keyInput.value = 'Business status, Terms and Privacy acknowledgement are required.';
      if (resBox) resBox.style.display = 'block';
      return;
    }
    if (role === 'provider' && (!country || !checked('cm-provider-data-terms') || !checked('cm-provider-no-logs'))) {
      if (keyInput) keyInput.value = 'EEA country and provider data/security obligations are required.';
      if (resBox) resBox.style.display = 'block';
      return;
    }

    if (keyInput) keyInput.value = 'Registering…';
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
        note.textContent = 'Account created. Production node admission remains pending operator verification and server-side compliance enrollment.';
        resBox.appendChild(note);
      }
    } catch (error) {
      if (keyInput) keyInput.value = `Registration failed: ${String(error.message || error).slice(0, 160)}`;
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
    };
    window.handleRegistration = compliantRegistration;
    ensureComplianceControls();
    applyLegalPositioning();
  }

  const core = document.createElement('script');
  core.src = '/portal-core.js';
  core.async = false;
  core.onload = installOverrides;
  core.onerror = function () {
    console.error('ComputeMesh portal core failed to load');
  };
  document.head.appendChild(core);
})();
