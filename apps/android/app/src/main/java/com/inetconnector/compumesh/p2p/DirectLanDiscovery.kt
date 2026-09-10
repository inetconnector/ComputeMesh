package com.inetconnector.compumesh.p2p

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import com.inetconnector.compumesh.service.MeshNodeService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import java.net.URL

data class LocalMeshPeer(
    val nodeId: String,
    val ipAddress: String,
    val port: Int,
    val gpuSummary: String,
    val isLocalLan: Boolean = true,
    val remoteUrl: String = ""
) {
    val targetUrl: String
        get() = if (remoteUrl.isNotBlank()) remoteUrl else "http://$ipAddress:$port"
}

/**
 * Direct Peer-to-Peer Local Network Discovery & Fleet Hub for Zero-Server-Traffic & Cloud Mesh.
 *
 * Combines UDP broadcast, unicast subnet sweeps, and Fleet coordinator polling to reliably
 * discover ComputeMesh nodes across all home Wi-Fi, mining rigs, and registered fleet devices.
 */
class DirectLanDiscovery(private val context: Context) {

    companion object {
        private const val TAG = "DirectLanDiscovery"
        const val DISCOVERY_PORT = 13379
        const val DISCOVERY_PROBE_MESSAGE = "COMPUTEMESH_DISCOVERY_PING"
    }

    suspend fun discoverFleetPeers(gatewayUrl: String, ownerKey: String): List<LocalMeshPeer> = withContext(Dispatchers.IO) {
        val fleetPeers = mutableListOf<LocalMeshPeer>()
        val gateways = linkedSetOf("https://mesh.inetconnector.com")
        if (gatewayUrl.isNotBlank() && gatewayUrl.startsWith("http")) {
            gateways.add(gatewayUrl.trimEnd('/'))
        }

        val endpoints = mutableListOf<String>()
        for (gw in gateways) {
            if (ownerKey.isNotBlank() && !ownerKey.startsWith("http")) {
                endpoints.add("$gw/api/v1/mesh/fleet?owner_key=${java.net.URLEncoder.encode(ownerKey, "UTF-8")}")
                endpoints.add("$gw/api/portal/fleet?owner_key=${java.net.URLEncoder.encode(ownerKey, "UTF-8")}")
            }
            endpoints.add("$gw/api/v1/mesh/fleet")
            endpoints.add("$gw/api/portal/fleet")
        }

        for (ep in endpoints) {
            try {
                val conn = (URL(ep).openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    setRequestProperty("Accept", "application/json")
                    if (ownerKey.isNotBlank() && !ownerKey.startsWith("http")) {
                        setRequestProperty("X-Owner-Key", ownerKey)
                        setRequestProperty("Authorization", "Bearer $ownerKey")
                    }
                    connectTimeout = 3000
                    readTimeout = 3000
                }
                if (conn.responseCode in 200..299) {
                    val rawStr = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                    val json = JSONObject(rawStr)
                    val nodes = json.optJSONArray("nodes") ?: JSONArray()
                    val myNodeId = MeshNodeService.getOrCreateNodeId(context)
                    for (i in 0 until nodes.length()) {
                        val n = nodes.getJSONObject(i)
                        val nodeId = n.optString("node_id", "fleet-node")
                        val isOnline = n.optBoolean("is_online", true) && n.optString("status", "online") != "offline"
                        if (!isOnline) {
                            continue
                        }
                        // Skip self and skip battery-powered mobile clients from remote compute tunneling list
                        if (nodeId == myNodeId || nodeId == MeshNodeService.nodeId || (nodeId.startsWith("android-") && n.optInt("vram_gb", 0) == 0 && n.optDouble("tflops", 0.0) <= 2.0)) {
                            continue
                        }
                        val remoteUrl = n.optString("remote_url", "")
                        val vram = n.optInt("vram_gb", 0)
                        val tflops = n.optDouble("tflops", 0.0)
                        val gpuName = n.optString("device_name", n.optString("gpu_name", "Compute Node GPU"))
                        val summary = if (vram > 0) "$gpuName (${vram} GB VRAM • ${tflops} TF)" else gpuName

                        var ip = ""
                        var port = 8080
                        if (remoteUrl.isNotBlank()) {
                            try {
                                val u = URL(remoteUrl)
                                ip = u.host
                                port = if (u.port > 0) u.port else (if (u.protocol == "https") 443 else 80)
                            } catch (_: Exception) {}
                        }
                        val primaryGw = gateways.first().trimEnd('/')
                        val fullRemoteUrl = when {
                            remoteUrl.startsWith("http://") || remoteUrl.startsWith("https://") -> remoteUrl
                            remoteUrl.isNotBlank() -> "$primaryGw${if (remoteUrl.startsWith("/")) "" else "/"}$remoteUrl"
                            else -> "$primaryGw/node/$nodeId"
                        }

                        if (ip.isBlank()) {
                            ip = primaryGw.removePrefix("https://").removePrefix("http://").substringBefore(':').substringBefore('/')
                            port = if (primaryGw.startsWith("https")) 443 else 80
                        }

                        fleetPeers.add(
                            LocalMeshPeer(
                                nodeId = nodeId,
                                ipAddress = ip,
                                port = port,
                                gpuSummary = summary,
                                isLocalLan = false,
                                remoteUrl = fullRemoteUrl
                            )
                        )
                    }
                    if (fleetPeers.isNotEmpty()) {
                        break
                    }
                }
            } catch (e: Exception) {
                Log.d(TAG, "Fleet peer query to $ep failed: ${e.message}")
            }
        }
        fleetPeers
    }

