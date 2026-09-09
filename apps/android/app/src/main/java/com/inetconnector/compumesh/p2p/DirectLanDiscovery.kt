package com.inetconnector.compumesh.p2p

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
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
    val isLocalLan: Boolean = true
)

/**
 * Direct Peer-to-Peer Local Network Discovery for Zero-Server-Traffic Operation.
 *
 * Combines UDP broadcast, unicast subnet sweeps, and fast HTTP probing to reliably
 * discover ComputeMesh nodes across all home Wi-Fi and router configurations.
 */
class DirectLanDiscovery(private val context: Context) {

    companion object {
        private const val TAG = "DirectLanDiscovery"
        const val DISCOVERY_PORT = 13379
        const val DISCOVERY_PROBE_MESSAGE = "COMPUTEMESH_DISCOVERY_PING"
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
                                gpuSummary = gpu
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

