package com.inetconnector.compumesh.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.inetconnector.compumesh.p2p.LocalMeshPeer
import com.inetconnector.compumesh.ui.models.AgentTaskItem
import com.inetconnector.compumesh.ui.models.AgentWorkspaceItem
import com.inetconnector.compumesh.ui.models.TaskUiState
import com.inetconnector.compumesh.ui.theme.*

/**
 * Codex-oriented Active Workspace and Task Management View for Mobile screens.
 * Focuses on active task, real workspaces, source provenance, and authentic operations.
 */
@Composable
fun AgentWorkspaceView(
    detectedNode: LocalMeshPeer?,
    activeWorkspaceItem: AgentWorkspaceItem?,
    tasksList: List<AgentTaskItem>,
    taskUiState: TaskUiState,
    onSwitchWorkspace: () -> Unit,
    onShowDetails: () -> Unit,
    onUnregister: () -> Unit,
    onSelectTask: (AgentTaskItem) -> Unit,
    onDeleteTask: (AgentTaskItem) -> Unit,
    onNewTask: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp)
    ) {
        // Node Status Card
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = CardSurface,
            border = BorderStroke(1.dp, CardSurfaceBorder),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(if (detectedNode != null) EmeraldSuccess else AmberWarning)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = detectedNode?.nodeId ?: "cm-win-mifcom-rtx3080",
                        fontWeight = FontWeight.Bold,
                        fontSize = 14.sp,
                        color = TextPrimary
                    )
                    Spacer(modifier = Modifier.weight(1f))
                    Text(
                        text = if (detectedNode != null) "Online" else "Suche läuft...",
                        fontSize = 12.sp,
                        color = if (detectedNode != null) EmeraldSuccess else AmberWarning
                    )
                }
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = detectedNode?.gpuSummary ?: "NVIDIA GeForce RTX 3080 10GB • Local PC",
                    fontSize = 12.sp,
                    color = TextMuted
                )
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Active Workspace Card
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = CardSurface,
            border = BorderStroke(1.dp, CardSurfaceBorder),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        Icons.Default.Folder,
                        contentDescription = null,
                        tint = IndigoAccent,
                        modifier = Modifier.size(20.dp)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = activeWorkspaceItem?.name ?: "Kein Projekt ausgewählt",
                        fontWeight = FontWeight.Bold,
                        fontSize = 15.sp,
                        color = TextPrimary,
                        modifier = Modifier.weight(1f),
                        maxLines = 1
                    )
                    if (activeWorkspaceItem != null) {
                        Surface(
                            shape = RoundedCornerShape(4.dp),
                            color = BubbleSurface,
                            modifier = Modifier.padding(end = 4.dp)
                        ) {
                            Text(
                                text = activeWorkspaceItem.displaySource,
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Medium,
                                color = TextSecondary,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                        if (activeWorkspaceItem.gitBranch.isNotBlank()) {
                            Surface(
                                shape = RoundedCornerShape(4.dp),
                                color = BubbleSurface
                            ) {
                                Text(
                                    text = activeWorkspaceItem.gitBranch,
                                    fontSize = 10.sp,
                                    color = TextSecondary,
                                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                                )
                            }
                        }
                    }
                }

                if (activeWorkspaceItem != null) {
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text = activeWorkspaceItem.path,
                        fontSize = 11.5.sp,
                        fontFamily = FontFamily.Monospace,
                        color = TextMuted,
                        maxLines = 2
                    )
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Actions (touch target >= 48dp)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Button(
                        onClick = onSwitchWorkspace,
                        colors = ButtonDefaults.buttonColors(containerColor = PillSurface),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.weight(1f).height(48.dp)
                    ) {
                        Icon(Icons.Default.SwapHoriz, contentDescription = null, modifier = Modifier.size(16.dp), tint = TextPrimary)
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Wechseln", fontSize = 12.sp, color = TextPrimary)
                    }
                    Button(
                        onClick = onShowDetails,
                        colors = ButtonDefaults.buttonColors(containerColor = PillSurface),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.height(48.dp),
                        enabled = activeWorkspaceItem != null
                    ) {
                        Icon(Icons.Default.Info, contentDescription = null, modifier = Modifier.size(16.dp), tint = TextSecondary)
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("Details", fontSize = 12.sp, color = TextSecondary)
                    }
                    Button(
                        onClick = onUnregister,
                        colors = ButtonDefaults.buttonColors(containerColor = PillSurface),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.height(48.dp),
                        enabled = activeWorkspaceItem != null
                    ) {
                        Icon(Icons.Default.Delete, contentDescription = null, modifier = Modifier.size(16.dp), tint = AmberWarning)
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("Entfernen", fontSize = 12.sp, color = AmberWarning)
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(18.dp))

        // Tasks Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = "Aufgaben im Workspace (${tasksList.size})",
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                color = TextMuted
            )
            TextButton(onClick = onNewTask) {
                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp), tint = IndigoAccent)
                Spacer(modifier = Modifier.width(4.dp))
                Text("Neue Aufgabe", fontSize = 12.sp, color = IndigoAccent)
            }
        }

        Spacer(modifier = Modifier.height(6.dp))

        if (taskUiState is TaskUiState.Loading) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(vertical = 12.dp)
            ) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = IndigoAccent)
                Spacer(modifier = Modifier.width(10.dp))
                Text("Lade Aufgaben aus ControlPlane...", fontSize = 13.sp, color = TextMuted)
            }
        } else if (tasksList.isEmpty()) {
            Surface(
                shape = RoundedCornerShape(12.dp),
                color = PillSurface,
                border = BorderStroke(1.dp, CardSurfaceBorder),
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(
                        text = "Keine Aufgaben in diesem Workspace.",
                        fontSize = 13.sp,
                        color = TextSecondary
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Gib unten einen Prompt ein, um eine autonome Aufgabe zu starten.",
                        fontSize = 12.sp,
                        color = TextMuted
                    )
                }
            }
        } else {
            tasksList.forEach { task ->
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = PillSurface,
                    border = BorderStroke(1.dp, CardSurfaceBorder),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 3.dp)
                        .clickable { onSelectTask(task) }
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)
                    ) {
                        Icon(
                            Icons.Default.ChatBubbleOutline,
                            contentDescription = null,
                            tint = TextSecondary,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(modifier = Modifier.width(10.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = task.title,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Medium,
                                color = TextPrimary,
                                maxLines = 1
                            )
                            Text(
                                text = "Status: ${task.status}",
                                fontSize = 11.sp,
                                color = TextMuted
                            )
                        }
                        IconButton(
                            onClick = { onDeleteTask(task) },
                            modifier = Modifier.size(36.dp)
                        ) {
                            Icon(
                                Icons.Default.Delete,
                                contentDescription = "Aufgabe löschen",
                                tint = TextMuted,
                                modifier = Modifier.size(16.dp)
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * Modal Bottom Sheet for Workspace Switcher (Codex Parity)
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProjectSwitcherBottomSheet(
    show: Boolean,
    onDismiss: () -> Unit,
    workspaces: List<AgentWorkspaceItem>,
    activeWorkspace: AgentWorkspaceItem?,
    onSelect: (AgentWorkspaceItem) -> Unit
) {
    if (!show) return
    var query by remember { mutableStateOf("") }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = CardSurface
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp)
        ) {
            Text(
                text = "Workspaces & Projekte",
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
                color = TextPrimary
            )
            Spacer(modifier = Modifier.height(10.dp))

            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                placeholder = { Text("Projekt suchen...", fontSize = 13.sp, color = TextMuted) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = IndigoAccent,
                    unfocusedBorderColor = CardSurfaceBorder,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary
                )
            )

            Spacer(modifier = Modifier.height(12.dp))

            val filtered = if (query.isBlank()) workspaces else workspaces.filter {
                it.name.contains(query, ignoreCase = true) || it.path.contains(query, ignoreCase = true)
            }

            if (filtered.isEmpty()) {
                Box(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text("Keine passenden Workspaces gefunden", color = TextMuted, fontSize = 13.sp)
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().heightIn(max = 380.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    items(filtered.size) { idx ->
                        val ws = filtered[idx]
                        val isSelected = ws.id == activeWorkspace?.id
                        Surface(
                            shape = RoundedCornerShape(12.dp),
                            color = if (isSelected) BubbleSurface else PillSurface,
                            border = BorderStroke(1.dp, if (isSelected) IndigoAccent else CardSurfaceBorder),
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    onSelect(ws)
                                    onDismiss()
                                }
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)
                            ) {
                                Icon(
                                    Icons.Default.Folder,
                                    contentDescription = null,
                                    tint = if (isSelected) IndigoAccent else TextSecondary,
                                    modifier = Modifier.size(20.dp)
                                )
                                Spacer(modifier = Modifier.width(10.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = ws.name,
                                        fontWeight = FontWeight.SemiBold,
                                        fontSize = 14.sp,
                                        color = TextPrimary,
                                        maxLines = 1
                                    )
                                    Text(
                                        text = "${ws.displaySource} • ${ws.path}",
                                        fontSize = 11.sp,
                                        color = TextMuted,
                                        maxLines = 1
                                    )
                                }
                                if (ws.gitBranch.isNotBlank()) {
                                    Surface(
                                        shape = RoundedCornerShape(4.dp),
                                        color = CardSurface,
                                        modifier = Modifier.padding(horizontal = 4.dp)
                                    ) {
                                        Text(
                                            text = ws.gitBranch,
                                            fontSize = 10.sp,
                                            color = TextSecondary,
                                            modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(16.dp))
        }
    }
}

/**
 * Project Details Dialog
 */
@Composable
fun ProjectDetailsDialog(
    workspace: AgentWorkspaceItem?,
    onDismiss: () -> Unit
) {
    if (workspace == null) return
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = CardSurface,
        title = { Text("Projekt-Details", fontWeight = FontWeight.Bold, color = TextPrimary) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Name: ${workspace.name}", color = TextPrimary, fontSize = 13.sp)
                Text("ID: ${workspace.id}", color = TextSecondary, fontSize = 12.sp)
                Text("Pfad: ${workspace.path}", color = TextSecondary, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                Text("Git-Branch: ${workspace.gitBranch.ifBlank { "Kein Git" }}", color = TextSecondary, fontSize = 12.sp)
                Text("Quelle: ${workspace.displaySource} (${workspace.registrationSource})", color = TextSecondary, fontSize = 12.sp)
                Text("Node: ${workspace.nodeId}", color = TextSecondary, fontSize = 12.sp)
                Text("Status: ${workspace.status}", color = TextSecondary, fontSize = 12.sp)
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text("Schließen", color = IndigoAccent)
            }
        }
    )
}

/**
 * Unregister Workspace Dialog (Removes from list, preserves physical files)
 */
@Composable
fun UnregisterWorkspaceConfirmDialog(
    workspace: AgentWorkspaceItem?,
    onDismiss: () -> Unit,
    onConfirm: (AgentWorkspaceItem) -> Unit
) {
    if (workspace == null) return
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = CardSurface,
        title = { Text("Aus Liste entfernen?", fontWeight = FontWeight.Bold, color = TextPrimary) },
        text = {
            Text(
                "Möchtest du das Projekt '${workspace.name}' aus der Workspace-Liste abmelden?\n\nDer physische Ordner auf der Festplatte (${workspace.path}) bleibt unverändert erhalten.",
                color = TextSecondary,
                fontSize = 13.sp
            )
        },
        confirmButton = {
            Button(
                colors = ButtonDefaults.buttonColors(containerColor = AmberWarning),
                onClick = { onConfirm(workspace) }
            ) {
                Text("Aus Liste entfernen", color = Color.Black, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Abbrechen", color = TextSecondary)
            }
        }
    )
}

/**
 * Delete Session / Task Dialog
 */
@Composable
fun DeleteSessionConfirmDialog(
    task: AgentTaskItem?,
    onDismiss: () -> Unit,
    onConfirm: (AgentTaskItem) -> Unit
) {
    if (task == null) return
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = CardSurface,
        title = { Text("Aufgabe endgültig löschen?", fontWeight = FontWeight.Bold, color = RoseDanger) },
        text = {
            Text(
                "Möchtest du die Aufgabe '${task.title}' wirklich unwiderruflich aus der Datenbank löschen?\nAlle Zwischenschritte und Ereignisse gehen verloren.",
                color = TextSecondary,
                fontSize = 13.sp
            )
        },
        confirmButton = {
            Button(
                colors = ButtonDefaults.buttonColors(containerColor = RoseDanger),
                onClick = { onConfirm(task) }
            ) {
                Text("Endgültig löschen", color = Color.White, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Abbrechen", color = TextSecondary)
            }
        }
    )
}

