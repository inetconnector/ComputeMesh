package com.inetconnector.compumesh.ui

import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets

/** Accept only short-lived enrollment links emitted by the authenticated fleet portal. */
object EnrollmentLinkPolicy {
    const val TRUSTED_GATEWAY = "https://mesh.inetconnector.com"
    private val tokenPattern = Regex("cmenroll_[A-Za-z0-9_-]{20,64}")

    fun tokenFromQr(raw: String): String? {
        val candidate = raw.trim()
        if (candidate.length > 2048 || candidate.isEmpty()) return null
        val uri = try { URI(candidate) } catch (_: Exception) { return null }
        if (uri.isOpaque || uri.rawFragment != null || uri.rawUserInfo != null || uri.port != -1) return null
        val allowed = when (uri.scheme?.lowercase()) {
            "computemesh" -> uri.host == "pair" && (uri.path.isNullOrEmpty() || uri.path == "/")
            "https" -> uri.host == "mesh.inetconnector.com" && (uri.path == "/pair" || uri.path == "/pair/")
            else -> false
        }
        if (!allowed) return null
        val query = uri.rawQuery ?: return null
        if (query.length > 512) return null
        var token: String? = null
        var gatewaySeen = false
        for (part in query.split('&')) {
            val pair = part.split('=', limit = 2)
            if (pair.size != 2) return null
            val name = try { URLDecoder.decode(pair[0], StandardCharsets.UTF_8.name()) } catch (_: Exception) { return null }
            val value = try { URLDecoder.decode(pair[1], StandardCharsets.UTF_8.name()) } catch (_: Exception) { return null }
            when (name) {
                "enrollment_token" -> {
                    if (token != null || !tokenPattern.matches(value)) return null
                    token = value
                }
                "gateway" -> {
                    if (gatewaySeen || value != TRUSTED_GATEWAY) return null
                    gatewaySeen = true
                }
                else -> return null // owner_key, secret, aliases, unknown fields are forbidden
            }
        }
        return token
    }
}
