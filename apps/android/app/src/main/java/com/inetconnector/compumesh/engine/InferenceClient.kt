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

        val targetUrl = "${gatewayUrl.trimEnd('/')}/v1/chat/completions"
        val effectiveModel = if (attachment?.isImage == true && !model.contains("vl")) VISION_MODEL else model
        val effectiveKey = apiKey.ifBlank { "cm_live_demo_mobile" }

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
                connectTimeout = 15000
                readTimeout = 60000
            }

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

            OutputStreamWriter(conn.outputStream, StandardCharsets.UTF_8).use { writer ->
                writer.write(root.toString())
                writer.flush()
            }

            val responseCode = conn.responseCode
            if (responseCode !in 200..299) {
                val errStream = conn.errorStream ?: conn.inputStream
                val errorBody = errStream?.bufferedReader()?.use { it.readText() } ?: "HTTP $responseCode"
                emit(StreamToken(token = "", isDone = true, error = "Gateway Fehler ($responseCode): $errorBody"))
                return@flow
            }

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
        } catch (e: Throwable) {
            Log.e(TAG, "Inference stream error", e)
            emit(StreamToken(token = "", isDone = true, error = "Verbindungsfehler: ${e.localizedMessage ?: e.message}"))
        }
    }.flowOn(Dispatchers.IO)
}
