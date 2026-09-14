package com.inetconnector.compumesh.ui.tabs

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.webkit.*
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Launch
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.inetconnector.compumesh.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun LocalCodeTab(
    gatewayUrl: String = "https://mesh.inetconnector.com"
) {
    val context = LocalContext.current
    var webViewInstance by remember { mutableStateOf<WebView?>(null) }
    var isAppInstalled by remember { mutableStateOf(false) }
    var isNodeOnline by remember { mutableStateOf(false) }
    var isChecking by remember { mutableStateOf(true) }
    var targetUrl by remember { mutableStateOf("http://127.0.0.1:32145/") }

    fun checkLocalCodeInstalled(): Boolean {
        return try {
            context.packageManager.getPackageInfo("com.inetconnector.localcode", 0)
            true
        } catch (e: PackageManager.NameNotFoundException) {
            false
        }
    }

    fun openLocalCodeApp() {
        try {
            val intent = context.packageManager.getLaunchIntentForPackage("com.inetconnector.localcode")
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
            } else {
                val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://mesh.inetconnector.com/downloads/LocalCode-Remote-debug.apk"))
                browserIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(browserIntent)
            }
        } catch (e: Throwable) {
            Toast.makeText(context, "Fehler beim Starten: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    // Auto-detect best endpoint (localhost ADB reverse or LAN IP)
    LaunchedEffect(Unit) {
        isAppInstalled = checkLocalCodeInstalled()
        while (true) {
            isAppInstalled = checkLocalCodeInstalled()
            val onlineHost = withContext(Dispatchers.IO) {
                val candidates = listOf(
                    "http://127.0.0.1:32145",
                    "http://192.168.1.94:32145",
                    "http://localhost:32145"
                )
                for (cand in candidates) {
                    try {
                        val conn = (URL("$cand/api/status").openConnection() as HttpURLConnection).apply {
                            connectTimeout = 1000
                            readTimeout = 1000
                            requestMethod = "GET"
                        }
                        if (conn.responseCode in 200..499) {
                            return@withContext "$cand/"
                        }
                    } catch (_: Throwable) {}
                }
                null
            }

            if (onlineHost != null) {
                isNodeOnline = true
                if (targetUrl != onlineHost) {
                    targetUrl = onlineHost
                    webViewInstance?.post {
                        webViewInstance?.loadUrl(onlineHost)
                    }
                }
            } else {
                isNodeOnline = false
            }
            isChecking = false
            delay(5000)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(DeepVoidBg)
    ) {
        // Minimal High-Tech Top Bar
        Surface(
            color = CardSurface,
            tonalElevation = 4.dp,
            modifier = Modifier.fillMaxWidth()
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(if (isNodeOnline) EmeraldSuccess else AmberWarning)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = "LocalCode",
                        fontWeight = FontWeight.ExtraBold,
                        color = TextPrimary,
                        fontSize = 15.sp
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = if (isNodeOnline) "Node aktiv" else "Verbinde...",
                        color = if (isNodeOnline) EmeraldSuccess else AmberWarning,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    if (isAppInstalled) {
                        Surface(
                            shape = RoundedCornerShape(14.dp),
                            color = EmeraldSuccess.copy(alpha = 0.15f),
                            border = androidx.compose.foundation.BorderStroke(1.dp, EmeraldSuccess.copy(alpha = 0.4f)),
                            modifier = Modifier.clickable { openLocalCodeApp() }
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                            ) {
                                Icon(
                                    Icons.AutoMirrored.Filled.Launch,
                                    contentDescription = null,
                                    tint = EmeraldSuccess,
                                    modifier = Modifier.size(13.dp)
                                )
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("App öffnen", color = EmeraldSuccess, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    } else {
                        Surface(
                            shape = RoundedCornerShape(14.dp),
                            color = CyanAccent.copy(alpha = 0.15f),
                            border = androidx.compose.foundation.BorderStroke(1.dp, CyanAccent.copy(alpha = 0.4f)),
                            modifier = Modifier.clickable {
                                val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://mesh.inetconnector.com/downloads/LocalCode-Remote-debug.apk")).apply {
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                                context.startActivity(browserIntent)
                            }
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                            ) {
                                Icon(
                                    Icons.Default.Download,
                                    contentDescription = null,
                                    tint = CyanAccent,
                                    modifier = Modifier.size(13.dp)
                                )
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("APK", color = CyanAccent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    }

                    IconButton(
                        onClick = {
                            webViewInstance?.reload()
                        },
                        modifier = Modifier.size(32.dp)
                    ) {
                        Icon(
                            Icons.Default.Refresh,
                            contentDescription = "Neu laden",
                            tint = TextMuted,
                            modifier = Modifier.size(18.dp)
                        )
                    }
                }
            }
        }

        // Live Embedded IDE or Connecting State
        Box(
            modifier = Modifier
                .fillMaxSize()
                .weight(1f)
        ) {
            AndroidView(
                factory = { ctx ->
                    WebView(ctx).apply {
                        webViewInstance = this
                        layoutParams = android.view.ViewGroup.LayoutParams(
                            android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                            android.view.ViewGroup.LayoutParams.MATCH_PARENT
                        )
                        setBackgroundColor(android.graphics.Color.parseColor("#0b0f19"))

                        settings.apply {
                            javaScriptEnabled = true
                            domStorageEnabled = true
                            databaseEnabled = true
                            useWideViewPort = true
                            loadWithOverviewMode = true
                            setSupportZoom(true)
                            builtInZoomControls = true
                            displayZoomControls = false
                            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                            allowFileAccess = true
                            allowContentAccess = true
                            userAgentString = userAgentString + " ComputeMesh-LocalCode/2.0"
                        }

                        webViewClient = object : WebViewClient() {
                            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                                super.onPageStarted(view, url, favicon)
                            }

                            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                                super.onReceivedError(view, request, error)
                            }
                        }

                        webChromeClient = object : WebChromeClient() {
                            override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                                return true
                            }
                        }

                        loadUrl(targetUrl)
                    }
                },
                modifier = Modifier.fillMaxSize()
            )

            // Minimal Connecting Overlay when node is starting up
            if (!isNodeOnline && isChecking) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(DeepVoidBg),
                    contentAlignment = Alignment.Center
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        CircularProgressIndicator(color = CyanAccent, modifier = Modifier.size(36.dp))
                        Text(
                            "LocalCode Node wird initialisiert...",
                            color = TextSecondary,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Medium
                        )
                    }
                }
            }
        }
    }
}
