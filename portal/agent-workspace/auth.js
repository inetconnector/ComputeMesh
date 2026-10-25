// SPDX-License-Identifier: Apache-2.0
/**
 * ComputeMesh Agent Workspace - Authentication & Gateway API Client
 * Enforces fail-closed token resolution and avoids insecure fallback tokens.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.AgentAuth = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function resolveAuthToken() {
    try {
      const explicit = localStorage.getItem('cm_auth_token') ||
                       localStorage.getItem('cm_session_token') ||
                       localStorage.getItem('cm_api_key') ||
                       localStorage.getItem('apiKey');
      if (explicit && explicit.trim()) {
        return explicit.trim().replace(/^["'`]|["'`]$/g, '').replace(/^Bearer\s+/i, '');
      }
      const match = document.cookie.match(/(?:^|;\s*)cm_session=([^;]+)/);
      if (match && match[1]) {
        return decodeURIComponent(match[1]).trim();
      }
    } catch (_) {}
    return null;
  }

  async function fetchWithAuth(url, options = {}) {
    const token = resolveAuthToken();
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    return fetch(url, {
      credentials: 'include',
      ...options,
      headers
    });
  }

  return {
    resolveAuthToken,
    fetchWithAuth
  };
});
