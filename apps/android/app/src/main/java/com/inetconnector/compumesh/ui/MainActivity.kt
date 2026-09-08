package com.inetconnector.compumesh.ui

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.inetconnector.compumesh.engine.InferenceClient
import com.inetconnector.compumesh.engine.MiniCpmEngine
import com.inetconnector.compumesh.guard.BatteryPolicyGuard
import com.inetconnector.compumesh.p2p.DirectLanDiscovery
import com.inetconnector.compumesh.p2p.LocalMeshPeer
import com.inetconnector.compumesh.service.MeshNodeService
import com.inetconnector.compumesh.ui.theme.*
import com.inetconnector.compumesh.util.AttachmentInfo
import com.inetconnector.compumesh.util.DocumentParser
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Locale

data class ChatMessage(
    val role: String,
    var content: String,
    var speed: String = "",
    val attachment: AttachmentInfo? = null,
    var isStreaming: Boolean = false
)

class MainActivity : ComponentActivity() {

    companion object {
        const val PREFS_NAME = "computemesh_prefs"
        const val PREF_OWNER_KEY = "fleet_owner_key"
        const val PREF_GATEWAY_URL = "gateway_url"
        const val PREF_SELECTED_MODEL = "selected_model"
    }

    private lateinit var batteryGuard: BatteryPolicyGuard
    private lateinit var engine: MiniCpmEngine
    private lateinit var lanDiscovery: DirectLanDiscovery

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        batteryGuard = BatteryPolicyGuard(this)
        engine = MiniCpmEngine.getInstance(this)
        lanDiscovery = DirectLanDiscovery(this)

        // Restore saved fleet credentials
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val savedKey = prefs.getString(PREF_OWNER_KEY, "") ?: ""
        val savedGateway = prefs.getString(PREF_GATEWAY_URL, "https://mesh.inetconnector.com") ?: "https://mesh.inetconnector.com"
        if (savedKey.isNotBlank()) {
            MeshNodeService.ownerKey = savedKey
        }
        MeshNodeService.gatewayUrl = savedGateway

        // Handle possible deep link QR code pairing on launch
        handlePairingIntent(intent)

