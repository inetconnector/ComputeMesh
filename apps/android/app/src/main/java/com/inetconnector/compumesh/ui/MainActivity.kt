package com.inetconnector.compumesh.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.WebView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import com.inetconnector.compumesh.guard.BatteryPolicyGuard
import com.inetconnector.compumesh.p2p.DirectLanDiscovery
import com.inetconnector.compumesh.server.LocalChatServer
import com.inetconnector.compumesh.service.MeshNodeService
import com.inetconnector.compumesh.ui.components.ComputeMeshMainScreen
import com.inetconnector.compumesh.ui.theme.ComputeMeshTheme

/**
 * Slim, modular MainActivity orchestrating lifecycle, fleet configuration,
 * and high-level Compose navigation. Detailed views and bridges are separated
 * into dedicated modules in `ui.tabs`, `ui.components`, and `ui.bridge`.
 */
class MainActivity : ComponentActivity() {

    companion object {
        const val PREFS_NAME = "computemesh_prefs"
        const val PREF_OWNER_KEY = "fleet_owner_key"
        const val PREF_GATEWAY_URL = "gateway_url"
        const val PREF_SELECTED_MODEL = "selected_model"
        const val CHAT_SERVER_PORT = 8089
        var isColdStart = true
        var globalWebView: WebView? = null
    }

    private lateinit var batteryGuard: BatteryPolicyGuard
    private lateinit var lanDiscovery: DirectLanDiscovery
    private var localChatServer: LocalChatServer? = null
    private val chatServerPortState = mutableIntStateOf(CHAT_SERVER_PORT)

    // Reactive Compose state for instant multi-tab synchronization
    private val ownerKeyState = mutableStateOf("")
    private val gatewayUrlState = mutableStateOf("https://mesh.inetconnector.com")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        batteryGuard = BatteryPolicyGuard(this)
        lanDiscovery = DirectLanDiscovery(this)

        // Start LocalChatServer hosting embedded WebUI with resilient fallback ports
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

        // Auto-start ComputeMesh Node on launch
        try {
            startNodeService()
        } catch (e: Throwable) {
            android.util.Log.e("MainActivity", "Auto-start MeshNodeService error: ${e.message}")
        }

        setContent {
            ComputeMeshTheme {
                ComputeMeshMainScreen(
                    guard = batteryGuard,
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
