package com.inetconnector.compumesh.ui.tabs

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.util.Log
import android.webkit.*
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.inetconnector.compumesh.ui.MainActivity
import com.inetconnector.compumesh.ui.bridge.AndroidSpeechBridge
import com.inetconnector.compumesh.ui.theme.DeepVoidBg

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MiniCpmChatTab(
    serverPort: Int = MainActivity.CHAT_SERVER_PORT
) {
    val context = LocalContext.current
    val activity = context as? Activity
    var webViewInstance by remember { mutableStateOf<WebView?>(null) }
    var fileChooserCallback by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    var currentCameraPhotoUri by remember { mutableStateOf<Uri?>(null) }
    var pendingPermissionRequest by remember { mutableStateOf<PermissionRequest?>(null) }
    var pendingAudioCallback by remember { mutableStateOf<(() -> Unit)?>(null) }

    val multiplePermissionsLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { perms ->
        val recordGranted = perms[Manifest.permission.RECORD_AUDIO] ?: false
        val cameraGranted = perms[Manifest.permission.CAMERA] ?: false

        if (pendingPermissionRequest != null) {
            val resList = mutableListOf<String>()
            if (recordGranted) resList.add(PermissionRequest.RESOURCE_AUDIO_CAPTURE)
            if (cameraGranted) resList.add(PermissionRequest.RESOURCE_VIDEO_CAPTURE)
            if (resList.isNotEmpty()) {
                pendingPermissionRequest?.grant(resList.toTypedArray())
            } else {
                pendingPermissionRequest?.deny()
            }
            pendingPermissionRequest = null
        }
        if (recordGranted) {
            pendingAudioCallback?.invoke()
            pendingAudioCallback = null
        }
    }

    LaunchedEffect(Unit) {
        val needed = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.RECORD_AUDIO)
        }
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.CAMERA)
        }
        if (needed.isNotEmpty()) {
            multiplePermissionsLauncher.launch(needed.toTypedArray())
        }
    }

    val cameraAndFilePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val intentData = result.data
            val uris = mutableListOf<Uri>()

            if (intentData?.data != null) {
                uris.add(intentData.data!!)
            } else if (intentData?.clipData != null) {
                val clip = intentData.clipData!!
                for (i in 0 until clip.itemCount) {
                    clip.getItemAt(i).uri?.let { uris.add(it) }
                }
            } else if (currentCameraPhotoUri != null) {
                try {
                    val cr = context.contentResolver
                    val pfd = cr.openFileDescriptor(currentCameraPhotoUri!!, "r")
                    if (pfd != null && pfd.statSize > 0) {
                        uris.add(currentCameraPhotoUri!!)
                    }
                    pfd?.close()
                } catch (_: Throwable) {}
            }

            if (uris.isNotEmpty()) {
                val optimizedUris = com.inetconnector.compumesh.util.ImageUploadOptimizer.optimizeImageUris(context, uris)
                fileChooserCallback?.onReceiveValue(optimizedUris.toTypedArray())
            } else {
                fileChooserCallback?.onReceiveValue(null)
            }
        } else {
            fileChooserCallback?.onReceiveValue(null)
        }
        fileChooserCallback = null
    }

    BackHandler(enabled = true) {
        if (webViewInstance != null) {
            webViewInstance?.evaluateJavascript(
                """(function() {
                    if (typeof window.__dismissComputeMeshModals === 'function') {
                        return window.__dismissComputeMeshModals();
                    }
                    return false;
                })()"""
            ) { result ->
                if (result != "true") {
                    if (webViewInstance?.canGoBack() == true) {
                        webViewInstance?.goBack()
                    } else {
                        activity?.moveTaskToBack(true)
                    }
                }
            }
        } else {
            activity?.moveTaskToBack(true)
        }
    }

    val initialChatUrl = remember(serverPort) {
        if (MainActivity.isColdStart) {
            MainActivity.isColdStart = false
            "http://127.0.0.1:$serverPort/?new_chat=true&lang=de#/"
        } else {
            "http://127.0.0.1:$serverPort/?lang=de#/"
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(DeepVoidBg)
    ) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                val existing = MainActivity.globalWebView
                if (existing != null) {
                    (existing.parent as? android.view.ViewGroup)?.removeView(existing)
                    existing.resumeTimers()
                    existing.onResume()
                    webViewInstance = existing
                    return@AndroidView existing
                }

                WebView(ctx).apply {
                    webViewInstance = this
                    MainActivity.globalWebView = this
                    setBackgroundColor(0xFF090D16.toInt())
                    isVerticalScrollBarEnabled = true
                    isHorizontalScrollBarEnabled = false
                    isScrollbarFadingEnabled = true
                    overScrollMode = android.view.View.OVER_SCROLL_IF_CONTENT_SCROLLS
                    isNestedScrollingEnabled = true

                    settings.apply {
                        javaScriptEnabled = true
                        domStorageEnabled = true
                        allowFileAccess = true
                        allowContentAccess = true
                        databaseEnabled = true
                        useWideViewPort = true
                        loadWithOverviewMode = true
                        textZoom = 100
                        setSupportZoom(false)
                        builtInZoomControls = false
                        displayZoomControls = false
                        mediaPlaybackRequiresUserGesture = false
                        javaScriptCanOpenWindowsAutomatically = true
                        setSupportMultipleWindows(true)
                        mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                    }

                    if (activity != null) {
                        val bridge = AndroidSpeechBridge(
                            activity,
                            this,
                            onRequestAudioPermission = { onGranted ->
                                pendingAudioCallback = onGranted
                                multiplePermissionsLauncher.launch(arrayOf(Manifest.permission.RECORD_AUDIO))
                            }
                        )
                        addJavascriptInterface(bridge, "AndroidSpeechBridge")
                        addJavascriptInterface(bridge, "AndroidBridge")
                    }

                    webChromeClient = object : WebChromeClient() {
                        override fun onCreateWindow(
                            view: WebView?,
                            isDialog: Boolean,
                            isUserGesture: Boolean,
                            resultMsg: android.os.Message?
                        ): Boolean {
                            val transport = resultMsg?.obj as? WebView.WebViewTransport ?: return false
                            val tempWebView = WebView(view?.context ?: return false)
                            tempWebView.webViewClient = object : WebViewClient() {
                                override fun shouldOverrideUrlLoading(v: WebView?, req: WebResourceRequest?): Boolean {
                                    val url = req?.url?.toString() ?: return false
                                    try {
                                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
                                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                        }
                                        ctx.startActivity(intent)
                                    } catch (e: Throwable) {
                                        Log.e("WebViewChat", "Error opening external window URL $url: ${e.message}")
                                    }
                                    return true
                                }
                            }
                            transport.webView = tempWebView
                            resultMsg.sendToTarget()
                            return true
                        }

                        override fun onShowFileChooser(
                            webView: WebView?,
                            filePathCallback: ValueCallback<Array<Uri>>?,
                            fileChooserParams: FileChooserParams?
                        ): Boolean {
                            fileChooserCallback?.onReceiveValue(null)
                            fileChooserCallback = filePathCallback

                            try {
                                val photoFile = java.io.File(ctx.cacheDir, "camera_capture_${System.currentTimeMillis()}.jpg")
                                photoFile.createNewFile()
                                val photoUri = androidx.core.content.FileProvider.getUriForFile(
                                    ctx,
                                    "${ctx.packageName}.fileprovider",
                                    photoFile
                                )
                                currentCameraPhotoUri = photoUri

                                val takePictureIntent = Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE).apply {
                                    putExtra(android.provider.MediaStore.EXTRA_OUTPUT, photoUri)
                                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                                }

                                val getContentIntent = Intent(Intent.ACTION_GET_CONTENT).apply {
                                    addCategory(Intent.CATEGORY_OPENABLE)
                                    type = "*/*"
                                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                                }

                                val chooserIntent = Intent(Intent.ACTION_CHOOSER).apply {
                                    putExtra(Intent.EXTRA_INTENT, getContentIntent)
                                    putExtra(Intent.EXTRA_TITLE, "Datei auswählen oder Foto aufnehmen")
                                    putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(takePictureIntent))
                                }

                                cameraAndFilePickerLauncher.launch(chooserIntent)
                                return true
                            } catch (e: Throwable) {
                                Log.e("WebViewChat", "Error creating camera/file chooser: ${e.message}")
                                try {
                                    val fallbackIntent = Intent(Intent.ACTION_GET_CONTENT).apply {
                                        addCategory(Intent.CATEGORY_OPENABLE)
                                        type = "*/*"
                                    }
                                    cameraAndFilePickerLauncher.launch(fallbackIntent)
                                    return true
                                } catch (_: Throwable) {
                                    fileChooserCallback?.onReceiveValue(null)
                                    fileChooserCallback = null
                                    return false
                                }
                            }
                        }

                        override fun onPermissionRequest(request: PermissionRequest?) {
                            val resources = request?.resources ?: emptyArray()
                            val needed = mutableListOf<String>()
                            if (resources.contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE) &&
                                ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                                needed.add(Manifest.permission.RECORD_AUDIO)
                            }
                            if (resources.contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE) &&
                                ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                                needed.add(Manifest.permission.CAMERA)
                            }

                            if (needed.isEmpty()) {
                                activity?.runOnUiThread {
                                    request?.grant(resources)
                                }
                            } else {
                                pendingPermissionRequest = request
                                multiplePermissionsLauncher.launch(needed.toTypedArray())
                            }
                        }

                        override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                            android.util.Log.d("WebConsole", "[${consoleMessage?.messageLevel()}] ${consoleMessage?.message()} (at ${consoleMessage?.sourceId()}:${consoleMessage?.lineNumber()})")
                            return true
                        }

                        override fun onJsAlert(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
                            android.app.AlertDialog.Builder(view?.context)
                                .setTitle("ComputeMesh")
                                .setMessage(message ?: "")
                                .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                                .setOnCancelListener { result?.cancel() }
                                .show()
                            return true
                        }

                        override fun onJsConfirm(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
                            android.app.AlertDialog.Builder(view?.context)
                                .setTitle("ComputeMesh")
                                .setMessage(message ?: "")
                                .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                                .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                                .setOnCancelListener { result?.cancel() }
                                .show()
                            return true
                        }

                        override fun onJsPrompt(view: WebView?, url: String?, message: String?, defaultValue: String?, result: JsPromptResult?): Boolean {
                            val input = android.widget.EditText(view?.context).apply {
                                setText(defaultValue ?: "")
                            }
                            android.app.AlertDialog.Builder(view?.context)
                                .setTitle("ComputeMesh")
                                .setMessage(message ?: "")
                                .setView(input)
                                .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm(input.text.toString()) }
                                .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                                .setOnCancelListener { result?.cancel() }
                                .show()
                            return true
                        }
                    }

                    if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.KITKAT) {
                        WebView.setWebContentsDebuggingEnabled(true)
                    }

                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                            val url = request?.url?.toString() ?: return false
                            return if (url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost")) {
                                false
                            } else {
                                try {
                                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
                                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    }
                                    ctx.startActivity(intent)
                                } catch (_: Throwable) {}
                                true
                            }
                        }

                        override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                            super.onReceivedError(view, request, error)
                            android.util.Log.e("WebViewChat", "Error loading ${request?.url}: ${error?.description} (${error?.errorCode})")
                        }

                        override fun onPageFinished(view: WebView?, url: String?) {
                            super.onPageFinished(view, url)
                            android.util.Log.d("WebViewChat", "Page finished loading: $url")
                        }
                    }

                    loadUrl(initialChatUrl)
                }
            },
            update = { webView ->
                webView.resumeTimers()
                webView.onResume()
                webView.requestLayout()
                webView.invalidate()
            }
        )
    }
}