        setContent {
            ComputeMeshTheme {
                ComputeMeshMainScreen(
                    guard = batteryGuard,
                    engine = engine,
                    lanDiscovery = lanDiscovery,
                    onStartNode = { startNodeService() },
                    onStopNode = { stopNodeService() },
                    onSaveFleetConfig = { key, gateway ->
                        saveFleetConfig(key, gateway)
                    }
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handlePairingIntent(intent)
    }

    private fun handlePairingIntent(intent: Intent?) {
        val uri: Uri? = intent?.data
        if (uri != null) {
            val ownerKey = uri.getQueryParameter("owner_key") ?: uri.getQueryParameter("key") ?: ""
            val gateway = uri.getQueryParameter("gateway") ?: "https://mesh.inetconnector.com"

            if (ownerKey.isNotBlank()) {
                saveFleetConfig(ownerKey, gateway)
                Toast.makeText(this, "✓ Erfolgreich mit ComputeMesh Flotte gekoppelt!", Toast.LENGTH_LONG).show()
                startNodeService()
            }
        }
    }

    private fun saveFleetConfig(key: String, gateway: String) {
        MeshNodeService.ownerKey = key
        MeshNodeService.gatewayUrl = gateway
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(PREF_OWNER_KEY, key)
            .putString(PREF_GATEWAY_URL, gateway)
            .apply()
    }

    private fun startNodeService() {
        val intent = Intent(this, MeshNodeService::class.java).apply {
            action = MeshNodeService.ACTION_START
        }
        startForegroundService(intent)
    }

    private fun stopNodeService() {
        val intent = Intent(this, MeshNodeService::class.java).apply {
            action = MeshNodeService.ACTION_STOP
        }
        startService(intent)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ComputeMeshMainScreen(
    guard: BatteryPolicyGuard,
    engine: MiniCpmEngine,
    lanDiscovery: DirectLanDiscovery,
    onStartNode: () -> Unit,
    onStopNode: () -> Unit,
    onSaveFleetConfig: (String, String) -> Unit
) {
    var selectedTab by remember { mutableStateOf(0) }
    var guardStatus by remember { mutableStateOf(guard.getStatus()) }
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE) }
    var currentModel by remember {
        mutableStateOf(prefs.getString(MainActivity.PREF_SELECTED_MODEL, "qwen2.5:7b") ?: "qwen2.5:7b")
    }

    // Periodic guard status polling
    LaunchedEffect(Unit) {
        while (true) {
            guardStatus = guard.getStatus()
            delay(5000)
        }
    }

    Scaffold(
        containerColor = DeepVoidBg,
        topBar = {
            TopAppBar(
                title = {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Box(
                            modifier = Modifier
                                .size(28.dp)
                                .clip(RoundedCornerShape(8.dp))
                                .background(Brush.linearGradient(listOf(CyanAccent, IndigoAccent))),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                Icons.Default.Memory,
                                contentDescription = null,
                                tint = Color.Black,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Text("Compute", fontWeight = FontWeight.ExtraBold, color = TextPrimary, fontSize = 20.sp)
                        Text("Mesh", fontWeight = FontWeight.ExtraBold, color = CyanAccent, fontSize = 20.sp)
                        Spacer(modifier = Modifier.weight(1f))

                        // Status Chip
                        Surface(
                            shape = RoundedCornerShape(20.dp),
                            color = if (guardStatus.isComputePermitted) EmeraldSuccess.copy(alpha = 0.15f) else AmberWarning.copy(alpha = 0.15f),
                            border = androidx.compose.foundation.BorderStroke(
                                1.dp,
                                if (guardStatus.isComputePermitted) EmeraldSuccess.copy(alpha = 0.4f) else AmberWarning.copy(alpha = 0.4f)
                            )
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                            ) {
                                Box(
                                    modifier = Modifier
                                        .size(7.dp)
                                        .clip(CircleShape)
                                        .background(if (guardStatus.isComputePermitted) EmeraldSuccess else AmberWarning)
                                )
                                Spacer(modifier = Modifier.width(6.dp))
                                Text(
                                    text = if (guardStatus.isComputePermitted) "Aktiv" else "Standby",
                                    color = if (guardStatus.isComputePermitted) EmeraldSuccess else AmberWarning,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = DeepVoidBg)
            )
        },
        bottomBar = {
            NavigationBar(
                containerColor = CardSurface,
                tonalElevation = 8.dp
            ) {
                val tabs = listOf(
                    Triple(0, "KI Chat", Icons.Default.Chat),
                    Triple(1, "Edge Node", Icons.Default.ElectricBolt),
                    Triple(2, "LAN Mesh", Icons.Default.Hub),
                    Triple(3, "Setup", Icons.Default.Settings)
                )

                tabs.forEach { (index, label, icon) ->
                    val isSelected = selectedTab == index
                    NavigationBarItem(
                        icon = { Icon(icon, contentDescription = label) },
                        label = { Text(label, fontSize = 11.sp, fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal) },
                        selected = isSelected,
                        onClick = { selectedTab = index },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = CyanAccent,
                            selectedTextColor = CyanAccent,
                            unselectedIconColor = TextMuted,
                            unselectedTextColor = TextMuted,
                            indicatorColor = CyanAccent.copy(alpha = 0.12f)
                        )
                    )
                }
            }
        }
    ) { padding ->
        Box(modifier = Modifier.padding(padding)) {
            when (selectedTab) {
                0 -> MiniCpmChatTab(
                    engine = engine,
                    selectedModel = currentModel,
                    onSelectModel = {
                        currentModel = it
                        prefs.edit().putString(MainActivity.PREF_SELECTED_MODEL, it).apply()
                    }
                )
                1 -> EdgeNodeTab(guardStatus, onStartNode, onStopNode)
                2 -> LanMeshTab(lanDiscovery)
                3 -> SetupTab(onSaveFleetConfig = onSaveFleetConfig)
            }
        }
    }
}

@Composable
fun MiniCpmChatTab(
    engine: MiniCpmEngine,
    selectedModel: String,
    onSelectModel: (String) -> Unit
) {
    var inputMessage by remember { mutableStateOf("") }
    var isInferencing by remember { mutableStateOf(false) }
    var activeAttachment by remember { mutableStateOf<AttachmentInfo?>(null) }
    var showModelMenu by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val listState = rememberLazyListState()

    val availableModels = listOf(
        Pair("qwen2.5:7b", "Qwen 2.5 7B (High-Speed Allround)"),
        Pair("openbmb/minicpm5-2b", "MiniCPM5-2B (On-Device/Edge)"),
        Pair("qwen2.5-vl:7b", "Qwen 2.5 VL (Vision & Bilder)"),
        Pair("deepseek-coder:6.7b", "DeepSeek Coder (Programmierung)"),
        Pair("llama3.1:8b", "Llama 3.1 8B (Enterprise)")
    )

    val messages = remember {
        mutableStateListOf(
            ChatMessage(
                role = "assistant",
                content = "Willkommen bei ComputeMesh! Ich bin dein KI-Assistent. Du kannst mir beliebige Fragen stellen, Texte diktieren oder Dokumente (PDFs, Bilder, Code) zur vollständigen Analyse anhängen."
            )
        )
    }

    // 1. Voice Dictation Launcher
    val speechLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val matches = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            val spokenText = matches?.firstOrNull() ?: ""
            if (spokenText.isNotBlank()) {
                inputMessage = if (inputMessage.isBlank()) spokenText else "$inputMessage $spokenText"
            }
        }
    }

    // Microphone Permission Launcher
    val recordAudioPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                putExtra(RecognizerIntent.EXTRA_PROMPT, "Spreche deinen Prompt ein...")
            }
            try {
                speechLauncher.launch(intent)
            } catch (e: Throwable) {
                Toast.makeText(context, "Spracherkennung nicht verfügbar", Toast.LENGTH_SHORT).show()
            }
        } else {
            Toast.makeText(context, "Mikrofon-Berechtigung für Spracheingabe benötigt", Toast.LENGTH_SHORT).show()
        }
    }

    // 2. Document & Image Upload Picker Launcher
    val filePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        if (uri != null) {
            scope.launch {
                Toast.makeText(context, "Lese Datei ein...", Toast.LENGTH_SHORT).show()
                val parsed = DocumentParser.parseUri(context, uri)
                if (parsed != null) {
                    activeAttachment = parsed
                    Toast.makeText(context, "✓ ${parsed.fileName} angehängt (${parsed.sizeFormatted})", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(context, "Datei konnte nicht gelesen werden", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 12.dp, vertical = 8.dp)
    ) {
        // Model Selection & Privacy Bar
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            // Model Selector Pill
            Box {
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = CardSurface,
                    border = androidx.compose.foundation.BorderStroke(1.dp, CyanAccent.copy(alpha = 0.4f)),
                    modifier = Modifier.clickable { showModelMenu = true }
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("🧠", fontSize = 12.sp)
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = availableModels.find { it.first == selectedModel }?.second?.split(" ")?.first() ?: selectedModel,
                            color = CyanAccent,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold
                        )
                        Icon(Icons.Default.ArrowDropDown, contentDescription = null, tint = CyanAccent, modifier = Modifier.size(18.dp))
                    }
                }

                DropdownMenu(
                    expanded = showModelMenu,
                    onDismissRequest = { showModelMenu = false },
                    modifier = Modifier.background(CardSurface)
                ) {
                    availableModels.forEach { (id, label) ->
                        DropdownMenuItem(
                            text = {
                                Text(
                                    label,
                                    color = if (id == selectedModel) CyanAccent else TextPrimary,
                                    fontWeight = if (id == selectedModel) FontWeight.Bold else FontWeight.Normal
                                )
                            },
                            onClick = {
                                onSelectModel(id)
                                showModelMenu = false
                            }
                        )
                    }
                }
            }

            // Privacy Indicator
            Surface(
                shape = RoundedCornerShape(12.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder)
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Default.Lock, contentDescription = null, tint = EmeraldSuccess, modifier = Modifier.size(14.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("P2P E2E Verschlüsselt", color = TextSecondary, fontSize = 11.sp)
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        // Chat Messages List
        LazyColumn(
            state = listState,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            items(messages) { msg ->
                val isUser = msg.role == "user"
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start
                ) {
                    Surface(
                        shape = RoundedCornerShape(
                            topStart = 16.dp,
                            topEnd = 16.dp,
                            bottomStart = if (isUser) 16.dp else 4.dp,
                            bottomEnd = if (isUser) 4.dp else 16.dp
                        ),
                        color = if (isUser) IndigoAccent.copy(alpha = 0.28f) else CardSurface,
                        border = androidx.compose.foundation.BorderStroke(
                            1.dp,
                            if (isUser) IndigoAccent.copy(alpha = 0.6f) else CardSurfaceBorder
                        ),
                        modifier = Modifier.widthIn(max = 330.dp)
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            // Attachment preview in message
                            if (msg.attachment != null) {
                                if (msg.attachment.isImage && msg.attachment.thumbnail != null) {
                                    Image(
                                        bitmap = msg.attachment.thumbnail.asImageBitmap(),
                                        contentDescription = msg.attachment.fileName,
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .heightIn(max = 160.dp)
                                            .clip(RoundedCornerShape(8.dp))
                                    )
                                    Spacer(modifier = Modifier.height(6.dp))
                                } else {
                                    Surface(
                                        shape = RoundedCornerShape(8.dp),
                                        color = DeepVoidBg.copy(alpha = 0.7f),
                                        modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp)
                                    ) {
                                        Row(
                                            modifier = Modifier.padding(8.dp),
                                            verticalAlignment = Alignment.CenterVertically
                                        ) {
                                            Text(if (msg.attachment.mimeType.contains("pdf")) "📕" else "📄", fontSize = 16.sp)
                                            Spacer(modifier = Modifier.width(6.dp))
                                            Column {
                                                Text(msg.attachment.fileName, color = TextPrimary, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                                                Text(msg.attachment.sizeFormatted, color = TextMuted, fontSize = 10.sp)
                                            }
                                        }
                                    }
                                }
                            }

                            // Message Body
                            Text(
                                text = msg.content + if (msg.isStreaming) " ▋" else "",
                                color = TextPrimary,
                                fontSize = 14.sp,
                                lineHeight = 20.sp
                            )

                            // Telemetry / Speed Footer
                            if (msg.speed.isNotBlank()) {
                                Spacer(modifier = Modifier.height(6.dp))
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        text = msg.speed,
                                        color = CyanAccent,
                                        fontSize = 10.sp,
                                        fontFamily = FontFamily.Monospace,
                                        fontWeight = FontWeight.Medium
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(6.dp))

        // Active Attachment Preview Chip (Above Input Bar)
        if (activeAttachment != null) {
            val att = activeAttachment!!
            Surface(
                shape = RoundedCornerShape(12.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CyanAccent.copy(alpha = 0.6f)),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 6.dp)
            ) {
                Row(
                    modifier = Modifier.padding(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    if (att.isImage && att.thumbnail != null) {
                        Image(
                            bitmap = att.thumbnail.asImageBitmap(),
                            contentDescription = att.fileName,
                            modifier = Modifier
                                .size(40.dp)
                                .clip(RoundedCornerShape(6.dp))
                        )
                    } else {
                        Box(
                            modifier = Modifier
                                .size(40.dp)
                                .clip(RoundedCornerShape(6.dp))
                                .background(CyanAccent.copy(alpha = 0.15f)),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(if (att.mimeType.contains("pdf")) "📕" else "📄", fontSize = 18.sp)
                        }
                    }
                    Spacer(modifier = Modifier.width(10.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(att.fileName, color = TextPrimary, fontSize = 13.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                        Text(att.sizeFormatted, color = CyanAccent, fontSize = 11.sp)
                    }
                    IconButton(onClick = { activeAttachment = null }) {
                        Icon(Icons.Default.Close, contentDescription = "Entfernen", tint = RoseDanger, modifier = Modifier.size(20.dp))
                    }
                }
            }
        }

        // Input Action Bar with Upload, Dictation, Text & Send
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 1. Upload Button (Paperclip / Plus)
            IconButton(
                onClick = { filePickerLauncher.launch("*/*") },
                enabled = !isInferencing,
                colors = IconButtonDefaults.iconButtonColors(containerColor = CardSurface),
                modifier = Modifier.size(44.dp)
            ) {
                Icon(Icons.Default.AttachFile, contentDescription = "Datei / Bild anhängen", tint = CyanAccent)
            }

            Spacer(modifier = Modifier.width(6.dp))

            // 2. Voice Dictation Button (Microphone)
            IconButton(
                onClick = {
                    val hasPerm = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
                    if (hasPerm) {
                        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                            putExtra(RecognizerIntent.EXTRA_PROMPT, "Spreche deinen Prompt ein...")
                        }
                        try {
                            speechLauncher.launch(intent)
                        } catch (e: Throwable) {
                            Toast.makeText(context, "Spracheingabe nicht unterstützt", Toast.LENGTH_SHORT).show()
                        }
                    } else {
                        recordAudioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                },
                enabled = !isInferencing,
                colors = IconButtonDefaults.iconButtonColors(containerColor = CardSurface),
                modifier = Modifier.size(44.dp)
            ) {
                Icon(Icons.Default.Mic, contentDescription = "Diktieren", tint = EmeraldSuccess)
            }

            Spacer(modifier = Modifier.width(6.dp))

            // 3. Text Prompt Input
            OutlinedTextField(
                value = inputMessage,
                onValueChange = { inputMessage = it },
                placeholder = { Text("Frage eingeben oder diktieren...", color = TextMuted, fontSize = 13.sp) },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedBorderColor = CyanAccent,
                    unfocusedBorderColor = CardSurfaceBorder,
                    focusedContainerColor = CardSurface,
                    unfocusedContainerColor = CardSurface
                ),
                shape = RoundedCornerShape(22.dp),
                maxLines = 4,
                modifier = Modifier.weight(1f)
            )

            Spacer(modifier = Modifier.width(6.dp))

            // 4. Send Button
            IconButton(
                onClick = {
                    if ((inputMessage.isNotBlank() || activeAttachment != null) && !isInferencing) {
                        val prompt = inputMessage.trim()
                        val sentAttachment = activeAttachment
                        inputMessage = ""
                        activeAttachment = null
                        isInferencing = true

                        // Add user message
                        messages.add(
                            ChatMessage(
                                role = "user",
                                content = prompt.ifBlank { "[Datei-Analyse]" },
                                attachment = sentAttachment
                            )
                        )

                        // Add placeholder assistant message
                        val assistantIndex = messages.size
                        val assistantMsg = ChatMessage(
                            role = "assistant",
                            content = "",
                            isStreaming = true
                        )
                        messages.add(assistantMsg)

                        scope.launch {
                            listState.animateScrollToItem(messages.size - 1)

                            // Prepare conversation context history
                            val historyList = messages.take(messages.size - 1).map { it.role to it.content }

                            val gateway = MeshNodeService.gatewayUrl.ifBlank { "https://mesh.inetconnector.com" }
                            val apiKey = MeshNodeService.ownerKey

                            var accumulatedText = ""
                            var finalSpeed = ""

                            InferenceClient.streamChatCompletion(
                                gatewayUrl = gateway,
                                apiKey = apiKey,
                                model = selectedModel,
                                messages = historyList,
                                attachment = sentAttachment
                            ).collect { tokenChunk ->
                                if (tokenChunk.error != null) {
                                    accumulatedText += "\n\n⚠️ ${tokenChunk.error}"
                                    messages[assistantIndex] = messages[assistantIndex].copy(
                                        content = accumulatedText,
                                        isStreaming = false
                                    )
                                } else if (tokenChunk.isDone) {
                                    finalSpeed = "⚡ ${String.format(Locale.US, "%.1f", tokenChunk.speedTokensPerSec)} tok/s • ${tokenChunk.latencyMs}ms TTFT"
                                    messages[assistantIndex] = messages[assistantIndex].copy(
                                        content = accumulatedText,
                                        speed = finalSpeed,
                                        isStreaming = false
                                    )
                                } else {
                                    accumulatedText += tokenChunk.token
                                    messages[assistantIndex] = messages[assistantIndex].copy(
                                        content = accumulatedText,
                                        isStreaming = true
                                    )
                                }
                            }
                            isInferencing = false
                        }
                    }
                },
                enabled = !isInferencing && (inputMessage.isNotBlank() || activeAttachment != null),
                colors = IconButtonDefaults.iconButtonColors(
                    containerColor = CyanAccent,
                    disabledContainerColor = CardSurfaceBorder
                ),
                modifier = Modifier.size(44.dp)
            ) {
                if (isInferencing) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), color = DeepVoidBg, strokeWidth = 2.dp)
                } else {
                    Icon(Icons.Default.Send, contentDescription = "Senden", tint = DeepVoidBg)
                }
            }
        }
    }
}

@Composable
fun EdgeNodeTab(
    guardStatus: com.inetconnector.compumesh.guard.BatteryGuardStatus,
    onStartNode: () -> Unit,
    onStopNode: () -> Unit
) {
    var nodeActive by remember { mutableStateOf(MeshNodeService.isRunning) }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            // Hero Earnings & Token Counter
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(20.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("Berechnete Tokens", color = TextSecondary, fontSize = 13.sp, fontWeight = FontWeight.Medium)
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = CyanAccent.copy(alpha = 0.15f)
                        ) {
                            Text(
                                "Snapdragon 8 ARM64",
                                color = CyanAccent,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        "${MeshNodeService.totalTokensProcessed}",
                        color = CyanAccent,
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 38.sp,
                        fontFamily = FontFamily.Monospace
                    )

                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        "Verdienst: ${MeshNodeService.totalTokensProcessed} CM Credits",
                        color = EmeraldSuccess,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }
            }
        }

        item {
            // Battery & Health Status Guard
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Hardware & Akku-Wächter", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 16.sp)

                    HorizontalDivider(color = CardSurfaceBorder, thickness = 1.dp)

                    StatusRow(
                        label = "Akkuladung",
                        value = "${guardStatus.batteryPct}%",
                        statusGood = guardStatus.batteryPct >= 80 || guardStatus.isCharging
                    )
                    StatusRow(
                        label = "Ladekabel",
                        value = if (guardStatus.isCharging) "🔌 AC Ladegerät verbunden" else "🔋 Batteriebetrieb",
                        statusGood = guardStatus.isCharging
                    )
                    StatusRow(
                        label = "Temperatur",
                        value = "${guardStatus.temperatureCelsius} °C (Max 42.0 °C)",
                        statusGood = guardStatus.temperatureCelsius < 42.0f
                    )
                    StatusRow(
                        label = "WLAN-Verbindung",
                        value = if (guardStatus.isWifiConnected) "📶 Heim-WLAN verbunden" else "❌ Kein WLAN",
                        statusGood = guardStatus.isWifiConnected
                    )
                }
            }
        }

        item {
            // Action Button
            Button(
                onClick = {
                    if (nodeActive) {
                        onStopNode()
                        nodeActive = false
                    } else {
                        onStartNode()
                        nodeActive = true
                    }
                },
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (nodeActive) RoseDanger else CyanAccent
                ),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp)
            ) {
                Icon(
                    if (nodeActive) Icons.Default.Stop else Icons.Default.PlayArrow,
                    contentDescription = null,
                    tint = if (nodeActive) Color.White else DeepVoidBg
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = if (nodeActive) "Node Dienst stoppen" else "ComputeMesh Node starten",
                    color = if (nodeActive) Color.White else DeepVoidBg,
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp
                )
            }
        }
    }
}

