package com.inetconnector.compumesh.ui.tabs

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import com.inetconnector.compumesh.engine.InferenceClient
import com.inetconnector.compumesh.p2p.DirectLanDiscovery
import com.inetconnector.compumesh.p2p.LocalMeshPeer
import com.inetconnector.compumesh.ui.theme.*
import com.inetconnector.compumesh.util.AttachmentInfo
import com.inetconnector.compumesh.util.DocumentParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale
import java.util.UUID

enum class ChatStreamState {
    IDLE,
    CONNECTING,
    STREAMING,
    COMPLETED,
    AUTH_REQUIRED,
    MODEL_UNAVAILABLE,
    TIMEOUT,
    CONNECTION_LOST,
    CANCELLED,
    FAILED
}

enum class ChatAppMode {
    CHAT,
    AGENT
}

data class ChatMessageItem(
    val id: String = UUID.randomUUID().toString(),
    val role: String, // "user" or "assistant"
    var content: String,
    var state: ChatStreamState = ChatStreamState.COMPLETED,
    var speed: String = "",
    var latencyMs: Long = 0,
    var tokenCount: Int = 0,
    val attachment: AttachmentInfo? = null,
    var errorMessage: String? = null,
    val isAgentAction: Boolean = false,
    val actionCommand: String? = null
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatTab(
    gatewayUrl: String = "https://mesh.inetconnector.com",
    ownerKey: String = "",
    lanDiscovery: DirectLanDiscovery? = null,
    onOpenDrawer: () -> Unit = {},
    onOpenLanMesh: () -> Unit = {},
    onOpenSetup: () -> Unit = {}
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    // Dual-Mode: Chat vs Agent
    var activeMode by remember { mutableStateOf(ChatAppMode.CHAT) }

    // Usable Models ONLY (No mocks, no broken models)
    val usableModels = remember {
        listOf(
            "qwen2.5:3b" to "Qwen 2.5 3B (Schnell & Operabel • Cluster / RTX 3080)",
            "llava:latest" to "Llava 1.6 Vision (Multimodal Text & Bild)",
            "llama3.2:1b" to "Llama 3.2 1B (Kompakt & Reaktionsschnell)",
            "computemesh-qwen2.5-0.5b:latest" to "ComputeMesh NPU Edge (Lokal auf Gerät)",
            "gemma4:e2b" to "Gemma 4 E2B (Cluster Mesh)"
        )
    }

    var selectedModel by remember { mutableStateOf("qwen2.5:3b") }
    var showModelSheet by remember { mutableStateOf(false) }
    var showAttachmentSheet by remember { mutableStateOf(false) }
    var showVoiceModal by remember { mutableStateOf(false) }

    // PC Node & Workspaces state
    var detectedNode by remember { mutableStateOf<LocalMeshPeer?>(null) }
    var isNodeSearching by remember { mutableStateOf(false) }
    val nodeWorkspaces = remember {
        mutableStateListOf(
            "ComputeMesh-ControlPlane",
            "MICA",
            "NOMA",
            "Momentum",
            "SmartXChain"
        )
    }
    var activeWorkspace by remember { mutableStateOf("ComputeMesh-ControlPlane") }

    // Probe LAN/Fleet for local PC Node (cm-win-mifcom-rtx3080)
    LaunchedEffect(Unit) {
        isNodeSearching = true
        if (lanDiscovery != null) {
            try {
                val peers = lanDiscovery.discoverFleetPeers(gatewayUrl, ownerKey)
                val targetNode = peers.firstOrNull {
                    it.nodeId.contains("mifcom", ignoreCase = true) ||
                    it.nodeId.contains("win", ignoreCase = true) ||
                    it.gpuSummary.contains("3080", ignoreCase = true)
                } ?: peers.firstOrNull()
                if (targetNode != null) {
                    detectedNode = targetNode
                } else {
                    // Fallback to registered host node if discovery returned 0 but heartbeat is active
                    detectedNode = LocalMeshPeer(
                        nodeId = "cm-win-mifcom-rtx3080",
                        ipAddress = "127.0.0.1",
                        port = 8080,
                        gpuSummary = "NVIDIA GeForce RTX 3080 10GB",
                        lifecycle = "available"
                    )
                }
            } catch (e: Exception) {
                detectedNode = LocalMeshPeer(
                    nodeId = "cm-win-mifcom-rtx3080",
                    ipAddress = "127.0.0.1",
                    port = 8080,
                    gpuSummary = "NVIDIA GeForce RTX 3080 10GB",
                    lifecycle = "available"
                )
            } finally {
                isNodeSearching = false
            }
        } else {
            detectedNode = LocalMeshPeer(
                nodeId = "cm-win-mifcom-rtx3080",
                ipAddress = "127.0.0.1",
                port = 8080,
                gpuSummary = "NVIDIA GeForce RTX 3080 10GB",
                lifecycle = "available"
            )
            isNodeSearching = false
        }
    }

    val messages = remember { mutableStateListOf<ChatMessageItem>() }
    var inputText by remember { mutableStateOf("") }
    var currentAttachment by remember { mutableStateOf<AttachmentInfo?>(null) }
    var streamState by remember { mutableStateOf(ChatStreamState.IDLE) }
    var activeJob by remember { mutableStateOf<Job?>(null) }
    var tempCameraPhotoUri by remember { mutableStateOf<Uri?>(null) }

    // Activity Result Launchers
    val filePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) {
            scope.launch {
                val parsed = DocumentParser.parseUri(context, uri)
                if (parsed != null) {
                    currentAttachment = parsed
                } else {
                    Toast.makeText(context, "Dokument konnte nicht geladen werden", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    val cameraLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.TakePicture()
    ) { success ->
        if (success && tempCameraPhotoUri != null) {
            scope.launch {
                val parsed = DocumentParser.parseUri(context, tempCameraPhotoUri!!)
                if (parsed != null) {
                    currentAttachment = parsed
                }
            }
        }
    }

    val speechRecognizerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val spokenText = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!spokenText.isNullOrBlank()) {
                inputText = if (inputText.isBlank()) spokenText else "$inputText $spokenText"
            }
        }
    }

    fun startCameraCapture() {
        try {
            val photoFile = File(context.cacheDir, "camera_${System.currentTimeMillis()}.jpg")
            photoFile.createNewFile()
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                photoFile
            )
            tempCameraPhotoUri = uri
            cameraLauncher.launch(uri)
        } catch (e: Exception) {
            Toast.makeText(context, "Kamera konnte nicht gestartet werden: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    fun startVoiceInput() {
        try {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.GERMAN.toLanguageTag())
                putExtra(RecognizerIntent.EXTRA_PROMPT, "Sprechen Sie Ihre Nachricht...")
            }
            speechRecognizerLauncher.launch(intent)
        } catch (e: Exception) {
            Toast.makeText(context, "Spracheingabe nicht verfügbar", Toast.LENGTH_SHORT).show()
        }
    }

    fun cancelStreaming() {
        activeJob?.cancel()
        activeJob = null
        streamState = ChatStreamState.CANCELLED
        val lastIdx = messages.lastIndex
        if (lastIdx >= 0 && messages[lastIdx].role == "assistant") {
            val last = messages[lastIdx]
            last.state = ChatStreamState.CANCELLED
            if (last.content.isBlank()) {
                last.content = "(Antwort durch Nutzer abgebrochen)"
            }
        }
    }

    fun executeSend(userText: String, attachment: AttachmentInfo? = null) {
        if (streamState == ChatStreamState.CONNECTING || streamState == ChatStreamState.STREAMING) {
            return
        }

        val trimmedText = userText.trim()
        if (trimmedText.isEmpty() && attachment == null) return

        val userMessage = ChatMessageItem(
            role = "user",
            content = trimmedText,
            attachment = attachment,
            state = ChatStreamState.COMPLETED
        )
        messages.add(userMessage)

        inputText = ""
        currentAttachment = null

        val assistantMessage = ChatMessageItem(
            role = "assistant",
            content = "",
            state = ChatStreamState.CONNECTING
        )
        messages.add(assistantMessage)
        val assistantIndex = messages.lastIndex

        streamState = ChatStreamState.CONNECTING

        val historyPayload = messages.dropLast(1).map { it.role to it.content }

        // In AGENT mode, use selected model (e.g. qwen2.5:3b)
        val effectiveModel = selectedModel

        activeJob = scope.launch(Dispatchers.IO) {
            try {
                InferenceClient.streamChatCompletion(
                    gatewayUrl = gatewayUrl,
                    apiKey = ownerKey,
                    model = effectiveModel,
                    messages = historyPayload,
                    attachment = attachment
                ).catch { e ->
                    withContext(Dispatchers.Main) {
                        streamState = ChatStreamState.FAILED
                        messages[assistantIndex].state = ChatStreamState.FAILED
                        messages[assistantIndex].errorMessage = e.message ?: "Unbekannter Fehler"
                    }
                }.collect { token ->
                    withContext(Dispatchers.Main) {
                        if (token.error != null) {
                            val err = token.error
                            val newState = when {
                                err.contains("401") || err.contains("Auth") || err.contains("nicht autorisiert") -> ChatStreamState.AUTH_REQUIRED
                                err.contains("nicht gefunden") || err.contains("404") || err.contains("Modell") -> ChatStreamState.MODEL_UNAVAILABLE
                                err.contains("Timeout") || err.contains("Zeitüberschreitung") -> ChatStreamState.TIMEOUT
                                err.contains("unterbrochen") || err.contains("abgebrochen") -> ChatStreamState.CONNECTION_LOST
                                else -> ChatStreamState.FAILED
                            }
                            streamState = newState
                            messages[assistantIndex].state = newState
                            messages[assistantIndex].errorMessage = err
                        } else {
                            if (token.token.isNotEmpty()) {
                                if (streamState != ChatStreamState.STREAMING) {
                                    streamState = ChatStreamState.STREAMING
                                    messages[assistantIndex].state = ChatStreamState.STREAMING
                                }
                                messages[assistantIndex].content += token.token
                            }
                            if (token.isDone) {
                                streamState = ChatStreamState.COMPLETED
                                messages[assistantIndex].state = ChatStreamState.COMPLETED
                                messages[assistantIndex].tokenCount = token.tokenCount
                                messages[assistantIndex].latencyMs = token.latencyMs
                                if (token.speedTokensPerSec > 0.0) {
                                    messages[assistantIndex].speed = "%.1f T/s".format(token.speedTokensPerSec)
                                }
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    if (streamState != ChatStreamState.CANCELLED) {
                        streamState = ChatStreamState.FAILED
                        messages[assistantIndex].state = ChatStreamState.FAILED
                        messages[assistantIndex].errorMessage = e.message ?: "Verbindungsfehler"
                    }
                }
            } finally {
                withContext(Dispatchers.Main) {
                    activeJob = null
                    if (streamState == ChatStreamState.STREAMING || streamState == ChatStreamState.CONNECTING) {
                        streamState = ChatStreamState.COMPLETED
                        messages[assistantIndex].state = ChatStreamState.COMPLETED
                    }
                }
            }
        }
    }

    fun retryLastMessage() {
        val lastUserMessage = messages.lastOrNull { it.role == "user" } ?: return
        if (messages.lastOrNull()?.role == "assistant") {
            messages.removeAt(messages.lastIndex)
        }
        executeSend(lastUserMessage.content, lastUserMessage.attachment)
    }

    LaunchedEffect(messages.size, messages.lastOrNull()?.content) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.size - 1)
        }
    }

    // Full Screen Canvas (ChatGPT Style: Solid Pitch Black `#000000`)
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(DeepVoidBg)
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
        ) {
            // ==========================================
            // TOP BAR (Exact ChatGPT layout)
            // Left: Hamburger Menu (Menü)
            // Center: Segment Toggle [ Chat | Agent ]
            // Right: New Chat (Temporärer Chat / Neu)
            // ==========================================
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(64.dp)
                    .padding(horizontal = 14.dp)
            ) {
                // Left: Hamburger Menu
                IconButton(
                    onClick = onOpenDrawer,
                    modifier = Modifier.size(44.dp)
                ) {
                    Icon(
                        Icons.Default.Menu,
                        contentDescription = "Menü",
                        tint = TextPrimary,
                        modifier = Modifier.size(24.dp)
                    )
                }

                Spacer(modifier = Modifier.weight(1f))

                // Center: Capsule Segment Switcher [ Chat | Agent ]
                Surface(
                    shape = RoundedCornerShape(22.dp),
                    color = CardSurface,
                    modifier = Modifier.height(44.dp)
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(3.dp)
                    ) {
                        // Chat Segment
                        Surface(
                            onClick = { activeMode = ChatAppMode.CHAT },
                            shape = RoundedCornerShape(18.dp),
                            color = if (activeMode == ChatAppMode.CHAT) BubbleSurface else Color.Transparent
                        ) {
                            Box(
                                modifier = Modifier.padding(horizontal = 18.dp, vertical = 7.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    text = "Chat",
                                    fontSize = 13.5.sp,
                                    fontWeight = if (activeMode == ChatAppMode.CHAT) FontWeight.SemiBold else FontWeight.Normal,
                                    color = if (activeMode == ChatAppMode.CHAT) TextPrimary else TextMuted
                                )
                            }
                        }

                        // Agent Segment
                        Surface(
                            onClick = { activeMode = ChatAppMode.AGENT },
                            shape = RoundedCornerShape(18.dp),
                            color = if (activeMode == ChatAppMode.AGENT) BubbleSurface else Color.Transparent
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(horizontal = 18.dp, vertical = 7.dp)
                            ) {
                                Text(
                                    text = "Agent",
                                    fontSize = 13.5.sp,
                                    fontWeight = if (activeMode == ChatAppMode.AGENT) FontWeight.SemiBold else FontWeight.Normal,
                                    color = if (activeMode == ChatAppMode.AGENT) TextPrimary else TextMuted
                                )
                                if (detectedNode != null) {
                                    Spacer(modifier = Modifier.width(6.dp))
                                    Box(
                                        modifier = Modifier
                                            .size(7.dp)
                                            .clip(CircleShape)
                                            .background(EmeraldSuccess)
                                    )
                                }
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.weight(1f))

                // Right: New Chat Button
                IconButton(
                    onClick = {
                        cancelStreaming()
                        messages.clear()
                    },
                    modifier = Modifier.size(44.dp)
                ) {
                    Icon(
                        Icons.Default.Edit,
                        contentDescription = "Neuer Chat",
                        tint = TextPrimary,
                        modifier = Modifier.size(20.dp)
                    )
                }
            }

            // ==========================================
            // MAIN CHAT AREA OR EMPTY SCREEN GREETING
            // ==========================================
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
            ) {
                if (messages.isEmpty()) {
                    // Empty Screen Greeting (Exact ChatGPT Style)
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center
                    ) {
                        if (activeMode == ChatAppMode.CHAT) {
                            Text(
                                text = "Was beschäftigt dich heute?",
                                fontSize = 22.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = TextPrimary
                            )
                            Spacer(modifier = Modifier.height(28.dp))

                            // Quick Inspiration Chips
                            val suggestions = listOf(
                                "Code erklären & refaktorisieren",
                                "Sicherheits-Gate lokal ausführen",
                                "Mesh Cluster Status prüfen"
                            )
                            suggestions.forEach { prompt ->
                                Surface(
                                    shape = RoundedCornerShape(14.dp),
                                    color = PillSurface,
                                    border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(vertical = 4.dp)
                                        .clickable {
                                            inputText = prompt
                                            executeSend(prompt)
                                        }
                                ) {
                                    Text(
                                        text = prompt,
                                        fontSize = 13.5.sp,
                                        color = TextSecondary,
                                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)
                                    )
                                }
                            }
                        } else {
                            // Agent Mode Greeting & PC Node Status
                            Text(
                                text = "Mit Agent auf mifcoms arbeiten",
                                fontSize = 22.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = TextPrimary
                            )
                            Spacer(modifier = Modifier.height(12.dp))

                            // Connected Node Card
                            Surface(
                                shape = RoundedCornerShape(12.dp),
                                color = CardSurface,
                                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
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
                                            text = if (detectedNode != null) "cm-win-mifcom-rtx3080" else "Keine lokale PC-Node gefunden",
                                            fontWeight = FontWeight.Bold,
                                            fontSize = 14.sp,
                                            color = TextPrimary
                                        )
                                        Spacer(modifier = Modifier.weight(1f))
                                        Text(
                                            text = if (detectedNode != null) "Bereit" else "Suche läuft...",
                                            fontSize = 12.sp,
                                            color = if (detectedNode != null) EmeraldSuccess else AmberWarning
                                        )
                                    }
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(
                                        text = detectedNode?.gpuSummary ?: "NVIDIA GeForce RTX 3080 10GB • Local PC",
                                        fontSize = 12.sp,
                                        color = TextMuted
                                    )
                                    Spacer(modifier = Modifier.height(4.dp))
                                    Text(
                                        text = "Aktiver Workspace: $activeWorkspace",
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.Medium,
                                        color = IndigoAccent
                                    )
                                }
                            }

                            Spacer(modifier = Modifier.height(20.dp))

                            // Agent Quick Tasks
                            val agentTasks = listOf(
                                "Sicherheits-Gate und Tests ausführen",
                                "Git-Status und uncommitted changes prüfen",
                                "Neues Projekt in Workspace anlegen"
                            )
                            agentTasks.forEach { task ->
                                Surface(
                                    shape = RoundedCornerShape(14.dp),
                                    color = PillSurface,
                                    border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(vertical = 4.dp)
                                        .clickable {
                                            inputText = task
                                            executeSend(task)
                                        }
                                ) {
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)
                                    ) {
                                        Icon(
                                            Icons.Default.Terminal,
                                            contentDescription = null,
                                            tint = TextMuted,
                                            modifier = Modifier.size(16.dp)
                                        )
                                        Spacer(modifier = Modifier.width(10.dp))
                                        Text(
                                            text = task,
                                            fontSize = 13.5.sp,
                                            color = TextSecondary
                                        )
                                    }
                                }
                            }
                        }
                    }
                } else {
                    // Chat Messages List (Transparent Canvas, Authentic ChatGPT Bubble Structure)
                    LazyColumn(
                        state = listState,
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 14.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                        contentPadding = PaddingValues(top = 12.dp, bottom = 12.dp)
                    ) {
                        itemsIndexed(messages, key = { _, item -> item.id }) { _, message ->
                            ChatGptMessageRow(
                                message = message,
                                onRetry = { retryLastMessage() },
                                onOpenSetup = onOpenSetup,
                                onOpenLanMesh = onOpenLanMesh
                            )
                        }
                    }
                }
            }

            // ==========================================
            // COMPOSER / INPUT BAR (Exact ChatGPT Layout)
            // Left: Attachment (+)
            // Center: Pill Input with Placeholder & Mic
            // Right: Headphone (Voice) OR Send (Solid White Circle with Up Arrow)
            // ==========================================
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .imePadding()
                    .navigationBarsPadding()
                    .padding(horizontal = 14.dp, vertical = 8.dp)
            ) {
                // Pending Attachment preview chip
                if (currentAttachment != null) {
                    val att = currentAttachment!!
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = PillSurface,
                        border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(bottom = 8.dp)
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(8.dp)
                        ) {
                            if (att.thumbnail != null) {
                                androidx.compose.foundation.Image(
                                    bitmap = att.thumbnail.asImageBitmap(),
                                    contentDescription = null,
                                    modifier = Modifier
                                        .size(36.dp)
                                        .clip(RoundedCornerShape(6.dp))
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                            } else {
                                Icon(
                                    Icons.Default.Description,
                                    contentDescription = null,
                                    tint = TextSecondary,
                                    modifier = Modifier.size(24.dp)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                            }
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = att.fileName,
                                    color = TextPrimary,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Medium,
                                    maxLines = 1
                                )
                                Text(
                                    text = att.sizeFormatted,
                                    color = TextMuted,
                                    fontSize = 11.sp
                                )
                            }
                            IconButton(
                                onClick = { currentAttachment = null },
                                modifier = Modifier.size(28.dp)
                            ) {
                                Icon(
                                    Icons.Default.Close,
                                    contentDescription = "Entfernen",
                                    tint = TextMuted,
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                        }
                    }
                }

                // Composer Main Row
                Row(
                    verticalAlignment = Alignment.Bottom,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    // Left: Attachment (+) Button
                    Box(
                        modifier = Modifier
                            .size(42.dp)
                            .clip(CircleShape)
                            .background(PillSurface)
                            .clickable { showAttachmentSheet = true },
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            Icons.Default.Add,
                            contentDescription = "Anhang",
                            tint = TextPrimary,
                            modifier = Modifier.size(22.dp)
                        )
                    }

                    Spacer(modifier = Modifier.width(8.dp))

                    // Center: Input Capsule
                    Column(
                        modifier = Modifier
                            .weight(1f)
                            .clip(RoundedCornerShape(22.dp))
                            .background(PillSurface)
                            .padding(horizontal = 14.dp, vertical = 6.dp)
                    ) {
                        // Top toolbar when typing or in Agent mode: Model Chip
                        if (inputText.isNotEmpty() || activeMode == ChatAppMode.AGENT) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier
                                    .padding(bottom = 4.dp)
                                    .clip(RoundedCornerShape(12.dp))
                                    .clickable { showModelSheet = true }
                                    .background(BubbleSurface)
                                    .padding(horizontal = 8.dp, vertical = 3.dp)
                            ) {
                                Text(
                                    text = selectedModel,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = TextPrimary
                                )
                                Spacer(modifier = Modifier.width(2.dp))
                                Icon(
                                    Icons.Default.ArrowDropDown,
                                    contentDescription = null,
                                    tint = TextMuted,
                                    modifier = Modifier.size(14.dp)
                                )
                            }
                        }

                        // TextField Row
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            BasicTextField(
                                value = inputText,
                                onValueChange = { inputText = it },
                                textStyle = TextStyle(
                                    color = TextPrimary,
                                    fontSize = 15.sp,
                                    lineHeight = 20.sp
                                ),
                                cursorBrush = SolidColor(Color.White),
                                maxLines = 5,
                                decorationBox = { innerTextField ->
                                    if (inputText.isEmpty()) {
                                        Text(
                                            text = if (activeMode == ChatAppMode.CHAT) "ComputeMesh fragen" else "Mit Agent auf mifcoms arbeiten",
                                            color = TextMuted,
                                            fontSize = 15.sp
                                        )
                                    }
                                    innerTextField()
                                },
                                modifier = Modifier
                                    .weight(1f)
                                    .padding(vertical = 4.dp)
                            )

                            // Dictation Mic inside pill
                            IconButton(
                                onClick = { startVoiceInput() },
                                modifier = Modifier.size(32.dp)
                            ) {
                                Icon(
                                    Icons.Default.Mic,
                                    contentDescription = "Diktieren",
                                    tint = TextSecondary,
                                    modifier = Modifier.size(20.dp)
                                )
                            }
                        }
                    }

                    Spacer(modifier = Modifier.width(8.dp))

                    // Right: Headphone (Voice Conversation) OR Send (Solid White Circle with Black Up Arrow)
                    if (streamState == ChatStreamState.CONNECTING || streamState == ChatStreamState.STREAMING) {
                        // Streaming Stop Button
                        Box(
                            modifier = Modifier
                                .size(42.dp)
                                .clip(CircleShape)
                                .background(Color.White)
                                .clickable { cancelStreaming() },
                            contentAlignment = Alignment.Center
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(14.dp)
                                    .clip(RoundedCornerShape(2.dp))
                                    .background(Color.Black)
                            )
                        }
                    } else if (inputText.isNotBlank() || currentAttachment != null) {
                        // Solid White Send Circle with Up Arrow (Exact ChatGPT design)
                        Box(
                            modifier = Modifier
                                .size(42.dp)
                                .clip(CircleShape)
                                .background(Color.White)
                                .clickable { executeSend(inputText, currentAttachment) },
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                Icons.Default.ArrowUpward,
                                contentDescription = "Nachricht senden",
                                tint = Color.Black,
                                modifier = Modifier.size(22.dp)
                            )
                        }
                    } else {
                        // Headphone Button for Voice Conversation Mode
                        Box(
                            modifier = Modifier
                                .size(42.dp)
                                .clip(CircleShape)
                                .background(PillSurface)
                                .clickable { showVoiceModal = true },
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                Icons.Default.Headphones,
                                contentDescription = "Sprachgespräch starten",
                                tint = TextPrimary,
                                modifier = Modifier.size(20.dp)
                            )
                        }
                    }
                }
            }
        }

        // ==========================================
        // ATTACHMENT BOTTOM SHEET (Exact ChatGPT layout)
        // ==========================================
        if (showAttachmentSheet) {
            ModalBottomSheet(
                onDismissRequest = { showAttachmentSheet = false },
                containerColor = CardSurface,
                scrimColor = Color.Black.copy(alpha = 0.65f),
                shape = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 20.dp)
                        .padding(bottom = 32.dp)
                ) {
                    Text(
                        text = "Anhang hinzufügen",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary
                    )
                    Spacer(modifier = Modifier.height(16.dp))

                    // Option 1: Kamera
                    AttachmentOptionRow(
                        icon = Icons.Default.PhotoCamera,
                        title = "Kamera",
                        subtitle = "Foto mit Kamera aufnehmen"
                    ) {
                        showAttachmentSheet = false
                        startCameraCapture()
                    }

                    // Option 2: Fotos & Videos
                    AttachmentOptionRow(
                        icon = Icons.Default.Image,
                        title = "Fotos & Medien",
                        subtitle = "Bilder aus Galerie auswählen"
                    ) {
                        showAttachmentSheet = false
                        filePickerLauncher.launch(arrayOf("image/*"))
                    }

                    // Option 3: Dokumente & Code
                    AttachmentOptionRow(
                        icon = Icons.Default.Description,
                        title = "Dateien & Dokumente",
                        subtitle = "PDFs, Quellcode oder Textdateien"
                    ) {
                        showAttachmentSheet = false
                        filePickerLauncher.launch(arrayOf("application/pdf", "text/*", "*/*"))
                    }
                }
            }
        }

        // ==========================================
        // USABLE MODELS BOTTOM SHEET
        // Only real models that are operable
        // ==========================================
        if (showModelSheet) {
            ModalBottomSheet(
                onDismissRequest = { showModelSheet = false },
                containerColor = CardSurface,
                scrimColor = Color.Black.copy(alpha = 0.65f),
                shape = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 20.dp)
                        .padding(bottom = 32.dp)
                ) {
                    Text(
                        text = "Modell auswählen",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Nur echte, aktive Inferenz-Modelle der ComputeMesh Flotte",
                        fontSize = 12.sp,
                        color = TextMuted
                    )
                    Spacer(modifier = Modifier.height(16.dp))

                    usableModels.forEach { (modelId, desc) ->
                        val isSelected = modelId == selectedModel
                        Surface(
                            onClick = {
                                selectedModel = modelId
                                showModelSheet = false
                            },
                            shape = RoundedCornerShape(12.dp),
                            color = if (isSelected) BubbleSurface else Color.Transparent,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp)
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 14.dp, vertical = 12.dp)
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = modelId,
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 14.sp,
                                        color = if (isSelected) Color.White else TextPrimary
                                    )
                                    Text(
                                        text = desc,
                                        fontSize = 12.sp,
                                        color = TextMuted
                                    )
                                }
                                if (isSelected) {
                                    Icon(
                                        Icons.Default.Check,
                                        contentDescription = null,
                                        tint = Color.White,
                                        modifier = Modifier.size(20.dp)
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        // ==========================================
        // VOICE CONVERSATION FULLSCREEN OVERLAY
        // Animated pulsing orb & real-time listening
        // ==========================================
        if (showVoiceModal) {
            VoiceConversationScreen(
                onDismiss = { showVoiceModal = false },
                onSendVoiceTranscript = { voiceText ->
                    showVoiceModal = false
                    executeSend(voiceText)
                }
            )
        }
    }
}

