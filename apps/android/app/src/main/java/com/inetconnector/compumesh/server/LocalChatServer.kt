package com.inetconnector.compumesh.server

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.Log
import com.inetconnector.compumesh.service.MeshNodeService
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject
import java.io.*
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.util.concurrent.Executors

class LocalChatServer(
    private val context: Context,
    port: Int = 0 // 0 = pick ephemeral available port
) : NanoHTTPD("127.0.0.1", if (port == 0) 8089 else port) {

    companion object {
        private const val TAG = "LocalChatServer"
        private val EXECUTOR = Executors.newCachedThreadPool()
    }

    override fun serve(session: IHTTPSession): Response {
        val uri = session.uri
        val method = session.method
        Log.d(TAG, "Request: $method $uri")

        if (method == Method.OPTIONS) {
            return addCorsHeaders(newFixedLengthResponse(Response.Status.NO_CONTENT, "text/plain", ""))
        }

        return try {
            when {
                uri == "/health" -> jsonResponse(
                    JSONObject()
                        .put("ok", true)
                        .put("server", "ComputeMesh")
                        .put("version", "1.2.143")
                        .put("model", "qwen2.5:7b")
                )

                uri in listOf("/props", "/api/props", "/properties", "/v1/props") -> jsonResponse(
                    JSONObject().apply {
                        put("model_alias", "qwen2.5:7b")
                        put("model_path", "qwen2.5:7b")
                        put("default_generation_settings", JSONObject().apply {
                            put("n_ctx", 32768)
                            put("n_predict", 2048)
                            put("temperature", 0.7)
                            put("top_k", 40)
                            put("top_p", 0.95)
                            put("min_p", 0.05)
                            put("stop", JSONArray().apply {
                                put("<|im_end|>")
                                put("<|endoftext|>")
                            })
                        })
                        put("total_slots", 1)
                        put("chat_template", "{% for message in messages %}{% if message['role'] == 'system' %}<|im_start|>system\n{{ message['content'] }}<|im_end|>\n{% elif message['role'] == 'user' %}<|im_start|>user\n{{ message['content'] }}<|im_end|>\n{% elif message['role'] == 'assistant' %}<|im_start|>assistant\n{% if message['reasoning_content'] %}<think>\n{{ message['reasoning_content'] }}\n</think>\n{% endif %}{{ message['content'] }}<|im_end|>\n{% endif %}{% endfor %}{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}")
                        put("modalities", JSONObject().apply {
                            put("text", true)
                            put("vision", true)
                            put("image", true)
                            put("audio", true)
                            put("video", false)
                        })
                    }
                )

                uri == "/slots" -> jsonResponse(
                    JSONArray().put(JSONObject().put("id", 0).put("is_processing", false))
                )

                uri in listOf("/tools", "/api/tools", "/v1/tools") -> jsonResponse(
                    JSONArray()
                )

                uri in listOf("/v1/streams/lookup", "/streams/lookup", "/api/streams/lookup") -> jsonResponse(
                    JSONArray()
                )

                uri.startsWith("/v1/stream/") || uri.startsWith("/stream/") -> {
                    val sseText = "data: [DONE]\n\n"
                    val bytes = sseText.toByteArray(StandardCharsets.UTF_8)
                    val resp = newFixedLengthResponse(Response.Status.OK, "text/event-stream; charset=utf-8", ByteArrayInputStream(bytes), bytes.size.toLong())
                    resp.addHeader("Cache-Control", "no-cache")
                    addCorsHeaders(resp)
                }

                uri in listOf("/version", "/api/version", "/v1/version") -> jsonResponse(
                    JSONObject().apply {
                        put("version", "1.2.143")
                        put("commit", "7371d49")
                    }
                )

                uri in listOf("/api/tags", "/tags") -> {
                    handleModelsProxy(session, true)
                }

                uri in listOf("/models/sse", "/v1/models/sse") -> {
                    val sseText = "data: {\"event\":\"models_reload\"}\n\n"
                    val bytes = sseText.toByteArray(StandardCharsets.UTF_8)
                    val resp = newFixedLengthResponse(Response.Status.OK, "text/event-stream; charset=utf-8", ByteArrayInputStream(bytes), bytes.size.toLong())
                    resp.addHeader("Cache-Control", "no-cache")
                    resp.addHeader("Connection", "keep-alive")
                    addCorsHeaders(resp)
                }

                uri in listOf("/v1/models/load", "/models/load", "/models/unload", "/v1/models/unload") -> {
                    jsonResponse(JSONObject().put("status", "ok").put("message", "model ready"))
                }

                uri in listOf("/v1/models", "/models", "/api/models") -> {
                    if (method == Method.GET) {
                        handleModelsProxy(session, false)
                    } else {
                        jsonResponse(JSONObject().put("status", "ok").put("message", "model ready"))
                    }
                }

                uri in listOf("/v1/chat/completions", "/chat/completions", "/completions", "/v1/completions", "/completion", "/api/chat") && method == Method.POST -> {
                    handleChatCompletionProxy(session)
                }

                uri.startsWith("/v1/") || uri.startsWith("/api/") || uri.startsWith("/models/") -> {
                    jsonResponse(JSONObject().put("status", "ok"))
                }

                else -> serveStaticAsset(uri)
            }
        } catch (e: Throwable) {
            Log.e(TAG, "Server error handling $uri", e)
            jsonResponse(
                JSONObject().put("error", JSONObject().put("message", e.message ?: "Internal error")),
                Response.Status.INTERNAL_ERROR
            )
        }
    }

    private fun handleModelsProxy(session: IHTTPSession, isTags: Boolean): Response {
        val rawGateway = MeshNodeService.gatewayUrl.trim()
        val rawKey = MeshNodeService.ownerKey.trim()

        val gateway = when {
            rawGateway.isNotBlank() && rawGateway != "https://mesh.inetconnector.com" -> rawGateway
            rawKey.startsWith("http://") || rawKey.startsWith("https://") -> rawKey
            rawGateway.isNotBlank() -> rawGateway
            else -> "https://mesh.inetconnector.com"
        }

        val targetPath = if (isTags) "/api/tags" else "/v1/models"
        val targetUrl = "${gateway.trimEnd('/')}$targetPath"

        try {
            val url = URL(targetUrl)
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                setRequestProperty("Accept", "application/json")
                connectTimeout = 3000
                readTimeout = 4000
            }
            if (conn.responseCode in 200..299) {
                val rawBytes = conn.inputStream.use { it.readBytes() }
                val rawStr = String(rawBytes, StandardCharsets.UTF_8)
                val json = JSONObject(rawStr)

                if (isTags) {
                    val models = json.optJSONArray("models") ?: JSONArray()
                    val enriched = JSONArray()
                    for (i in 0 until models.length()) {
                        val m = models.getJSONObject(i)
                        m.put("status", JSONObject().put("value", "loaded"))
                        m.put("modalities", JSONObject().apply {
                            put("vision", true)
                            put("text", true)
                            put("audio", true)
                            put("video", false)
                        })
                        if (!m.has("meta")) m.put("meta", JSONObject())
                        enriched.put(m)
                    }
                    return jsonResponse(JSONObject().put("models", enriched))
                } else {
                    val data = json.optJSONArray("data") ?: JSONArray()
                    val enriched = JSONArray()
                    for (i in 0 until data.length()) {
                        val m = data.getJSONObject(i)
                        m.put("status", JSONObject().put("value", "loaded"))
                        m.put("object", "model")
                        m.put("owned_by", "computemesh")
                        m.put("modalities", JSONObject().apply {
                            put("vision", true)
                            put("text", true)
                            put("audio", true)
                            put("video", false)
                        })
                        if (!m.has("meta")) m.put("meta", JSONObject())
                        enriched.put(m)
                    }
                    return jsonResponse(JSONObject().put("object", "list").put("data", enriched))
                }
            }
        } catch (_: Throwable) {}

        // High quality fallback models with complete metadata and loaded status
        val fallbackModels = listOf(
            Triple("qwen2.5:7b", "Qwen 2.5 7B (Fast General Assistant)", "alibaba"),
            Triple("gemma3:4b", "Gemma 3 4B (Multimodal Vision/Text)", "google"),
            Triple("qwen/qwen2.5-vl-7b-instruct", "Qwen 2.5 VL 7B (Vision & Document OCR)", "alibaba"),
            Triple("qwen2.5-coder:14b", "Qwen 2.5 Coder 14B (Code & Tool Calling)", "alibaba"),
            Triple("deepseek-r1:14b", "DeepSeek R1 14B (Advanced Reasoning)", "deepseek"),
            Triple("llama3.3:70b", "Llama 3.3 70B (High Capacity Fleet Cluster)", "meta"),
            Triple("computemesh-cluster-default", "ComputeMesh Fleet Cluster (Adaptive Mesh)", "computemesh")
        )

        return if (isTags) {
            val modelsArr = JSONArray()
            for ((id, desc, family) in fallbackModels) {
                modelsArr.put(JSONObject().apply {
                    put("name", id)
                    put("model", id)
                    put("description", desc)
                    put("status", JSONObject().put("value", "loaded"))
                    put("modalities", JSONObject().apply {
                        put("vision", true)
                        put("text", true)
                        put("audio", true)
                        put("video", false)
                    })
                    put("meta", JSONObject())
                    put("details", JSONObject().apply {
                        put("format", "gguf")
                        put("family", family)
                        put("parameter_size", id.substringAfterLast(':'))
                    })
                })
            }
            jsonResponse(JSONObject().put("models", modelsArr))
        } else {
            val dataArr = JSONArray()
            for ((id, desc, _) in fallbackModels) {
                dataArr.put(JSONObject().apply {
                    put("id", id)
                    put("object", "model")
                    put("owned_by", "computemesh")
                    put("description", desc)
                    put("modalities", JSONObject().apply {
                        put("vision", true)
                        put("text", true)
                        put("audio", true)
                        put("video", false)
                    })
                    put("meta", JSONObject())
                    put("status", JSONObject().put("value", "loaded"))
                })
            }
            jsonResponse(JSONObject().put("object", "list").put("data", dataArr))
        }
    }

    private fun sanitizeErrorMessage(rawError: String): String {
        if (rawError.isBlank()) return "Unbekannter Inferenz-Fehler"
        var clean = rawError.replace(Regex("<[^>]*>"), " ")
        clean = clean.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
        clean = clean.replace(Regex("\\s+"), " ").trim()
        if (clean.contains("404") || clean.contains("Not Found") || clean.contains("Nothing matches")) {
            return "Inferenz-Endpunkt nicht gefunden (404)"
        }
        if (clean.contains("502") || clean.contains("Bad Gateway")) {
            return "Inferenz-Server überlastet oder offline (502)"
        }
        if (clean.contains("503") || clean.contains("Service Unavailable")) {
            return "Inferenz-Dienst vorübergehend nicht erreichbar (503)"
        }
        return clean.take(150)
    }

    private fun handleChatCompletionProxy(session: IHTTPSession): Response {
        // Accurately read UTF-8 body without NanoHTTPD ISO-8859-1 corruption
        val contentLength = session.headers["content-length"]?.toIntOrNull() ?: -1
        val postData = if (contentLength > 0) {
            val buf = ByteArray(contentLength)
            var totalRead = 0
            while (totalRead < contentLength) {
                val r = session.inputStream.read(buf, totalRead, contentLength - totalRead)
                if (r <= 0) break
                totalRead += r
            }
            String(buf, 0, totalRead, StandardCharsets.UTF_8)
        } else {
            val baos = ByteArrayOutputStream()
            val buf = ByteArray(4096)
            var r: Int
            while (session.inputStream.read(buf).also { r = it } > 0) {
                baos.write(buf, 0, r)
            }
            if (baos.size() > 0) {
                baos.toString(StandardCharsets.UTF_8.name())
            } else {
                val files = HashMap<String, String>()
                try { session.parseBody(files) } catch (_: Throwable) {}
                files["postData"] ?: ""
            }
        }

        val rootJson = try {
            JSONObject(postData)
        } catch (_: Throwable) {
            JSONObject()
        }

        val isStream = rootJson.optBoolean("stream", true)
        val rawGateway = MeshNodeService.gatewayUrl.trim()
        val rawKey = MeshNodeService.ownerKey.trim()

        // Build list of candidate endpoints in priority order
        val candidates = mutableListOf<String>()

        // 1. Custom LAN / Fleet Gateway if configured
        if (rawGateway.isNotBlank() && rawGateway != "https://mesh.inetconnector.com") {
            val target = if (rawGateway.endsWith("/v1/chat/completions")) rawGateway else "${rawGateway.trimEnd('/')}/v1/chat/completions"
            if (!candidates.contains(target)) candidates.add(target)
            if (rawGateway.contains(":8080")) {
                val ollamaPortUrl = rawGateway.replace(":8080", ":11434").trimEnd('/') + "/v1/chat/completions"
                if (!candidates.contains(ollamaPortUrl)) candidates.add(ollamaPortUrl)
            }
            if (rawGateway.contains("192.168.") || rawGateway.contains("10.") || rawGateway.contains("172.16.")) {
                val tunnelTarget = "https://mesh.inetconnector.com/node/cm-inference-node-01/v1/chat/completions"
                if (!candidates.contains(tunnelTarget)) candidates.add(tunnelTarget)
            }
        }

        // 2. If rawKey is a URL
        if (rawKey.startsWith("http://") || rawKey.startsWith("https://")) {
            val keyUrl = if (rawKey.endsWith("/v1/chat/completions")) rawKey else "${rawKey.trimEnd('/')}/v1/chat/completions"
            if (!candidates.contains(keyUrl)) candidates.add(keyUrl)
            if (rawKey.contains(":8080")) {
                val ollamaPortUrl = rawKey.replace(":8080", ":11434").trimEnd('/') + "/v1/chat/completions"
                if (!candidates.contains(ollamaPortUrl)) candidates.add(ollamaPortUrl)
            }
        }

        // 3. Primary ComputeMesh Cloud Gateway
        candidates.add("https://mesh.inetconnector.com/v1/chat/completions")
        candidates.add("https://mesh.inetconnector.com/chat/completions")
        candidates.add("https://mesh.inetconnector.com/node/cm-inference-node-01/v1/chat/completions")

        // 4. Raw Klartext Fallback
        candidates.add("https://apps.inetconnector.com/klartext/api/v1/chat/completions")

        val key = if (rawKey.startsWith("http://") || rawKey.startsWith("https://")) "cm_live_demo_mobile" else rawKey.ifBlank { "cm_live_demo_mobile" }

        // Check if user is asking to paint / generate / draw an image
        val messages = rootJson.optJSONArray("messages")
        var lastUserText = ""
        if (messages != null) {
            for (i in (messages.length() - 1) downTo 0) {
                val m = messages.optJSONObject(i)
                if (m?.optString("role") == "user") {
                    val rawContent = m.opt("content")
                    lastUserText = when (rawContent) {
                        is String -> rawContent
                        is JSONArray -> {
                            val sb = StringBuilder()
                            for (j in 0 until rawContent.length()) {
                                val part = rawContent.optJSONObject(j)
                                if (part != null) {
                                    val t = part.optString("text", "")
                                    if (t.isNotBlank()) sb.append(t).append(" ")
                                } else {
                                    val strPart = rawContent.optString(j)
                                    if (strPart.isNotBlank()) sb.append(strPart).append(" ")
                                }
                            }
                            sb.toString().trim()
                        }
                        else -> rawContent?.toString() ?: ""
                    }
                    if (lastUserText.isNotBlank()) break
                }
            }
        }

        val isImageIntent = lastUserText.isNotBlank() && (
            (lastUserText.contains("bild", ignoreCase = true) && (
                lastUserText.contains("mal", ignoreCase = true) ||
                lastUserText.contains("mach", ignoreCase = true) ||
                lastUserText.contains("generier", ignoreCase = true) ||
                lastUserText.contains("erstell", ignoreCase = true) ||
                lastUserText.contains("zeig", ignoreCase = true) ||
                lastUserText.contains("render", ignoreCase = true) ||
                lastUserText.contains("zeichn", ignoreCase = true) ||
                lastUserText.contains("soll", ignoreCase = true)
            )) ||
            (lastUserText.contains("foto", ignoreCase = true) && (
                lastUserText.contains("mach", ignoreCase = true) ||
                lastUserText.contains("generier", ignoreCase = true) ||
                lastUserText.contains("erstell", ignoreCase = true) ||
                lastUserText.contains("von", ignoreCase = true)
            )) ||
            lastUserText.contains("male ", ignoreCase = true) ||
            lastUserText.contains("zeichne", ignoreCase = true) ||
            lastUserText.contains("paint a", ignoreCase = true) ||
            lastUserText.contains("paint an", ignoreCase = true) ||
            lastUserText.contains("generate an image", ignoreCase = true) ||
            lastUserText.contains("generate image", ignoreCase = true) ||
            lastUserText.contains("draw a", ignoreCase = true) ||
            lastUserText.contains("picture of", ignoreCase = true) ||
            lastUserText.contains("photo of", ignoreCase = true) ||
            lastUserText.contains("image of", ignoreCase = true)
        )

        if (isImageIntent) {
            val cleanPrompt = lastUserText
                .replace(Regex("(?i)^(?:bitte\\s+)?(?:kannst\\s+du\\s+)?(?:er\\s+soll\\s+)?(?:mach\\s+mir|mach\\s+uns|mach|male\\s+mir|male|generiere|erstelle|zeichne|paint|draw|create|render)(?:\\s+uns|\\s+mir)?(?:\\s+ein[e|en|er|em]?\\s+(?:bild|foto|zeichnung|photo|image|picture))?(?:\\s+von|\\s+über|\\s+mit|\\s+of|\\s+about)?[:\\s]*"), "")
                .trim()
                .ifBlank { lastUserText }

            if (isStream) {
                val pipedIn = PipedInputStream(64 * 1024)
                val pipedOut = PipedOutputStream(pipedIn)
                EXECUTOR.execute {
                    try {
                        val initChunk = JSONObject().apply {
                            put("id", "chatcmpl-img-${System.currentTimeMillis()}")
                            put("object", "chat.completion.chunk")
                            put("created", System.currentTimeMillis() / 1000)
                            put("model", "computemesh-generative-art")
                            put("choices", JSONArray().apply {
                                put(JSONObject().apply {
                                    put("index", 0)
                                    put("delta", JSONObject().apply {
                                        put("role", "assistant")
                                        put("content", "🎨 Generiere Bild...\n\n")
                                    })
                                })
                            })
                        }
                        pipedOut.write("data: ${initChunk}\n\n".toByteArray(StandardCharsets.UTF_8))
                        pipedOut.flush()

                        val replyMarkdown = generateImageWithLocalMeshFallback(cleanPrompt, rawGateway)
                        val chunkObj = JSONObject().apply {
                            put("id", "chatcmpl-img-${System.currentTimeMillis()}")
                            put("object", "chat.completion.chunk")
                            put("created", System.currentTimeMillis() / 1000)
                            put("model", "computemesh-generative-art")
                            put("choices", JSONArray().apply {
                                put(JSONObject().apply {
                                    put("index", 0)
                                    put("delta", JSONObject().apply {
                                        put("content", replyMarkdown)
                                    })
                                    put("finish_reason", "stop")
                                })
                            })
                        }
                        val sseData = "data: ${chunkObj}\n\ndata: [DONE]\n\n"
                        pipedOut.write(sseData.toByteArray(StandardCharsets.UTF_8))
                        pipedOut.flush()
                    } catch (_: Throwable) {}
                    finally {
                        try { pipedOut.close() } catch (_: Throwable) {}
                    }
                }
                val streamResp = newChunkedResponse(Response.Status.OK, "text/event-stream; charset=utf-8", pipedIn)
                streamResp.addHeader("Cache-Control", "no-cache")
                streamResp.addHeader("Connection", "close")
                return addCorsHeaders(streamResp)
            } else {
                val replyMarkdown = generateImageWithLocalMeshFallback(cleanPrompt, rawGateway)
                val nonStreamObj = JSONObject().apply {
                    put("id", "chatcmpl-img-${System.currentTimeMillis()}")
                    put("object", "chat.completion")
                    put("created", System.currentTimeMillis() / 1000)
                    put("model", "computemesh-generative-art")
                    put("choices", JSONArray().apply {
                        put(JSONObject().apply {
                            put("index", 0)
                            put("message", JSONObject().apply {
                                put("role", "assistant")
                                put("content", replyMarkdown)
                            })
                            put("finish_reason", "stop")
                        })
                    })
                }
                return jsonResponse(nonStreamObj)
            }
        }

        // Check if query is compound multi-step (should be handled by gateway agent loop)
        val isCompoundQuery = lastUserText.isNotBlank() && (
            Regex("""(?i)\b(?:und|sowie|and|dann|plus)\s+(?:was|wie|wo|welch|nachricht|news|schlagzeil|tagesschau|wetter|temperatur|kurs|aktie|krypto|bitcoin|btc|eth|sol|uhrzeit|zeit|bild|foto|suche)\b""").containsMatchIn(lastUserText) ||
            Regex("""(?i)\b(?:wetter|temperatur)\b.*\b(?:und|sowie|and|plus)\b.*\b(?:nachricht|news|schlagzeil|aktie|kurs|bitcoin|krypto|uhrzeit)\b""").containsMatchIn(lastUserText)
        )

        // Real-Time Live News Intent Intercept (Typo-Tolerant, Tagesschau / Spiegel / Heise RSS)
        val isNewsIntent = !isCompoundQuery && lastUserText.isNotBlank() && (
            Regex("""(?i)(?:was\s+(?:gibt'?s?|gibts|bits?|bit'?s?|geht|gehts|is|ist|steht)(?:\s+es)?\s+neu(?:es)?|aktuelle\s+(?:nachrichten|news|schlagzeilen|meldungen|berichte)|nachrichten\s+(?:von\s+|aus\s+|in\s+|für\s+|fuer\s+|jn\s+)?(?:den\s+)?(?:nachrichten|heute|aktuell)|news\s+(?:von\s+|aus\s+|in\s+|für\s+|fuer\s+)?heute|schlagzeilen(?:\s+von)?\s+heute|top\s+news|breaking\s+news|what'?s\s+new(?:\s+in\s+the\s+news)?|latest\s+news)""").containsMatchIn(lastUserText) ||
            (lastUserText.contains("nachricht", ignoreCase = true) && listOf("neu", "aktuell", "heute", "was", "gibt", "bit", "schlagzeil", "world", "deutschland", "jn", "in", "top").any { lastUserText.contains(it, ignoreCase = true) }) ||
            listOf("tagesschau", "spiegel online", "spiegel", "heise", "zeit online", "faz.net", "schlagzeilen").any { lastUserText.contains(it, ignoreCase = true) }
        )
        if (isNewsIntent) {
            val liveNewsText = fetchLiveNews(lastUserText)
            return respondWithAssistantText(isStream, liveNewsText, "computemesh-live-news")
        }

        // Real-Time Live Weather Intent Intercept (Open-Meteo API)
        val isWeatherIntent = !isCompoundQuery && lastUserText.isNotBlank() && (
            Regex("""(?i)(?:wie\s+(?:ist|wird)\s+das\s+wetter|wetter\s+in|wetter\s+für|wetter\s+fuer|wetter\s+heute|wetter\s+morgen|temperatur\s+in|regnet\s+es|wetterbericht|weather\s+in|weather\s+today|\bwetter\b)""").containsMatchIn(lastUserText)
        )
        if (isWeatherIntent) {
            val liveWeatherText = fetchLiveWeather(lastUserText)
            return respondWithAssistantText(isStream, liveWeatherText, "computemesh-live-weather")
        }

        // Real-Time Clock / Date Intent Intercept
        val isTimeIntent = lastUserText.isNotBlank() && (
            Regex("""(?i)(?:wie\s+spät\s+ist\s+es|wieviel\s+uhr\s+ist\s+es|aktuelle\s+uhrzeit|welcher\s+tag\s+ist\s+heute|welches\s+datum|current\s+time|what\s+time\s+is\s+it|\buhrzeit\b|\bdatum\s+heute\b)""").containsMatchIn(lastUserText)
        )
        if (isTimeIntent) {
            val liveTimeText = fetchLiveTime()
            return respondWithAssistantText(isStream, liveTimeText, "computemesh-live-clock")
        }

        // Real-Time Crypto / Stock Market Intent Intercept
        val isCryptoIntent = lastUserText.isNotBlank() && (
            Regex("""(?i)(?:bitcoin|btc|ethereum|eth|solana|sol|krypto|crypto)\s*(?:kurs|preis|price|quote)""").containsMatchIn(lastUserText) ||
            Regex("""(?i)(?:kurs|preis|price)\s+(?:von\s+)?(?:bitcoin|btc|ethereum|eth|solana|sol)""").containsMatchIn(lastUserText)
        )
        if (isCryptoIntent) {
            val sym = when {
                lastUserText.contains("eth", ignoreCase = true) -> "ETH"
                lastUserText.contains("sol", ignoreCase = true) -> "SOL"
                else -> "BTC"
            }
            val liveCryptoText = fetchLiveCrypto(sym)
            return respondWithAssistantText(isStream, liveCryptoText, "computemesh-live-crypto")
        }

        // Active MCP Modules & Tools Overview Intent Intercept
        val isToolsListIntent = lastUserText.isNotBlank() && (
            Regex("""(?i)(?:welche\s+tools|welche\s+module|welche\s+mcp|aktive\s+tools|aktive\s+module|was\s+kannst\s+du|welche\s+funktionen\s+hast\s+du|list\s+tools|available\s+tools)""").containsMatchIn(lastUserText)
        )
        if (isToolsListIntent) {
            val toolsOverview = getToolsOverviewText()
            return respondWithAssistantText(isStream, toolsOverview, "computemesh-tool-registry")
        }

        // Sanitize and compress any large base64 image data to prevent 502 Bad Gateway
        val hasImages = sanitizeMultimodalPayload(rootJson)
        if (hasImages) {
            val curModel = rootJson.optString("model", "")
            if (curModel.isBlank() || curModel == "qwen2.5:7b" || curModel == "computemesh-cluster-default" || (!curModel.contains("vl") && !curModel.contains("vision") && !curModel.contains("llava") && !curModel.contains("gemma3"))) {
                rootJson.put("model", "qwen/qwen2.5-vl-7b-instruct")
            }
        }

        val targetPayloadBytes = rootJson.toString().toByteArray(StandardCharsets.UTF_8)

        if (isStream) {
            val pipedIn = PipedInputStream(128 * 1024)
            val pipedOut = PipedOutputStream(pipedIn)

            EXECUTOR.execute {
                var lastErrorMessage = ""
                var streamedAnyBytes = false

                for (candidateUrl in candidates) {
                    var conn: HttpURLConnection? = null
                    try {
                        Log.d(TAG, "Trying streaming inference candidate: $candidateUrl")
                        conn = (URL(candidateUrl).openConnection() as HttpURLConnection).apply {
                            requestMethod = "POST"
                            setRequestProperty("Content-Type", "application/json; charset=utf-8")
                            setRequestProperty("Authorization", "Bearer $key")
                            setRequestProperty("Accept", "text/event-stream")
                            setRequestProperty("Accept-Encoding", "identity")
                            setRequestProperty("Cache-Control", "no-cache")
                            setRequestProperty("User-Agent", "ComputeMesh-Android/1.2")
                            doOutput = true
                            connectTimeout = if (candidateUrl.contains("192.168.") || candidateUrl.contains("127.0.0.1") || candidateUrl.contains("10.")) 2500 else 3500
                            readTimeout = 90000
                        }
                        conn.outputStream.use { os ->
                            os.write(targetPayloadBytes)
                            os.flush()
                        }
                        val code = conn.responseCode
                        if (code in 200..299) {
                            Log.i(TAG, "Streaming connected to $candidateUrl (HTTP $code)")
                            val contentType = conn.contentType ?: ""
                            if (contentType.contains("event-stream")) {
                                conn.inputStream.use { netIn ->
                                    val buffer = ByteArray(4096)
                                    var read: Int
                                    while (netIn.read(buffer).also { read = it } != -1) {
                                        pipedOut.write(buffer, 0, read)
                                        pipedOut.flush()
                                        streamedAnyBytes = true
                                    }
                                }
                            } else {
                                // Upstream returned application/json: convert to SSE
                                val responseBytes = conn.inputStream.use { it.readBytes() }
                                val jsonStr = String(responseBytes, StandardCharsets.UTF_8)
                                val jsonResp = try { JSONObject(jsonStr) } catch (_: Throwable) { JSONObject() }
                                val choices = jsonResp.optJSONArray("choices")
                                val contentText = choices?.optJSONObject(0)?.optJSONObject("message")?.optString("content")
                                    ?: choices?.optJSONObject(0)?.optJSONObject("delta")?.optString("content")
                                    ?: jsonStr

                                val chunkObj = JSONObject().apply {
                                    put("id", jsonResp.optString("id", "chatcmpl-stream"))
                                    put("object", "chat.completion.chunk")
                                    put("created", System.currentTimeMillis() / 1000)
                                    put("model", jsonResp.optString("model", "qwen2.5:7b"))
                                    put("choices", JSONArray().apply {
                                        put(JSONObject().apply {
                                            put("index", 0)
                                            put("delta", JSONObject().apply {
                                                put("content", contentText)
                                            })
                                            put("finish_reason", "stop")
                                        })
                                    })
                                }
                                val sseData = "data: ${chunkObj}\n\ndata: [DONE]\n\n"
                                pipedOut.write(sseData.toByteArray(StandardCharsets.UTF_8))
                                pipedOut.flush()
                                streamedAnyBytes = true
                            }
                            try { conn.disconnect() } catch (_: Throwable) {}
                            break
                        } else {
                            val errStream = conn.errorStream ?: conn.inputStream
                            val rawErr = errStream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() } ?: "HTTP $code"
                            lastErrorMessage = sanitizeErrorMessage(rawErr)
                            Log.w(TAG, "Candidate $candidateUrl returned HTTP $code: $lastErrorMessage")
                            try { conn.disconnect() } catch (_: Throwable) {}
                        }
                    } catch (e: Throwable) {
                        lastErrorMessage = e.message ?: "Verbindungsfehler"
                        Log.w(TAG, "Candidate $candidateUrl failed: ${e.message}")
                        try { conn?.disconnect() } catch (_: Throwable) {}
                    }
                }

                if (!streamedAnyBytes) {
                    val cleanErr = if (lastErrorMessage.isNotBlank()) lastErrorMessage else "Inferenz-Gateway nicht erreichbar. Bitte prüfe deine Verbindung."
                    val errChunk = JSONObject().apply {
                        put("id", "chatcmpl-err")
                        put("object", "chat.completion.chunk")
                        put("created", System.currentTimeMillis() / 1000)
                        put("model", "computemesh-mesh")
                        put("choices", JSONArray().apply {
                            put(JSONObject().apply {
                                put("index", 0)
                                put("delta", JSONObject().apply {
                                    put("content", "⚠️ Inferenz-Dienst: $cleanErr")
                                })
                                put("finish_reason", "stop")
                            })
                        })
                    }
                    val sseData = "data: ${errChunk}\n\ndata: [DONE]\n\n"
                    try {
                        pipedOut.write(sseData.toByteArray(StandardCharsets.UTF_8))
                        pipedOut.flush()
                    } catch (_: Throwable) {}
                }

                try { pipedOut.close() } catch (_: Throwable) {}
            }

            val streamResp = newChunkedResponse(Response.Status.OK, "text/event-stream; charset=utf-8", pipedIn)
            streamResp.addHeader("Cache-Control", "no-cache")
            streamResp.addHeader("Connection", "close")
            return addCorsHeaders(streamResp)
        }

        // Non-streaming fallback path
        var successfulConn: HttpURLConnection? = null
        var lastErrorMessage = ""

        for (candidateUrl in candidates) {
            var conn: HttpURLConnection? = null
            try {
                Log.d(TAG, "Trying non-stream inference candidate: $candidateUrl")
                conn = (URL(candidateUrl).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    setRequestProperty("Authorization", "Bearer $key")
                    setRequestProperty("Accept", "application/json")
                    setRequestProperty("Accept-Encoding", "identity")
                    setRequestProperty("Cache-Control", "no-cache")
                    setRequestProperty("User-Agent", "ComputeMesh-Android/1.2")
                    doOutput = true
                    connectTimeout = if (candidateUrl.contains("192.168.") || candidateUrl.contains("127.0.0.1") || candidateUrl.contains("10.")) 2500 else 3500
                    readTimeout = 90000
                }
                conn.outputStream.use { os ->
                    os.write(targetPayloadBytes)
                    os.flush()
                }
                val code = conn.responseCode
                if (code in 200..299) {
                    successfulConn = conn
                    Log.i(TAG, "Successfully connected to inference candidate: $candidateUrl (HTTP $code)")
                    break
                } else {
                    val errStream = conn.errorStream ?: conn.inputStream
                    val rawErr = errStream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() } ?: "HTTP $code"
                    lastErrorMessage = sanitizeErrorMessage(rawErr)
                    Log.w(TAG, "Candidate $candidateUrl returned HTTP $code: $lastErrorMessage")
                    try { conn.disconnect() } catch (_: Throwable) {}
                }
            } catch (e: Throwable) {
                lastErrorMessage = e.message ?: "Verbindungsfehler"
                Log.w(TAG, "Candidate $candidateUrl failed: ${e.message}")
                try { conn?.disconnect() } catch (_: Throwable) {}
            }
        }

        val conn = successfulConn
        if (conn == null) {
            val cleanErr = if (lastErrorMessage.isNotBlank()) lastErrorMessage else "Inferenz-Gateway nicht erreichbar. Bitte prüfe deine Verbindung."
            return jsonResponse(
                JSONObject().put("error", JSONObject().put("message", "Inferenz-Fehler: $cleanErr")),
                Response.Status.INTERNAL_ERROR
            )
        }

        val responseBytes = conn.inputStream.use { it.readBytes() }
        val resp = newFixedLengthResponse(Response.Status.OK, "application/json; charset=utf-8", ByteArrayInputStream(responseBytes), responseBytes.size.toLong())
        return addCorsHeaders(resp)
    }

    private fun sanitizeMultimodalPayload(root: JSONObject): Boolean {
        var hasImages = false
        val messages = root.optJSONArray("messages") ?: return false
        for (i in 0 until messages.length()) {
            val msg = messages.optJSONObject(i) ?: continue
            val content = msg.opt("content")
            if (content is JSONArray) {
                for (j in 0 until content.length()) {
                    val part = content.optJSONObject(j) ?: continue
                    if (part.optString("type") == "image_url") {
                        hasImages = true
                        val imgObj = part.optJSONObject("image_url")
                        val urlStr = imgObj?.optString("url") ?: ""
                        if (urlStr.startsWith("data:image/") && urlStr.contains(";base64,")) {
                            val mime = urlStr.substringBefore(";base64,")
                            val base64Data = urlStr.substringAfter(";base64,")
                            val compressedBase64 = downsampleBase64Image(base64Data)
                            imgObj?.put("url", "$mime;base64,$compressedBase64")
                        }
                    }
                }
            } else if (content is String) {
                val dataUriMatch = Regex("""data:image/[a-zA-Z0-9.+_-]+;base64,[a-zA-Z0-9+/=]+""").find(content)
                if (dataUriMatch != null) {
                    hasImages = true
                    val fullDataUri = dataUriMatch.value
                    val mime = fullDataUri.substringBefore(";base64,")
                    val base64Data = fullDataUri.substringAfter(";base64,")
                    val compressedBase64 = downsampleBase64Image(base64Data)
                    val cleanedText = content.replace(fullDataUri, "")
                        .replace("--- [ATTACHMENTS ANALYZER] ---", "")
                        .replace("Data URI:", "")
                        .replace(Regex("""\[Image Attached:.*?\]"""), "")
                        .trim()

                    val contentArr = JSONArray().apply {
                        if (cleanedText.isNotBlank()) {
                            put(JSONObject().put("type", "text").put("text", cleanedText))
                        }
                        put(JSONObject().apply {
                            put("type", "image_url")
                            put("image_url", JSONObject().put("url", "$mime;base64,$compressedBase64"))
                        })
                    }
                    msg.put("content", contentArr)
                }
            }
            if (msg.has("images")) {
                hasImages = true
            }
        }
        return hasImages
    }

    private fun downsampleBase64Image(base64: String): String {
        return try {
            val decoded = Base64.decode(base64, Base64.DEFAULT)
            val bmp = BitmapFactory.decodeByteArray(decoded, 0, decoded.size) ?: return base64
            val maxDim = 1024
            val scale = if (bmp.width > maxDim || bmp.height > maxDim) {
                maxDim.toFloat() / maxOf(bmp.width, bmp.height)
            } else 1.0f

            val scaledBmp = if (scale < 1.0f) {
                Bitmap.createScaledBitmap(bmp, (bmp.width * scale).toInt(), (bmp.height * scale).toInt(), true)
            } else bmp

            val baos = ByteArrayOutputStream()
            scaledBmp.compress(Bitmap.CompressFormat.JPEG, 80, baos)
            if (scaledBmp != bmp) {
                try { scaledBmp.recycle() } catch (_: Throwable) {}
            }
            try { bmp.recycle() } catch (_: Throwable) {}
            Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
        } catch (e: Throwable) {
            Log.w(TAG, "Image compression fallback: ${e.message}")
            base64
        }
    }

    private fun serveStaticAsset(uri: String): Response {
        val pathWithoutQuery = uri.trim().substringBefore('?')
        val clean = when (pathWithoutQuery) {
            "/", "" -> "index.html"
            else -> pathWithoutQuery.removePrefix("/")
        }

        val assetPath = "webui/$clean"
        return try {
            val bytes = try {
                context.assets.open(assetPath).use { it.readBytes() }
            } catch (_: Throwable) {
                val fallback = "webui/" + clean.replace("_app", "app_dist")
                context.assets.open(fallback).use { it.readBytes() }
            }
            Log.d(TAG, "Serving asset: $assetPath (${bytes.size} bytes, ${mimeFor(clean)})")
            addCorsHeaders(newFixedLengthResponse(Response.Status.OK, mimeFor(clean), ByteArrayInputStream(bytes), bytes.size.toLong()))
        } catch (e: Throwable) {
            Log.w(TAG, "Asset not found: $assetPath (${e.message})")
            val looksLikeFile = clean.contains(".") || clean.startsWith("_")
            if (looksLikeFile && clean != "index.html") {
                newFixedLengthResponse(Response.Status.NOT_FOUND, "text/plain", "Not Found: $clean")
            } else {
                // SPA Fallback to index.html
                try {
                    val bytes = context.assets.open("webui/index.html").use { it.readBytes() }
                    addCorsHeaders(newFixedLengthResponse(Response.Status.OK, "text/html; charset=utf-8", ByteArrayInputStream(bytes), bytes.size.toLong()))
                } catch (err: Throwable) {
                    Log.e(TAG, "SPA index.html fallback failed: ${err.message}")
                    newFixedLengthResponse(Response.Status.NOT_FOUND, "text/plain", "WebUI Not Found")
                }
            }
        }
    }

    private fun generateImageWithLocalMeshFallback(cleanPrompt: String, rawGateway: String): String {
        val endpoints = mutableListOf<String>()

        val host = when {
            rawGateway.startsWith("http://") || rawGateway.startsWith("https://") -> {
                try {
                    val u = java.net.URI(rawGateway)
                    u.host
                } catch (_: Throwable) { null }
            }
            rawGateway.isNotBlank() && !rawGateway.contains("://") -> {
                rawGateway.substringBefore(':')
            }
            else -> null
        }

        if (host != null && (host.startsWith("192.168.") || host.startsWith("10.") || host.startsWith("172.") || host == "127.0.0.1" || host == "localhost")) {
            endpoints.add("http://$host:8085/v1/images/generations")
        }

        // Standard LAN mesh node endpoint & Android emulator host loopback
        endpoints.add("http://192.168.1.94:8085/v1/images/generations")
        endpoints.add("http://10.0.2.2:8085/v1/images/generations")
        endpoints.add("http://127.0.0.1:8085/v1/images/generations")

        for (ep in endpoints.distinct()) {
            try {
                val u = java.net.URL(ep)
                val conn = (u.openConnection() as java.net.HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 400
                    readTimeout = 45000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    setRequestProperty("Accept", "application/json")
                }

                val payload = JSONObject().apply {
                    put("prompt", cleanPrompt)
                    put("n", 1)
                    put("size", "1024x576")
                    put("response_format", "b64_json")
                }

                conn.outputStream.use { os ->
                    os.write(payload.toString().toByteArray(StandardCharsets.UTF_8))
                    os.flush()
                }

                if (conn.responseCode in 200..299) {
                    val respStr = conn.inputStream.bufferedReader().use { it.readText() }
                    val respJson = JSONObject(respStr)
                    val dataArr = respJson.optJSONArray("data")
                    if (dataArr != null && dataArr.length() > 0) {
                        val item = dataArr.getJSONObject(0)
                        val b64 = item.optString("b64_json", "")
                        val imgUrl = item.optString("url", "")
                        if (b64.isNotBlank()) {
                            val dataUri = "data:image/png;base64,$b64"
                            return "Hier ist dein generiertes Bild für **\"$cleanPrompt\"** ⚡ *(Lokal gerendert auf RTX 3080 Mesh-GPU)*:\n\n![$cleanPrompt]($dataUri)\n\n[⬇️ **Bild in voller Auflösung herunterladen**]($dataUri)"
                        } else if (imgUrl.isNotBlank()) {
                            return "Hier ist dein generiertes Bild für **\"$cleanPrompt\"** ⚡ *(Lokal gerendert auf Mesh-GPU)*:\n\n![$cleanPrompt]($imgUrl)\n\n[⬇️ **Bild in voller Auflösung herunterladen**]($imgUrl)"
                        }
                    }
                }
            } catch (_: Throwable) {
                // Ignore and proceed to fallback
            }
        }

        // Cloud-Fallback
        val seed = (100000..999999).random()
        val encoded = java.net.URLEncoder.encode(cleanPrompt, "UTF-8")
        val imageUrl = "https://image.pollinations.ai/prompt/$encoded?width=1024&height=576&seed=$seed&nologo=true&enhance=true"
        return "Hier ist dein generiertes Bild für **\"$cleanPrompt\"** 🎨 *(Cloud-Fallback, lokale GPU offline)*:\n\n![$cleanPrompt]($imageUrl)\n\n[⬇️ **Bild in voller Auflösung herunterladen**]($imageUrl)"
    }

    private fun respondWithAssistantText(isStream: Boolean, assistantText: String, modelName: String = "computemesh-tools"): Response {
        if (isStream) {
            val pipedIn = PipedInputStream(64 * 1024)
            val pipedOut = PipedOutputStream(pipedIn)
            EXECUTOR.execute {
                try {
                    val chunkObj = JSONObject().apply {
                        put("id", "chatcmpl-tool-${System.currentTimeMillis()}")
                        put("object", "chat.completion.chunk")
                        put("created", System.currentTimeMillis() / 1000)
                        put("model", modelName)
                        put("choices", JSONArray().apply {
                            put(JSONObject().apply {
                                put("index", 0)
                                put("delta", JSONObject().apply {
                                    put("role", "assistant")
                                    put("content", assistantText)
                                })
                                put("finish_reason", "stop")
                            })
                        })
                    }
                    val sseData = "data: ${chunkObj}\n\ndata: [DONE]\n\n"
                    pipedOut.write(sseData.toByteArray(StandardCharsets.UTF_8))
                    pipedOut.flush()
                } catch (_: Throwable) {}
                finally {
                    try { pipedOut.close() } catch (_: Throwable) {}
                }
            }
            val streamResp = newChunkedResponse(Response.Status.OK, "text/event-stream; charset=utf-8", pipedIn)
            streamResp.addHeader("Cache-Control", "no-cache")
            streamResp.addHeader("Connection", "close")
            return addCorsHeaders(streamResp)
        } else {
            val nonStreamObj = JSONObject().apply {
                put("id", "chatcmpl-tool-${System.currentTimeMillis()}")
                put("object", "chat.completion")
                put("created", System.currentTimeMillis() / 1000)
                put("model", modelName)
                put("choices", JSONArray().apply {
                    put(JSONObject().apply {
                        put("index", 0)
                        put("message", JSONObject().apply {
                            put("role", "assistant")
                            put("content", assistantText)
                        })
                        put("finish_reason", "stop")
                    })
                })
            }
            return jsonResponse(nonStreamObj)
        }
    }

    private fun fetchLiveNews(userQuery: String): String {
        val feeds = listOf(
            Pair("Tagesschau", "https://www.tagesschau.de/xml/rss2/"),
            Pair("Spiegel Online", "https://www.spiegel.de/schlagzeilen/tops/index.rss"),
            Pair("Heise Online", "https://www.heise.de/rss/heise.rss")
        )

        val articles = mutableListOf<Triple<String, String, String>>() // title, link, source

        for ((sourceName, feedUrl) in feeds) {
            try {
                val conn = (URL(feedUrl).openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    setRequestProperty("User-Agent", "ComputeMesh/1.2 (Android)")
                    connectTimeout = 3000
                    readTimeout = 4000
                }
                if (conn.responseCode in 200..299) {
                    val xml = conn.inputStream.bufferedReader(StandardCharsets.UTF_8).use { it.readText() }
                    val itemRegex = Regex("<item>(.*?)</item>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))
                    val titleRegex = Regex("<title>(?:<!\\[CDATA\\[)?(.*?)(?:\\]\\]>)?</title>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))
                    val linkRegex = Regex("<link>(?:<!\\[CDATA\\[)?(.*?)(?:\\]\\]>)?</link>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))

                    var count = 0
                    for (itemMatch in itemRegex.findAll(xml)) {
                        val itemXml = itemMatch.groupValues[1]
                        val rawTitle = titleRegex.find(itemXml)?.groupValues?.get(1)?.trim() ?: ""
                        val rawLink = linkRegex.find(itemXml)?.groupValues?.get(1)?.trim() ?: ""

                        val cleanTitle = rawTitle
                            .replace("&amp;", "&")
                            .replace("&quot;", "\"")
                            .replace("&apos;", "'")
                            .replace("&#39;", "'")
                            .replace("&lt;", "<")
                            .replace("&gt;", ">")
                            .replace(Regex("<[^>]*>"), "")
                            .trim()

                        if (cleanTitle.isNotBlank() && rawLink.startsWith("http")) {
                            if (!articles.any { it.first.equals(cleanTitle, ignoreCase = true) }) {
                                articles.add(Triple(cleanTitle, rawLink, sourceName))
                                count++
                                if (count >= 3) break
                            }
                        }
                    }
                }
                conn.disconnect()
            } catch (e: Throwable) {
                Log.w(TAG, "RSS fetch failed for $sourceName: ${e.message}")
            }
            if (articles.size >= 6) break
        }

        if (articles.isEmpty()) {
            return "### 📰 Aktuelle Nachrichten\n\nZurzeit konnten keine Live-Schlagzeilen abgerufen werden (Netzwerk-Timeout). Bitte prüfe deine Internetverbindung."
        }

        val sb = StringBuilder()
        sb.append("### 📰 Aktuelle Live-Schlagzeilen & Nachrichten\n\n")
        sb.append("*Echtzeit-Meldungen aus dem ComputeMesh Live-Feed (Tagesschau / Spiegel / Heise):*\n\n")
        articles.take(6).forEachIndexed { index, (title, link, src) ->
            sb.append("${index + 1}. [**$title**]($link) *($src)*\n")
        }
        sb.append("\n---\n*Live synchronisiert über ComputeMesh Tool Engine*")
        return sb.toString()
    }

    private fun fetchLiveWeather(userText: String): String {
        var rawCity = "Berlin"
        val m = Regex("""(?i)(?:in|für|fuer|von)\s+([a-zA-ZäöüÄÖÜß\s\-]+)""").find(userText)
        if (m != null) {
            val candidate = m.groupValues[1].trim()
                .replace(Regex("""(?i)\b(heute|morgen|übermorgen|aktuell|am|wochenende|wird|ist|sein|aussehen|aussieht|vorhersage|bitte|gerade|now|today|tomorrow|please|is|will|be|forecast)\b"""), "")
                .trim()
                .trim(',', '.', '?', '!', ':', ';', '-')
            if (candidate.length >= 2) rawCity = candidate
        }

        val searchCandidates = mutableListOf<String>()
        if (rawCity.isNotBlank()) searchCandidates.add(rawCity)
        val firstWord = rawCity.split(Regex("""\s+""")).firstOrNull()?.trim() ?: ""
        if (firstWord.length >= 2 && firstWord != rawCity) {
            searchCandidates.add(firstWord)
        }
        if (searchCandidates.isEmpty()) searchCandidates.add("Berlin")

        for (candidate in searchCandidates) {
            try {
                val geoUrl = "https://geocoding-api.open-meteo.com/v1/search?name=${java.net.URLEncoder.encode(candidate, "UTF-8")}&count=1&language=de&format=json"
                val geoConn = (URL(geoUrl).openConnection() as HttpURLConnection).apply {
                    connectTimeout = 3500
                    readTimeout = 4500
                    setRequestProperty("User-Agent", "ComputeMesh-Mobile/1.2")
                }
                if (geoConn.responseCode in 200..299) {
                    val geoJson = JSONObject(geoConn.inputStream.bufferedReader(StandardCharsets.UTF_8).use { it.readText() })
                    val results = geoJson.optJSONArray("results")
                    if (results != null && results.length() > 0) {
                        val place = results.getJSONObject(0)
                        val lat = place.getDouble("latitude")
                        val lon = place.getDouble("longitude")
                        val name = place.optString("name", candidate)
                        val country = place.optString("country", "Deutschland")
                        val admin1 = place.optString("admin1", "")

                        val forecastUrl = "https://api.open-meteo.com/v1/forecast?latitude=$lat&longitude=$lon&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
                        val fcConn = (URL(forecastUrl).openConnection() as HttpURLConnection).apply {
                            connectTimeout = 3500
                            readTimeout = 4500
                            setRequestProperty("User-Agent", "ComputeMesh-Mobile/1.2")
                        }
                        if (fcConn.responseCode in 200..299) {
                            val fcJson = JSONObject(fcConn.inputStream.bufferedReader(StandardCharsets.UTF_8).use { it.readText() })
                            val current = fcJson.optJSONObject("current")
                            if (current != null) {
                                val temp = current.optDouble("temperature_2m", 0.0)
                                val appTemp = current.optDouble("apparent_temperature", temp)
                                val hum = current.optInt("relative_humidity_2m", 0)
                                val wind = current.optDouble("wind_speed_10m", 0.0)
                                val precip = current.optDouble("precipitation", 0.0)
                                val code = current.optInt("weather_code", 0)

                                val condition = when (code) {
                                    0 -> "☀️ Klar / Sonnig"
                                    1, 2, 3 -> "⛅ Leicht bewölkt"
                                    45, 48 -> "🌫️ Nebelig"
                                    51, 53, 55 -> "🌧️ Leichter Nieselregen"
                                    61, 63, 65 -> "🌧️ Regen"
                                    71, 73, 75 -> "🌨️ Schneefall"
                                    80, 81, 82 -> "🌦️ Regenschauer"
                                    95, 96, 99 -> "⛈️ Gewitter"
                                    else -> "🌤️ Wechselhaft"
                                }

                                val locStr = if (admin1.isNotBlank()) "$name ($admin1, $country)" else "$name ($country)"
                                return "### 🌤️ Aktuelles Live-Wetter für **$locStr**:\n\n" +
                                        "- **Wetterlage:** $condition\n" +
                                        "- **Temperatur:** ${String.format(java.util.Locale.US, "%.1f", temp)} °C (gefühlt ${String.format(java.util.Locale.US, "%.1f", appTemp)} °C)\n" +
                                        "- **Luftfeuchtigkeit:** $hum %\n" +
                                        "- **Wind:** ${String.format(java.util.Locale.US, "%.1f", wind)} km/h\n" +
                                        "- **Niederschlag:** ${String.format(java.util.Locale.US, "%.1f", precip)} mm\n\n" +
                                        "*Quelle: Open-Meteo Live API*"
                            }
                        }
                    }
                }
            } catch (e: Throwable) {
                Log.w(TAG, "Weather fetch attempt for '$candidate' failed: ${e.message}")
            }
        }
        return "### 🌤️ Live-Wetter\n\nWetterdaten für **$rawCity** konnten aktuell nicht ermittelt werden. Bitte prüfe deine Internetverbindung."
    }

    private fun fetchLiveTime(): String {
        val now = java.util.Date()
        val tz = java.util.TimeZone.getTimeZone("Europe/Berlin")
        val timeFmt = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.GERMANY).apply { timeZone = tz }
        val dateFmt = java.text.SimpleDateFormat("EEEE, dd. MMMM yyyy", java.util.Locale.GERMANY).apply { timeZone = tz }
        val kwFmt = java.text.SimpleDateFormat("w", java.util.Locale.GERMANY).apply { timeZone = tz }

        return "### ⏰ Aktuelle Uhrzeit & Datum\n\n" +
                "- **Uhrzeit:** ${timeFmt.format(now)} Uhr\n" +
                "- **Datum:** ${dateFmt.format(now)}\n" +
                "- **Kalenderwoche:** KW ${kwFmt.format(now)}\n" +
                "- **Zeitzone:** Europe/Berlin"
    }

    private fun fetchLiveCrypto(symbol: String): String {
        val symUpper = symbol.uppercase()
        val cgId = when (symUpper) {
            "BTC", "BITCOIN" -> "bitcoin"
            "ETH", "ETHEREUM" -> "ethereum"
            "SOL", "SOLANA" -> "solana"
            else -> "bitcoin"
        }
        val name = when (cgId) {
            "bitcoin" -> "Bitcoin (BTC)"
            "ethereum" -> "Ethereum (ETH)"
            "solana" -> "Solana (SOL)"
            else -> "Krypto"
        }

        try {
            val url = "https://api.coingecko.com/api/v3/simple/price?ids=$cgId&vs_currencies=usd,eur&include_24hr_change=true"
            val conn = (URL(url).openConnection() as HttpURLConnection).apply {
                setRequestProperty("User-Agent", "ComputeMesh/1.2 (Android)")
                connectTimeout = 3000
                readTimeout = 4000
            }
            if (conn.responseCode in 200..299) {
                val json = JSONObject(conn.inputStream.bufferedReader(StandardCharsets.UTF_8).use { it.readText() })
                val item = json.optJSONObject(cgId)
                if (item != null) {
                    val usd = item.optDouble("usd", 0.0)
                    val eur = item.optDouble("eur", 0.0)
                    val ch24 = item.optDouble("usd_24h_change", 0.0)
                    val chSign = if (ch24 >= 0) "+" else ""

                    return "### 📈 Aktueller Kurs für **$name**:\n\n" +
                            "- **Preis USD:** $${String.format(java.util.Locale.US, "%,.2f", usd)}\n" +
                            "- **Preis EUR:** ${String.format(java.util.Locale.GERMANY, "%,.2f", eur)} €\n" +
                            "- **24h Veränderung:** $chSign${String.format(java.util.Locale.US, "%.2f", ch24)} %\n\n" +
                            "*Quelle: CoinGecko Live Index*"
                }
            }
        } catch (e: Throwable) {
            Log.w(TAG, "Crypto fetch failed: ${e.message}")
        }
        return "### 📈 Krypto-Kurs\n\nAktuelle Kursdaten für **$name** konnten zurzeit nicht abgerufen werden."
    }

    private fun getToolsOverviewText(): String {
        return """### 🛠️ Aktive ComputeMesh MCP-Module & Live-Tools

Folgende Live-Werkzeuge sind auf diesem Cluster einsatzbereit:
- **`generate_ai_image`**: Lokale RealVisXL / SDXL GPU-Bilderstellung auf RTX 3080 Mesh-Node
- **`get_live_news`**: Echtzeit-Nachrichten & Schlagzeilen (Tagesschau, Spiegel, Heise RSS)
- **`get_current_weather`**: Live-Wetterdaten weltweit (Open-Meteo API)
- **`get_current_time_calendar`**: Präzise Atomuhrzeit, Datum & Kalenderwochen
- **`get_market_quote`**: Live Krypto- & Börsenkurse (BTC, ETH, SOL)
- **`python_sandbox`**: Code Interpreter & Datenanalyse mit Plot-Generierung
- **`document_rag`**: Semantische Wissensdatenbank & Hybrid-Vektorsuche
- **`user_memory`**: Persistentes Gedächtnis & Profil-Präferenzen

*Alle Werkzeuge können direkt durch natürliche Anfragen im Chat genutzt werden.*"""
    }

    private fun mimeFor(path: String): String {
        val lower = path.lowercase().substringBefore('?')
        return when {
            lower.endsWith(".html") || lower.endsWith(".htm") -> "text/html; charset=utf-8"
            lower.endsWith(".js") || lower.endsWith(".mjs") -> "text/javascript; charset=utf-8"
            lower.endsWith(".css") -> "text/css; charset=utf-8"
            lower.endsWith(".json") -> "application/json; charset=utf-8"
            lower.endsWith(".webmanifest") -> "application/manifest+json; charset=utf-8"
            lower.endsWith(".png") -> "image/png"
            lower.endsWith(".jpg") || lower.endsWith(".jpeg") -> "image/jpeg"
            lower.endsWith(".svg") -> "image/svg+xml"
            lower.endsWith(".webp") -> "image/webp"
            lower.endsWith(".ico") -> "image/x-icon"
            lower.endsWith(".woff2") -> "font/woff2"
            lower.endsWith(".woff") -> "font/woff"
            lower.endsWith(".ttf") -> "font/ttf"
            lower.endsWith(".txt") -> "text/plain; charset=utf-8"
            else -> "application/octet-stream"
        }
    }

    private fun jsonResponse(json: Any, status: Response.Status = Response.Status.OK): Response {
        val bytes = json.toString().toByteArray(StandardCharsets.UTF_8)
        val resp = newFixedLengthResponse(status, "application/json; charset=utf-8", ByteArrayInputStream(bytes), bytes.size.toLong())
        return addCorsHeaders(resp)
    }

    private fun addCorsHeaders(response: Response): Response {
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, HEAD")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept, X-Requested-With")
        response.addHeader("Access-Control-Max-Age", "86400")
        return response
    }
}
