package com.inetconnector.compumesh.engine

import android.util.Log
import com.inetconnector.compumesh.ui.models.AgentTaskItem
import com.inetconnector.compumesh.ui.models.AgentWorkspaceItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

object AgentWorkspaceClient {
    private const val TAG = "AgentWorkspaceClient"
    private const val CONNECT_TIMEOUT_MS = 6000
    private const val READ_TIMEOUT_MS = 10000

    private fun normalizeUrl(baseUrl: String, path: String): String {
        val trimmedBase = baseUrl.trim().trimEnd('/')
        val trimmedPath = if (path.startsWith("/")) path else "/$path"
        return "$trimmedBase$trimmedPath"
    }

    private fun setupConnection(urlStr: String, method: String, apiKey: String): HttpURLConnection {
        val url = URL(urlStr)
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = CONNECT_TIMEOUT_MS
        conn.readTimeout = READ_TIMEOUT_MS
        conn.setRequestProperty("Accept", "application/json")
        if (apiKey.isNotBlank()) {
            conn.setRequestProperty("Authorization", "Bearer $apiKey")
            conn.setRequestProperty("X-Owner-Key", apiKey)
        }
        return conn
    }

    suspend fun getWorkspaces(
        gatewayUrl: String,
        apiKey: String
    ): Result<List<AgentWorkspaceItem>> = withContext(Dispatchers.IO) {
        try {
            val urlStr = normalizeUrl(gatewayUrl, "/v1/fleet/workspaces")
            val conn = setupConnection(urlStr, "GET", apiKey)
            val code = conn.responseCode
            if (code in 200..299) {
                val reader = BufferedReader(InputStreamReader(conn.inputStream, "UTF-8"))
                val body = reader.readText()
                reader.close()
                val json = JSONObject(body)
                val wsArray = json.optJSONArray("workspaces") ?: JSONArray()
                val list = mutableListOf<AgentWorkspaceItem>()
                for (i in 0 until wsArray.length()) {
                    val obj = wsArray.getJSONObject(i)
                    list.add(
                        AgentWorkspaceItem(
                            id = obj.optString("id", ""),
                            name = obj.optString("name", obj.optString("id", "")),
                            path = obj.optString("path", ""),
                            nodeId = obj.optString("node_id", "cm-win-mifcom-rtx3080"),
                            gitBranch = obj.optString("git_branch", ""),
                            registrationSource = obj.optString("registration_source", "user_registered"),
                            status = obj.optString("status", "active")
                        )
                    )
                }
                Result.success(list)
            } else {
                val errReader = conn.errorStream?.let { BufferedReader(InputStreamReader(it, "UTF-8")) }
                val errBody = errReader?.readText() ?: "HTTP $code"
                errReader?.close()
                Result.failure(Exception("Gateway error $code: $errBody"))
            }
        } catch (e: Exception) {
            Log.w(TAG, "getWorkspaces failed: ${e.message}")
            Result.failure(e)
        }
    }

    suspend fun unregisterWorkspace(
        gatewayUrl: String,
        apiKey: String,
        wsId: String,
        deletePhysical: Boolean = false,
        confirmName: String? = null
    ): Result<Boolean> = withContext(Dispatchers.IO) {
        try {
            val encodedId = URLEncoder.encode(wsId, "UTF-8")
            var urlStr = normalizeUrl(gatewayUrl, "/v1/fleet/workspaces/$encodedId")
            if (deletePhysical && !confirmName.isNullOrBlank()) {
                urlStr += "?delete_physical=true&confirm_name=" + URLEncoder.encode(confirmName, "UTF-8")
            }
            val conn = setupConnection(urlStr, "DELETE", apiKey)
            val code = conn.responseCode
            if (code in 200..299) {
                Result.success(true)
            } else {
                val errReader = conn.errorStream?.let { BufferedReader(InputStreamReader(it, "UTF-8")) }
                val errBody = errReader?.readText() ?: "HTTP $code"
                errReader?.close()
                Result.failure(Exception(errBody))
            }
        } catch (e: Exception) {
            Log.w(TAG, "unregisterWorkspace failed: ${e.message}")
            Result.failure(e)
        }
    }

    suspend fun getSessions(
        gatewayUrl: String,
        apiKey: String,
        workspaceFilter: String? = null
    ): Result<List<AgentTaskItem>> = withContext(Dispatchers.IO) {
        try {
            var urlStr = normalizeUrl(gatewayUrl, "/v1/agents/sessions?limit=50")
            if (!workspaceFilter.isNullOrBlank()) {
                urlStr += "&workspace=" + URLEncoder.encode(workspaceFilter, "UTF-8")
            }
            val conn = setupConnection(urlStr, "GET", apiKey)
            val code = conn.responseCode
            if (code in 200..299) {
                val reader = BufferedReader(InputStreamReader(conn.inputStream, "UTF-8"))
                val body = reader.readText()
                reader.close()
                val json = JSONObject(body)
                val sessArray = json.optJSONArray("sessions") ?: JSONArray()
                val list = mutableListOf<AgentTaskItem>()
                for (i in 0 until sessArray.length()) {
                    val obj = sessArray.getJSONObject(i)
                    list.add(
                        AgentTaskItem(
                            sessionId = obj.optString("session_id", ""),
                            title = obj.optString("title", obj.optString("session_id", "")),
                            workspace = obj.optString("workspace", ""),
                            status = obj.optString("status", "ready"),
                            createdAt = obj.optLong("created_at", System.currentTimeMillis()),
                            archived = obj.optBoolean("archived", false)
                        )
                    )
                }
                Result.success(list)
            } else {
                val errReader = conn.errorStream?.let { BufferedReader(InputStreamReader(it, "UTF-8")) }
                val errBody = errReader?.readText() ?: "HTTP $code"
                errReader?.close()
                Result.failure(Exception("Gateway error $code: $errBody"))
            }
        } catch (e: Exception) {
            Log.w(TAG, "getSessions failed: ${e.message}")
            Result.failure(e)
        }
    }

    suspend fun deleteSession(
        gatewayUrl: String,
        apiKey: String,
        sessionId: String
    ): Result<Boolean> = withContext(Dispatchers.IO) {
        try {
            val encodedId = URLEncoder.encode(sessionId, "UTF-8")
            val urlStr = normalizeUrl(gatewayUrl, "/v1/agents/sessions/$encodedId")
            val conn = setupConnection(urlStr, "DELETE", apiKey)
            val code = conn.responseCode
            if (code in 200..299) {
                Result.success(true)
            } else {
                val errReader = conn.errorStream?.let { BufferedReader(InputStreamReader(it, "UTF-8")) }
                val errBody = errReader?.readText() ?: "HTTP $code"
                errReader?.close()
                Result.failure(Exception(errBody))
            }
        } catch (e: Exception) {
            Log.w(TAG, "deleteSession failed: ${e.message}")
            Result.failure(e)
        }
    }
}

