package com.inetconnector.compumesh.ui.tabs

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.inetconnector.compumesh.p2p.DirectLanDiscovery
import com.inetconnector.compumesh.p2p.LocalMeshPeer
import com.inetconnector.compumesh.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

enum class EndpointConnectionState(val displayTitle: String) {
    NOT_CONFIGURED("NICHT KONFIGURIERT"),
    CONNECTING("VERBINDUNG WIRD HERGESTELLT"),
    AUTH_REQUIRED("AUTHENTIFIZIERUNG ERFORDERLICH"),
    CONNECTED("VERBUNDEN"),
    OFFLINE("OFFLINE"),
    ERROR("FEHLER")
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

    var connectionState by remember { mutableStateOf(EndpointConnectionState.CONNECTING) }
    var connectionDetails by remember { mutableStateOf("") }
    var showAuthDialog by remember { mutableStateOf(false) }

    val cleanActiveGateway = currentGatewayUrl.trim().trimEnd('/')
    val isCustomActive = cleanActiveGateway.isNotBlank() && cleanActiveGateway != "https://mesh.inetconnector.com"

    fun probeGateway(targetUrl: String, ownerKey: String) {
        if (targetUrl.isBlank()) {
            connectionState = EndpointConnectionState.NOT_CONFIGURED
            connectionDetails = "Kein Inferenz-Endpunkt hinterlegt"
            return
        }

        connectionState = EndpointConnectionState.CONNECTING
        connectionDetails = "Prüfe Erreichbarkeit..."

        scope.launch(Dispatchers.IO) {
            val startMs = System.currentTimeMillis()
            var state = EndpointConnectionState.ERROR
            var detail = ""

            val candidates = mutableListOf<String>()
            if (targetUrl.endsWith("/health") || targetUrl.endsWith("/v1/models")) {
                candidates.add(targetUrl)
            } else {
                candidates.add("${targetUrl.trimEnd('/')}/health")
                candidates.add("${targetUrl.trimEnd('/')}/v1/models")
                candidates.add("${targetUrl.trimEnd('/')}/api/tags")
                candidates.add(targetUrl)
            }

            for (candidate in candidates) {
                var conn: HttpURLConnection? = null
                try {
                    conn = (URL(candidate).openConnection() as HttpURLConnection).apply {
                        requestMethod = "GET"
                        setRequestProperty("Accept", "application/json")
                        setRequestProperty("User-Agent", "ComputeMesh-Android-Probe/1.2")
                        if (ownerKey.isNotBlank()) {
                            setRequestProperty("Authorization", "Bearer $ownerKey")
                            setRequestProperty("X-Owner-Key", ownerKey)
                        }
                        connectTimeout = 3000
                        readTimeout = 3000
                    }
                    val code = conn.responseCode
                    val latency = System.currentTimeMillis() - startMs

                    when (code) {
                        in 200..299 -> {
                            state = EndpointConnectionState.CONNECTED
                            detail = "Erreichbar (${latency}ms Latenz)"
                            break
                        }
                        401, 403 -> {
                            state = EndpointConnectionState.AUTH_REQUIRED
                            detail = "HTTP $code: Autorisierung erforderlich"
                            break
                        }
                        404, 500, 502, 503 -> {
                            state = EndpointConnectionState.ERROR
                            detail = "HTTP $code: Dienst meldet Fehler"
                        }
                        else -> {
                            state = EndpointConnectionState.ERROR
                            detail = "HTTP $code"
                        }
                    }
                } catch (e: java.net.SocketTimeoutException) {
                    state = EndpointConnectionState.OFFLINE
                    detail = "Zeitüberschreitung (Timeout)"
                } catch (e: java.net.ConnectException) {
                    state = EndpointConnectionState.OFFLINE
                    detail = "Verbindung abgelehnt (Offline)"
                } catch (e: java.net.UnknownHostException) {
                    state = EndpointConnectionState.OFFLINE
                    detail = "Host nicht auflösbar"
                } catch (e: Exception) {
                    state = EndpointConnectionState.ERROR
                    detail = e.message ?: "Verbindungsfehler"
                } finally {
                    try { conn?.disconnect() } catch (_: Throwable) {}
                }
            }

            withContext(Dispatchers.Main) {
                connectionState = state
                connectionDetails = detail
            }
        }
    }

    fun runDiscovery() {
        if (isScanning) return
        isScanning = true
        scope.launch {
            val peers = lanDiscovery.discoverAllPeers(
                gatewayUrl = currentGatewayUrl,
                ownerKey = currentOwnerKey,
                timeoutMs = 3500
            )
            discoveredPeers.clear()
            discoveredPeers.addAll(peers)
            isScanning = false
        }
        probeGateway(currentGatewayUrl, currentOwnerKey)
    }

    LaunchedEffect(currentGatewayUrl, currentOwnerKey) {
        probeGateway(currentGatewayUrl, currentOwnerKey)
        runDiscovery()
    }