@Composable
fun StatusRow(label: String, value: String, statusGood: Boolean) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label, color = TextSecondary, fontSize = 13.sp)
        Text(
            value,
            color = if (statusGood) TextPrimary else AmberWarning,
            fontWeight = FontWeight.SemiBold,
            fontSize = 13.sp
        )
    }
}

@Composable
fun LanMeshTab(lanDiscovery: DirectLanDiscovery) {
    val scope = rememberCoroutineScope()
    var isScanning by remember { mutableStateOf(false) }
    val discoveredPeers = remember { mutableStateListOf<LocalMeshPeer>() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Text("P2P LAN Mesh Radar", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        Text(
            "Findet automatisch ComputeMesh Mining-Rigs & PCs in deinem Heimnetzwerk über UDP Port 13379 – 100% lokal ohne Internet-Traffic.",
            color = TextSecondary,
            fontSize = 13.sp
        )

        Button(
            onClick = {
                isScanning = true
                scope.launch {
                    val peers = lanDiscovery.discoverLocalPeers()
                    discoveredPeers.clear()
                    discoveredPeers.addAll(peers)
                    isScanning = false
                }
            },
            colors = ButtonDefaults.buttonColors(containerColor = IndigoAccent),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            if (isScanning) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), color = DeepVoidBg, strokeWidth = 2.dp)
                Spacer(modifier = Modifier.width(8.dp))
                Text("Scanne Heimnetzwerk...", color = DeepVoidBg, fontWeight = FontWeight.Bold)
            } else {
                Icon(Icons.Default.Refresh, contentDescription = null, tint = DeepVoidBg)
                Spacer(modifier = Modifier.width(8.dp))
                Text("Lokale LAN-Knoten suchen", color = DeepVoidBg, fontWeight = FontWeight.Bold)
            }
        }

        if (discoveredPeers.isEmpty() && !isScanning) {
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier.padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Icon(Icons.Default.WifiTethering, contentDescription = null, tint = TextMuted, modifier = Modifier.size(36.dp))
                    Spacer(modifier = Modifier.height(10.dp))
                    Text("Keine LAN-Knoten gefunden", color = TextPrimary, fontWeight = FontWeight.SemiBold)
                    Text("Stelle sicher, dass PC/Rig im selben Wi-Fi läuft", color = TextSecondary, fontSize = 12.sp)
                }
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(discoveredPeers) { peer ->
                    Surface(
                        shape = RoundedCornerShape(14.dp),
                        color = CardSurface,
                        border = androidx.compose.foundation.BorderStroke(1.dp, CyanAccent.copy(alpha = 0.3f)),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(
                            modifier = Modifier.padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Default.Computer, contentDescription = null, tint = CyanAccent)
                            Spacer(modifier = Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(peer.nodeId, color = TextPrimary, fontWeight = FontWeight.Bold)
                                Text("${peer.ipAddress}:${peer.port} • ${peer.gpuSummary}", color = TextSecondary, fontSize = 12.sp)
                            }
                            Surface(
                                shape = RoundedCornerShape(8.dp),
                                color = EmeraldSuccess.copy(alpha = 0.15f)
                            ) {
                                Text("P2P Direct", color = EmeraldSuccess, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(6.dp, 2.dp))
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SetupTab(onSaveFleetConfig: (String, String) -> Unit) {
    var ownerKeyInput by remember { mutableStateOf(MeshNodeService.ownerKey) }
    var gatewayUrlInput by remember { mutableStateOf(MeshNodeService.gatewayUrl) }
    var directTrafficOnly by remember { mutableStateOf(true) }
    var showQrScanDialog by remember { mutableStateOf(false) }
    var scanInputText by remember { mutableStateOf("") }
    val clipboardManager = LocalClipboardManager.current
    val context = LocalContext.current

    val isBound = ownerKeyInput.isNotBlank()

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            Text("Flotten-Kopplung & Sicherheit", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Text(
                "Verbinde dieses Smartphone mit deiner ComputeMesh Flotte für Echtzeit-Telemetrie und Earnings.",
                color = TextSecondary,
                fontSize = 13.sp
            )
        }

        item {
            // 1-Click QR Pairing Hero Card
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, if (isBound) EmeraldSuccess.copy(alpha = 0.5f) else CyanAccent.copy(alpha = 0.5f)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.QrCodeScanner, contentDescription = null, tint = CyanAccent, modifier = Modifier.size(24.dp))
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("1-Klick Flotten QR-Code", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                        }
                        Surface(
                            shape = RoundedCornerShape(10.dp),
                            color = if (isBound) EmeraldSuccess.copy(alpha = 0.15f) else AmberWarning.copy(alpha = 0.15f)
                        ) {
                            Text(
                                text = if (isBound) "✓ Gekoppelt" else "Nicht gekoppelt",
                                color = if (isBound) EmeraldSuccess else AmberWarning,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))
                    Text(
                        "Scanne den Barcode / QR-Code aus deinem ComputeMesh Cockpit auf dem PC, um dieses Gerät sofort hinzuzufügen.",
                        color = TextSecondary,
                        fontSize = 12.sp,
                        lineHeight = 17.sp
                    )

                    Spacer(modifier = Modifier.height(14.dp))

                    Button(
                        onClick = {
                            showQrScanDialog = true
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) {
                        Icon(Icons.Default.QrCodeScanner, contentDescription = null, tint = DeepVoidBg)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("📷 QR-Code scannen & koppeln", color = DeepVoidBg, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                    }
                }
            }
        }

        item {
            // Manual Key Input
            OutlinedTextField(
                value = ownerKeyInput,
                onValueChange = {
                    ownerKeyInput = it
                    onSaveFleetConfig(it, gatewayUrlInput)
                },
                label = { Text("Owner Key / Flotten-Secret") },
                placeholder = { Text("inet-... oder owner_...") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedBorderColor = CyanAccent,
                    unfocusedBorderColor = CardSurfaceBorder,
                    focusedContainerColor = CardSurface,
                    unfocusedContainerColor = CardSurface
                ),
                trailingIcon = {
                    IconButton(onClick = {
                        val clip = clipboardManager.getText()?.text
                        if (!clip.isNullOrBlank()) {
                            val parsedKey = if (clip.contains("owner_key=")) {
                                Uri.parse(clip).getQueryParameter("owner_key") ?: clip
                            } else {
                                clip.trim()
                            }
                            ownerKeyInput = parsedKey
                            onSaveFleetConfig(parsedKey, gatewayUrlInput)
                            Toast.makeText(context, "Owner Key aus Zwischenablage eingefügt!", Toast.LENGTH_SHORT).show()
                        }
                    }) {
                        Icon(Icons.Default.ContentPaste, contentDescription = "Paste", tint = CyanAccent)
                    }
                },
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth()
            )
        }

        item {
            OutlinedTextField(
                value = gatewayUrlInput,
                onValueChange = {
                    gatewayUrlInput = it
                    onSaveFleetConfig(ownerKeyInput, it)
                },
                label = { Text("Control-Plane Gateway") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedBorderColor = CyanAccent,
                    unfocusedBorderColor = CardSurfaceBorder,
                    focusedContainerColor = CardSurface,
                    unfocusedContainerColor = CardSurface
                ),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth()
            )
        }

        item {
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Strict Privacy Mode", color = TextPrimary, fontWeight = FontWeight.SemiBold)
                        Text("Blockiert jeglichen externen Traffic für Prompts/Tokens", color = TextSecondary, fontSize = 11.sp)
                    }
                    Switch(
                        checked = directTrafficOnly,
                        onCheckedChange = { directTrafficOnly = it },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = CyanAccent,
                            checkedTrackColor = CyanAccent.copy(alpha = 0.3f)
                        )
                    )
                }
            }
        }
    }

    // QR Scan / Pairing Dialog
    if (showQrScanDialog) {
        AlertDialog(
            onDismissRequest = { showQrScanDialog = false },
            title = {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.QrCodeScanner, contentDescription = null, tint = CyanAccent)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Flotten QR-Code einlesen", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                }
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(
                        "Scanne den Barcode im ComputeMesh Cockpit oder füge den Link / Key ein:",
                        color = TextSecondary,
                        fontSize = 13.sp
                    )

                    OutlinedTextField(
                        value = scanInputText,
                        onValueChange = { scanInputText = it },
                        placeholder = { Text("computemesh://pair?owner_key=...", color = TextMuted, fontSize = 12.sp) },
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedTextColor = TextPrimary,
                            unfocusedTextColor = TextPrimary,
                            focusedBorderColor = CyanAccent,
                            unfocusedBorderColor = CardSurfaceBorder,
                            focusedContainerColor = DeepVoidBg,
                            unfocusedContainerColor = DeepVoidBg
                        ),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth()
                    )

                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                val clip = clipboardManager.getText()?.text
                                if (!clip.isNullOrBlank()) {
                                    scanInputText = clip.trim()
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = CardSurfaceBorder),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("📋 Einfügen", color = TextPrimary, fontSize = 12.sp)
                        }
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        val input = scanInputText.trim()
                        if (input.isNotBlank()) {
                            val parsedKey = if (input.contains("owner_key=")) {
                                Uri.parse(input).getQueryParameter("owner_key") ?: input
                            } else if (input.startsWith("computemesh://")) {
                                Uri.parse(input).getQueryParameter("owner_key") ?: input
                            } else {
                                input
                            }

                            val parsedGateway = if (input.contains("gateway=")) {
                                Uri.parse(input).getQueryParameter("gateway") ?: "https://mesh.inetconnector.com"
                            } else {
                                "https://mesh.inetconnector.com"
                            }

                            ownerKeyInput = parsedKey
                            onSaveFleetConfig(parsedKey, parsedGateway)
                            showQrScanDialog = false
                            scanInputText = ""
                            Toast.makeText(context, "🎉 Gerät erfolgreich mit Flotte gekoppelt!", Toast.LENGTH_LONG).show()
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("Koppeln", color = DeepVoidBg, fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                TextButton(onClick = { showQrScanDialog = false }) {
                    Text("Abbrechen", color = TextSecondary)
                }
            },
            containerColor = CardSurface,
            shape = RoundedCornerShape(16.dp)
        )
    }
}
