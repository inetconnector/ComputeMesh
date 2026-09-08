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

                uri == "/props" || uri == "/api/props" -> jsonResponse(
                    JSONObject().apply {
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
                        put("chat_template", "{% for message in messages %}{{'<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>' + '\\n'}}{% endfor %}{% if add_generation_prompt %}{{'<|im_start|>assistant\\n'}}{% endif %}")
                        put("modalities", JSONObject().apply {
                            put("text", true)
                            put("image", true)
                            put("audio", true)
                        })
                    }
                )

                uri == "/slots" -> jsonResponse(
                    JSONArray().put(JSONObject().put("id", 0).put("is_processing", false))
                )

                uri in listOf("/v1/models", "/models", "/api/models", "/v1/models/load", "/models/load") -> {
                    if (method == Method.GET) {
                        jsonResponse(
                            JSONObject().apply {
                                put("object", "list")
                                put("data", JSONArray().apply {
                                    put(JSONObject().put("id", "qwen2.5:7b").put("object", "model").put("owned_by", "computemesh"))
                                    put(JSONObject().put("id", "openbmb/minicpm5-2b").put("object", "model").put("owned_by", "computemesh"))
                                    put(JSONObject().put("id", "qwen2.5-vl:7b").put("object", "model").put("owned_by", "computemesh"))
                                    put(JSONObject().put("id", "deepseek-coder:6.7b").put("object", "model").put("owned_by", "computemesh"))
                                    put(JSONObject().put("id", "llama3.1:8b").put("object", "model").put("owned_by", "computemesh"))
                                })
                            }
                        )
                    } else {
                        jsonResponse(JSONObject().put("status", "ok").put("message", "model ready"))
                    }
                }

                uri in listOf("/v1/chat/completions", "/chat/completions", "/completions", "/v1/completions", "/completion", "/api/chat") && method == Method.POST -> {
                    handleChatCompletionProxy(session)
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

    private fun handleChatCompletionProxy(session: IHTTPSession): Response {
        val files = HashMap<String, String>()
        session.parseBody(files)
        val postData = files["postData"] ?: ""

        val rootJson = try {
            JSONObject(postData)
        } catch (_: Throwable) {
            JSONObject()
        }

        val isStream = rootJson.optBoolean("stream", true)
        val gateway = MeshNodeService.gatewayUrl.ifBlank { "https://mesh.inetconnector.com" }
        val targetUrl = "${gateway.trimEnd('/')}/v1/chat/completions"
        val key = MeshNodeService.ownerKey.ifBlank { "cm_live_demo_mobile" }

        // Sanitize and compress any large base64 image data to prevent 502 Bad Gateway
        sanitizeMultimodalPayload(rootJson)

        val targetPayloadBytes = rootJson.toString().toByteArray(StandardCharsets.UTF_8)

        val url = URL(targetUrl)
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Authorization", "Bearer $key")
            setRequestProperty("Accept", if (isStream) "text/event-stream" else "application/json")
            setRequestProperty("Accept-Encoding", "identity")
            setRequestProperty("Cache-Control", "no-cache")
            setRequestProperty("User-Agent", "ComputeMesh-Android/1.2")
            doOutput = true
            connectTimeout = 15000
            readTimeout = 90000
        }

        conn.outputStream.use { os ->
            os.write(targetPayloadBytes)
            os.flush()
        }

        val respCode = conn.responseCode
        if (respCode !in 200..299) {
            val errStream = conn.errorStream ?: conn.inputStream
            val errText = errStream?.bufferedReader()?.use { it.readText() } ?: "HTTP $respCode"
            return jsonResponse(
                JSONObject().put("error", JSONObject().put("message", "Gateway Error ($respCode): $errText")),
                Response.Status.lookup(respCode) ?: Response.Status.INTERNAL_ERROR
            )
        }

        if (!isStream) {
            val responseText = conn.inputStream.bufferedReader(StandardCharsets.UTF_8).use { it.readText() }
            return addCorsHeaders(newFixedLengthResponse(Response.Status.OK, "application/json; charset=utf-8", responseText))
        }

        // Streaming SSE via PipedStream
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
    }

    private fun sanitizeMultimodalPayload(root: JSONObject) {
        val messages = root.optJSONArray("messages") ?: return
        for (i in 0 until messages.length()) {
            val msg = messages.optJSONObject(i) ?: continue
            val content = msg.opt("content")
            if (content is JSONArray) {
                for (j in 0 until content.length()) {
                    val part = content.optJSONObject(j) ?: continue
                    if (part.optString("type") == "image_url") {
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
            }
        }
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
        return addCorsHeaders(newFixedLengthResponse(status, "application/json; charset=utf-8", json.toString()))
    }

    private fun addCorsHeaders(response: Response): Response {
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, HEAD")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept, X-Requested-With")
        response.addHeader("Access-Control-Max-Age", "86400")
        return response
    }
}
