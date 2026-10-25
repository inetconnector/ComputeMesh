// SPDX-License-Identifier: Apache-2.0
/**
 * ComputeMesh Agent Workspace - Timeline Component
 * Renders typed events: user inputs, assistant outputs, tool calls, terminal outputs, diffs, approvals.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./state'), require('./i18n'));
  } else {
    root.AgentTimeline = factory(root.AgentState, root.AgentI18n);
  }
})(typeof self !== 'undefined' ? self : this, function (AgentState, AgentI18n) {
  'use strict';

  function renderTimeline(container) {
    if (!container) return;
    const { events } = AgentState.state;
    if (!events || events.length === 0) {
      container.innerHTML = `<div style="padding: 2rem; color: var(--text-muted); text-align: center; font-size: 0.9rem;">${AgentI18n.t('emptyTimeline')}</div>`;
      return;
    }

    container.innerHTML = events.map(evt => renderEventCard(evt)).join('');
    container.scrollTop = container.scrollHeight;
  }

  function renderEventCard(evt) {
    const type = evt.type || evt.event_type || 'unknown';
    const payload = evt.payload || evt.data || {};

    if (type === 'turn_start' || type === 'user_message') {
      return `
        <div class="timeline-card card-user">
          <div class="card-header">
            <span>👤 User</span>
            <span class="card-seq">#${evt.sequence || ''}</span>
          </div>
          <div class="card-content">${escapeHtml(payload.prompt || payload.text || '')}</div>
        </div>
      `;
    }

    if (type === 'agent_message' || type === 'assistant_message') {
      return `
        <div class="timeline-card card-agent">
          <div class="card-header">
            <span>🤖 Agent</span>
            <span class="card-seq">#${evt.sequence || ''}</span>
          </div>
          <div class="card-content">${escapeHtml(payload.text || payload.content || '')}</div>
        </div>
      `;
    }

    if (type === 'tool_call') {
      return `
        <div class="timeline-card card-tool">
          <div class="card-header">
            <span>🔧 Tool: ${escapeHtml(payload.tool_name || payload.name || 'exec')}</span>
            <span class="card-seq">#${evt.sequence || ''}</span>
          </div>
          <div class="card-content">
            <pre class="code-block">${escapeHtml(JSON.stringify(payload.args || payload.parameters || {}, null, 2))}</pre>
          </div>
        </div>
      `;
    }

    if (type === 'tool_result') {
      return `
        <div class="timeline-card card-result">
          <div class="card-header">
            <span>📋 Tool Result</span>
            <span class="card-seq">#${evt.sequence || ''}</span>
          </div>
          <div class="card-content">
            <pre class="terminal-block">${escapeHtml(String(payload.output || payload.result || ''))}</pre>
          </div>
        </div>
      `;
    }

    if (type === 'approval_requested') {
      const approvalId = payload.approval_id || evt.approval_id || '';
      return `
        <div class="timeline-card card-approval">
          <div class="card-header" style="color: var(--accent-amber);">
            <span>⚠️ Freigabe angefordert (Approval Required)</span>
            <span class="card-seq">#${evt.sequence || ''}</span>
          </div>
          <div class="card-content">
            <p><strong>Aktion:</strong> ${escapeHtml(payload.action || 'Side-effect operation')}</p>
            <p><strong>Details:</strong> ${escapeHtml(payload.description || JSON.stringify(payload))}</p>
            <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
              <button class="btn btn-primary btn-sm" onclick="AgentApp.handleApproval('${approvalId}', 'approve')">✓ Freigeben (Approve)</button>
              <button class="btn btn-secondary btn-sm" onclick="AgentApp.handleApproval('${approvalId}', 'reject')">✕ Ablehnen (Reject)</button>
            </div>
          </div>
        </div>
      `;
    }

    if (type === 'diff' || type === 'file_patch') {
      return `
        <div class="timeline-card card-diff">
          <div class="card-header">
            <span>📝 File Diff: ${escapeHtml(payload.path || '')}</span>
            <span class="card-seq">#${evt.sequence || ''}</span>
          </div>
          <div class="card-content">
            <pre class="diff-block">${escapeHtml(payload.diff || payload.patch || '')}</pre>
          </div>
        </div>
      `;
    }

    return `
      <div class="timeline-card card-generic">
        <div class="card-header">
          <span>ℹ️ ${escapeHtml(type)}</span>
          <span class="card-seq">#${evt.sequence || ''}</span>
        </div>
        <div class="card-content">${escapeHtml(JSON.stringify(payload))}</div>
      </div>
    `;
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  return {
    renderTimeline
  };
});
