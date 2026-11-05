package com.inetconnector.compumesh.ui.models

data class AgentWorkspaceItem(
    val id: String,
    val name: String,
    val path: String,
    val nodeId: String = "cm-win-mifcom-rtx3080",
    val gitBranch: String = "",
    val registrationSource: String = "user_registered",
    val status: String = "active"
) {
    val displaySource: String
        get() = when (registrationSource.lowercase()) {
            "auto_discovered" -> "Auto-Scan"
            "node_heartbeat" -> "Node"
            else -> "Lokal"
        }
}

data class AgentTaskItem(
    val sessionId: String,
    val title: String,
    val workspace: String = "",
    val status: String = "ready",
    val createdAt: Long = System.currentTimeMillis(),
    val archived: Boolean = false
)

sealed interface WorkspaceUiState {
    object Loading : WorkspaceUiState
    data class Success(
        val workspaces: List<AgentWorkspaceItem>,
        val activeWorkspace: AgentWorkspaceItem?
    ) : WorkspaceUiState
    object Empty : WorkspaceUiState
    data class Offline(val message: String) : WorkspaceUiState
    data class Error(val message: String) : WorkspaceUiState
}

sealed interface TaskUiState {
    object Loading : TaskUiState
    data class Success(val tasks: List<AgentTaskItem>) : TaskUiState
    object Empty : TaskUiState
    data class Error(val message: String) : TaskUiState
}

