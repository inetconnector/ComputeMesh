package com.inetconnector.compumesh.engine

import android.content.Context
import android.util.Log
import com.inetconnector.compumesh.util.AttachmentInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets

data class StreamToken(
    val token: String,
    val isDone: Boolean = false,
    val tokenCount: Int = 0,
    val speedTokensPerSec: Double = 0.0,
    val latencyMs: Long = 0,
    val error: String? = null
)

object InferenceClient {
    private const val TAG = "InferenceClient"
    const val DEFAULT_GATEWAY = "https://mesh.inetconnector.com"
    const val DEFAULT_MODEL = "qwen2.5:7b"
    const val VISION_MODEL = "qwen2.5-vl:7b"

    private fun sanitizeError(raw: String): String {
        var clean = raw.replace(Regex("<[^>]*>"), " ")
            .replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
        clean = clean.replace(Regex("\\s+"), " ").trim()
        if (clean.contains("404") || clean.contains("Not Found")) return "Endpunkt nicht gefunden (404)"
        if (clean.contains("502") || clean.contains("Bad Gateway")) return "Server überlastet oder offline (502)"
        return clean.take(120)
    }

    fun streamChatCompletion(
        gatewayUrl: String,
        apiKey: String,
        model: String,
        messages: List<Pair<String, String>>, // role to content
        attachment: AttachmentInfo? = null
    ): Flow<StreamToken> = flow {
        val startTime = System.currentTimeMillis()
        var firstTokenTime: Long = 0
        var tokenCount = 0

        val effectiveModel = if (attachment?.isImage == true && !model.contains("vl")) VISION_MODEL else model
        val effectiveKey = apiKey.ifBlank { "cm_live_demo_mobile" }

        // Construct OpenAI JSON payload
        val root = JSONObject().apply {
            put("model", effectiveModel)
            put("stream", true)
            put("temperature", 0.7)
            put("max_tokens", 2048)

            val msgsArray = JSONArray()

            // System instruction
            msgsArray.put(JSONObject().apply {
                put("role", "system")
                put("content", "Du bist der offizielle ComputeMesh KI-Assistent. Antworte immer präzise, fundiert, hilfreich, auf Deutsch (oder in der Sprache des Nutzers), formatiert in klarem Markdown. Wenn Dokumente oder Bilder übergeben werden, analysiere diese gründlich.")
            })

            // Previous history and current message
            messages.forEachIndexed { index, (role, text) ->
                val isLast = index == messages.lastIndex
                if (isLast && attachment != null) {
                    if (attachment.isImage && attachment.base64DataUri != null) {
                        val contentArray = JSONArray()
                        contentArray.put(JSONObject().apply {
                            put("type", "text")
                            put("text", text.ifBlank { "Bitte analysiere dieses angehängte Bild im Detail." })
                        })
                        contentArray.put(JSONObject().apply {
                            put("type", "image_url")
                            put("image_url", JSONObject().apply {
                                put("url", attachment.base64DataUri)
                            })
                        })
                        msgsArray.put(JSONObject().apply {
                            put("role", role)
                            put("content", contentArray)
                        })
                    } else {
                        val fullText = buildString {
                            append(text)
                            if (!attachment.textContent.isNullOrBlank()) {
                                append("\n\n--- [ANGEHÄNGTES DOKUMENT: ${attachment.fileName} (${attachment.sizeFormatted})] ---\n")
                                append(attachment.textContent.take(150_000))
                                append("\n--- [ENDE DES DOKUMENTS] ---\n")
                            }
                        }
                        msgsArray.put(JSONObject().apply {
                            put("role", role)
                            put("content", fullText)
                        })
                    }
                } else {
                    msgsArray.put(JSONObject().apply {
                        put("role", role)
                        put("content", text)
                    })
                }
            }
            put("messages", msgsArray)
        }

        val payloadBytes = root.toString().toByteArray(StandardCharsets.UTF_8)

        // Build candidate URLs list
        val candidates = mutableListOf<String>()
        if (gatewayUrl.isNotBlank() && gatewayUrl != DEFAULT_GATEWAY) {
            val target = if (gatewayUrl.endsWith("/v1/chat/completions")) gatewayUrl else "${gatewayUrl.trimEnd('/')}/v1/chat/completions"
            if (!candidates.contains(target)) candidates.add(target)
            if (gatewayUrl.contains(":8080")) {
                val ollamaPort = gatewayUrl.replace(":8080", ":11434").trimEnd('/') + "/v1/chat/completions"
                if (!candidates.contains(ollamaPort)) candidates.add(ollamaPort)
            }
        }
        candidates.add("https://apps.inetconnector.com/klartext/api/v1/chat/completions")
        candidates.add("${DEFAULT_GATEWAY.trimEnd('/')}/v1/chat/completions")

        var successfulConn: HttpURLConnection? = null
        var lastErr = ""

        for (targetUrl in candidates) {
            try {
                val url = URL(targetUrl)
                val conn = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    setRequestProperty("Authorization", "Bearer $effectiveKey")
                    setRequestProperty("Accept", "text/event-stream")
                    setRequestProperty("Accept-Encoding", "identity")
                    setRequestProperty("Cache-Control", "no-cache")
                    setRequestProperty("User-Agent", "ComputeMesh-Android/1.2")
                    doOutput = true
                    connectTimeout = if (targetUrl.contains("192.168.") || targetUrl.contains("127.0.0.1")) 3500 else 8000
                    readTimeout = 60000
                }
                conn.outputStream.use { os ->
                    os.write(payloadBytes)
                    os.flush()
                }
                val responseCode = conn.responseCode
                if (responseCode in 200..299) {
                    successfulConn = conn
                    break
                } else {
                    val errStream = conn.errorStream ?: conn.inputStream
                    val errorBody = errStream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() } ?: "HTTP $responseCode"
                    lastErr = sanitizeError(errorBody)
                    try { conn.disconnect() } catch (_: Throwable) {}
                }
            } catch (e: Throwable) {
                lastErr = e.message ?: "Verbindungsfehler"
            }
        }

        val conn = successfulConn
        if (conn == null) {
            emit(StreamToken(token = "", isDone = true, error = "Inferenz-Gateway nicht erreichbar ($lastErr)"))
            return@flow
        }

        try {
            val contentType = conn.contentType ?: ""
            if (contentType.contains("event-stream")) {
                BufferedReader(InputStreamReader(conn.inputStream, StandardCharsets.UTF_8)).use { reader ->
                    var line: String?
                    while (reader.readLine().also { line = it } != null) {
                        val raw = line!!.trim()
                        if (raw.isEmpty() || raw.startsWith(":")) continue

                        if (raw == "data: [DONE]") {
                            val durationSec = (System.currentTimeMillis() - startTime) / 1000.0
                            val speed = if (durationSec > 0.05) tokenCount / durationSec else 0.0
                            emit(StreamToken(token = "", isDone = true, tokenCount = tokenCount, speedTokensPerSec = speed, latencyMs = firstTokenTime - startTime))
                            break
                        }

                        if (raw.startsWith("data:")) {
                            val dataJson = raw.removePrefix("data:").trim()
                            try {
                                val chunk = JSONObject(dataJson)
                                val choices = chunk.optJSONArray("choices")
                                if (choices != null && choices.length() > 0) {
                                    val delta = choices.getJSONObject(0).optJSONObject("delta")
                                    val textChunk = delta?.optString("content", "") ?: ""
                                    if (textChunk.isNotEmpty()) {
                                        if (tokenCount == 0) {
                                            firstTokenTime = System.currentTimeMillis()
                                        }
                                        tokenCount++
                                        val durationSec = (System.currentTimeMillis() - startTime) / 1000.0
                                        val currentSpeed = if (durationSec > 0.05) tokenCount / durationSec else 0.0
                                        val latency = if (firstTokenTime > 0) firstTokenTime - startTime else 0L

                                        emit(StreamToken(
                                            token = textChunk,
                                            isDone = false,
                                            tokenCount = tokenCount,
                                            speedTokensPerSec = currentSpeed,
                                            latencyMs = latency
                                        ))
                                    }
                                }
                            } catch (e: Throwable) {
                                Log.w(TAG, "Chunk parse error on: $raw", e)
                            }
                        }
                    }
                }
            } else {
                // Non-streaming JSON response fallback
                val bodyStr = conn.inputStream.bufferedReader(StandardCharsets.UTF_8).use { it.readText() }
                val json = JSONObject(bodyStr)
                val choices = json.optJSONArray("choices")
                val text = choices?.optJSONObject(0)?.optJSONObject("message")?.optString("content")
                    ?: choices?.optJSONObject(0)?.optJSONObject("delta")?.optString("content")
                    ?: bodyStr
                val durationSec = (System.currentTimeMillis() - startTime) / 1000.0
                emit(StreamToken(token = text, isDone = true, tokenCount = 1, speedTokensPerSec = 1.0 / maxOf(0.1, durationSec), latencyMs = 0L))
            }
        } catch (e: Throwable) {
            Log.e(TAG, "Stream reading error", e)
            emit(StreamToken(token = "", isDone = true, error = "Stream unterbrochen: ${e.message}"))
        } finally {
            try { conn.disconnect() } catch (_: Throwable) {}
        }
    }.flowOn(Dispatchers.IO)
}
