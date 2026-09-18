package com.inetconnector.compumesh.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

data class AndroidUpdateInfo(
    val version: String,
    val downloadUrl: String,
    val expectedSha256: String,
    val sizeBytes: Long,
)

object AndroidUpdateChecker {
    private const val METADATA_URL = "https://mesh.inetconnector.com/downloads/ComputeMesh-Android.json"
    private const val CONNECT_TIMEOUT_MS = 6000
    private const val READ_TIMEOUT_MS = 10000

    suspend fun check(currentVersion: String): AndroidUpdateInfo? = withContext(Dispatchers.IO) {
        runCatching {
            val connection = URL(METADATA_URL).openConnection() as HttpURLConnection
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.requestMethod = "GET"
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Cache-Control", "no-cache")
            connection.connect()
            if (connection.responseCode !in 200..299) return@runCatching null

            val json = connection.inputStream.bufferedReader().use { JSONObject(it.readText()) }
            val latest = json.optString("version_name", json.optString("version")).trim()
            val url = json.optString("url").trim()
            val sha256 = json.optString("apk_sha256", json.optString("sha256")).trim().lowercase()
            if (latest.isBlank() || url.isBlank() || !sha256.matches(Regex("[0-9a-f]{64}"))) return@runCatching null
            if (compareVersions(latest, currentVersion) <= 0) return@runCatching null

            AndroidUpdateInfo(
                version = latest,
                downloadUrl = url,
                expectedSha256 = sha256,
                sizeBytes = json.optLong("apk_size", json.optLong("size", 0L)),
            )
        }.getOrNull()
    }

    suspend fun downloadAndInstall(context: Context, update: AndroidUpdateInfo) = withContext(Dispatchers.IO) {
        val apkFile = File(context.cacheDir, "ComputeMesh-update-${update.version}.apk")
        if (apkFile.exists()) apkFile.delete()

        val connection = URL(update.downloadUrl).openConnection() as HttpURLConnection
        connection.connectTimeout = CONNECT_TIMEOUT_MS
        connection.readTimeout = 30000
        connection.requestMethod = "GET"
        connection.connect()
        if (connection.responseCode !in 200..299) error("Server antwortete mit HTTP ${connection.responseCode}")

        val digest = MessageDigest.getInstance("SHA-256")
        connection.inputStream.use { input ->
            FileOutputStream(apkFile).use { output ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                    digest.update(buffer, 0, count)
                }
            }
        }

        val actualSha256 = digest.digest().joinToString("") { "%02x".format(it) }
        if (!actualSha256.equals(update.expectedSha256, ignoreCase = true)) {
            apkFile.delete()
            error("APK-Prüfsumme stimmt nicht überein")
        }

        withContext(Dispatchers.Main) {
            val contentUri: Uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                apkFile,
            )
            val installIntent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(contentUri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(installIntent)
        }
    }

    internal fun compareVersions(left: String, right: String): Int {
        val a = parseVersion(left)
        val b = parseVersion(right)
        val max = maxOf(a.size, b.size)
        for (index in 0 until max) {
            val av = a.getOrElse(index) { 0 }
            val bv = b.getOrElse(index) { 0 }
            if (av != bv) return av.compareTo(bv)
        }
        return 0
    }

    private fun parseVersion(value: String): List<Int> = value
        .trim()
        .removePrefix("v")
        .removePrefix("V")
        .split(".")
        .map { it.takeWhile(Char::isDigit).toIntOrNull() ?: 0 }
}
