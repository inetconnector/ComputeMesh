package com.inetconnector.compumesh.ui.bridge

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.util.Locale

class AndroidSpeechBridge(
    private val activity: Activity,
    private val webView: WebView,
    private val onRequestAudioPermission: (() -> Unit) -> Unit
) {
    private var speechRecognizer: SpeechRecognizer? = null
    private var isListeningSession = false
    private var currentLang: String? = null

    @JavascriptInterface
    fun startSpeechRecognition(lang: String?) {
        activity.runOnUiThread {
            currentLang = lang
            if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                onRequestAudioPermission {
                    startSpeechRecognition(lang)
                }
                return@runOnUiThread
            }

            isListeningSession = true
            startInternalRecognizer(lang)
        }
    }

    private fun startInternalRecognizer(lang: String?) {
        if (!isListeningSession) return
        try {
            speechRecognizer?.destroy()
            if (!SpeechRecognizer.isRecognitionAvailable(activity)) {
                Log.w("SpeechBridge", "SpeechRecognizer service not available on device")
                notifyJs("onerror", "Sprachdienst auf dem Gerät nicht verfügbar")
                notifyJs("onend")
                return
            }

            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(activity).apply {
                setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        Log.i("SpeechBridge", "onReadyForSpeech")
                        notifyJs("onstart")
                    }
                    override fun onBeginningOfSpeech() {
                        Log.i("SpeechBridge", "onBeginningOfSpeech")
                    }
                    override fun onRmsChanged(rmsdB: Float) {
                        notifyJs("onrms", rmsdB.toString())
                    }
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() {
                        Log.i("SpeechBridge", "onEndOfSpeech")
                    }
                    override fun onError(error: Int) {
                        Log.w("SpeechBridge", "Recognition error: code $error (isListening=$isListeningSession)")
                        if (isListeningSession) {
                            // Transient errors: no speech input, silence timeout, or server disconnect
                            if (error == SpeechRecognizer.ERROR_NO_MATCH ||
                                error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT ||
                                error == 11 /* ERROR_SERVER_DISCONNECTED */ ||
                                error == SpeechRecognizer.ERROR_CLIENT ||
                                error == SpeechRecognizer.ERROR_NETWORK_TIMEOUT) {
                                Log.i("SpeechBridge", "Transient pause / error $error, restarting listening...")
                                activity.window.decorView.postDelayed({
                                    if (isListeningSession) {
                                        startInternalRecognizer(currentLang)
                                    }
                                }, 200)
                                return
                            }
                        }
                        notifyJs("onerror", "Sprachdienst: Code $error")
                        notifyJs("onend")
                    }
                    override fun onResults(results: Bundle?) {
                        val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        val text = matches?.firstOrNull() ?: ""
                        Log.i("SpeechBridge", "Recognized text: $text")
                        if (text.isNotBlank()) {
                            notifyJs("onresult", text)
                        }
                        notifyJs("onend")
                    }
                    override fun onPartialResults(partialResults: Bundle?) {
                        val matches = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        val text = matches?.firstOrNull() ?: ""
                        if (text.isNotBlank()) {
                            notifyJs("onpartialresult", text)
                        }
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })
            }

            val targetLang = if (!lang.isNullOrBlank()) lang else Locale.getDefault().toLanguageTag()
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, targetLang)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, targetLang)
                putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, activity.packageName)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false)
                putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 3000L)
            }
            speechRecognizer?.startListening(intent)
        } catch (e: Throwable) {
            Log.e("SpeechBridge", "Failed to start speech recognizer: ${e.message}")
            notifyJs("onerror", e.message ?: "Fehler bei Spracherkennung")
            notifyJs("onend")
        }
    }

    @JavascriptInterface
    fun stopSpeechRecognition() {
        activity.runOnUiThread {
            isListeningSession = false
            try {
                speechRecognizer?.stopListening()
                speechRecognizer?.destroy()
                speechRecognizer = null
            } catch (_: Throwable) {}
        }
    }

    @JavascriptInterface
    fun openExternalUrl(url: String?) {
        if (url.isNullOrBlank()) return
        activity.runOnUiThread {
            try {
                val parsedUri = Uri.parse(url)
                val intent = Intent(Intent.ACTION_VIEW, parsedUri).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                activity.startActivity(intent)
            } catch (e: Throwable) {
                Log.e("SpeechBridge", "Failed to open URL $url: ${e.message}")
            }
        }
    }

    @JavascriptInterface
    fun openOrInstallLocalCode() {
        activity.runOnUiThread {
            val packageName = "com.inetconnector.localcode"
            val pm = activity.packageManager
            try {
                // Check if package is installed
                pm.getPackageInfo(packageName, 0)
                // Installed -> Launch LocalCode app!
                val launchIntent = pm.getLaunchIntentForPackage(packageName)
                if (launchIntent != null) {
                    launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    activity.startActivity(launchIntent)
                    android.widget.Toast.makeText(activity, "LocalCode wird geöffnet...", android.widget.Toast.LENGTH_SHORT).show()
                } else {
                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse("localcode://pair")).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                    activity.startActivity(intent)
                }
            } catch (_: PackageManager.NameNotFoundException) {
                // Not installed -> open download / install page
                try {
                    val downloadUri = Uri.parse("https://mesh.inetconnector.com/downloads")
                    val browserIntent = Intent(Intent.ACTION_VIEW, downloadUri).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                    activity.startActivity(browserIntent)
                    android.widget.Toast.makeText(activity, "LocalCode wird heruntergeladen / installiert...", android.widget.Toast.LENGTH_LONG).show()
                } catch (ex: Exception) {
                    Log.e("SpeechBridge", "Failed to open LocalCode download link", ex)
                }
            } catch (ex: Exception) {
                Log.e("SpeechBridge", "Failed to launch LocalCode", ex)
            }
        }
    }

    private fun notifyJs(event: String, data: String = "") {
        activity.runOnUiThread {
            val safeData = JSONObject.quote(data)
            val script = "window.__onAndroidSpeechEvent && window.__onAndroidSpeechEvent('$event', $safeData);"
            webView.evaluateJavascript(script, null)
        }
    }
}
