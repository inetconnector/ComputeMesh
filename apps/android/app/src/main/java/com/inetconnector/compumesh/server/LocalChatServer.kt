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

                uri in listOf("/props", "/api/props", "/properties") -> jsonResponse(
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

        // Sanitize and compress any large base64 image data to prevent 502 Bad Gateway
        val hasImages = sanitizeMultimodalPayload(rootJson)
        if (hasImages) {
            val curModel = rootJson.optString("model", "")
            if (curModel.isBlank() || curModel == "qwen2.5:7b" || curModel == "computemesh-cluster-default" || (!curModel.contains("vl") && !curModel.contains("vision") && !curModel.contains("llava") && !curModel.contains("gemma3"))) {
                rootJson.put("model", "qwen/qwen2.5-vl-7b-instruct")
            }
        }

        val targetPayloadBytes = rootJson.toString().toByteArray(StandardCharsets.UTF_8)

        var successfulConn: HttpURLConnection? = null
        var lastErrorCode = -1
        var lastErrorMessage = ""

        for (candidateUrl in candidates) {
            var conn: HttpURLConnection? = null
            try {
                Log.d(TAG, "Trying inference candidate: $candidateUrl")
                conn = (URL(candidateUrl).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    setRequestProperty("Authorization", "Bearer $key")
                    setRequestProperty("Accept", if (isStream) "text/event-stream" else "application/json")
                    setRequestProperty("Accept-Encoding", "identity")
                    setRequestProperty("Cache-Control", "no-cache")
                    setRequestProperty("User-Agent", "ComputeMesh-Android/1.2")
                    doOutput = true
                    connectTimeout = if (candidateUrl.contains("192.168.") || candidateUrl.contains("127.0.0.1") || candidateUrl.contains("10.")) 3500 else 8000
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
                    lastErrorCode = code
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

        val contentType = conn.contentType ?: ""
        val isEventStreamResponse = contentType.contains("event-stream")

        if (!isStream) {
            val responseBytes = conn.inputStream.use { it.readBytes() }
            val resp = newFixedLengthResponse(Response.Status.OK, "application/json; charset=utf-8", ByteArrayInputStream(responseBytes), responseBytes.size.toLong())
            return addCorsHeaders(resp)
        }

        // If client requested stream and server returned text/event-stream
        if (isEventStreamResponse) {
            val pipedIn = PipedInputStream(64 * 1024)
            val pipedOut = PipedOutputStream(pipedIn)

            EXECUTOR.execute {
                try {
                    conn.inputStream.use { netIn ->
                        val buffer = ByteArray(4096)
                        var read: Int
                        while (netIn.read(buffer).also { read = it } != -1) {
                            pipedOut.write(buffer, 0, read)
                            pipedOut.flush()
                        }
                    }
                } catch (e: Throwable) {
                    Log.w(TAG, "Streaming pump finished: ${e.message}")
                } finally {
                    try { pipedOut.close() } catch (_: Throwable) {}
                    try { conn.disconnect() } catch (_: Throwable) {}
                }
            }

            val streamResp = newChunkedResponse(Response.Status.OK, "text/event-stream; charset=utf-8", pipedIn)
            streamResp.addHeader("Cache-Control", "no-cache")
            streamResp.addHeader("Connection", "close")
            return addCorsHeaders(streamResp)
        } else {
            // Upstream returned application/json: synthesize SSE chunk stream so WebUI receives stream seamlessly
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
            val sseBytes = sseData.toByteArray(StandardCharsets.UTF_8)
            val resp = newFixedLengthResponse(Response.Status.OK, "text/event-stream; charset=utf-8", ByteArrayInputStream(sseBytes), sseBytes.size.toLong())
            resp.addHeader("Cache-Control", "no-cache")
            resp.addHeader("Connection", "close")
            return addCorsHeaders(resp)
        }
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