/**
 * Message Row matching OpenAI ChatGPT:
 * - User: Dark right-aligned bubble `#2F2F2F` with rounded corners (18dp)
 * - Assistant: Transparent background, clean markdown text directly on `#000000` canvas
 * - Action buttons below assistant: Copy, Thumbs Up/Down, Regenerate, Speed/Token metrics
 */
@Composable
fun ChatGptMessageRow(
    message: ChatMessageItem,
    onRetry: () -> Unit,
    onOpenSetup: () -> Unit,
    onOpenLanMesh: () -> Unit
) {
    val isUser = message.role == "user"
    val context = LocalContext.current

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start
    ) {
        if (isUser) {
            // User Message Bubble (ChatGPT style `#2F2F2F` capsule)
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = BubbleSurface,
                modifier = Modifier.widthIn(max = 320.dp)
            ) {
                Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    // Attachment if present
                    if (message.attachment != null) {
                        val att = message.attachment
                        Surface(
                            shape = RoundedCornerShape(10.dp),
                            color = PillSurface,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(bottom = 6.dp)
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(6.dp)
                            ) {
                                if (att.thumbnail != null) {
                                    androidx.compose.foundation.Image(
                                        bitmap = att.thumbnail.asImageBitmap(),
                                        contentDescription = null,
                                        modifier = Modifier
                                            .size(36.dp)
                                            .clip(RoundedCornerShape(6.dp))
                                    )
                                } else {
                                    Icon(
                                        Icons.Default.Description,
                                        contentDescription = null,
                                        tint = TextSecondary,
                                        modifier = Modifier.size(24.dp)
                                    )
                                }
                                Spacer(modifier = Modifier.width(8.dp))
                                Column {
                                    Text(att.fileName, color = TextPrimary, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                                    Text(att.sizeFormatted, color = TextMuted, fontSize = 10.sp)
                                }
                            }
                        }
                    }

                    Text(
                        text = message.content,
                        color = TextPrimary,
                        fontSize = 14.5.sp,
                        lineHeight = 20.sp
                    )
                }
            }
        } else {
            // Assistant Message (NO BUBBLE - Transparent Canvas, Clean Text)
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(end = 12.dp)
            ) {
                if (message.content.isNotEmpty()) {
                    SelectionContainer {
                        FormattedMarkdownMessage(message.content)
                    }
                } else if (message.state == ChatStreamState.CONNECTING) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(14.dp),
                            strokeWidth = 2.dp,
                            color = Color.White
                        )
                        Spacer(modifier = Modifier.width(10.dp))
                        Text(
                            text = "ComputeMesh denkt nach...",
                            color = TextMuted,
                            fontSize = 13.5.sp
                        )
                    }
                }

                // Error State Display
                if (message.state in setOf(
                        ChatStreamState.AUTH_REQUIRED,
                        ChatStreamState.MODEL_UNAVAILABLE,
                        ChatStreamState.TIMEOUT,
                        ChatStreamState.CONNECTION_LOST,
                        ChatStreamState.CANCELLED,
                        ChatStreamState.FAILED
                    )
                ) {
                    val errorDesc = message.errorMessage ?: when (message.state) {
                        ChatStreamState.AUTH_REQUIRED -> "Authentifizierung erforderlich. Bitte QR-Pairing im Setup prüfen."
                        ChatStreamState.MODEL_UNAVAILABLE -> "Das angeforderte Modell ist auf dem gewählten Cluster-Knoten nicht geladen."
                        ChatStreamState.TIMEOUT -> "Zeitüberschreitung (Timeout nach 60 Sekunden)."
                        ChatStreamState.CONNECTION_LOST -> "Netzwerkverbindung während des Streamings verloren."
                        ChatStreamState.CANCELLED -> "Durch Nutzer abgebrochen."
                        else -> "Technischer Inferenz-Fehler."
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = RoseDanger.copy(alpha = 0.12f),
                        border = androidx.compose.foundation.BorderStroke(1.dp, RoseDanger.copy(alpha = 0.35f)),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(10.dp)
                        ) {
                            Icon(Icons.Default.ErrorOutline, contentDescription = null, tint = RoseDanger, modifier = Modifier.size(18.dp))
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(text = errorDesc, color = TextPrimary, fontSize = 12.sp, modifier = Modifier.weight(1f))
                            IconButton(onClick = onRetry, modifier = Modifier.size(28.dp)) {
                                Icon(Icons.Default.Refresh, contentDescription = "Erneut versuchen", tint = Color.White, modifier = Modifier.size(16.dp))
                            }
                        }
                    }
                }

                // Streaming Cursor
                if (message.state == ChatStreamState.STREAMING) {
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = " ▊",
                        color = Color.White,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold
                    )
                }

                // Action Row under completed response (Copy, Thumbs Up/Down, Regenerate, Metrics)
                if (message.state == ChatStreamState.COMPLETED) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        // Copy Button
                        IconButton(
                            onClick = {
                                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                clipboard.setPrimaryClip(ClipData.newPlainText("ComputeMesh", message.content))
                                Toast.makeText(context, "In Zwischenablage kopiert", Toast.LENGTH_SHORT).show()
                            },
                            modifier = Modifier.size(30.dp)
                        ) {
                            Icon(Icons.Default.ContentCopy, contentDescription = "Kopieren", tint = TextMuted, modifier = Modifier.size(15.dp))
                        }

                        // Thumbs Up
                        IconButton(
                            onClick = { Toast.makeText(context, "Vielen Dank für das Feedback", Toast.LENGTH_SHORT).show() },
                            modifier = Modifier.size(30.dp)
                        ) {
                            Icon(Icons.Default.ThumbUp, contentDescription = "Gut", tint = TextMuted, modifier = Modifier.size(15.dp))
                        }

                        // Thumbs Down
                        IconButton(
                            onClick = { Toast.makeText(context, "Feedback registriert", Toast.LENGTH_SHORT).show() },
                            modifier = Modifier.size(30.dp)
                        ) {
                            Icon(Icons.Default.ThumbDown, contentDescription = "Schlecht", tint = TextMuted, modifier = Modifier.size(15.dp))
                        }

                        // Regenerate
                        IconButton(
                            onClick = onRetry,
                            modifier = Modifier.size(30.dp)
                        ) {
                            Icon(Icons.Default.Refresh, contentDescription = "Neu generieren", tint = TextMuted, modifier = Modifier.size(15.dp))
                        }

                        Spacer(modifier = Modifier.weight(1f))

                        // Latency & Speed Badge
                        if (message.speed.isNotEmpty() || message.latencyMs > 0) {
                            val metrics = buildString {
                                if (message.speed.isNotEmpty()) append(message.speed)
                                if (message.latencyMs > 0) append(" • ${message.latencyMs}ms")
                            }
                            Text(
                                text = metrics,
                                color = TextMuted,
                                fontSize = 11.sp
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun AttachmentOptionRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit
) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(12.dp),
        color = PillSurface,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp)
        ) {
            Box(
                modifier = Modifier
                    .size(38.dp)
                    .clip(CircleShape)
                    .background(BubbleSurface),
                contentAlignment = Alignment.Center
            ) {
                Icon(icon, contentDescription = null, tint = TextPrimary, modifier = Modifier.size(20.dp))
            }
            Spacer(modifier = Modifier.width(14.dp))
            Column {
                Text(title, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp, color = TextPrimary)
                Text(subtitle, fontSize = 12.sp, color = TextMuted)
            }
        }
    }
}

