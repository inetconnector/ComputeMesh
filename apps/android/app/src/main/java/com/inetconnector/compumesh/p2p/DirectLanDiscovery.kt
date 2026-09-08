package com.inetconnector.compumesh.p2p

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException

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
 * Automatically pairs Android phones with local PCs/Mining Rigs on the same Wi-Fi
 * so 100% of inference, streaming, and model traffic stays inside the local home network.
 */
class DirectLanDiscovery(private val context: Context) {

    companion object {
        private const val TAG = "DirectLanDiscovery"
        const val DISCOVERY_PORT = 13379
        const val DISCOVERY_PROBE_MESSAGE = "COMPUTEMESH_DISCOVERY_PING"
    }

    /**
     * Broadcasts discovery probes across all local network interfaces to find nearby ComputeMesh nodes.
     */
    suspend fun discoverLocalPeers(timeoutMs: Int = 3000): List<LocalMeshPeer> = withContext(Dispatchers.IO) {
        val peersMap = LinkedHashMap<String, LocalMeshPeer>()
        var socket: DatagramSocket? = null
        var multicastLock: WifiManager.MulticastLock? = null

        try {
            // 1. Acquire Android MulticastLock to prevent Wi-Fi hardware from dropping broadcast/multicast packets
            try {
                val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                multicastLock = wifiManager?.createMulticastLock("ComputeMeshLanDiscovery")
                multicastLock?.setReferenceCounted(true)
                multicastLock?.acquire()
                Log.d(TAG, "Acquired Wi-Fi MulticastLock")
            } catch (e: Exception) {
                Log.w(TAG, "Could not acquire MulticastLock: ${e.message}")
            }

            // 2. Enumerate all active network broadcast addresses (e.g. 192.168.1.255, 192.168.178.255, etc.)
            val broadcastTargets = LinkedHashSet<InetAddress>()
            try {
                val interfaces = NetworkInterface.getNetworkInterfaces()
                while (interfaces != null && interfaces.hasMoreElements()) {
                    val networkInterface = interfaces.nextElement()
                    if (networkInterface.isLoopback || !networkInterface.isUp) continue
                    for (interfaceAddress in networkInterface.interfaceAddresses) {
                        val broadcast = interfaceAddress.broadcast
                        if (broadcast != null) {
                            broadcastTargets.add(broadcast)
                            Log.d(TAG, "Found broadcast address: ${broadcast.hostAddress} on ${networkInterface.displayName}")
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error enumerating network interfaces: ${e.message}")
            }

            // Always add global broadcast as fallback
            try {
                broadcastTargets.add(InetAddress.getByName("255.255.255.255"))
            } catch (e: Exception) {
                Log.w(TAG, "Could not resolve global broadcast address: ${e.message}")
            }

            // 3. Create DatagramSocket with broadcast enabled
            socket = DatagramSocket().apply {
                broadcast = true
                soTimeout = 300 // short timeout for iterative polling
            }

            val sendData = DISCOVERY_PROBE_MESSAGE.toByteArray(Charsets.UTF_8)

            fun sendProbeBurst() {
                for (target in broadcastTargets) {
                    try {
                        val sendPacket = DatagramPacket(sendData, sendData.size, target, DISCOVERY_PORT)
                        socket?.send(sendPacket)
                        Log.d(TAG, "Sent discovery ping to ${target.hostAddress}:$DISCOVERY_PORT")
                    } catch (e: Exception) {
                        Log.w(TAG, "Failed sending probe to $target: ${e.message}")
                    }
                }
            }

            // Send initial burst
            sendProbeBurst()

            val receiveBuf = ByteArray(2048)
            val receivePacket = DatagramPacket(receiveBuf, receiveBuf.size)
            val startTime = System.currentTimeMillis()
            var lastBurstTime = startTime
            var burstCount = 1

            while (System.currentTimeMillis() - startTime < timeoutMs) {
                // Send additional probe bursts at 400ms intervals up to 3 times
                if (burstCount < 3 && System.currentTimeMillis() - lastBurstTime >= 400) {
                    sendProbeBurst()
                    burstCount++
                    lastBurstTime = System.currentTimeMillis()
                }

                try {
                    socket.receive(receivePacket)
                    val response = String(receivePacket.data, 0, receivePacket.length, Charsets.UTF_8).trim()
                    Log.d(TAG, "Received UDP response: $response from ${receivePacket.address.hostAddress}")

                    if (response.startsWith("COMPUTEMESH_PONG:")) {
                        val payload = response.removePrefix("COMPUTEMESH_PONG:").trim()
                        val parts = payload.split(";")
                        val nodeId = parts.getOrNull(0)?.trim()?.ifBlank { null } ?: "local-node"
                        val port = parts.getOrNull(1)?.trim()?.toIntOrNull() ?: 8080
                        val gpu = parts.getOrNull(2)?.trim()?.ifBlank { null } ?: "Local GPU"
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
                } catch (e: SocketTimeoutException) {
                    // Normal timeout during receive window
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Local LAN discovery failed", e)
        } finally {
            try {
                socket?.close()
            } catch (e: Exception) {
                Log.w(TAG, "Error closing socket: ${e.message}")
            }
            try {
                if (multicastLock?.isHeld == true) {
                    multicastLock.release()
                    Log.d(TAG, "Released Wi-Fi MulticastLock")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error releasing MulticastLock: ${e.message}")
            }
        }

        peersMap.values.toList()
    }
}
