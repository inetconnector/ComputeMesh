package com.computemesh.p2p

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
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
     * Broadcasts a discovery probe on the local Wi-Fi subnet to find nearby ComputeMesh nodes.
     */
    suspend fun discoverLocalPeers(timeoutMs: Int = 3000): List<LocalMeshPeer> = withContext(Dispatchers.IO) {
        val peers = mutableListOf<LocalMeshPeer>()
        var socket: DatagramSocket? = null

        try {
            socket = DatagramSocket().apply {
                broadcast = true
                soTimeout = 1000
            }

            val sendData = DISCOVERY_PROBE_MESSAGE.toByteArray(Charsets.UTF_8)
            val broadcastAddr = InetAddress.getByName("255.255.255.255")
            val sendPacket = DatagramPacket(sendData, sendData.size, broadcastAddr, DISCOVERY_PORT)
            socket.send(sendPacket)

            val receiveBuf = ByteArray(1024)
            val receivePacket = DatagramPacket(receiveBuf, receiveBuf.size)
            val startTime = System.currentTimeMillis()

            while (System.currentTimeMillis() - startTime < timeoutMs) {
                try {
                    socket.receive(receivePacket)
                    val response = String(receivePacket.data, 0, receivePacket.length, Charsets.UTF_8)
                    if (response.startsWith("COMPUTEMESH_PONG:")) {
                        val parts = response.removePrefix("COMPUTEMESH_PONG:").split(";")
                        val nodeId = parts.getOrNull(0) ?: "local-node"
                        val port = parts.getOrNull(1)?.toIntOrNull() ?: 8000
                        val gpu = parts.getOrNull(2) ?: "Local GPU"

                        peers.add(
                            LocalMeshPeer(
                                nodeId = nodeId,
                                ipAddress = receivePacket.address.hostAddress ?: "",
                                port = port,
                                gpuSummary = gpu
                            )
                        )
                    }
                } catch (e: SocketTimeoutException) {
                    // Normal timeout while waiting for packets
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Local LAN discovery failed", e)
        } finally {
            socket?.close()
        }

        peers
    }
}
