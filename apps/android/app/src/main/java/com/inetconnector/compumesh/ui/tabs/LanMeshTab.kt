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
import kotlinx.coroutines.launch

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
            val peers = lanDiscovery.discoverAllPeers(
                gatewayUrl = currentGatewayUrl,
                ownerKey = currentOwnerKey,
                timeoutMs = 3500
            )
            discoveredPeers.clear()
            discoveredPeers.addAll(peers)
            isScanning = false
        }
    }

    LaunchedEffect(Unit) {
        runDiscovery()
    }

    val cleanActiveGateway = currentGatewayUrl.trim().trimEnd('/')
    val isTunnelActive = cleanActiveGateway.contains("/node/")
    val isLanActive = cleanActiveGateway.isNotBlank() && cleanActiveGateway != "https://mesh.inetconnector.com" && !isTunnelActive
    val isCustomActive = isTunnelActive || isLanActive

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
                    when {
                        isTunnelActive -> CyanAccent.copy(alpha = 0.6f)
                        isLanActive -> EmeraldSuccess.copy(alpha = 0.6f)
                        else -> CardSurfaceBorder
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
                            imageVector = when {
                                isTunnelActive -> Icons.Default.VpnLock
                                isLanActive -> Icons.Default.Router
                                else -> Icons.Default.Cloud
                            },
                            contentDescription = null,
                            tint = when {
                                isTunnelActive -> CyanAccent
                                isLanActive -> EmeraldSuccess
                                else -> CyanAccent
                            },
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
                            color = when {
                                isTunnelActive -> CyanAccent.copy(alpha = 0.18f)
                                isLanActive -> EmeraldSuccess.copy(alpha = 0.15f)
                                else -> CyanAccent.copy(alpha = 0.12f)
                            }
                        ) {
                            Text(
                                when {
                                    isTunnelActive -> "✓ Cloud-Tunnel Aktiv"
                                    isLanActive -> "✓ LAN Aktiv"
                                    else -> "Cloud Gateway"
                                },
                                color = when {
                                    isTunnelActive -> CyanAccent
                                    isLanActive -> EmeraldSuccess
                                    else -> CyanAccent
                                },
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        if (isCustomActive) currentGatewayUrl else "https://mesh.inetconnector.com",
                        color = when {
                            isTunnelActive -> CyanAccent
                            isLanActive -> EmeraldSuccess
                            else -> TextPrimary
                        },
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )

                    if (isTunnelActive) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text("✓ 1:1 gesicherter Fernzugriff über Mobilfunk & WAN", color = CyanAccent.copy(alpha = 0.85f), fontSize = 11.5.sp)
                    } else if (isLanActive) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text("✓ 100% lokaler P2P Heimnetzwerk-Traffic", color = EmeraldSuccess.copy(alpha = 0.85f), fontSize = 11.5.sp)
                    }

                    if (isCustomActive) {
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
                        Text("Keine lokalen LAN-Knoten im aktuellen WLAN gefunden", color = TextPrimary, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                        Spacer(modifier = Modifier.height(4.dp))
                        Text("Unterwegs im Mobilfunknetz? Verbinde dich direkt mit dem Cloud-Tunnel deiner Heimflotte.", color = TextSecondary, fontSize = 12.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                        Spacer(modifier = Modifier.height(14.dp))
                        Button(
                            onClick = {
                                onSaveFleetConfig(currentOwnerKey, "https://mesh.inetconnector.com/node/cm-inference-node-01")
                                Toast.makeText(context, "✓ Gekoppelt mit Heimserver-Tunnel (cm-inference-node-01)!", Toast.LENGTH_SHORT).show()
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                            shape = RoundedCornerShape(10.dp),
                            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp)
                        ) {
                            Icon(Icons.Default.VpnLock, contentDescription = null, tint = DeepVoidBg, modifier = Modifier.size(16.dp))
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("🌐 Heimserver tunneln (cm-inference-node-01)", color = DeepVoidBg, fontSize = 12.5.sp, fontWeight = FontWeight.Bold)
                        }
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
                                        "🌐 Cloud-Tunnel",
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
                                    Text(if (!peer.isLocalLan) "🌐 Tunneln" else "Verbinden", color = DeepVoidBg, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
