package com.inetconnector.compumesh.security

import java.net.URI
import java.net.URISyntaxException

/** Pure protocol encoding, shared by Android QR registration and heartbeat. */
internal object MobileQrProtocol {
    private val inviteRegex = Regex("[A-Za-z0-9_-]{32,128}")
    private val nodeRegex = Regex("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    private val nonceRegex = Regex("[A-Za-z0-9_-]{12,120}")

    fun invitationFromQr(raw: String): String {
        val uri = try {
            URI(raw.trim())
        } catch (_: URISyntaxException) {
            throw IllegalArgumentException("QR-Code ist keine gültige ComputeMesh-Einladung.")
        }
        require(
            uri.scheme == "computemesh" &&
                uri.rawAuthority == "pair" &&
                uri.rawPath.isNullOrEmpty() &&
                uri.rawUserInfo == null &&
                uri.port == -1
        ) {
            "QR-Code ist kein eindeutiger ComputeMesh-Gerätecode."
        }
        val query = uri.rawQuery ?: ""
        require(query.startsWith("invite=") && !query.contains("&")) {
            "QR-Code enthält keine einzelne sichere Einladung."
        }
        val invite = query.removePrefix("invite=")
        require(inviteRegex.matches(invite)) {
            "QR-Code ist ungültig oder veraltet."
        }
        require(uri.fragment == null) { "QR-Code darf keine Zusatzdaten enthalten." }
        return invite
    }

    fun pairingMessage(
        action: String, invitation: String, nodeId: String,
        nonce: String, timestamp: Long,
    ): ByteArray {
        require(action == "mobile-join" && inviteRegex.matches(invitation))
        require(nodeRegex.matches(nodeId) && nonceRegex.matches(nonce) && timestamp > 0)
        val canonical = "{\"action\":\"$action\",\"node_id\":\"$nodeId\",\"nonce\":\"$nonce\",\"request_id\":\"$invitation\",\"timestamp\":$timestamp}"
        return ("ComputeMesh.Pairing.v1:" + canonical).toByteArray(Charsets.US_ASCII)
    }

    fun heartbeatMessage(
        nodeId: String, token: String, nonce: String, timestamp: Long,
    ): ByteArray {
        require(nodeRegex.matches(nodeId) && token.startsWith("cm_pair_"))
        require(nonceRegex.matches(nonce) && timestamp > 0)
        val canonical = "{\"auth_token\":\"$token\",\"node_id\":\"$nodeId\",\"nonce\":\"$nonce\",\"previous_node_id\":\"\",\"timestamp\":$timestamp}"
        return ("ComputeMesh.NodeHeartbeat.v2:" + canonical).toByteArray(Charsets.US_ASCII)
    }
}