    if (showAuthDialog) {
        AlertDialog(
            onDismissRequest = { showAuthDialog = false },
            title = { Text("Authentifizierung erforderlich", fontWeight = FontWeight.Bold) },
            text = {
                Text(
                    "Dieser Knoten ($cleanActiveGateway) verlangt eine autorisierte Web-Sitzung.\n\n" +
                    "Um das Dashboard im Browser aufzurufen, melde dich bitte zuerst auf mesh.inetconnector.com mit deinem Benutzerkonto an."
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showAuthDialog = false
                        try {
                            val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://mesh.inetconnector.com/login"))
                            context.startActivity(intent)
                        } catch (e: Exception) {
                            Toast.makeText(context, "Fehler beim Öffnen: ${e.message}", Toast.LENGTH_SHORT).show()
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = CyanAccent)
                ) {
                    Text("Zum Login ↗", color = DeepVoidBg, fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                TextButton(onClick = { showAuthDialog = false }) {
                    Text("Schließen", color = TextSecondary)
                }
            }
        )
    }

    fun isPeerConnected(peer: LocalMeshPeer): Boolean {
        val target = peer.targetUrl.trimEnd('/')
        return cleanActiveGateway == target ||
                (peer.ipAddress.isNotBlank() && cleanActiveGateway.contains(peer.ipAddress) && !cleanActiveGateway.contains("inetconnector.com"))
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
                "Findet automatisch ComputeMesh Mining-Rigs & Rechner im lokalen Netzwerk über UDP Port 13379 – 100% lokal ohne externen Traffic.",
                color = TextSecondary,
                fontSize = 13.sp,
                lineHeight = 18.sp
            )
        }

        item {
            // Echter, geprüfter Inferenz-Endpunkt Status
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(
                    1.dp,
                    when (connectionState) {
                        EndpointConnectionState.CONNECTED -> EmeraldSuccess.copy(alpha = 0.6f)
                        EndpointConnectionState.AUTH_REQUIRED -> AmberWarning.copy(alpha = 0.6f)
                        EndpointConnectionState.OFFLINE -> RoseDanger.copy(alpha = 0.6f)
                        EndpointConnectionState.ERROR -> RoseDanger.copy(alpha = 0.6f)
                        EndpointConnectionState.CONNECTING -> CyanAccent.copy(alpha = 0.5f)
                        EndpointConnectionState.NOT_CONFIGURED -> CardSurfaceBorder
                    }
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Icon(
                            imageVector = when (connectionState) {
                                EndpointConnectionState.CONNECTED -> Icons.Default.CheckCircle
                                EndpointConnectionState.AUTH_REQUIRED -> Icons.Default.Lock
                                EndpointConnectionState.OFFLINE -> Icons.Default.CloudOff
                                EndpointConnectionState.ERROR -> Icons.Default.Warning
                                EndpointConnectionState.CONNECTING -> Icons.Default.Sync
                                EndpointConnectionState.NOT_CONFIGURED -> Icons.Default.CloudQueue
                            },
                            contentDescription = null,
                            tint = when (connectionState) {
                                EndpointConnectionState.CONNECTED -> EmeraldSuccess
                                EndpointConnectionState.AUTH_REQUIRED -> AmberWarning
                                EndpointConnectionState.OFFLINE -> RoseDanger
                                EndpointConnectionState.ERROR -> RoseDanger
                                EndpointConnectionState.CONNECTING -> CyanAccent
                                EndpointConnectionState.NOT_CONFIGURED -> TextMuted
                            },
                            modifier = Modifier.size(24.dp)
                        )
                        Spacer(modifier = Modifier.width(10.dp))
                        Text(
                            "Inferenz-Endpunkt Status",
                            color = TextSecondary,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Medium
                        )
                        Spacer(modifier = Modifier.weight(1f))
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = when (connectionState) {
                                EndpointConnectionState.CONNECTED -> EmeraldSuccess.copy(alpha = 0.18f)
                                EndpointConnectionState.AUTH_REQUIRED -> AmberWarning.copy(alpha = 0.18f)
                                EndpointConnectionState.OFFLINE -> RoseDanger.copy(alpha = 0.18f)
                                EndpointConnectionState.ERROR -> RoseDanger.copy(alpha = 0.18f)
                                EndpointConnectionState.CONNECTING -> CyanAccent.copy(alpha = 0.15f)
                                EndpointConnectionState.NOT_CONFIGURED -> CardSurfaceBorder
                            }
                        ) {
                            Text(
                                connectionState.displayTitle,
                                color = when (connectionState) {
                                    EndpointConnectionState.CONNECTED -> EmeraldSuccess
                                    EndpointConnectionState.AUTH_REQUIRED -> AmberWarning
                                    EndpointConnectionState.OFFLINE -> RoseDanger
                                    EndpointConnectionState.ERROR -> RoseDanger
                                    EndpointConnectionState.CONNECTING -> CyanAccent
                                    EndpointConnectionState.NOT_CONFIGURED -> TextMuted
                                },
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    Text(
                        if (cleanActiveGateway.isNotBlank()) cleanActiveGateway else "https://mesh.inetconnector.com",
                        color = TextPrimary,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )

                    if (connectionDetails.isNotBlank()) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            connectionDetails,
                            color = when (connectionState) {
                                EndpointConnectionState.CONNECTED -> EmeraldSuccess.copy(alpha = 0.9f)
                                EndpointConnectionState.AUTH_REQUIRED -> AmberWarning.copy(alpha = 0.9f)
                                EndpointConnectionState.OFFLINE -> RoseDanger.copy(alpha = 0.9f)
                                EndpointConnectionState.ERROR -> RoseDanger.copy(alpha = 0.9f)
                                else -> TextSecondary
                            },
                            fontSize = 12.sp
                        )
                    }

                    Spacer(modifier = Modifier.height(12.dp))
                    Row(
                        horizontalArrangement = Arrangement.End,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Button(
                            onClick = {
                                if (connectionState == EndpointConnectionState.AUTH_REQUIRED) {
                                    showAuthDialog = true
                                } else {
                                    try {
                                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(cleanActiveGateway.ifBlank { "https://mesh.inetconnector.com" }))
                                        context.startActivity(intent)
                                    } catch (e: Exception) {
                                        Toast.makeText(context, "Konnte Browser nicht öffnen: ${e.message}", Toast.LENGTH_SHORT).show()
                                    }
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = CardSurfaceBorder),
                            shape = RoundedCornerShape(8.dp),
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
                        ) {
                            Icon(Icons.Default.OpenInBrowser, contentDescription = null, tint = CyanAccent, modifier = Modifier.size(16.dp))
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Dashboard ↗", color = CyanAccent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                        }

                        if (isCustomActive) {
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
                    Text("Scanne Heimnetzwerk & Flotte...", color = DeepVoidBg, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                } else {
                    Icon(Icons.Default.Refresh, contentDescription = null, tint = DeepVoidBg)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Mesh- & Flotten-Knoten suchen", color = DeepVoidBg, fontWeight = FontWeight.Bold, fontSize = 14.sp)
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
                        modifier = Modifier.padding(20.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Icon(Icons.Default.WifiTethering, contentDescription = null, tint = CyanAccent, modifier = Modifier.size(36.dp))
                        Spacer(modifier = Modifier.height(10.dp))
                        Text("Keine lokalen LAN-Knoten im aktuellen Netzwerk gefunden", color = TextPrimary, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                        Spacer(modifier = Modifier.height(4.dp))
                        Text("Stelle sicher, dass andere Knoten im selben WLAN sind oder nutze das Cloud-Gateway.", color = TextSecondary, fontSize = 12.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                    }
                }
            }
        } else {
            items(discoveredPeers) { peer ->
                val peerTargetUrl = peer.targetUrl
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
                            if (peer.requiresAuth) {
                                showAuthDialog = true
                            } else {
                                try {
                                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(peerTargetUrl))
                                    context.startActivity(intent)
                                } catch (e: Exception) {
                                    Toast.makeText(context, "Konnte Browser nicht öffnen: ${e.message}", Toast.LENGTH_SHORT).show()
                                }
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
                                Text(
                                    if (peer.ipAddress.isNotBlank()) "${peer.ipAddress}:${peer.port}" else peer.targetUrl,
                                    color = CyanAccent,
                                    fontSize = 13.sp,
                                    fontFamily = FontFamily.Monospace,
                                    fontWeight = FontWeight.Medium
                                )
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
                            } else if (!peer.isLocalLan) {
                                Surface(
                                    shape = RoundedCornerShape(8.dp),
                                    color = IndigoAccent.copy(alpha = 0.15f)
                                ) {
                                    Text(
                                        "🌐 Flotten-Node",
                                        color = IndigoAccent,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
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

                        Spacer(modifier = Modifier.height(8.dp))

                        val statusColor = when {
                            peer.requiresAuth -> AmberWarning
                            peer.isAvailable -> EmeraldSuccess
                            peer.lifecycle == "reachable" -> CyanAccent
                            else -> TextMuted
                        }
                        Text(
                            when {
                                peer.requiresAuth -> "⚠ Authentifizierung erforderlich"
                                peer.isAvailable -> "✓ Verfügbar${if (peer.modelIds.isNotEmpty()) " · ${peer.modelIds.size} Modelle erkannt" else ""}"
                                peer.lifecycle == "reachable" -> "Erreichbar"
                                peer.lifecycle == "unreachable" -> "Knoten nicht erreichbar"
                                else -> "Prüfe Knotenstatus …"
                            },
                            color = statusColor,
                            fontSize = 11.5.sp,
                            lineHeight = 16.sp
                        )

                        Spacer(modifier = Modifier.height(12.dp))

                        Row(
                            horizontalArrangement = Arrangement.End,
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Button(
                                onClick = {
                                    if (peer.requiresAuth) {
                                        showAuthDialog = true
                                    } else {
                                        try {
                                            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(peerTargetUrl))
                                            context.startActivity(intent)
                                        } catch (e: Exception) {
                                            Toast.makeText(context, "Fehler: ${e.message}", Toast.LENGTH_SHORT).show()
                                        }
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
                                            "✓ Gekoppelt mit ${peer.nodeId}!",
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
