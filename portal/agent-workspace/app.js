// SPDX-License-Identifier: Apache-2.0
/**
 * ComputeMesh Agent Workspace - Main Coordinator Application
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(
      require('./auth'),
      require('./i18n'),
      require('./state'),
      require('./sidebar'),
      require('./timeline'),
      require('./composer'),
      require('./inspector')
    );
  } else {
    root.AgentApp = factory(
      root.AgentAuth,
      root.AgentI18n,
      root.AgentState,
      root.AgentSidebar,
      root.AgentTimeline,
      root.AgentComposer,
      root.AgentInspector
    );
  }
})(typeof self !== 'undefined' ? self : this, function (
  AgentAuth,
  AgentI18n,
  AgentState,
  AgentSidebar,
  AgentTimeline,
  AgentComposer,
  AgentInspector
) {
  'use strict';

  async function init() {
    // Check URL parameters for session_id or model
    const params = new URLSearchParams(window.location.search);
    const initialSessionId = params.get('session_id');

    // Load initial sessions
    const sessions = await AgentState.loadSessions();
    const listContainer = document.getElementById('session-list-container');
    if (listContainer) {
      AgentSidebar.renderSessionList(listContainer);
    }

    if (initialSessionId) {
      await selectSession(initialSessionId);
    } else if (sessions.length > 0) {
      await selectSession(sessions[0].session_id);
    }

    // Start background event polling every 2.5s
    setInterval(async () => {
      if (AgentState.state.activeSessionId) {
        const newEvents = await AgentState.loadEvents(
          AgentState.state.activeSessionId,
          AgentState.state.eventCursor
        );
        if (newEvents && newEvents.length > 0) {
          const timelineContainer = document.getElementById('timeline-container');
          if (timelineContainer) {
            AgentTimeline.renderTimeline(timelineContainer);
          }
          await AgentState.loadArtifacts(AgentState.state.activeSessionId);
          AgentInspector.renderInspector();
        }
      }
    }, 2500);
  }

  async function selectSession(sessionId) {
    if (!sessionId) return;
    AgentState.state.activeSessionId = sessionId;
    AgentState.state.events = [];
    AgentState.state.eventCursor = 0;

    await AgentState.loadSessionDetails(sessionId);
    await AgentState.loadEvents(sessionId, 0);
    await AgentState.loadArtifacts(sessionId);

    // Update active session UI
    const titleInput = document.getElementById('active-session-title');
    if (titleInput && AgentState.state.activeSession) {
      titleInput.value = AgentState.state.activeSession.title || sessionId;
    }

    const badge = document.getElementById('active-session-badge');
    if (badge && AgentState.state.activeSession) {
      const status = (AgentState.state.activeSession.status || 'ready').toLowerCase();
      badge.className = `status-badge status-${status}`;
      badge.textContent = status.toUpperCase();
    }

    // Re-render components
    const listContainer = document.getElementById('session-list-container');
    if (listContainer) AgentSidebar.renderSessionList(listContainer);

    const timelineContainer = document.getElementById('timeline-container');
    if (timelineContainer) AgentTimeline.renderTimeline(timelineContainer);

    AgentInspector.renderInspector();
  }

  async function handleApproval(approvalId, decision) {
    const ok = await AgentState.decideApproval(approvalId, decision);
    if (ok && AgentState.state.activeSessionId) {
      await AgentState.loadEvents(AgentState.state.activeSessionId, AgentState.state.eventCursor);
      const timelineContainer = document.getElementById('timeline-container');
      if (timelineContainer) AgentTimeline.renderTimeline(timelineContainer);
    }
  }

  return {
    init,
    selectSession,
    handleApproval
  };
});
