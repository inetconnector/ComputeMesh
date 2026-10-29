package com.inetconnector.compumesh.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class EnrollmentLinkPolicyTest {
    private val token = "cmenroll_" + "A".repeat(27)

    @Test
    fun acceptsOnlyFleetIssuedEnrollmentLinks() {
        val accepted = listOf(
            "computemesh://pair?enrollment_token=" + token,
            "computemesh://pair?enrollment_token=" + token + "&gateway=https://mesh.inetconnector.com",
            "https://mesh.inetconnector.com/pair?enrollment_token=" + token,
            "https://mesh.inetconnector.com/pair/?enrollment_token=" + token
        )
        accepted.forEach { assertEquals(token, EnrollmentLinkPolicy.tokenFromQr(it)) }
    }

    @Test
    fun rejectsUntrustedHostAndInsecureTransport() {
        val rejected = listOf(
            "http://mesh.inetconnector.com/pair?enrollment_token=" + token,
            "https://evil.test/pair?enrollment_token=" + token,
            "https://mesh.inetconnector.com.evil.test/pair?enrollment_token=" + token,
            "computemesh://other?enrollment_token=" + token,
            "https://user@mesh.inetconnector.com/pair?enrollment_token=" + token,
            "https://mesh.inetconnector.com:443/pair?enrollment_token=" + token,
            "computemesh://pair?enrollment_token=" + token + "&gateway=https://evil.test",
            "computemesh://pair?enrollment_token=" + token + "&gateway=http://mesh.inetconnector.com"
        )
        rejected.forEach { assertNull(EnrollmentLinkPolicy.tokenFromQr(it)) }
    }

    @Test
    fun rejectsMasterKeysSecretsAndInvalidTokenLinks() {
        val rejected = listOf(
            "inet-master-secret",
            "computemesh://pair?owner_key=inet-secret",
            "computemesh://pair?enrollment_token=" + token + "&owner_key=inet-secret",
            "computemesh://pair?enrollment_token=" + token + "&%6fwner_key=secret",
            "computemesh://pair?enrollment_token=" + token + "&enrollment_token=" + token,
            "computemesh://pair?enrollment_token=" + token + "#secret=anything",
            "computemesh://pair?enrollment_token=invalid",
            "computemesh://pair?enrollment_token=" + token + "&gateway=https%3A%2F%2Fmesh.inetconnector.com%2Fbad"
        )
        rejected.forEach { assertNull(EnrollmentLinkPolicy.tokenFromQr(it)) }
    }
}
