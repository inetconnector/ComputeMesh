// SPDX-License-Identifier: Apache-2.0
/**
 * ComputeMesh Agent Workspace - Internationalization (DE / EN)
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.AgentI18n = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const translations = {
    de: {
      brandBadge: "AGENT WORKSPACE",
      navFleet: "🖥️ Flotte",
      navChat: "💬 AI-Chat ↗",
      btnNewTask: "+ Neue Aufgabe",
      lblWorkspace: "Workspace:",
      lblBranch: "Branch:",
      lblNode: "Node:",
      lblModel: "Model:",
      lblPolicy: "Policy:",
      searchPlaceholder: "Sitzung suchen...",
      tabActive: "Aktiv",
      tabPinned: "Angeheftet",
      tabArchived: "Archiv",
      modeQueue: "📥 Turn einreihen (Queue)",
      modeSteer: "⚡ Turn steuern (Steer)",
      hintQueue: "Normaler Folgeauftrag – wird nach aktuellem Turn ausgeführt",
      hintSteer: "Echtzeit-Steuerung – unterbricht oder lenkt den aktiven Turn sofort um",
      btnSend: "Senden",
      inspectorPlan: "Aktiver Ausführungsplan",
      inspectorGoal: "Dauerhaftes Ziel (Grand Goal)",
      inspectorArtifacts: "Erzeugte Artefakte",
      inspectorFiles: "Geänderte Dateien (Diff / Review)",
      inspectorMetrics: "Kontext- & Laufzeitmetriken",
      inspectorCluster: "Mesh Node & Inferenzstatus",
      statusReady: "BEREIT",
      statusRunning: "LÄUFT",
      statusPaused: "PAUSIERT",
      statusWaitingTool: "WARTET AUF TOOL",
      statusWaitingApproval: "APPROVAL ERFORDERLICH",
      statusCompleted: "ABGESCHLOSSEN",
      statusFailed: "FEHLGESCHLAGEN",
      statusCancelled: "ABGEBROCHEN",
      emptyTimeline: "Noch keine Aktivität vorhanden. Starte eine Aufgabe über den Composer unten.",
      emptySessions: "Keine Sitzungen gefunden."
    },
    en: {
      brandBadge: "AGENT WORKSPACE",
      navFleet: "🖥️ Fleet",
      navChat: "💬 AI Chat ↗",
      btnNewTask: "+ New Task",
      lblWorkspace: "Workspace:",
      lblBranch: "Branch:",
      lblNode: "Node:",
      lblModel: "Model:",
      lblPolicy: "Policy:",
      searchPlaceholder: "Search sessions...",
      tabActive: "Active",
      tabPinned: "Pinned",
      tabArchived: "Archived",
      modeQueue: "📥 Queue Turn",
      modeSteer: "⚡ Steer Turn",
      hintQueue: "Standard follow-up turn – executed after current turn finishes",
      hintSteer: "Priority steering – interrupts or redirects active turn immediately",
      btnSend: "Send",
      inspectorPlan: "Active Execution Plan",
      inspectorGoal: "Persistent Goal (Grand Goal)",
      inspectorArtifacts: "Produced Artifacts",
      inspectorFiles: "Changed Files (Diff / Review)",
      inspectorMetrics: "Context & Runtime Metrics",
      inspectorCluster: "Mesh Node & Inference Status",
      statusReady: "READY",
      statusRunning: "RUNNING",
      statusPaused: "PAUSED",
      statusWaitingTool: "WAITING FOR TOOL",
      statusWaitingApproval: "APPROVAL REQUIRED",
      statusCompleted: "COMPLETED",
      statusFailed: "FAILED",
      statusCancelled: "CANCELLED",
      emptyTimeline: "No activity yet. Start a task using the composer below.",
      emptySessions: "No sessions found."
    }
  };

  let currentLocale = 'de';

  function getLocale() {
    return currentLocale;
  }

  function setLocale(locale) {
    if (translations[locale]) {
      currentLocale = locale;
    }
    return currentLocale;
  }

  function t(key) {
    const dict = translations[currentLocale] || translations.en;
    return dict[key] || translations.en[key] || key;
  }

  return {
    translations,
    getLocale,
    setLocale,
    t
  };
});
