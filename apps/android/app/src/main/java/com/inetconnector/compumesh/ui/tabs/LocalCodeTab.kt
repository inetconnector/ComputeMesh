package com.inetconnector.compumesh.ui.tabs

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.widget.Toast
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Launch
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import com.inetconnector.compumesh.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

@Composable
fun LocalCodeTab(
    gatewayUrl: String = "https://mesh.inetconnector.com"
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val scrollState = rememberScrollState()

    var isAppInstalled by remember { mutableStateOf(false) }
    var isNodeOnline by remember { mutableStateOf(false) }
    var nodeLatencyMs by remember { mutableStateOf<Long?>(null) }
    var isCheckingNode by remember { mutableStateOf(false) }
    // 127.0.0.1 points back to the phone. LocalCode runs on the Windows host,
    // so use the known LAN address as the initial desktop endpoint.
    var customHost by remember { mutableStateOf("192.168.1.94:32145") }

    // Download & installation state
    var isDownloading by remember { mutableStateOf(false) }
    var downloadProgress by remember { mutableStateOf(0f) }
    var downloadStatusText by remember { mutableStateOf("") }

    val packageName = "com.inetconnector.localcode"
    val apkDownloadUrl = "https://mesh.inetconnector.com/downloads/LocalCode-Remote-debug.apk"
    val webFallbackUrl = "https://inetconnector.com#apps"

    fun checkIsAppInstalled(): Boolean {
        return try {
            context.packageManager.getPackageInfo(packageName, 0)
            true
        } catch (e: PackageManager.NameNotFoundException) {
            false
        }
    }

    fun openLocalCodeApp() {
        try {
            val intent = context.packageManager.getLaunchIntentForPackage(packageName)
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
            } else {
                Toast.makeText(context, "LocalCode App nicht gefunden", Toast.LENGTH_SHORT).show()
            }
        } catch (e: Throwable) {
            Toast.makeText(context, "Fehler beim Starten: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    fun downloadAndInstallApk() {
        if (isDownloading) return
        isDownloading = true
        downloadProgress = 0f
        downloadStatusText = "Verbinde mit Server..."

        coroutineScope.launch(Dispatchers.IO) {
            try {
                val url = URL(apkDownloadUrl)
                val connection = url.openConnection() as HttpURLConnection
                connection.connectTimeout = 10000
                connection.readTimeout = 15000
                connection.requestMethod = "GET"
                connection.connect()

                if (connection.responseCode !in 200..299) {
                    throw Exception("Server antwortete mit HTTP ${connection.responseCode}")
                }

                val totalBytes = connection.contentLength.coerceAtLeast(1)
                val apkFile = File(context.cacheDir, "LocalCode-Companion.apk")
                if (apkFile.exists()) apkFile.delete()

                val input = connection.inputStream
                val output = FileOutputStream(apkFile)
                val buffer = ByteArray(8192)
                var bytesRead: Int
                var downloadedBytes = 0L

                withContext(Dispatchers.Main) {
                    downloadStatusText = "Lade LocalCode APK herunter..."
                }

                while (input.read(buffer).also { bytesRead = it } != -1) {
                    output.write(buffer, 0, bytesRead)
                    downloadedBytes += bytesRead
                    val progress = (downloadedBytes.toFloat() / totalBytes).coerceIn(0f, 1f)
                    withContext(Dispatchers.Main) {
                        downloadProgress = progress
                        val mbDownloaded = downloadedBytes / (1024f * 1024f)
                        val mbTotal = totalBytes / (1024f * 1024f)
                        downloadStatusText = if (totalBytes > 1) {
                            "%.1f MB / %.1f MB (%.0f%%)".format(mbDownloaded, mbTotal, progress * 100)
                        } else {
                            "%.1f MB geladen...".format(mbDownloaded)
                        }
                    }
                }

                output.flush()
                output.close()
                input.close()

                withContext(Dispatchers.Main) {
                    downloadStatusText = "Starte Installation..."
                    isDownloading = false
                    isAppInstalled = checkIsAppInstalled()

                    // Trigger Android Package Installer
                    try {
                        val contentUri = FileProvider.getUriForFile(
                            context,
                            "${context.packageName}.fileprovider",
                            apkFile
                        )
                        val installIntent = Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(contentUri, "application/vnd.android.package-archive")
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        context.startActivity(installIntent)
                    } catch (e: Throwable) {
                        Toast.makeText(context, "Installer-Fehler: ${e.message}", Toast.LENGTH_LONG).show()
                        // Fallback browser
                        val fallback = Intent(Intent.ACTION_VIEW, Uri.parse(apkDownloadUrl)).apply {
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        context.startActivity(fallback)
                    }
                }
            } catch (e: Throwable) {
                withContext(Dispatchers.Main) {
                    isDownloading = false
                    downloadStatusText = "Fehler: ${e.message}"
                    Toast.makeText(context, "Download fehlgeschlagen: ${e.message}", Toast.LENGTH_LONG).show()
                    // Fallback to web browser
                    val fallback = Intent(Intent.ACTION_VIEW, Uri.parse(webFallbackUrl)).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                    context.startActivity(fallback)
                }
            }
        }
    }

    suspend fun checkNodeConnection() {
        isCheckingNode = true
        withContext(Dispatchers.IO) {
            val gatewayHost = runCatching {
                val parsed = URL(gatewayUrl)
                parsed.host.takeIf { it.isNotBlank() && it != "127.0.0.1" && it != "localhost" }
                    ?.let { "http://$it:32145" }
            }.getOrNull()
            val candidates = listOfNotNull(
                "http://$customHost".takeUnless { customHost.startsWith("127.") || customHost.startsWith("localhost") },
                gatewayHost,
                "http://192.168.1.94:32145"
            ).distinct()
            var online = false
            var latency: Long? = null

            for (cand in candidates) {
                try {
                    val start = System.currentTimeMillis()
                    val conn = (URL("$cand/api/status").openConnection() as HttpURLConnection).apply {
                        connectTimeout = 1200
                        readTimeout = 1200
                        requestMethod = "GET"
                    }
                    if (conn.responseCode in 200..499) {
                        online = true
                        latency = System.currentTimeMillis() - start
                        break
                    }
                } catch (_: Throwable) {}
            }

            withContext(Dispatchers.Main) {
                isNodeOnline = online
                nodeLatencyMs = latency
                isCheckingNode = false
                isAppInstalled = checkIsAppInstalled()
            }
        }
    }

    // Periodic check for installed package and node status
    LaunchedEffect(Unit) {
        isAppInstalled = checkIsAppInstalled()
        while (true) {
            isAppInstalled = checkIsAppInstalled()
            checkNodeConnection()
            delay(5000)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(DeepVoidBg)
            .verticalScroll(scrollState)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Top Banner / Header
        Surface(
            shape = RoundedCornerShape(20.dp),
            color = CardSurface,
            border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Box(
                    modifier = Modifier
                        .size(64.dp)
                        .clip(RoundedCornerShape(18.dp))
                        .background(
                            Brush.linearGradient(
                                listOf(CyanAccent, IndigoAccent)
                            )
                        ),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        Icons.Default.Code,
                        contentDescription = "LocalCode Icon",
                        tint = Color.Black,
                        modifier = Modifier.size(36.dp)
                    )
                }

                Spacer(modifier = Modifier.height(14.dp))

                Text(
                    text = "LocalCode Studio Companion",
                    fontWeight = FontWeight.ExtraBold,
                    fontSize = 20.sp,
                    color = TextPrimary,
                    textAlign = TextAlign.Center
                )

                Spacer(modifier = Modifier.height(6.dp))

                Text(
                    text = "Private KI-Entwicklungsumgebung & Autonome Programmier-Agenten",
                    color = TextSecondary,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                    lineHeight = 18.sp
                )

                Spacer(modifier = Modifier.height(16.dp))

                // Status Badges Row
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    // App Installation Status Badge
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = if (isAppInstalled) EmeraldSuccess.copy(alpha = 0.15f) else AmberWarning.copy(alpha = 0.15f),
                        border = androidx.compose.foundation.BorderStroke(
                            1.dp,
                            if (isAppInstalled) EmeraldSuccess.copy(alpha = 0.4f) else AmberWarning.copy(alpha = 0.4f)
                        )
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(8.dp)
                                    .clip(CircleShape)
                                    .background(if (isAppInstalled) EmeraldSuccess else AmberWarning)
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = if (isAppInstalled) "App installiert" else "Nicht installiert",
                                color = if (isAppInstalled) EmeraldSuccess else AmberWarning,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }

                    Spacer(modifier = Modifier.width(10.dp))

                    // Desktop Node Status Badge
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = if (isNodeOnline) CyanAccent.copy(alpha = 0.15f) else TextMuted.copy(alpha = 0.15f),
                        border = androidx.compose.foundation.BorderStroke(
                            1.dp,
                            if (isNodeOnline) CyanAccent.copy(alpha = 0.4f) else TextMuted.copy(alpha = 0.3f)
                        )
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                        ) {
                            Icon(
                                Icons.Default.Computer,
                                contentDescription = null,
                                tint = if (isNodeOnline) CyanAccent else TextMuted,
                                modifier = Modifier.size(14.dp)
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = if (isNodeOnline) "Node aktiv (${nodeLatencyMs ?: 0}ms)" else "Node offline",
                                color = if (isNodeOnline) CyanAccent else TextMuted,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold
                            )
                        }
                    }
                }
            }
        }

        // Primary Action Card (Start or Download & Install)
        Surface(
            shape = RoundedCornerShape(20.dp),
            color = CardSurface,
            border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp)
            ) {
                Text(
                    text = "Aktion",
                    fontWeight = FontWeight.Bold,
                    color = TextPrimary,
                    fontSize = 16.sp
                )

                if (isAppInstalled) {
                    // Main CTA: Open LocalCode App
                    Button(
                        onClick = { openLocalCodeApp() },
                        shape = RoundedCornerShape(14.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Color.Transparent),
                        contentPadding = PaddingValues(0.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(54.dp)
                            .background(
                                Brush.horizontalGradient(listOf(CyanAccent, IndigoAccent)),
                                shape = RoundedCornerShape(14.dp)
                            )
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Icon(
                                Icons.AutoMirrored.Filled.Launch,
                                contentDescription = null,
                                tint = Color.Black,
                                modifier = Modifier.size(20.dp)
                            )
                            Spacer(modifier = Modifier.width(10.dp))
                            Text(
                                text = "LocalCode App öffnen",
                                color = Color.Black,
                                fontWeight = FontWeight.ExtraBold,
                                fontSize = 16.sp
                            )
                        }
                    }

                    // Secondary action: open in mobile browser if needed
                    OutlinedButton(
                        onClick = {
                            val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse("http://$customHost")).apply {
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                            try {
                                context.startActivity(browserIntent)
                            } catch (e: Throwable) {
                                Toast.makeText(context, "Browser nicht verfügbar", Toast.LENGTH_SHORT).show()
                            }
                        },
                        shape = RoundedCornerShape(14.dp),
                        border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(48.dp)
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center
                        ) {
                            Icon(
                                Icons.Default.Public,
                                contentDescription = null,
                                tint = TextSecondary,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = "Node Web-Interface im Browser öffnen",
                                color = TextSecondary,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Medium
                            )
                        }
                    }
                } else {
                    // Not Installed: Download & Install Flow
                    Button(
                        onClick = { downloadAndInstallApk() },
                        enabled = !isDownloading,
                        shape = RoundedCornerShape(14.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Color.Transparent),
                        contentPadding = PaddingValues(0.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(54.dp)
                            .background(
                                Brush.horizontalGradient(listOf(EmeraldSuccess, CyanAccent)),
                                shape = RoundedCornerShape(14.dp)
                            )
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            if (isDownloading) {
                                CircularProgressIndicator(
                                    color = Color.Black,
                                    modifier = Modifier.size(20.dp),
                                    strokeWidth = 2.dp
                                )
                            } else {
                                Icon(
                                    Icons.Default.Download,
                                    contentDescription = null,
                                    tint = Color.Black,
                                    modifier = Modifier.size(20.dp)
                                )
                            }
                            Spacer(modifier = Modifier.width(10.dp))
                            Text(
                                text = if (isDownloading) "Wird heruntergeladen..." else "App herunterladen & installieren",
                                color = Color.Black,
                                fontWeight = FontWeight.ExtraBold,
                                fontSize = 15.sp
                            )
                        }
                    }

                    AnimatedVisibility(visible = isDownloading) {
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            LinearProgressIndicator(
                                progress = { downloadProgress },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(6.dp)
                                    .clip(RoundedCornerShape(3.dp)),
                                color = EmeraldSuccess,
                                trackColor = CardSurfaceBorder
                            )
                            Text(
                                text = downloadStatusText,
                                color = TextMuted,
                                fontSize = 12.sp,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.fillMaxWidth()
                            )
                        }
                    }

                    // Fallback button to visit Web App Center
                    OutlinedButton(
                        onClick = {
                            val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse(webFallbackUrl)).apply {
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                            context.startActivity(browserIntent)
                        },
                        shape = RoundedCornerShape(14.dp),
                        border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(48.dp)
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center
                        ) {
                            Icon(
                                Icons.Default.Public,
                                contentDescription = null,
                                tint = TextSecondary,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = "Auf Website / App Center ansehen",
                                color = TextSecondary,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Medium
                            )
                        }
                    }
                }
            }
        }

        // Desktop Node & Network Connection Card
        Surface(
            shape = RoundedCornerShape(20.dp),
            color = CardSurface,
            border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "LocalCode Server-Node",
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary,
                        fontSize = 16.sp
                    )

                    IconButton(
                        onClick = {
                            coroutineScope.launch { checkNodeConnection() }
                        },
                        modifier = Modifier.size(32.dp)
                    ) {
                        if (isCheckingNode) {
                            CircularProgressIndicator(
                                color = CyanAccent,
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp
                            )
                        } else {
                            Icon(
                                Icons.Default.Refresh,
                                contentDescription = "Aktualisieren",
                                tint = TextMuted,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                    }
                }

                // Node Address Display
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = DeepVoidBg,
                    border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column {
                            Text(
                                text = "Host / Endpoint",
                                color = TextMuted,
                                fontSize = 11.sp
                            )
                            Text(
                                text = "http://$customHost",
                                color = TextPrimary,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.SemiBold
                            )
                        }

                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(8.dp))
                                .background(if (isNodeOnline) EmeraldSuccess.copy(alpha = 0.15f) else TextMuted.copy(alpha = 0.15f))
                                .padding(horizontal = 8.dp, vertical = 4.dp)
                        ) {
                            Text(
                                text = if (isNodeOnline) "ONLINE" else "OFFLINE",
                                color = if (isNodeOnline) EmeraldSuccess else TextMuted,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }

                Text(
                    text = "Hinweis: Wenn LocalCode auf Ihrem Desktop-PC gestartet ist, lauscht der Dienst standardmäßig auf Port 32145. Über ADB Reverse oder das lokale WLAN verbindet sich die mobile Companion-App nahtlos.",
                    color = TextMuted,
                    fontSize = 12.sp,
                    lineHeight = 16.sp
                )
            }
        }
    }
}
