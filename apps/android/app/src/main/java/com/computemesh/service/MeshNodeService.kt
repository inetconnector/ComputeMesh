package com.computemesh.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.computemesh.engine.MiniCpmEngine
import com.computemesh.guard.BatteryPolicyGuard
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/**
 * Background Foreground Service managing the ComputeMesh Mobile Node.
 *
 * Transmits periodic heartbeats, updates token metrics, and listens for on-device inferencing.
 */
class MeshNodeService : Service() {

    companion object {
        private const val TAG = "MeshNodeService"
        private const val NOTIFICATION_ID = 1001
        private const val CHANNEL_ID = "computemesh_node_channel"

        const val ACTION_START = "com.computemesh.START_NODE"
        const val ACTION_STOP = "com.computemesh.STOP_NODE"

        var isRunning: Boolean = false
            private set

        var totalTokensProcessed: Long = 0
            private set

        var nodeId: String = "android-" + UUID.randomUUID().toString().substring(0, 8)
        var ownerKey: String = ""
        var gatewayUrl: String = "https://mesh.inetconnector.com"
    }

    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private lateinit var batteryGuard: BatteryPolicyGuard
    private lateinit var engine: MiniCpmEngine

    override fun onCreate() {
        super.onCreate()
        batteryGuard = BatteryPolicyGuard(this)
        engine = MiniCpmEngine.getInstance(this)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                startForeground(NOTIFICATION_ID, buildNotification("ComputeMesh Node aktiv (Standby)"))
                isRunning = true
                startHeartbeatLoop()
            }
        }
        return START_STICKY
    }

    private fun startHeartbeatLoop() {
        serviceScope.launch {
            while (isActive && isRunning) {
                try {
                    val guardStatus = batteryGuard.getStatus()
                    val payload = JSONObject().apply {
                        put("node_id", nodeId)
                        put("auth_token", "cm_mobile_" + nodeId.replace("-", "_"))
                        if (ownerKey.isNotBlank()) {
                            put("owner_key", ownerKey)
                        }
                        put("inventory", JSONObject().apply {
                            put("schema_version", 1)
                            put("host_architecture", "android_arm64")
                            put("total_gpus", 0)
                            put("total_vram_bytes", 0)
                            put("gpus", JSONArray())
                            put("battery_level", guardStatus.batteryPct)
                            put("is_charging", guardStatus.isCharging)
                            put("temperature_c", guardStatus.temperatureCelsius)
                        })
                        put("telemetry", JSONObject().apply {
                            put("tokens_processed", totalTokensProcessed)
                            put("earnings_cm", totalTokensProcessed)
                            put("local_compute_tflops", 1.5)
                            put("is_simulated", false)
                            put("is_compute_permitted", guardStatus.isComputePermitted)
                            put("restriction_reason", guardStatus.restrictionReason ?: "")
                        })
                        put("global_mesh", JSONObject())
                        put("software", JSONObject().apply {
                            put("model", "openbmb/minicpm5-2b")
                            put("version", "1.2.142")
                            put("client", "ComputeMesh-Android")
                        })
                    }

                    sendHeartbeat(payload)
                    updateNotification(guardStatus.isComputePermitted, guardStatus.restrictionReason)
                } catch (e: Exception) {
                    Log.e(TAG, "Heartbeat failed", e)
                }
                delay(10_000) // 10s Heartbeat
            }
        }
    }

    private fun sendHeartbeat(payload: JSONObject) {
        val url = URL("$gatewayUrl/api/v1/node/heartbeat")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("User-Agent", "ComputeMesh-Android-Node/1.2")
            doOutput = true
            connectTimeout = 8000
            readTimeout = 8000
        }

        conn.outputStream.use { os ->
            os.write(payload.toString().toByteArray(Charsets.UTF_8))
        }

        val code = conn.responseCode
        if (code == 200) {
            val resp = conn.inputStream.bufferedReader().use { it.readText() }
            try {
                val json = JSONObject(resp)
                if (json.has("tokens_processed")) {
                    totalTokensProcessed = json.getLong("tokens_processed")
                }
            } catch (_: Exception) {}
        }
        conn.disconnect()
    }

    private fun updateNotification(permitted: Boolean, reason: String?) {
        val text = if (permitted) {
            "Bereit für MiniCPM5-2B Mesh-Jobs (${totalTokensProcessed} Tokens)"
        } else {
            "Pausiert: ${reason ?: "Batterieschutz aktiv"}"
        }
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, buildNotification(text))
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "ComputeMesh Node Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Hintergrunddienst für dezentrale KI-Inferenz & Telemetrie"
            }
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(statusText: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("ComputeMesh Edge Node")
            .setContentText(statusText)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        isRunning = false
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
