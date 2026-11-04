package com.inetconnector.compumesh.security

import org.junit.Assert.*
import org.junit.Test

class MobileQrProtocolTest {
    private val invitation = "ABCDEFGHabcdefgh12345678uvwxyzABCD98765"
    private val nodeId = "android-pixel-test"
    private val nonce = "ABCDabcd1234567890"

    @Test fun scanOnlyAcceptsOneShortLivedInvitation() {
        assertEquals(
            invitation,
            MobileQrProtocol.invitationFromQr("computemesh://pair?invite=$invitation")
        )
        listOf(
            "computemesh://pair?owner_key=inet-SECRET",
            "computemesh://pair?enrollment_token=LEGACY",
            "computemesh://pair?invite=$invitation&owner_key=abc",
            "https://mesh.inetconnector.com/fleet?invite=$invitation",
            "computemesh://wrong?invite=$invitation",
            "computemesh://pair?invite=$invitation#untrusted",
            "computemesh://pair/?invite=$invitation",
            "computemesh://pair/other?invite=$invitation",
            "computemesh://attacker@pair?invite=$invitation",
            "computemesh://pair:443?invite=$invitation",
            "computemesh://pair?invite=$invitation;extra=true",
            "computemesh://pair?invite=$invitation?unexpected",
            "computemesh://pair?invite=%ZZ",
            "computemesh://pair?invite=$invitation%4X",
        ).forEach { value ->
            try {
                MobileQrProtocol.invitationFromQr(value)
                fail("Old or untrusted QR should be rejected: $value")
            } catch (_: IllegalArgumentException) { /* expected */ }
        }
    }

    @Test fun deviceSignatureMessageMatchesPythonCanonicalEncoding() {
        val expected = "ComputeMesh.Pairing.v1:" +
            "{\"action\":\"mobile-join\",\"node_id\":\"$nodeId\",\"nonce\":\"$nonce\",\"request_id\":\"$invitation\",\"timestamp\":123456}"
        assertEquals(expected,
            String(MobileQrProtocol.pairingMessage("mobile-join", invitation, nodeId, nonce, 123456)))
    }

    @Test fun deviceSignatureIsBoundToActionAndParameters() {
        try {
            MobileQrProtocol.pairingMessage("approve", invitation, nodeId, nonce, 123456)
            fail("Wrong action must not be signed")
        } catch (_: IllegalArgumentException) { /* expected */ }
        try {
            MobileQrProtocol.pairingMessage("mobile-join", invitation, "bad|id", nonce, 123456)
            fail("Invalid node IDs must not be signed")
        } catch (_: IllegalArgumentException) { /* expected */ }
    }

    @Test fun heartbeatSignatureMessageMatchesPythonCanonicalEncoding() {
        val token = "cm_pair_" + "x".repeat(54)
        val expected = "ComputeMesh.NodeHeartbeat.v2:" +
            "{\"auth_token\":\"$token\",\"node_id\":\"$nodeId\",\"nonce\":\"$nonce\",\"previous_node_id\":\"\",\"timestamp\":123456}"
        assertEquals(expected,
            String(MobileQrProtocol.heartbeatMessage(nodeId, token, nonce, 123456)))
    }
}
