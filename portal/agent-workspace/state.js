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
    eventCursor: 0,
    nodes: [],
    workspaces: [],
    activeNodeId: null,
    activeWorkspaceId: null,
    activeWorkspace: null,
    models: []
  };

  async function loadFleetWorkspaces() {
    try {
      const resp = await AgentAuth.fetchWithAuth('/v1/fleet/workspaces');
      if (resp.ok) {
        const data = await resp.json();
        state.workspaces = Array.isArray(data && data.workspaces) ? data.workspaces : [];
        state.nodes = Array.isArray(data && data.nodes) ? data.nodes : [];
        if (!state.activeNodeId && (data && data.active_node_id)) {
          state.activeNodeId = data.active_node_id;
        } else if (!state.activeNodeId && state.nodes.length > 0) {
          state.activeNodeId = state.nodes[0].node_id;
        }
        if (!state.activeWorkspaceId && state.workspaces.length > 0) {
          state.activeWorkspaceId = state.workspaces[0].id;
          state.activeWorkspace = state.workspaces[0];
        } else if (state.activeWorkspaceId) {
          state.activeWorkspace = state.workspaces.find(w => w.id === state.activeWorkspaceId) || state.workspaces[0] || null;
        }
        return { workspaces: state.workspaces, nodes: state.nodes };
      }
    } catch (err) {
      console.warn('[AgentState] loadFleetWorkspaces error:', err);
    }
    return { workspaces: [], nodes: [] };
  }

  async function registerWorkspace(path, name) {
    if (!path) return null;
    try {
      const resp = await AgentAuth.fetchWithAuth('/v1/fleet/workspaces', {
        method: 'POST',
        body: JSON.stringify({
          path: path.trim(),
          name: name ? name.trim() : undefined,
          node_id: state.activeNodeId
        })
      });
      if (resp.ok) {
        const result = await resp.json();
        await loadFleetWorkspaces();
        return result;
      }
    } catch (err) {
      console.warn('[AgentState] registerWorkspace error:', err);
    }
    return null;
  }

  async function loadModels() {
    try {
      const resp = await AgentAuth.fetchWithAuth('/v1/models');
      if (resp.ok) {
        const data = await resp.json();
        const raw = Array.isArray(data && data.data) ? data.data : (Array.isArray(data && data.models) ? data.models : []);
        state.models = raw.map(m => {
          if (typeof m === 'string') return { id: m, name: m };
          return { id: m.id || m.model || m.name, name: m.name || m.id || m.model };
        });
        return state.models;
      }
    } catch (err) {
      console.warn('[AgentState] loadModels error:', err);
    }
    // Fallback to authentic supported cluster models if endpoint unreachable
    state.models = [
      { id: 'qwen2.5-coder:32b', name: 'Qwen 2.5 Coder 32B (Inference Engine)' },
      { id: 'deepseek-r1:70b', name: 'DeepSeek R1 70B (P2P Cluster / Kimi RPC)' },
      { id: 'gemma3:4b', name: 'Gemma 3 4B (Local CUDA / Node)' },
      { id: 'llama-3.3:70b', name: 'Llama 3.3 70B (Mesh Reasoning)' }
    ];
    return state.models;
  }

  async function createSession(workspaceId, model, policy = 'interactive') {
    try {
      const resp = await AgentAuth.fetchWithAuth('/v1/agents/sessions', {
        method: 'POST',
        body: JSON.stringify({
          workspace_id: workspaceId || state.activeWorkspaceId,
          model: model || (state.models[0] && state.models[0].id),
          policy: policy
        })
      });
      if (resp.ok) {
        const newSession = await resp.json();
        await loadSessions();
        if (newSession && newSession.session_id) {
          state.activeSessionId = newSession.session_id;
          state.activeSession = newSession;
        }
        return newSession;
      }
    } catch (err) {
      console.warn('[AgentState] createSession error:', err);
    }
    return null;
  }

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
    decideApproval,
    loadFleetWorkspaces,
    registerWorkspace,
    loadModels,
    createSession
  };
});
