// SPDX-License-Identifier: Apache-2.0
/**
 * ComputeMesh Agent Workspace - State & Event Management
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./auth'));
  } else {
    root.AgentState = factory(root.AgentAuth);
  }
})(typeof self !== 'undefined' ? self : this, function (AgentAuth) {
  'use strict';

  const state = {
    allSessions: [],
    activeSessionId: null,
    activeSession: null,
    events: [],
    artifacts: [],
    approvals: [],
    currentTab: 'active',
    composerMode: 'queue',
    pollTimer: null,
    eventCursor: 0
  };

  async function loadSessions() {
    try {
      const resp = await AgentAuth.fetchWithAuth('/v1/agents/sessions?limit=100');
      if (resp.ok) {
        const data = await resp.json();
        state.allSessions = Array.isArray(data && data.sessions) ? data.sessions : [];
        return state.allSessions;
      }
    } catch (err) {
      console.warn('[AgentState] loadSessions error:', err);
    }
    return [];
  }

  async function loadSessionDetails(sessionId) {
    if (!sessionId) return null;
    try {
      const resp = await AgentAuth.fetchWithAuth(`/v1/agents/sessions/${encodeURIComponent(sessionId)}`);
      if (resp.ok) {
        state.activeSession = await resp.json();
        state.activeSessionId = sessionId;
        return state.activeSession;
      }
    } catch (err) {
      console.warn('[AgentState] loadSessionDetails error:', err);
    }
    return null;
  }

  async function loadEvents(sessionId, afterSequence = 0) {
    if (!sessionId) return [];
    try {
      const url = `/v1/agents/sessions/${encodeURIComponent(sessionId)}/events?after_sequence=${afterSequence}&limit=200`;
      const resp = await AgentAuth.fetchWithAuth(url);
      if (resp.ok) {
        const data = await resp.json();
        const newEvents = Array.isArray(data && data.events) ? data.events : [];
        if (newEvents.length > 0) {
          const maxSeq = Math.max(...newEvents.map(e => e.sequence || 0));
          if (maxSeq > state.eventCursor) state.eventCursor = maxSeq;
          state.events.push(...newEvents);
        }
        return newEvents;
      }
    } catch (err) {
      console.warn('[AgentState] loadEvents error:', err);
    }
    return [];
  }

  async function loadArtifacts(sessionId) {
    if (!sessionId) return [];
    try {
      const resp = await AgentAuth.fetchWithAuth(`/v1/agents/sessions/${encodeURIComponent(sessionId)}/artifacts`);
      if (resp.ok) {
        const data = await resp.json();
        state.artifacts = Array.isArray(data && data.artifacts) ? data.artifacts : [];
        return state.artifacts;
      }
    } catch (err) {
      console.warn('[AgentState] loadArtifacts error:', err);
    }
    return [];
  }

  async function submitTurn(sessionId, prompt, mode = 'queue', options = {}) {
    if (!sessionId || !prompt) return false;
    try {
      const path = mode === 'steer'
        ? `/v1/agents/sessions/${encodeURIComponent(sessionId)}/steer`
        : `/v1/agents/sessions/${encodeURIComponent(sessionId)}/turns`;
      const resp = await AgentAuth.fetchWithAuth(path, {
        method: 'POST',
        body: JSON.stringify({
          prompt,
          mode,
          ...options
        })
      });
      return resp.ok;
    } catch (err) {
      console.warn('[AgentState] submitTurn error:', err);
      return false;
    }
  }

  async function controlSession(sessionId, action) {
    if (!sessionId || !action) return false;
    try {
      const resp = await AgentAuth.fetchWithAuth(`/v1/agents/sessions/${encodeURIComponent(sessionId)}/control`, {
        method: 'POST',
        body: JSON.stringify({ action })
      });
      return resp.ok;
    } catch (err) {
      console.warn('[AgentState] controlSession error:', err);
      return false;
    }
  }

  async function decideApproval(approvalId, decision) {
    if (!approvalId || !decision) return false;
    try {
      const resp = await AgentAuth.fetchWithAuth(`/v1/agents/approvals/${encodeURIComponent(approvalId)}`, {
        method: 'POST',
        body: JSON.stringify({ decision })
      });
      return resp.ok;
    } catch (err) {
      console.warn('[AgentState] decideApproval error:', err);
      return false;
    }
  }

  return {
    state,
    loadSessions,
    loadSessionDetails,
    loadEvents,
    loadArtifacts,
    submitTurn,
    controlSession,
    decideApproval
  };
});
