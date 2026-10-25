// SPDX-License-Identifier: Apache-2.0
/**
 * ComputeMesh Agent Workspace - Inspector Component
 * Active Plan, Grand Goal, Context Metrics, Artifacts, Diff/Review, Cluster Nodes.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./state'), require('./i18n'));
  } else {
    root.AgentInspector = factory(root.AgentState, root.AgentI18n);
  }
})(typeof self !== 'undefined' ? self : this, function (AgentState, AgentI18n) {
  'use strict';

  function renderInspector() {
    const { activeSession, artifacts } = AgentState.state;
    if (!activeSession) return;

    // Render Grand Goal
    const goalEl = document.getElementById('inspector-goal-content');
    if (goalEl) {
      goalEl.textContent = activeSession.goal || activeSession.title || 'Kein explizites Ziel hinterlegt';
    }

    // Render Plan
    const planEl = document.getElementById('inspector-plan-content');
    if (planEl) {
      const plan = activeSession.plan || (activeSession.metadata && activeSession.metadata.plan) || [];
      if (Array.isArray(plan) && plan.length > 0) {
        planEl.innerHTML = plan.map((step, idx) => `
          <div class="plan-step ${step.completed ? 'completed' : step.active ? 'active' : ''}">
            <span>${idx + 1}.</span>
            <span>${escapeHtml(step.title || step.description || step)}</span>
          </div>
        `).join('');
      } else {
        planEl.innerHTML = `<span style="color: var(--text-muted); font-size: 0.8rem;">Kein Plan aktiv</span>`;
      }
    }

    // Render Artifacts
    const artifactsEl = document.getElementById('inspector-artifacts-content');
    if (artifactsEl) {
      if (artifacts && artifacts.length > 0) {
        artifactsEl.innerHTML = artifacts.map(art => `
          <div class="artifact-item">
            <span class="artifact-name">${escapeHtml(art.name || art.ref_id)}</span>
            <a href="/v1/agents/artifacts/${encodeURIComponent(art.ref_id)}" download="${escapeHtml(art.name || 'artifact')}" class="btn btn-secondary btn-xs">Download</a>
          </div>
        `).join('');
      } else {
        artifactsEl.innerHTML = `<span style="color: var(--text-muted); font-size: 0.8rem;">Keine Artefakte erzeugt</span>`;
      }
    }

    // Render Metrics
    const metricsEl = document.getElementById('inspector-metrics-content');
    if (metricsEl) {
      const tokens = (activeSession.usage && activeSession.usage.total_tokens) || activeSession.tokens_used || 0;
      metricsEl.innerHTML = `
        <div class="metric-row"><span>Tokens verwendet:</span><strong>${tokens.toLocaleString()}</strong></div>
        <div class="metric-row"><span>Status:</span><strong>${(activeSession.status || 'READY').toUpperCase()}</strong></div>
        <div class="metric-row"><span>Erstellt:</span><span>${new Date(activeSession.created_at || Date.now()).toLocaleString()}</span></div>
      `;
    }
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  return {
    renderInspector
  };
});
