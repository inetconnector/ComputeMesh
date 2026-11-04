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
        <div class="sidebar-session-item session-card ${isActive ? 'active' : ''}" data-id="${s.session_id}" onclick="typeof selectSession === 'function' ? selectSession('${s.session_id}') : AgentApp.selectSession('${s.session_id}')">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem;">
            <span class="session-item-title session-title">${escapeHtml(s.title || s.session_id)}</span>
            <span class="status-badge ${statusClass}">${(s.status || 'READY').toUpperCase()}</span>
          </div>
          <div class="session-meta" style="display: flex; gap: 0.35rem; font-size: 0.7rem; color: var(--studio-text-tertiary, #94a3b8);">
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

  function renderNodeSelector(container, onSelectNode) {
    if (!container) return;
    const { nodes, activeNodeId } = AgentState.state;
    if (!nodes || nodes.length === 0) {
      container.innerHTML = `
        <div class="node-pill-status">
          <span class="status-indicator-dot online"></span>
          <span class="node-name-label">mifcom (cm-win-mifcom-rtx3080)</span>
        </div>
      `;
      return;
    }
    container.innerHTML = `
      <select class="node-select-dropdown" onchange="typeof selectNode === 'function' ? selectNode(this.value) : (AgentState.state.activeNodeId = this.value)">
        ${nodes.map(n => `
          <option value="${escapeHtml(n.node_id)}" ${n.node_id === activeNodeId ? 'selected' : ''}>
            ${escapeHtml(n.display_name || n.node_name || n.node_id)} ${n.is_online ? '(Online)' : ''}
          </option>
        `).join('')}
      </select>
    `;
  }

  function renderWorkspacesList(container, onSelectWorkspace) {
    if (!container) return;
    const { workspaces, activeWorkspaceId } = AgentState.state;
    if (!workspaces || workspaces.length === 0) {
      container.innerHTML = `<div style="padding: 1rem; color: var(--text-muted); font-size: 0.82rem; text-align: center;">Keine Projekte auf Node registriert.</div>`;
      return;
    }

    container.innerHTML = workspaces.map(w => {
      const isActive = w.id === activeWorkspaceId;
      const branchBadge = w.git_branch ? `<span class="project-branch-tag">${escapeHtml(w.git_branch)}</span>` : '';
      return `
        <div class="sidebar-project-item ${isActive ? 'active' : ''}" data-id="${escapeHtml(w.id)}" onclick="typeof selectWorkspace === 'function' ? selectWorkspace('${escapeHtml(w.id)}') : (AgentState.state.activeWorkspaceId = '${escapeHtml(w.id)}')">
          <span class="project-item-icon">📁</span>
          <span class="project-item-name" title="${escapeHtml(w.path)}">${escapeHtml(w.name || w.id)}</span>
          ${branchBadge}
        </div>
      `;
    }).join('');
  }

  return {
    renderSessionList,
    renderNodeSelector,
    renderWorkspacesList
  };
});