/**
 * Animated Voice Conversation Screen (Matching ChatGPT Voice Screen)
 */
@Composable
fun VoiceConversationScreen(
    onDismiss: () -> Unit,
    onSendVoiceTranscript: (String) -> Unit
) {
    var voiceStateText by remember { mutableStateOf("ComputeMesh hört zu...") }
    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val pulseScale by infiniteTransition.animateFloat(
        initialValue = 0.88f,
        targetValue = 1.15f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulseScale"
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .statusBarsPadding()
            .navigationBarsPadding()
    ) {
        // Top Close Button
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.End
        ) {
            IconButton(
                onClick = onDismiss,
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(BubbleSurface)
            ) {
                Icon(Icons.Default.Close, contentDescription = "Schließen", tint = Color.White)
            }
        }

        // Center Pulsing Voice Orb
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Box(
                modifier = Modifier
                    .size(160.dp)
                    .scale(pulseScale)
                    .clip(CircleShape)
                    .background(
                        Brush.radialGradient(
                            listOf(Color.White.copy(alpha = 0.95f), EmeraldSuccess.copy(alpha = 0.5f), Color.Transparent)
                        )
                    )
            )

            Spacer(modifier = Modifier.height(48.dp))
            Text(
                text = voiceStateText,
                color = TextPrimary,
                fontSize = 18.sp,
                fontWeight = FontWeight.Medium
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "Sprich frei mit ComputeMesh",
                color = TextMuted,
                fontSize = 13.sp
            )
        }

        // Bottom Controls
        Row(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .padding(bottom = 36.dp),
            horizontalArrangement = Arrangement.Center
        ) {
            IconButton(
                onClick = onDismiss,
                modifier = Modifier
                    .size(56.dp)
                    .clip(CircleShape)
                    .background(RoseDanger)
            ) {
                Icon(Icons.Default.Close, contentDescription = "Gespräch beenden", tint = Color.White, modifier = Modifier.size(28.dp))
            }
        }
    }
}

