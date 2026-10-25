// SPDX-License-Identifier: Apache-2.0
/**
 * ComputeMesh Agent Workspace - Sidebar Component
 * Manages projects, session list, search filter, active/pinned/archived tabs.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./state'), require('./i18n'));
  } else {
    root.AgentSidebar = factory(root.AgentState, root.AgentI18n);
  }
})(typeof self !== 'undefined' ? self : this, function (AgentState, AgentI18n) {
  'use strict';

  function renderSessionList(container, onSelectSession) {
    if (!container) return;
    const { allSessions, currentTab, activeSessionId } = AgentState.state;
    const searchInput = document.getElementById('sidebar-search-input');
    const query = searchInput ? (searchInput.value || '').toLowerCase() : '';

    const filtered = allSessions.filter(s => {
      const matchText = (s.title || s.session_id || '').toLowerCase();
      if (query && !matchText.includes(query)) return false;
      if (currentTab === 'pinned') return s.pinned === true;
      if (currentTab === 'archived') return s.archived === true;
      return !s.archived;
    });

    if (filtered.length === 0) {
      container.innerHTML = `<div style="padding: 1.5rem; color: var(--text-muted); font-size: 0.85rem; text-align: center;">${AgentI18n.t('emptySessions')}</div>`;
      return;
    }

    container.innerHTML = filtered.map(s => {
      const isActive = s.session_id === activeSessionId;
      const statusClass = `status-${(s.status || 'ready').toLowerCase()}`;
      return `
        <div class="session-card ${isActive ? 'active' : ''}" data-id="${s.session_id}" onclick="AgentApp.selectSession('${s.session_id}')">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem;">
            <span class="session-title">${escapeHtml(s.title || s.session_id)}</span>
            <span class="status-badge ${statusClass}">${(s.status || 'READY').toUpperCase()}</span>
          </div>
          <div class="session-meta">
            <span>${escapeHtml(s.model || 'auto')}</span>
            <span>·</span>
            <span>${formatTime(s.created_at)}</span>
          </div>
        </div>
      `;
    }).join('');
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatTime(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (_) {
      return '';
    }
  }

  return {
    renderSessionList
  };
});