    suspend fun discoverAllPeers(
        gatewayUrl: String = "",
        ownerKey: String = "",
        timeoutMs: Int = 3500
    ): List<LocalMeshPeer> = coroutineScope {
        val lanDeferred = async { discoverLocalPeers(timeoutMs) }
        val fleetDeferred = async { discoverFleetPeers(gatewayUrl, ownerKey) }

        val lanList = lanDeferred.await()
        val fleetList = fleetDeferred.await()

        val merged = LinkedHashMap<String, LocalMeshPeer>()
        // 1. Add direct local LAN peers
        for (peer in lanList) {
            merged[peer.nodeId] = peer
        }

        // 2. Add or enrich with fleet peers
        for (fleetPeer in fleetList) {
            val existing = merged[fleetPeer.nodeId]
            if (existing != null) {
                merged[fleetPeer.nodeId] = existing.copy(
                    gpuSummary = if (existing.gpuSummary == "Local Compute" || existing.gpuSummary.isBlank()) fleetPeer.gpuSummary else existing.gpuSummary
                )
            } else {
                merged[fleetPeer.nodeId] = fleetPeer
            }
        }

        merged.values.toList()
    }

    suspend fun discoverLocalPeers(timeoutMs: Int = 3500): List<LocalMeshPeer> = withContext(Dispatchers.IO) {
        val peersMap = LinkedHashMap<String, LocalMeshPeer>()
        var socket: DatagramSocket? = null
        var multicastLock: WifiManager.MulticastLock? = null

        val localIpv4Prefixes = mutableListOf<String>()
        val broadcastTargets = LinkedHashSet<InetAddress>()

        try {
            // 1. Acquire Android MulticastLock
            try {
                val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                multicastLock = wifiManager?.createMulticastLock("ComputeMeshLanDiscovery")
                multicastLock?.setReferenceCounted(true)
                multicastLock?.acquire()
            } catch (e: Exception) {
                Log.w(TAG, "MulticastLock unavailable: ${e.message}")
            }

            // 2. Discover local network interfaces & subnets
            try {
                val interfaces = NetworkInterface.getNetworkInterfaces()
                while (interfaces != null && interfaces.hasMoreElements()) {
                    val iface = interfaces.nextElement()
                    if (iface.isLoopback || !iface.isUp) continue
                    for (addr in iface.interfaceAddresses) {
                        val broadcast = addr.broadcast
                        if (broadcast != null) {
                            broadcastTargets.add(broadcast)
                        }
                        val ip = addr.address
                        if (ip is Inet4Address && !ip.isLoopbackAddress) {
                            val host = ip.hostAddress ?: ""
                            val lastDot = host.lastIndexOf('.')
                            if (lastDot > 0) {
                                localIpv4Prefixes.add(host.substring(0, lastDot + 1))
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error enumerating interfaces: ${e.message}")
            }

            // Global broadcast fallback
            try {
                broadcastTargets.add(InetAddress.getByName("255.255.255.255"))
            } catch (_: Exception) {}

            // 3. UDP Socket for sending and receiving discovery packets
            socket = DatagramSocket().apply {
                broadcast = true
                soTimeout = 250
            }

            val sendData = DISCOVERY_PROBE_MESSAGE.toByteArray(Charsets.UTF_8)

            fun sendProbeBurst() {
                // Broadcast burst
                for (target in broadcastTargets) {
                    try {
                        val sendPacket = DatagramPacket(sendData, sendData.size, target, DISCOVERY_PORT)
                        socket?.send(sendPacket)
                    } catch (_: Exception) {}
                }

                // Unicast subnet sweep (bypasses Wi-Fi router AP isolation & broadcast filters)
                for (prefix in localIpv4Prefixes.distinct()) {
                    for (i in 1..254) {
                        try {
                            val ip = InetAddress.getByName("$prefix$i")
                            val sendPacket = DatagramPacket(sendData, sendData.size, ip, DISCOVERY_PORT)
                            socket?.send(sendPacket)
                        } catch (_: Exception) {}
                    }
                }
            }

            sendProbeBurst()

            val receiveBuf = ByteArray(2048)
            val receivePacket = DatagramPacket(receiveBuf, receiveBuf.size)
            val startTime = System.currentTimeMillis()
            var lastBurstTime = startTime
            var burstCount = 1

            while (System.currentTimeMillis() - startTime < timeoutMs) {
                if (burstCount < 2 && System.currentTimeMillis() - lastBurstTime >= 500) {
                    sendProbeBurst()
                    burstCount++
                    lastBurstTime = System.currentTimeMillis()
                }

                try {
                    socket.receive(receivePacket)
                    val response = String(receivePacket.data, 0, receivePacket.length, Charsets.UTF_8).trim()
                    Log.d(TAG, "UDP response: $response from ${receivePacket.address.hostAddress}")

                    if (response.startsWith("COMPUTEMESH_PONG:")) {
                        val payload = response.removePrefix("COMPUTEMESH_PONG:").trim()
                        val parts = payload.split(";")
                        val nodeId = parts.getOrNull(0)?.trim()?.ifBlank { null } ?: "local-node"
                        val port = parts.getOrNull(1)?.trim()?.toIntOrNull() ?: 8080
                        val gpu = parts.getOrNull(2)?.trim()?.ifBlank { null } ?: "Local Compute"
                        val peerIp = receivePacket.address.hostAddress ?: ""

                        if (peerIp.isNotBlank()) {
                            val key = "$peerIp:$port"
                            peersMap[key] = LocalMeshPeer(
                                nodeId = nodeId,
                                ipAddress = peerIp,
                                port = port,
                                gpuSummary = gpu,
                                isLocalLan = true,
                                remoteUrl = "http://$peerIp:$port"
                            )
                        }
                    }
                } catch (_: SocketTimeoutException) {
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Local LAN discovery failed", e)
        } finally {
            try { socket?.close() } catch (_: Exception) {}
            try {
                if (multicastLock?.isHeld == true) multicastLock.release()
            } catch (_: Exception) {}
        }

        peersMap.values.toList()
    }
}

