@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.inetconnector.compumesh.ui

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import android.webkit.*
import android.widget.Toast
import org.json.JSONObject
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
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
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.inetconnector.compumesh.engine.InferenceClient
import com.inetconnector.compumesh.engine.MiniCpmEngine
import com.inetconnector.compumesh.guard.BatteryPolicyGuard
import com.inetconnector.compumesh.p2p.DirectLanDiscovery
import com.inetconnector.compumesh.p2p.LocalMeshPeer
import com.inetconnector.compumesh.server.LocalChatServer
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
        const val CHAT_SERVER_PORT = 8089
        var isColdStart = true
    }

    private lateinit var batteryGuard: BatteryPolicyGuard
    private lateinit var engine: MiniCpmEngine
    private lateinit var lanDiscovery: DirectLanDiscovery
    private var localChatServer: LocalChatServer? = null
    private val chatServerPortState = mutableIntStateOf(CHAT_SERVER_PORT)

    // Reactive Compose state for instant multi-tab synchronization
    private val ownerKeyState = mutableStateOf("")
    private val gatewayUrlState = mutableStateOf("https://mesh.inetconnector.com")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        batteryGuard = BatteryPolicyGuard(this)
        engine = MiniCpmEngine.getInstance(this)
        lanDiscovery = DirectLanDiscovery(this)

        // Start LocalChatServer hosting embedded AHSMA WebUI with resilient fallback ports
        startLocalChatServer()

        // Restore saved fleet credentials
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val savedKey = prefs.getString(PREF_OWNER_KEY, "") ?: ""
        val savedGateway = prefs.getString(PREF_GATEWAY_URL, "https://mesh.inetconnector.com") ?: "https://mesh.inetconnector.com"
        MeshNodeService.ownerKey = savedKey
        MeshNodeService.gatewayUrl = savedGateway
        ownerKeyState.value = savedKey
        gatewayUrlState.value = savedGateway

        // Handle possible deep link QR code pairing on launch
        handlePairingIntent(intent)

        setContent {
            ComputeMeshTheme {
                ComputeMeshMainScreen(
                    guard = batteryGuard,
                    engine = engine,
                    lanDiscovery = lanDiscovery,
                    chatServerPort = chatServerPortState.intValue,
                    currentOwnerKey = ownerKeyState.value,
                    currentGatewayUrl = gatewayUrlState.value,
                    onStartNode = { startNodeService() },
                    onStopNode = { stopNodeService() },
                    onSaveFleetConfig = { key, gateway ->
                        saveFleetConfig(key, gateway)
                    }
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        if (localChatServer == null || !localChatServer!!.isAlive) {
            startLocalChatServer()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        try {
            localChatServer?.stop()
        } catch (_: Throwable) {}
    }

    private fun startLocalChatServer(): Int {
        try {
            localChatServer?.stop()
        } catch (_: Throwable) {}

        val portsToTry = listOf(8089, 8090, 8091, 8092, 8093, 8094, 8095)
        for (port in portsToTry) {
            try {
                val server = LocalChatServer(this, port)
                server.start(fi.iki.elonen.NanoHTTPD.SOCKET_READ_TIMEOUT, false)
                localChatServer = server
                chatServerPortState.intValue = port
                android.util.Log.i("MainActivity", "LocalChatServer successfully started on port $port")
                return port
            } catch (e: Throwable) {
                android.util.Log.w("MainActivity", "Port $port busy: ${e.message}, trying next...")
            }
        }
        return CHAT_SERVER_PORT
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
        val cleanKey = key.trim()
        val cleanGateway = gateway.trim()

        val isKeyUrl = cleanKey.startsWith("http://") || cleanKey.startsWith("https://") ||
                cleanKey.matches(Regex("""^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?/?.*$"""))

        val effectiveGateway = when {
            isKeyUrl -> if (cleanKey.startsWith("http://") || cleanKey.startsWith("https://")) cleanKey else "http://$cleanKey"
            cleanGateway.isNotBlank() -> cleanGateway
            else -> "https://mesh.inetconnector.com"
        }.trimEnd('/')

        val effectiveKey = when {
            isKeyUrl -> ""
            else -> cleanKey
        }

        MeshNodeService.ownerKey = effectiveKey
        MeshNodeService.gatewayUrl = effectiveGateway
        ownerKeyState.value = effectiveKey
        gatewayUrlState.value = effectiveGateway
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(PREF_OWNER_KEY, effectiveKey)
            .putString(PREF_GATEWAY_URL, effectiveGateway)
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

@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
fun ComputeMeshMainScreen(
    guard: BatteryPolicyGuard,
    engine: MiniCpmEngine,
    lanDiscovery: DirectLanDiscovery,
    chatServerPort: Int = MainActivity.CHAT_SERVER_PORT,
    currentOwnerKey: String,
    currentGatewayUrl: String,
    onStartNode: () -> Unit,
    onStopNode: () -> Unit,
    onSaveFleetConfig: (String, String) -> Unit
) {
    val pagerState = rememberPagerState(initialPage = 0, pageCount = { 4 })
    val coroutineScope = rememberCoroutineScope()
    var guardStatus by remember { mutableStateOf(guard.getStatus()) }
    val context = LocalContext.current

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
                    Triple(0, "KI Chat", Icons.Default.ChatBubble),
                    Triple(1, "Edge Node", Icons.Default.ElectricBolt),
                    Triple(2, "LAN Mesh", Icons.Default.Hub),
                    Triple(3, "Setup", Icons.Default.Settings)
                )

                tabs.forEach { (index, label, icon) ->
                    val isSelected = pagerState.currentPage == index
                    NavigationBarItem(
                        icon = { Icon(icon, contentDescription = label) },
                        label = { Text(label, fontSize = 11.sp, fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal) },
                        selected = isSelected,
                        onClick = {
                            coroutineScope.launch {
                                pagerState.animateScrollToPage(index)
                            }
                        },
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
        HorizontalPager(
            state = pagerState,
            userScrollEnabled = pagerState.currentPage != 0,
            beyondBoundsPageCount = 3,
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) { page ->
            when (page) {
                0 -> MiniCpmChatTab(serverPort = chatServerPort)
                1 -> EdgeNodeTab(guardStatus, onStartNode, onStopNode)
                2 -> LanMeshTab(
                    lanDiscovery = lanDiscovery,
                    currentGatewayUrl = currentGatewayUrl,
                    currentOwnerKey = currentOwnerKey,
                    onSaveFleetConfig = onSaveFleetConfig
                )
                3 -> SetupTab(
                    currentOwnerKey = currentOwnerKey,
                    currentGatewayUrl = currentGatewayUrl,
                    onSaveFleetConfig = onSaveFleetConfig
                )
            }
        }
    }
}

class AndroidSpeechBridge(
    private val activity: Activity,
    private val webView: WebView,
    private val onRequestAudioPermission: (() -> Unit) -> Unit
) {
    private var speechRecognizer: SpeechRecognizer? = null

    @JavascriptInterface
    fun startSpeechRecognition(lang: String?) {
        activity.runOnUiThread {
            if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                onRequestAudioPermission {
                    startSpeechRecognition(lang)
                }
                return@runOnUiThread
            }

            try {
                speechRecognizer?.destroy()
                if (!SpeechRecognizer.isRecognitionAvailable(activity)) {
                    Log.w("SpeechBridge", "SpeechRecognizer service not available on device")
                    notifyJs("onerror", "SpeechRecognizer not available")
                    notifyJs("onend")
                    return@runOnUiThread
                }

                speechRecognizer = SpeechRecognizer.createSpeechRecognizer(activity).apply {
                    setRecognitionListener(object : RecognitionListener {
                        override fun onReadyForSpeech(params: Bundle?) {
                            Log.i("SpeechBridge", "onReadyForSpeech")
                            notifyJs("onstart")
                        }
                        override fun onBeginningOfSpeech() {
                            Log.i("SpeechBridge", "onBeginningOfSpeech")
                        }
                        override fun onRmsChanged(rmsdB: Float) {}
                        override fun onBufferReceived(buffer: ByteArray?) {}
                        override fun onEndOfSpeech() {
                            Log.i("SpeechBridge", "onEndOfSpeech")
                        }
                        override fun onError(error: Int) {
                            val msg = when (error) {
                                SpeechRecognizer.ERROR_AUDIO -> "Audio recording error"
                                SpeechRecognizer.ERROR_CLIENT -> "Client side error"
                                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Insufficient permissions"
                                SpeechRecognizer.ERROR_NETWORK -> "Network error"
                                SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Network timeout"
                                SpeechRecognizer.ERROR_NO_MATCH -> "No speech match"
                                SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Recognition service busy"
                                SpeechRecognizer.ERROR_SERVER -> "Server error"
                                SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "No speech input"
                                else -> "Error code $error"
                            }
                            Log.w("SpeechBridge", "Recognition error: $msg ($error)")
                            notifyJs("onerror", msg)
                            notifyJs("onend")
                        }
                        override fun onResults(results: Bundle?) {
                            val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            val text = matches?.firstOrNull() ?: ""
                            Log.i("SpeechBridge", "Recognized text: $text")
                            if (text.isNotBlank()) {
                                notifyJs("onresult", text)
                            }
                            notifyJs("onend")
                        }
                        override fun onPartialResults(partialResults: Bundle?) {
                            val matches = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            val text = matches?.firstOrNull() ?: ""
                            if (text.isNotBlank()) {
                                notifyJs("onpartialresult", text)
                            }
                        }
                        override fun onEvent(eventType: Int, params: Bundle?) {}
                    })
                }

                val targetLang = if (!lang.isNullOrBlank()) lang else Locale.getDefault().toLanguageTag()
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, targetLang)
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, targetLang)
                    putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, activity.packageName)
                    putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                    putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                    putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false)
                    putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2000L)
                }
                speechRecognizer?.startListening(intent)
            } catch (e: Throwable) {
                Log.e("SpeechBridge", "Failed to start speech recognizer: ${e.message}")
                notifyJs("onerror", e.message ?: "Failed to start speech recognizer")
                notifyJs("onend")
            }
        }
    }

    @JavascriptInterface
    fun stopSpeechRecognition() {
        activity.runOnUiThread {
            try {
                speechRecognizer?.stopListening()
            } catch (_: Throwable) {}
        }
    }

    private fun notifyJs(event: String, data: String = "") {
        activity.runOnUiThread {
            val safeData = JSONObject.quote(data)
            val script = "window.__onAndroidSpeechEvent && window.__onAndroidSpeechEvent('$event', $safeData);"
            webView.evaluateJavascript(script, null)
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MiniCpmChatTab(
    serverPort: Int = MainActivity.CHAT_SERVER_PORT
) {
    val context = LocalContext.current
    val activity = context as? Activity
    var fileChooserCallback by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    var pendingPermissionRequest by remember { mutableStateOf<PermissionRequest?>(null) }
    var pendingAudioCallback by remember { mutableStateOf<(() -> Unit)?>(null) }

    val filePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetMultipleContents()
    ) { uris: List<Uri> ->
        fileChooserCallback?.onReceiveValue(uris.toTypedArray())
        fileChooserCallback = null
    }

    val audioPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted: Boolean ->
        if (isGranted) {
            pendingPermissionRequest?.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
            pendingAudioCallback?.invoke()
        } else {
            pendingPermissionRequest?.deny()
            Toast.makeText(context, "Mikrofon-Berechtigung verweigert", Toast.LENGTH_SHORT).show()
        }
        pendingPermissionRequest = null
        pendingAudioCallback = null
    }

    val initialChatUrl = remember(serverPort) {
        if (MainActivity.isColdStart) {
            MainActivity.isColdStart = false
            "http://127.0.0.1:$serverPort/?new_chat=true&lang=de#/"
        } else {
            "http://127.0.0.1:$serverPort/?lang=de#/"
        }
    }
    val fallbackUrl = "http://127.0.0.1:$serverPort/?lang=de#/"

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(DeepVoidBg)
    ) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                WebView(ctx).apply {
                    setBackgroundColor(0xFF090D16.toInt())
                    settings.apply {
                        javaScriptEnabled = true
                        domStorageEnabled = true
                        allowFileAccess = true
                        allowContentAccess = true
                        databaseEnabled = true
                        useWideViewPort = false
                        loadWithOverviewMode = false
                        mediaPlaybackRequiresUserGesture = false
                        javaScriptCanOpenWindowsAutomatically = true
                        setSupportMultipleWindows(false)
                        mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                    }

                    if (activity != null) {
                        addJavascriptInterface(
                            AndroidSpeechBridge(
                                activity,
                                this,
                                onRequestAudioPermission = { onGranted ->
                                    pendingAudioCallback = onGranted
                                    audioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                }
                            ),
                            "AndroidSpeechBridge"
                        )
                    }

                    webChromeClient = object : WebChromeClient() {
                        override fun onShowFileChooser(
                            webView: WebView?,
                            filePathCallback: ValueCallback<Array<Uri>>?,
                            fileChooserParams: FileChooserParams?
                        ): Boolean {
                            fileChooserCallback?.onReceiveValue(null)
                            fileChooserCallback = filePathCallback
                            filePickerLauncher.launch("*/*")
                            return true
                        }

                        override fun onPermissionRequest(request: PermissionRequest?) {
                            val resources = request?.resources ?: emptyArray()
                            if (resources.contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE)) {
                                if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                                    request?.grant(resources)
                                } else {
                                    pendingPermissionRequest = request
                                    audioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                }
                            } else {
                                request?.grant(resources)
                            }
                        }

                        override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                            android.util.Log.d("WebConsole", "[${consoleMessage?.messageLevel()}] ${consoleMessage?.message()} (at ${consoleMessage?.sourceId()}:${consoleMessage?.lineNumber()})")
                            return true
                        }

                        override fun onJsAlert(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
                            android.app.AlertDialog.Builder(view?.context)
                                .setTitle("ComputeMesh")
                                .setMessage(message ?: "")
                                .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                                .setOnCancelListener { result?.cancel() }
                                .show()
                            return true
                        }

                        override fun onJsConfirm(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
                            android.app.AlertDialog.Builder(view?.context)
                                .setTitle("ComputeMesh")
                                .setMessage(message ?: "")
                                .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                                .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                                .setOnCancelListener { result?.cancel() }
                                .show()
                            return true
                        }

                        override fun onJsPrompt(view: WebView?, url: String?, message: String?, defaultValue: String?, result: JsPromptResult?): Boolean {
                            val input = android.widget.EditText(view?.context).apply {
                                setText(defaultValue ?: "")
                            }
                            android.app.AlertDialog.Builder(view?.context)
                                .setTitle("ComputeMesh")
                                .setMessage(message ?: "")
                                .setView(input)
                                .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm(input.text.toString()) }
                                .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                                .setOnCancelListener { result?.cancel() }
                                .show()
                            return true
                        }
                    }

                    if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.KITKAT) {
                        WebView.setWebContentsDebuggingEnabled(true)
                    }

                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                            val url = request?.url?.toString() ?: return false
                            return if (url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost")) {
                                false
                            } else {
                                try {
                                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                                    ctx.startActivity(intent)
                                } catch (_: Throwable) {}
                                true
                            }
                        }

                        override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                            super.onReceivedError(view, request, error)
                            android.util.Log.e("WebViewChat", "Error loading ${request?.url}: ${error?.description} (${error?.errorCode})")
                            if (request?.isForMainFrame == true) {
                                view?.postDelayed({
                                    view.loadUrl(fallbackUrl)
                                }, 1500)
                            }
                        }

                        override fun onPageFinished(view: WebView?, url: String?) {
                            super.onPageFinished(view, url)
                            android.util.Log.d("WebViewChat", "Page finished loading: $url")
                        }
                    }

                    loadUrl(initialChatUrl)
                }
            },
            update = { webView ->
                val currentUrl = webView.url.orEmpty()
                if (currentUrl.isBlank() || currentUrl == "about:blank") {
                    webView.loadUrl(fallbackUrl)
                }
            }
        )
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
fun LanMeshTab(
    lanDiscovery: DirectLanDiscovery,
    currentGatewayUrl: String,
    currentOwnerKey: String = "",
    onSaveFleetConfig: (String, String) -> Unit = { _, _ -> }
) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var isScanning by remember { mutableStateOf(false) }
    val discoveredPeers = remember { mutableStateListOf<LocalMeshPeer>() }

    fun runDiscovery() {
        if (isScanning) return
        isScanning = true
        scope.launch {
            val peers = lanDiscovery.discoverLocalPeers(timeoutMs = 3500)
            discoveredPeers.clear()
            discoveredPeers.addAll(peers)
            isScanning = false
        }
    }

    // Auto-scan upon opening the LAN Mesh tab
    LaunchedEffect(Unit) {
        runDiscovery()
    }

    val cleanActiveGateway = currentGatewayUrl.trim().trimEnd('/')
    val isLanActive = cleanActiveGateway.isNotBlank() && cleanActiveGateway != "https://mesh.inetconnector.com"

    fun isPeerConnected(peer: LocalMeshPeer): Boolean {
        val peerHttp = "http://${peer.ipAddress}:${peer.port}".trimEnd('/')
        val peerHttps = "https://${peer.ipAddress}:${peer.port}".trimEnd('/')
        return cleanActiveGateway == peerHttp || cleanActiveGateway == peerHttps ||
                (cleanActiveGateway.contains(peer.ipAddress) && !cleanActiveGateway.contains("inetconnector.com"))
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Text("P2P LAN Mesh Radar", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                "Findet automatisch ComputeMesh Mining-Rigs & PCs in deinem Heimnetzwerk über UDP Port 13379 – 100% lokal ohne Internet-Traffic.",
                color = TextSecondary,
                fontSize = 13.sp,
                lineHeight = 18.sp
            )
        }

        item {
            // Active Connection Status Card
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(
                    1.dp,
                    if (isLanActive) EmeraldSuccess.copy(alpha = 0.6f) else CardSurfaceBorder
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Icon(
                            imageVector = if (isLanActive) Icons.Default.Router else Icons.Default.Cloud,
                            contentDescription = null,
                            tint = if (isLanActive) EmeraldSuccess else CyanAccent,
                            modifier = Modifier.size(24.dp)
                        )
                        Spacer(modifier = Modifier.width(10.dp))
                        Text(
                            "Aktiver Inferenz-Endpunkt",
                            color = TextSecondary,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Medium
                        )
                        Spacer(modifier = Modifier.weight(1f))
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = if (isLanActive) EmeraldSuccess.copy(alpha = 0.15f) else CyanAccent.copy(alpha = 0.12f)
                        ) {
                            Text(
                                if (isLanActive) "✓ LAN Aktiv" else "Cloud Gateway",
                                color = if (isLanActive) EmeraldSuccess else CyanAccent,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        if (isLanActive) currentGatewayUrl else "https://mesh.inetconnector.com",
                        color = if (isLanActive) EmeraldSuccess else TextPrimary,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )

                    if (isLanActive) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text("✓ 100% lokaler P2P Heimnetzwerk-Traffic", color = EmeraldSuccess.copy(alpha = 0.85f), fontSize = 11.5.sp)
                    }

                    if (isLanActive) {
                        Spacer(modifier = Modifier.height(10.dp))
                        Row(
                            horizontalArrangement = Arrangement.End,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Button(
                                onClick = {
                                    try {
                                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(cleanActiveGateway))
                                        context.startActivity(intent)
                                    } catch (e: Exception) {
                                        Toast.makeText(context, "Konnte Browser nicht öffnen: ${e.message}", Toast.LENGTH_SHORT).show()
                                    }
                                },
                                colors = ButtonDefaults.buttonColors(containerColor = CardSurfaceBorder),
                                shape = RoundedCornerShape(8.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
                            ) {
                                Text("Dashboard ↗", color = CyanAccent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                            }
                            Spacer(modifier = Modifier.width(8.dp))
                            Button(
                                onClick = {
                                    onSaveFleetConfig(currentOwnerKey, "https://mesh.inetconnector.com")
                                    Toast.makeText(context, "Auf Standard Cloud-Gateway zurückgesetzt", Toast.LENGTH_SHORT).show()
                                },
                                colors = ButtonDefaults.buttonColors(containerColor = RoseDanger.copy(alpha = 0.2f)),
                                shape = RoundedCornerShape(8.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
                            ) {
                                Text("Trennen", color = RoseDanger, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                }
            }
        }

        item {
            Button(
                onClick = { runDiscovery() },
                colors = ButtonDefaults.buttonColors(containerColor = IndigoAccent),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp)
            ) {
                if (isScanning) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), color = DeepVoidBg, strokeWidth = 2.dp)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Scanne Heimnetzwerk (UDP & Subnetz)...", color = DeepVoidBg, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                } else {
                    Icon(Icons.Default.Refresh, contentDescription = null, tint = DeepVoidBg)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Lokale LAN-Knoten suchen", color = DeepVoidBg, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                }
            }
        }

        item {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp)
            ) {
                Text(
                    "Gefundene Mesh-Knoten (${discoveredPeers.size})",
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp
                )
                Spacer(modifier = Modifier.weight(1f))
                Text(
                    "💡 Klick öffnet Node",
                    color = TextMuted,
                    fontSize = 11.5.sp
                )
            }
        }

        if (discoveredPeers.isEmpty() && !isScanning) {
            item {
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
            }
        } else {
            items(discoveredPeers) { peer ->
                val peerTargetUrl = "http://${peer.ipAddress}:${peer.port}"
                val isConnected = isPeerConnected(peer)

                Surface(
                    shape = RoundedCornerShape(16.dp),
                    color = CardSurface,
                    border = androidx.compose.foundation.BorderStroke(
                        1.5.dp,
                        if (isConnected) EmeraldSuccess else CyanAccent.copy(alpha = 0.4f)
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            try {
                                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(peerTargetUrl))
                                context.startActivity(intent)
                            } catch (e: Exception) {
                                Toast.makeText(context, "Konnte Browser nicht öffnen: ${e.message}", Toast.LENGTH_SHORT).show()
                            }
                        }
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(38.dp)
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (isConnected) EmeraldSuccess.copy(alpha = 0.15f) else CyanAccent.copy(alpha = 0.15f)),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(
                                    Icons.Default.Computer,
                                    contentDescription = null,
                                    tint = if (isConnected) EmeraldSuccess else CyanAccent,
                                    modifier = Modifier.size(22.dp)
                                )
                            }
                            Spacer(modifier = Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(peer.nodeId, color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                                Text("${peer.ipAddress}:${peer.port}", color = CyanAccent, fontSize = 13.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Medium)
                            }
                            if (isConnected) {
                                Surface(
                                    shape = RoundedCornerShape(8.dp),
                                    color = EmeraldSuccess.copy(alpha = 0.18f)
                                ) {
                                    Text(
                                        "✓ Verbunden",
                                        color = EmeraldSuccess,
                                        fontSize = 11.5.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                                    )
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(10.dp))

                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = CardSurfaceBorder.copy(alpha = 0.5f),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(
                                peer.gpuSummary.ifBlank { "ComputeMesh AI Accelerator" },
                                color = TextSecondary,
                                fontSize = 12.sp,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                            )
                        }

                        Spacer(modifier = Modifier.height(12.dp))

                        Row(
                            horizontalArrangement = Arrangement.End,
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Button(
                                onClick = {
                                    try {
                                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(peerTargetUrl))
                                        context.startActivity(intent)
                                    } catch (e: Exception) {
                                        Toast.makeText(context, "Fehler: ${e.message}", Toast.LENGTH_SHORT).show()
                                    }
                                },
                                colors = ButtonDefaults.buttonColors(containerColor = CardSurfaceBorder),
                                shape = RoundedCornerShape(10.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp)
                            ) {
                                Icon(Icons.Default.OpenInBrowser, contentDescription = null, tint = CyanAccent, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("Dashboard ↗", color = CyanAccent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                            }

                            if (!isConnected) {
                                Spacer(modifier = Modifier.width(10.dp))
                                Button(
                                    onClick = {
                                        onSaveFleetConfig(currentOwnerKey, peerTargetUrl)
                                        Toast.makeText(
                                            context,
                                            "✓ Gekoppelt mit ${peer.nodeId} (${peer.ipAddress}:${peer.port})!",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    },
                                    colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                                    shape = RoundedCornerShape(10.dp),
                                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 6.dp)
                                ) {
                                    Icon(Icons.Default.Link, contentDescription = null, tint = DeepVoidBg, modifier = Modifier.size(16.dp))
                                    Spacer(modifier = Modifier.width(6.dp))
                                    Text("Verbinden", color = DeepVoidBg, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SetupTab(
    currentOwnerKey: String,
    currentGatewayUrl: String,
    onSaveFleetConfig: (String, String) -> Unit
) {
    var ownerKeyInput by remember(currentOwnerKey) { mutableStateOf(currentOwnerKey) }
    var gatewayUrlInput by remember(currentGatewayUrl) { mutableStateOf(currentGatewayUrl) }
    var directTrafficOnly by remember { mutableStateOf(true) }
    var showQrCameraScanner by remember { mutableStateOf(false) }
    val clipboardManager = LocalClipboardManager.current
    val context = LocalContext.current

    val cleanActiveGateway = currentGatewayUrl.trim().trimEnd('/')
    val isLanConnected = cleanActiveGateway.isNotBlank() && cleanActiveGateway != "https://mesh.inetconnector.com"
    val isFleetBound = currentOwnerKey.isNotBlank()
    val isCoupled = isFleetBound || isLanConnected

    val pairingBadgeText = when {
        isFleetBound && isLanConnected -> "✓ Flotte & LAN gekoppelt"
        isLanConnected -> "✓ LAN Node verbunden"
        isFleetBound -> "✓ Flotte gekoppelt"
        else -> "Standard Cloud"
    }

    val pairingStatusSubtitle = when {
        isFleetBound && isLanConnected -> "Gekoppelt mit ComputeMesh Flotte • Inferenz über lokales LAN Gateway ($currentGatewayUrl)"
        isLanConnected -> "Verbunden mit lokalem Inferenz-Knoten ($currentGatewayUrl). Telemetrie & Inferenz laufen direkt über dein Heimnetzwerk."
        isFleetBound -> "Gekoppelt mit ComputeMesh Flotte für Telemetrie & Earnings."
        else -> "Scanne den QR-Code aus deinem ComputeMesh Cockpit auf dem PC, um dieses Gerät sofort hinzuzufügen."
    }

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
                border = androidx.compose.foundation.BorderStroke(
                    1.dp,
                    if (isCoupled) EmeraldSuccess.copy(alpha = 0.6f) else CyanAccent.copy(alpha = 0.5f)
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                Icons.Default.QrCodeScanner,
                                contentDescription = null,
                                tint = if (isCoupled) EmeraldSuccess else CyanAccent,
                                modifier = Modifier.size(24.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("1-Klick Flotten QR-Code", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                        }
                        Surface(
                            shape = RoundedCornerShape(10.dp),
                            color = if (isCoupled) EmeraldSuccess.copy(alpha = 0.15f) else AmberWarning.copy(alpha = 0.15f)
                        ) {
                            Text(
                                text = pairingBadgeText,
                                color = if (isCoupled) EmeraldSuccess else AmberWarning,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))
                    Text(
                        pairingStatusSubtitle,
                        color = TextSecondary,
                        fontSize = 12.sp,
                        lineHeight = 17.sp
                    )

                    Spacer(modifier = Modifier.height(14.dp))

                    Button(
                        onClick = {
                            showQrCameraScanner = true
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
                onValueChange = { input ->
                    val clean = input.trim()
                    if (clean.startsWith("http://") || clean.startsWith("https://") || clean.matches(Regex("""^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?/?.*$"""))) {
                        // User entered a URL/IP into OwnerKey -> intelligently route it directly to gatewayUrl!
                        val url = if (clean.startsWith("http://") || clean.startsWith("https://")) clean else "http://$clean"
                        ownerKeyInput = ""
                        gatewayUrlInput = url
                        onSaveFleetConfig("", url)
                        Toast.makeText(context, "Inferenz-Gateway aktualisiert: $url", Toast.LENGTH_SHORT).show()
                    } else {
                        ownerKeyInput = input
                        onSaveFleetConfig(input, gatewayUrlInput)
                    }
                },
                label = { Text("Owner Key / Flotten-Secret (Optional für Cloud)") },
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
                            val parsed = parseQrPayload(clip.toString(), gatewayUrlInput)
                            ownerKeyInput = parsed.ownerKey
                            if (parsed.gatewayUrl.isNotBlank()) {
                                gatewayUrlInput = parsed.gatewayUrl
                            }
                            onSaveFleetConfig(parsed.ownerKey, parsed.gatewayUrl)
                            Toast.makeText(context, "Konfiguration aus Zwischenablage übernommen!", Toast.LENGTH_SHORT).show()
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
                onValueChange = { input ->
                    gatewayUrlInput = input
                    onSaveFleetConfig(ownerKeyInput, input)
                },
                label = { Text("Control-Plane Gateway / Inferenz-Endpunkt") },
                placeholder = { Text("https://mesh.inetconnector.com oder http://192.168.1.x:8080") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedBorderColor = if (isLanConnected) EmeraldSuccess else CyanAccent,
                    unfocusedBorderColor = CardSurfaceBorder,
                    focusedContainerColor = CardSurface,
                    unfocusedContainerColor = CardSurface
                ),
                trailingIcon = {
                    if (gatewayUrlInput != "https://mesh.inetconnector.com" && gatewayUrlInput.isNotBlank()) {
                        IconButton(onClick = {
                            gatewayUrlInput = "https://mesh.inetconnector.com"
                            onSaveFleetConfig(ownerKeyInput, "https://mesh.inetconnector.com")
                            Toast.makeText(context, "Auf Standard Cloud-Gateway zurückgesetzt", Toast.LENGTH_SHORT).show()
                        }) {
                            Icon(Icons.Default.Refresh, contentDescription = "Reset", tint = AmberWarning)
                        }
                    }
                },
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

    // Live Camera QR Scanner Dialog
    if (showQrCameraScanner) {
        QrCameraScannerDialog(
            currentGateway = gatewayUrlInput,
            onCodeScanned = { result ->
                showQrCameraScanner = false
                ownerKeyInput = result.ownerKey
                gatewayUrlInput = result.gatewayUrl
                onSaveFleetConfig(result.ownerKey, result.gatewayUrl)
                Toast.makeText(
                    context,
                    "🎉 Erfolgreich gekoppelt: ${if (result.ownerKey.isNotBlank()) result.ownerKey.take(12) + "..." else result.gatewayUrl}",
                    Toast.LENGTH_LONG
                ).show()
            },
            onDismiss = {
                showQrCameraScanner = false
            }
        )
    }
}
