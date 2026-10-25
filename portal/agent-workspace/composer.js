// SPDX-License-Identifier: Apache-2.0
/**
 * ComputeMesh Agent Workspace - Composer Component
 * Multiline input, Queue Turn vs Priority Steer modes, Stop/Pause/Resume, shortcut support.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./state'), require('./i18n'));
  } else {
    root.AgentComposer = factory(root.AgentState, root.AgentI18n);
  }
})(typeof self !== 'undefined' ? self : this, function (AgentState, AgentI18n) {
  'use strict';

  let currentMode = 'queue';

  function setMode(mode) {
    currentMode = mode === 'steer' ? 'steer' : 'queue';
    AgentState.state.composerMode = currentMode;

    const queueBtn = document.getElementById('mode-queue-btn');
    const steerBtn = document.getElementById('mode-steer-btn');
    const hint = document.getElementById('composer-hint');

    if (queueBtn) queueBtn.classList.toggle('active', currentMode === 'queue');
    if (steerBtn) steerBtn.classList.toggle('active', currentMode === 'steer');
    if (hint) {
      hint.textContent = currentMode === 'queue' ? AgentI18n.t('hintQueue') : AgentI18n.t('hintSteer');
    }
  }

  function getMode() {
    return currentMode;
  }

  async function handleSend() {
    const input = document.getElementById('composer-textarea');
    if (!input) return;
    const text = (input.value || '').trim();
    if (!text) return;

    const { activeSessionId } = AgentState.state;
    if (!activeSessionId) {
      alert('Bitte wählen Sie zuerst eine Sitzung aus oder erstellen Sie eine neue Aufgabe.');
      return;
    }

    input.value = '';
    const success = await AgentState.submitTurn(activeSessionId, text, currentMode);
    if (success) {
      await AgentState.loadEvents(activeSessionId, AgentState.state.eventCursor);
      if (typeof AgentTimeline !== 'undefined') {
        const container = document.getElementById('timeline-container');
        AgentTimeline.renderTimeline(container);
      }
    }
  }

  return {
    setMode,
    getMode,
    handleSend
  };
});
