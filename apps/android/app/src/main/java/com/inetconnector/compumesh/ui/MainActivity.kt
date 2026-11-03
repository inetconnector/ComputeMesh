package com.inetconnector.compumesh.ui

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.webkit.WebView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.lifecycle.lifecycleScope
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import com.inetconnector.compumesh.guard.BatteryPolicyGuard
import com.inetconnector.compumesh.R
import com.inetconnector.compumesh.p2p.DirectLanDiscovery
import com.inetconnector.compumesh.server.LocalChatServer
import com.inetconnector.compumesh.service.MeshNodeService
import com.inetconnector.compumesh.service.MobileCredentialStore
import com.inetconnector.compumesh.update.AndroidUpdateChecker
import com.inetconnector.compumesh.update.AndroidUpdateInfo
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
    private val pendingUpdateState = mutableStateOf<AndroidUpdateInfo?>(null)
    private val updateCheckInProgressState = mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        batteryGuard = BatteryPolicyGuard(this)
        lanDiscovery = DirectLanDiscovery(this)

        // Start LocalChatServer hosting embedded WebUI with resilient fallback ports
        startLocalChatServer()

        // Restore saved fleet credentials
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        // Older builds stored a shared owner key in ordinary app preferences.
        // Never restore or send it from this QR-only client.
        prefs.edit().remove(PREF_OWNER_KEY).apply()
        val savedGateway = prefs.getString(PREF_GATEWAY_URL, "https://mesh.inetconnector.com") ?: "https://mesh.inetconnector.com"
        MeshNodeService.ownerKey = ""
        MeshNodeService.deviceToken = MobileCredentialStore.load(this)
        MeshNodeService.gatewayUrl = savedGateway
        ownerKeyState.value = if (MeshNodeService.deviceToken.isNotBlank()) "paired-device" else ""
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
                val pendingUpdate = pendingUpdateState.value
                ComputeMeshMainScreen(
                    guard = batteryGuard,
                    lanDiscovery = lanDiscovery,
                    chatServerPort = chatServerPortState.intValue,
                    currentOwnerKey = ownerKeyState.value,
                    currentGatewayUrl = gatewayUrlState.value,
                    onStartNode = { startNodeService() },
                    onStopNode = { stopNodeService() },
                    onSaveFleetConfig = { key, gateway ->
                        when {
                            key.startsWith("cmenroll_") -> {
                                resolveEnrollmentToken(key, EnrollmentLinkPolicy.TRUSTED_GATEWAY)
                            }
                            key.isBlank() || key == ownerKeyState.value -> saveFleetConfig(key, gateway)
                            else -> Toast.makeText(
                                this@MainActivity,
                                "Flottenkopplung nur über den QR-Code aus dem ComputeMesh-Cockpit",
                                Toast.LENGTH_LONG
                            ).show()
                        }
                    }
                )
                if (pendingUpdate != null) {
                    AlertDialog(
                        onDismissRequest = { pendingUpdateState.value = null },
                        title = { Text("Neue App-Version verfügbar") },
                        text = { Text("ComputeMesh ${pendingUpdate.version} ist verfügbar. Jetzt herunterladen und installieren?") },
                        confirmButton = {
                            TextButton(onClick = {
                                pendingUpdateState.value = null
                                lifecycleScope.launch {
                                    updateCheckInProgressState.value = true
                                    try {
                                        AndroidUpdateChecker.downloadAndInstall(this@MainActivity, pendingUpdate)
                                    } catch (error: Throwable) {
                                        Toast.makeText(
                                            this@MainActivity,
                                            "Update konnte nicht installiert werden: ${error.message ?: "unbekannter Fehler"}",
                                            Toast.LENGTH_LONG,
                                        ).show()
                                    } finally {
                                        updateCheckInProgressState.value = false
                                    }
                                }
                            }) { Text("Aktualisieren") }
                        },
                        dismissButton = {
                            TextButton(onClick = { pendingUpdateState.value = null }) { Text("Später") }
                        },
                    )
                }
            }
        }

    }

    override fun onResume() {
        super.onResume()
        if (localChatServer == null || !localChatServer!!.isAlive) {
            startLocalChatServer()
        }
        // Check on every foreground transition so an update published while
        // the app was open is not missed. The in-flight guard prevents overlap.
        checkForAndroidUpdate()
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
        val payload = intent?.data?.toString() ?: return
        val enrollmentToken = EnrollmentLinkPolicy.tokenFromQr(payload)
        if (enrollmentToken == null) {
            Toast.makeText(this, "Ungültiger ComputeMesh-Pairing-Link", Toast.LENGTH_LONG).show()
            return
        }
        resolveEnrollmentToken(enrollmentToken, EnrollmentLinkPolicy.TRUSTED_GATEWAY)
    }

    private fun resolveEnrollmentToken(token: String, gateway: String) {
        // No QR token may be posted to a gateway controlled by the scanned data.
        if (gateway != EnrollmentLinkPolicy.TRUSTED_GATEWAY ||
            !Regex("cmenroll_[A-Za-z0-9_-]{20,64}").matches(token)) {
            Toast.makeText(this, "Ungültiger Pairing-Code oder Gateway", Toast.LENGTH_LONG).show()
            return
        }
        lifecycleScope.launch {
            try {
                val deviceToken = withContext(Dispatchers.IO) {
                    val endpoint = URL("${gateway.trimEnd('/')}/api/portal/fleet/mobile/enrollment/consume")
                    val connection = endpoint.openConnection() as HttpURLConnection
                    connection.instanceFollowRedirects = false
                    connection.requestMethod = "POST"
                    connection.doOutput = true
                    connection.setRequestProperty("Content-Type", "application/json")
                    connection.connectTimeout = 6000
                    connection.readTimeout = 6000
                    connection.outputStream.use {
                        it.write(
                            JSONObject().put("enrollment_token", token)
                                .put("node_id", MeshNodeService.getOrCreateNodeId(this@MainActivity))
                                .toString().toByteArray(Charsets.UTF_8)
                        )
                    }
                    if (connection.responseCode !in 200..299) {
                        error(getString(R.string.enrollment_failed_http, connection.responseCode))
                    }
                    JSONObject(connection.inputStream.bufferedReader().use { it.readText() }).optString("device_token")
                }
                if (!Regex("cm_mobile_[a-f0-9]{64}").matches(deviceToken)) {
                    error("Mobile device enrollment response invalid")
                }
                MobileCredentialStore.save(this@MainActivity, deviceToken)
                MeshNodeService.deviceToken = deviceToken
                MeshNodeService.ownerKey = ""
                MeshNodeService.gatewayUrl = EnrollmentLinkPolicy.TRUSTED_GATEWAY
                ownerKeyState.value = "paired-device"
                gatewayUrlState.value = EnrollmentLinkPolicy.TRUSTED_GATEWAY
                Toast.makeText(this@MainActivity, "QR-Berechtigung gespeichert. Online-Status erst nach Gateway-Heartbeat bestätigt.", Toast.LENGTH_LONG).show()
                startNodeService()
            } catch (error: Throwable) {
                Toast.makeText(
                    this@MainActivity,
                    getString(R.string.pairing_failed, error.message ?: getString(R.string.unknown_error)),
                    Toast.LENGTH_LONG,
                ).show()
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

        // A LAN inference gateway is not the mobile device's enrollment
        // authority. Do not revive master fleet keys from free-text inputs.
        MeshNodeService.ownerKey = ""
        MeshNodeService.gatewayUrl = effectiveGateway
        ownerKeyState.value = if (MeshNodeService.deviceToken.isNotBlank()) "paired-device" else ""
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

    private fun checkForAndroidUpdate() {
        if (updateCheckInProgressState.value) return
        updateCheckInProgressState.value = true
        lifecycleScope.launch {
            try {
                val currentVersion = packageManager.getPackageInfo(packageName, 0).versionName ?: "0.0.0"
                pendingUpdateState.value = AndroidUpdateChecker.check(currentVersion)
            } catch (error: Throwable) {
                android.util.Log.i("MainActivity", "Android update check skipped: ${error.message}")
            } finally {
                updateCheckInProgressState.value = false
            }
        }
    }
}
