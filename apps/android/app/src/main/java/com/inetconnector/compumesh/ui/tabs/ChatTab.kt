package com.inetconnector.compumesh.ui.tabs

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.MediaStore
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import com.inetconnector.compumesh.engine.InferenceClient
import com.inetconnector.compumesh.ui.theme.*
import com.inetconnector.compumesh.util.AttachmentInfo
import com.inetconnector.compumesh.util.DocumentParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
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

data class ChatMessageItem(
    val id: String = UUID.randomUUID().toString(),
    val role: String, // "user" or "assistant"
    var content: String,
    var state: ChatStreamState = ChatStreamState.COMPLETED,
    var speed: String = "",
    var latencyMs: Long = 0,
    var tokenCount: Int = 0,
    val attachment: AttachmentInfo? = null,
    var errorMessage: String? = null
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatTab(
    gatewayUrl: String = "https://mesh.inetconnector.com",
    ownerKey: String = "",
    onOpenLanMesh: () -> Unit = {},
    onOpenSetup: () -> Unit = {}
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    val availableModels = remember {
        listOf(
            "qwen2.5:3b" to "Qwen 2.5 3B (Schnell & Effizient)",
            "qwen2.5-vl:7b" to "Qwen 2.5 VL 7B (Vision & OCR)",
            "gemma3:4b" to "Gemma 3 4B (Multimodal Text/Bild)",
            "kimi-linear-48b" to "Kimi Linear 48B (ComputeMesh Flotte)",
            "deepseek-r1:14b" to "DeepSeek R1 14B (Reasoning)"
        )
    }

    var selectedModel by remember { mutableStateOf("qwen2.5:3b") }
    var modelDropdownExpanded by remember { mutableStateOf(false) }

    val messages = remember {
        mutableStateListOf(
            ChatMessageItem(
                role = "assistant",
                content = "Hallo! Ich bin dein ComputeMesh KI-Assistent. Ich kann deine Anfragen lokal im LAN oder über deine verbundene ComputeMesh-Flotte beantworten. Wie kann ich dir helfen?",
                state = ChatStreamState.COMPLETED
            )
        )
    }

    var inputText by remember { mutableStateOf("") }
    var currentAttachment by remember { mutableStateOf<AttachmentInfo?>(null) }
    var streamState by remember { mutableStateOf(ChatStreamState.IDLE) }
    var activeJob by remember { mutableStateOf<Job?>(null) }
    var tempCameraPhotoUri by remember { mutableStateOf<Uri?>(null) }

    // File / Document / Image picker launcher
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

    // Camera photo capture launcher
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

    // Speech recognition launcher
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

        activeJob = scope.launch(Dispatchers.IO) {
            try {
                InferenceClient.streamChatCompletion(
                    gatewayUrl = gatewayUrl,
                    apiKey = ownerKey,
                    model = selectedModel,
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

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(DeepVoidBg)
    ) {
        // Top Toolbar: Model Selector & Actions
        Surface(
            color = CardSurface,
            tonalElevation = 4.dp,
            border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
            modifier = Modifier.fillMaxWidth()
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 14.dp, vertical = 8.dp)
            ) {
                // Model Dropdown Chip
                Box {
                    Surface(
                        onClick = { modelDropdownExpanded = true },
                        shape = RoundedCornerShape(20.dp),
                        color = CardSurfaceBorder,
                        border = androidx.compose.foundation.BorderStroke(1.dp, CyanAccent.copy(alpha = 0.5f))
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                        ) {
                            Icon(
                                Icons.Default.AutoAwesome,
                                contentDescription = null,
                                tint = CyanAccent,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = selectedModel,
                                color = TextPrimary,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Icon(
                                Icons.Default.ArrowDropDown,
                                contentDescription = null,
                                tint = TextMuted,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                    }

                    DropdownMenu(
                        expanded = modelDropdownExpanded,
                        onDismissRequest = { modelDropdownExpanded = false },
                        modifier = Modifier.background(CardSurface)
                    ) {
                        availableModels.forEach { (modelId, desc) ->
                            DropdownMenuItem(
                                text = {
                                    Column {
                                        Text(modelId, fontWeight = FontWeight.Bold, color = if (modelId == selectedModel) CyanAccent else TextPrimary)
                                        Text(desc, fontSize = 11.sp, color = TextSecondary)
                                    }
                                },
                                onClick = {
                                    selectedModel = modelId
                                    modelDropdownExpanded = false
                                },
                                leadingIcon = {
                                    if (modelId == selectedModel) {
                                        Icon(Icons.Default.Check, contentDescription = null, tint = CyanAccent)
                                    }
                                }
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.weight(1f))

                // Clear Chat button
                IconButton(
                    onClick = {
                        cancelStreaming()
                        messages.clear()
                        messages.add(
                            ChatMessageItem(
                                role = "assistant",
                                content = "Neuer Chat gestartet. Wie kann ich dir helfen?",
                                state = ChatStreamState.COMPLETED
                            )
                        )
                    },
                    modifier = Modifier.size(36.dp)
                ) {
                    Icon(
                        Icons.Default.DeleteOutline,
                        contentDescription = "Neuer Chat",
                        tint = TextSecondary,
                        modifier = Modifier.size(20.dp)
                    )
                }
            }
        }

        // Chat Messages List
        LazyColumn(
            state = listState,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(horizontal = 14.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
            contentPadding = PaddingValues(top = 12.dp, bottom = 12.dp)
        ) {
            itemsIndexed(messages, key = { _, item -> item.id }) { _, message ->
                ChatMessageBubble(
                    message = message,
                    onRetry = { retryLastMessage() },
                    onOpenSetup = onOpenSetup,
                    onOpenLanMesh = onOpenLanMesh
                )
            }
        }

        // Status Indicator Strip during Streaming / Connecting / Error
        AnimatedVisibility(
            visible = streamState == ChatStreamState.CONNECTING || streamState == ChatStreamState.STREAMING,
            enter = fadeIn() + expandVertically(),
            exit = fadeOut() + shrinkVertically()
        ) {
            Surface(
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CyanAccent.copy(alpha = 0.3f)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(14.dp),
                        strokeWidth = 2.dp,
                        color = CyanAccent
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = if (streamState == ChatStreamState.CONNECTING) "Verbinde mit Inferenz-Knoten..." else "Empfange Antwort...",
                        color = CyanAccent,
                        fontSize = 12.sp
                    )
                    Spacer(modifier = Modifier.weight(1f))
                    TextButton(
                        onClick = { cancelStreaming() },
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                    ) {
                        Icon(Icons.Default.Stop, contentDescription = null, tint = RoseDanger, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("Stoppen", color = RoseDanger, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }

        // Bottom Input Area with imePadding so virtual keyboard doesn't overlap
        Surface(
            color = CardSurface,
            tonalElevation = 8.dp,
            border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
            modifier = Modifier
                .fillMaxWidth()
                .imePadding()
                .navigationBarsPadding()
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp)
            ) {
                // Pending Attachment Preview Chip
                if (currentAttachment != null) {
                    val att = currentAttachment!!
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = CardSurfaceBorder,
                        border = androidx.compose.foundation.BorderStroke(1.dp, CyanAccent.copy(alpha = 0.4f)),
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
                                    tint = CyanAccent,
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
                                    contentDescription = "Anhang entfernen",
                                    tint = RoseDanger,
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                        }
                    }
                }

                // Input Bar Row
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    // Attachment Picker Button (Document / Image)
                    IconButton(
                        onClick = {
                            filePickerLauncher.launch(
                                arrayOf("image/*", "application/pdf", "text/*")
                            )
                        },
                        modifier = Modifier.size(38.dp)
                    ) {
                        Icon(
                            Icons.Default.AttachFile,
                            contentDescription = "Datei anhängen",
                            tint = CyanAccent,
                            modifier = Modifier.size(22.dp)
                        )
                    }

                    // Camera Capture Button
                    IconButton(
                        onClick = { startCameraCapture() },
                        modifier = Modifier.size(38.dp)
                    ) {
                        Icon(
                            Icons.Default.PhotoCamera,
                            contentDescription = "Foto aufnehmen",
                            tint = IndigoAccent,
                            modifier = Modifier.size(22.dp)
                        )
                    }

                    // Voice Input Button
                    IconButton(
                        onClick = { startVoiceInput() },
                        modifier = Modifier.size(38.dp)
                    ) {
                        Icon(
                            Icons.Default.Mic,
                            contentDescription = "Spracheingabe",
                            tint = TextSecondary,
                            modifier = Modifier.size(22.dp)
                        )
                    }

                    Spacer(modifier = Modifier.width(4.dp))

                    // Message TextField
                    OutlinedTextField(
                        value = inputText,
                        onValueChange = { inputText = it },
                        placeholder = {
                            Text(
                                "Nachricht an ComputeMesh...",
                                color = TextMuted,
                                fontSize = 14.sp
                            )
                        },
                        maxLines = 4,
                        minLines = 1,
                        shape = RoundedCornerShape(20.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedTextColor = TextPrimary,
                            unfocusedTextColor = TextPrimary,
                            focusedBorderColor = CyanAccent,
                            unfocusedBorderColor = CardSurfaceBorder,
                            focusedContainerColor = DeepVoidBg,
                            unfocusedContainerColor = DeepVoidBg
                        ),
                        modifier = Modifier
                            .weight(1f)
                            .padding(horizontal = 4.dp)
                    )

                    Spacer(modifier = Modifier.width(4.dp))

                    // Send / Stop Button
                    if (streamState == ChatStreamState.CONNECTING || streamState == ChatStreamState.STREAMING) {
                        IconButton(
                            onClick = { cancelStreaming() },
                            modifier = Modifier
                                .size(42.dp)
                                .clip(CircleShape)
                                .background(RoseDanger.copy(alpha = 0.2f))
                        ) {
                            Icon(
                                Icons.Default.Stop,
                                contentDescription = "Inferenz abbrechen",
                                tint = RoseDanger,
                                modifier = Modifier.size(22.dp)
                            )
                        }
                    } else {
                        val canSend = inputText.isNotBlank() || currentAttachment != null
                        IconButton(
                            onClick = { executeSend(inputText, currentAttachment) },
                            enabled = canSend,
                            modifier = Modifier
                                .size(42.dp)
                                .clip(CircleShape)
                                .background(if (canSend) CyanAccent else CardSurfaceBorder)
                        ) {
                            Icon(
                                Icons.AutoMirrored.Filled.Send,
                                contentDescription = "Senden",
                                tint = if (canSend) Color.Black else TextMuted,
                                modifier = Modifier.size(20.dp)
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ChatMessageBubble(
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
        // Message Header: Role / Node / Timestamp
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(bottom = 4.dp, start = if (isUser) 0.dp else 4.dp, end = if (isUser) 4.dp else 0.dp)
        ) {
            if (!isUser) {
                Box(
                    modifier = Modifier
                        .size(18.dp)
                        .clip(CircleShape)
                        .background(CyanAccent),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        Icons.Default.Memory,
                        contentDescription = null,
                        tint = Color.Black,
                        modifier = Modifier.size(12.dp)
                    )
                }
                Spacer(modifier = Modifier.width(6.dp))
                Text(
                    text = "ComputeMesh KI",
                    color = CyanAccent,
                    fontSize = 11.5.sp,
                    fontWeight = FontWeight.Bold
                )
            } else {
                Text(
                    text = "Du",
                    color = TextSecondary,
                    fontSize = 11.5.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }

        // Message Surface Card
        Surface(
            shape = RoundedCornerShape(
                topStart = 16.dp,
                topEnd = 16.dp,
                bottomStart = if (isUser) 16.dp else 4.dp,
                bottomEnd = if (isUser) 4.dp else 16.dp
            ),
            color = if (isUser) CyanAccent.copy(alpha = 0.15f) else CardSurface,
            border = androidx.compose.foundation.BorderStroke(
                1.dp,
                if (isUser) CyanAccent.copy(alpha = 0.4f) else CardSurfaceBorder
            ),
            modifier = Modifier.widthIn(max = 340.dp)
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                // Attached Image / Document if present
                if (message.attachment != null) {
                    val att = message.attachment
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = DeepVoidBg,
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
                                        .size(44.dp)
                                        .clip(RoundedCornerShape(6.dp))
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                            } else {
                                Icon(
                                    Icons.Default.Description,
                                    contentDescription = null,
                                    tint = CyanAccent,
                                    modifier = Modifier.size(28.dp)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                            }
                            Column {
                                Text(
                                    text = att.fileName,
                                    color = TextPrimary,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                    maxLines = 1
                                )
                                Text(
                                    text = att.sizeFormatted,
                                    color = TextMuted,
                                    fontSize = 11.sp
                                )
                            }
                        }
                    }
                }

                // Render Content with Markdown & Code Blocks
                if (message.content.isNotEmpty()) {
                    SelectionContainer {
                        FormattedMarkdownMessage(message.content)
                    }
                } else if (message.state == ChatStreamState.CONNECTING) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(12.dp),
                            strokeWidth = 2.dp,
                            color = CyanAccent
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "Bereite Antwort vor...",
                            color = TextMuted,
                            fontSize = 13.sp
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
                    val errorTitle = when (message.state) {
                        ChatStreamState.AUTH_REQUIRED -> "Authentifizierung erforderlich"
                        ChatStreamState.MODEL_UNAVAILABLE -> "Modell nicht verfügbar"
                        ChatStreamState.TIMEOUT -> "Zeitüberschreitung (Timeout)"
                        ChatStreamState.CONNECTION_LOST -> "Verbindung unterbrochen"
                        ChatStreamState.CANCELLED -> "Durch Nutzer abgebrochen"
                        else -> "Inferenz-Fehler"
                    }
                    val errorDesc = message.errorMessage ?: when (message.state) {
                        ChatStreamState.AUTH_REQUIRED -> "Bitte überprüfe deinen QR-Kopplungsstatus im Setup-Tab."
                        ChatStreamState.MODEL_UNAVAILABLE -> "Das angeforderte Modell ist auf dem gewählten Knoten nicht geladen."
                        ChatStreamState.TIMEOUT -> "Der Knoten hat innerhalb von 60 Sekunden nicht geantwortet."
                        ChatStreamState.CONNECTION_LOST -> "Netzwerkverbindung während des Streamings verloren."
                        ChatStreamState.CANCELLED -> "Die Inferenz wurde gestoppt."
                        else -> "Technischer Verbindungsfehler."
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = RoseDanger.copy(alpha = 0.12f),
                        border = androidx.compose.foundation.BorderStroke(1.dp, RoseDanger.copy(alpha = 0.4f)),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(modifier = Modifier.padding(10.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(
                                    Icons.Default.ErrorOutline,
                                    contentDescription = null,
                                    tint = RoseDanger,
                                    modifier = Modifier.size(16.dp)
                                )
                                Spacer(modifier = Modifier.width(6.dp))
                                Text(
                                    text = errorTitle,
                                    color = RoseDanger,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 12.sp
                                )
                            }
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = errorDesc,
                                color = TextPrimary,
                                fontSize = 11.5.sp,
                                lineHeight = 16.sp
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                                if (message.state == ChatStreamState.AUTH_REQUIRED) {
                                    Button(
                                        onClick = onOpenSetup,
                                        colors = ButtonDefaults.buttonColors(containerColor = AmberWarning),
                                        shape = RoundedCornerShape(8.dp),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                                    ) {
                                        Text("Zum Setup ↗", color = Color.Black, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                                    }
                                } else {
                                    Button(
                                        onClick = onRetry,
                                        colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                                        shape = RoundedCornerShape(8.dp),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                                    ) {
                                        Icon(Icons.Default.Refresh, contentDescription = null, tint = Color.Black, modifier = Modifier.size(14.dp))
                                        Spacer(modifier = Modifier.width(4.dp))
                                        Text("Erneut versuchen", color = Color.Black, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                                    }
                                }
                            }
                        }
                    }
                }

                // Streaming Cursor
                if (message.state == ChatStreamState.STREAMING) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = " ▊",
                        color = CyanAccent,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold
                    )
                }

                // Speed & Metrics Footer
                if (message.state == ChatStreamState.COMPLETED && (message.speed.isNotEmpty() || message.tokenCount > 0)) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        val metricsText = buildString {
                            if (message.speed.isNotEmpty()) append("⚡ ${message.speed}")
                            if (message.latencyMs > 0) append(" • ${message.latencyMs}ms Latenz")
                            if (message.tokenCount > 0) append(" • ${message.tokenCount} Tokens")
                        }
                        Text(
                            text = metricsText,
                            color = TextMuted,
                            fontSize = 10.5.sp
                        )
                        Spacer(modifier = Modifier.weight(1f))
                        IconButton(
                            onClick = {
                                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                clipboard.setPrimaryClip(ClipData.newPlainText("ComputeMesh", message.content))
                                Toast.makeText(context, "In die Zwischenablage kopiert", Toast.LENGTH_SHORT).show()
                            },
                            modifier = Modifier.size(24.dp)
                        ) {
                            Icon(
                                Icons.Default.ContentCopy,
                                contentDescription = "Kopieren",
                                tint = TextMuted,
                                modifier = Modifier.size(14.dp)
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * Lightweight, robust Compose Markdown renderer:
 * Separates triple-backtick code blocks and renders them in code cards with copy buttons.
 * Formats paragraphs, bold markers (**), and lists cleanly.
 */
@Composable
fun FormattedMarkdownMessage(content: String) {
    val context = LocalContext.current
    val segments = remember(content) { parseMarkdownSegments(content) }

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        segments.forEach { segment ->
            when (segment) {
                is MarkdownSegment.CodeBlock -> {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = Color(0xFF05080E),
                        border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column {
                            // Code Block Header
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(Color(0xFF0C1322))
                                    .padding(horizontal = 10.dp, vertical = 4.dp)
                            ) {
                                Text(
                                    text = segment.language.ifBlank { "code" },
                                    color = CyanAccent,
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold
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
                                        tint = TextSecondary,
                                        modifier = Modifier.size(14.dp)
                                    )
                                }
                            }
                            // Code Content
                            Text(
                                text = segment.code,
                                color = TextPrimary,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                lineHeight = 17.sp,
                                modifier = Modifier.padding(10.dp)
                            )
                        }
                    }
                }
                is MarkdownSegment.Paragraph -> {
                    Text(
                        text = segment.text,
                        color = TextPrimary,
                        fontSize = 14.sp,
                        lineHeight = 20.sp
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