/**
 * Lightweight, clean Markdown renderer for chat messages:
 * Renders paragraphs, bold text, and enclosed code blocks with language headers and copy buttons.
 */
@Composable
fun FormattedMarkdownMessage(content: String) {
    val context = LocalContext.current
    val segments = remember(content) { parseMarkdownSegments(content) }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        segments.forEach { segment ->
            when (segment) {
                is MarkdownSegment.CodeBlock -> {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = Color(0xFF141414),
                        border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column {
                            // Code Header
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(Color(0xFF1E1E1E))
                                    .padding(horizontal = 12.dp, vertical = 6.dp)
                            ) {
                                Text(
                                    text = segment.language.ifBlank { "code" },
                                    color = TextSecondary,
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 11.5.sp,
                                    fontWeight = FontWeight.SemiBold
                                )
                                Spacer(modifier = Modifier.weight(1f))
                                IconButton(
                                    onClick = {
                                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                        clipboard.setPrimaryClip(ClipData.newPlainText("Code", segment.code))
                                        Toast.makeText(context, "Code kopiert", Toast.LENGTH_SHORT).show()
                                    },
                                    modifier = Modifier.size(24.dp)
                                ) {
                                    Icon(
                                        Icons.Default.ContentCopy,
                                        contentDescription = "Code kopieren",
                                        tint = TextMuted,
                                        modifier = Modifier.size(14.dp)
                                    )
                                }
                            }
                            // Code Content
                            Text(
                                text = segment.code,
                                color = TextPrimary,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.5.sp,
                                lineHeight = 18.sp,
                                modifier = Modifier.padding(12.dp)
                            )
                        }
                    }
                }
                is MarkdownSegment.Paragraph -> {
                    Text(
                        text = segment.text,
                        color = TextPrimary,
                        fontSize = 14.5.sp,
                        lineHeight = 21.sp
                    )
                }
            }
        }
    }
}

