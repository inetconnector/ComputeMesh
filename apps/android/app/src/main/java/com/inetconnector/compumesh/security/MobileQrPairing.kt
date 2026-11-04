package com.inetconnector.compumesh.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.inetconnector.compumesh.service.MeshNodeService
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * QR-only smartphone onboarding: the website holds the invitation, the
 * phone signs with a persistent device key. No master Owner-Key is transferred.
 *
 * API 29+: Ed25519 uses BouncyCastle lightweight primitives; its seed and
 * the scoped token are AES-GCM encrypted with a non-exportable AndroidKeyStore
 * key. No mutable global owner secret and no redirect-following HTTP requests.
 */
object MobileQrPairing {
    private const val GATEWAY = "https://mesh.inetconnector.com"
    private const val PREFS = "cm_mobile_qr_secure_v1"
    private const val KEY_ALIAS = "cm_mobile_qr_aes_v1"
    private const val KEY_SEED = "identity_seed"
    private const val KEY_TOKEN = "node_credential"

    private fun pref(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun secretKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore")
        store.load(null)
        val existing = store.getKey(KEY_ALIAS, null)
        if (existing is SecretKey) return existing
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(KeyGenParameterSpec.Builder(
            KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).build())
        return gen.generateKey()
    }

    private fun protect(bytes: ByteArray): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        return Base64.encodeToString(
            cipher.iv + cipher.doFinal(bytes), Base64.NO_WRAP
        )
    }

    private fun reveal(encrypted: String): ByteArray {
        val data = Base64.decode(encrypted, Base64.NO_WRAP)
        require(data.size > 28) { "Invalid encrypted credential" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, data.copyOfRange(0, 12)))
        return cipher.doFinal(data.copyOfRange(12, data.size))
    }

    @Synchronized
    private fun identity(context: Context): Ed25519PrivateKeyParameters {
        val stored = pref(context).getString(KEY_SEED, null)
        if (stored != null) {
            val raw = reveal(stored)
            require(raw.size == 32) { "Invalid persistent device identity" }
            return Ed25519PrivateKeyParameters(raw, 0)
        }
        val key = Ed25519PrivateKeyParameters(SecureRandom())
        check(pref(context).edit().putString(KEY_SEED, protect(key.encoded)).commit()) {
            "Could not securely persist mobile node identity"
        }
        return key
    }

    fun currentToken(context: Context): String? {
        val encrypted = pref(context).getString(KEY_TOKEN, null) ?: return null
        // Fail closed on corrupt encrypted storage, without rotating identity.
        return try {
            val token = String(reveal(encrypted), Charsets.US_ASCII)
            token.takeIf { it.startsWith("cm_pair_") && it.length in 40..127 }
        } catch (_: Exception) { null }
    }

    fun publicKeyHex(context: Context): String =
        identity(context).generatePublicKey().encoded.joinToString("") { "%02x".format(it) }

    private fun sign(key: Ed25519PrivateKeyParameters, payload: ByteArray): ByteArray {
        val signer = Ed25519Signer()
        signer.init(true, key)
        signer.update(payload, 0, payload.size)
        return signer.generateSignature()
    }

    fun invitationFromQr(raw: String): String =
        MobileQrProtocol.invitationFromQr(raw)

    fun pairFromQr(context: Context, raw: String): String {
        require(currentToken(context) == null) {
            "Dieses Handy ist bereits gekoppelt. Zum Wechseln erst sicher entkoppeln."
        }
        val invitation = invitationFromQr(raw)
        val nodeId = MeshNodeService.getOrCreateNodeId(context)
        require(nodeId.matches(Regex("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"))) {
            "Ungültige Gerätekennung."
        }
        val key = identity(context)
        val nonceBytes = ByteArray(24).also { SecureRandom().nextBytes(it) }
        val nonce = Base64.encodeToString(
            nonceBytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING
        )
        val timestamp = System.currentTimeMillis() / 1000
        val signature = sign(key, MobileQrProtocol.pairingMessage(
            "mobile-join", invitation, nodeId, nonce, timestamp
        )).joinToString("") { "%02x".format(it) }
        val body = JSONObject().apply {
            put("invitation", invitation)
            put("node_id", nodeId)
            put("public_key", publicKeyHex(context))
            put("nonce", nonce)
            put("timestamp", timestamp)
            put("signature", signature)
        }
        val url = URL("$GATEWAY/api/device/pairing/qr/redeem")
        val conn = url.openConnection() as HttpURLConnection
        try {
            conn.instanceFollowRedirects = false
            conn.connectTimeout = 8000
            conn.readTimeout = 10000
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            check(conn.responseCode == 200) { "QR ungültig, bereits verwendet oder abgelaufen." }
            val response = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
            check(response.optString("status") == "paired" &&
                  response.optString("node_id") == nodeId) { "Der Server hat das Gerät nicht bestätigt." }
            val token = response.optString("node_token")
            require(token.startsWith("cm_pair_") && token.length in 40..127) {
                "Server hat keine gültige Geräteberechtigung ausgestellt."
            }
            check(pref(context).edit().putString(KEY_TOKEN, protect(token.toByteArray(Charsets.US_ASCII))).commit()) {
                "Kopplung konnte nicht sicher gespeichert werden."
            }
            return nodeId
        } finally {
            conn.disconnect()
        }
    }

    fun signedHeartbeatIdentity(context: Context, nodeId: String): JSONObject? {
        val token = currentToken(context) ?: return null
        val key = identity(context)
        val nonceBytes = ByteArray(18).also { SecureRandom().nextBytes(it) }
        val nonce = Base64.encodeToString(nonceBytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        val timestamp = System.currentTimeMillis() / 1000
        val signature = sign(key, MobileQrProtocol.heartbeatMessage(nodeId, token, nonce, timestamp))
        val signed = Base64.encodeToString(signature, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        return JSONObject().apply {
            put("auth_token", token)
            put("public_key", publicKeyHex(context))
            put("signature", signed)
            put("timestamp", timestamp)
            put("nonce", nonce)
        }
    }
}