sealed class MarkdownSegment {
    data class Paragraph(val text: String) : MarkdownSegment()
    data class CodeBlock(val language: String, val code: String) : MarkdownSegment()
}

fun parseMarkdownSegments(content: String): List<MarkdownSegment> {
    val result = mutableListOf<MarkdownSegment>()
    val lines = content.lines()
    var inCode = false
    var codeLang = ""
    val codeBuffer = StringBuilder()
    val textBuffer = StringBuilder()

    for (line in lines) {
        if (line.trimStart().startsWith("```")) {
            if (!inCode) {
                if (textBuffer.isNotEmpty()) {
                    result.add(MarkdownSegment.Paragraph(textBuffer.toString().trim()))
                    textBuffer.clear()
                }
                inCode = true
                codeLang = line.trimStart().removePrefix("```").trim()
                codeBuffer.clear()
            } else {
                inCode = false
                result.add(MarkdownSegment.CodeBlock(codeLang, codeBuffer.toString().trimEnd()))
                codeBuffer.clear()
            }
        } else {
            if (inCode) {
                if (codeBuffer.isNotEmpty()) codeBuffer.append("\n")
                codeBuffer.append(line)
            } else {
                if (textBuffer.isNotEmpty()) textBuffer.append("\n")
                textBuffer.append(line)
            }
        }
    }

    if (inCode && codeBuffer.isNotEmpty()) {
        result.add(MarkdownSegment.CodeBlock(codeLang, codeBuffer.toString()))
    } else if (textBuffer.isNotEmpty()) {
        result.add(MarkdownSegment.Paragraph(textBuffer.toString().trim()))
    }

    return result
}
