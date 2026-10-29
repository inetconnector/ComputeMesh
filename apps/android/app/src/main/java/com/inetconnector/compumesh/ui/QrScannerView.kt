package com.inetconnector.compumesh.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.OptIn
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import com.inetconnector.compumesh.R
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.compose.ui.platform.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.inetconnector.compumesh.ui.theme.*
import java.util.concurrent.Executors

data class QrPairResult(
    val ownerKey: String,
    val gatewayUrl: String,
    val enrollmentToken: String = ""
)

/**
 * Only the authenticated fleet portal's one-time QR link is a pairing
 * credential. A raw Owner Key, JSON blob, IP address or foreign URL is not.
 */
@Suppress("UNUSED_PARAMETER")
fun parseQrPayload(raw: String, fallbackGateway: String = EnrollmentLinkPolicy.TRUSTED_GATEWAY): QrPairResult {
    return QrPairResult(
        ownerKey = "",
        gatewayUrl = EnrollmentLinkPolicy.TRUSTED_GATEWAY,
        enrollmentToken = EnrollmentLinkPolicy.tokenFromQr(raw).orEmpty()
    )
}

@Composable
fun QrCameraScannerDialog(
    currentGateway: String,
    onCodeScanned: (QrPairResult) -> Unit,
    onDismiss: () -> Unit
) {
    val context = LocalContext.current
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        hasCameraPermission = isGranted
        if (!isGranted) {
            Toast.makeText(context, "Kamera-Berechtigung erforderlich zum Scannen von QR-Codes", Toast.LENGTH_LONG).show()
        }
    }

    LaunchedEffect(Unit) {
        if (!hasCameraPermission) {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            dismissOnBackPress = true,
            dismissOnClickOutside = false
        )
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black)
        ) {
            if (hasCameraPermission) {
                CameraPreviewWithScanner(
                    onBarcodeFound = { rawValue ->
                        val result = parseQrPayload(rawValue)
                        if (result.enrollmentToken.isBlank()) {
                            Toast.makeText(context, "Nur gültige ComputeMesh QR-Pairing-Codes zulässig", Toast.LENGTH_SHORT).show()
                            false
                        } else {
                            onCodeScanned(result)
                            true
                        }
                    },
                    onClose = onDismiss
                )
            } else {
                // Permission Denied / Fallback View
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(32.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center
                ) {
                    Icon(
                        imageVector = Icons.Default.CameraAlt,
                        contentDescription = null,
                        tint = AmberWarning,
                        modifier = Modifier.size(64.dp)
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Text(
                        "Kamera-Zugriff benötigt",
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 20.sp,
                        textAlign = TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        "Um den Flotten-QR-Code vom PC-Bildschirm zu scannen, erlaube bitte den Kamera-Zugriff.",
                        color = TextSecondary,
                        fontSize = 14.sp,
                        textAlign = TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(24.dp))
                    Button(
                        onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                        colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                        shape = RoundedCornerShape(12.dp)
                    ) {
                        Text("Berechtigung anfordern", color = DeepVoidBg, fontWeight = FontWeight.Bold)
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    TextButton(onClick = onDismiss) {
                        Text("Schließen", color = TextSecondary)
                    }
                }
            }


        }
    }
}

@OptIn(ExperimentalGetImage::class)
@Composable
private fun CameraPreviewWithScanner(
    onBarcodeFound: (String) -> Boolean,
    onClose: () -> Unit
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var isTorchOn by remember { mutableStateOf(false) }
    var cameraControl by remember { mutableStateOf<CameraControl?>(null) }
    var hasScanned by remember { mutableStateOf(false) }

    val cameraExecutor = remember { Executors.newSingleThreadExecutor() }

    DisposableEffect(Unit) {
        onDispose {
            cameraExecutor.shutdown()
        }
    }

    // Laser Animation line
    val infiniteTransition = rememberInfiniteTransition(label = "laser")
    val laserProgress by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2000, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "laser_y"
    )

    Box(modifier = Modifier.fillMaxSize()) {
        // Camera Preview
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                val previewView = PreviewView(ctx).apply {
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT
                    )
                    scaleType = PreviewView.ScaleType.FILL_CENTER
                }

                val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
                cameraProviderFuture.addListener({
                    val cameraProvider = cameraProviderFuture.get()
                    val preview = Preview.Builder().build().also {
                        it.setSurfaceProvider(previewView.surfaceProvider)
                    }

                    val barcodeScanner = BarcodeScanning.getClient(
                        BarcodeScannerOptions.Builder()
                            .setBarcodeFormats(Barcode.FORMAT_QR_CODE, Barcode.FORMAT_ALL_FORMATS)
                            .build()
                    )

                    val imageAnalysis = ImageAnalysis.Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()

                    imageAnalysis.setAnalyzer(cameraExecutor) { imageProxy ->
                        val mediaImage = imageProxy.image
                        if (mediaImage != null && !hasScanned) {
                            val inputImage = InputImage.fromMediaImage(
                                mediaImage,
                                imageProxy.imageInfo.rotationDegrees
                            )
                            barcodeScanner.process(inputImage)
                                .addOnSuccessListener { barcodes ->
                                    for (barcode in barcodes) {
                                        val raw = barcode.rawValue ?: barcode.displayValue
                                        if (!raw.isNullOrBlank() && !hasScanned) {
                                            hasScanned = true
                                            previewView.post {
                                                if (!onBarcodeFound(raw)) {
                                                    hasScanned = false
                                                }
                                            }
                                            break
                                        }
                                    }
                                }
                                .addOnCompleteListener {
                                    imageProxy.close()
                                }
                        } else {
                            imageProxy.close()
                        }
                    }

                    val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA

                    try {
                        cameraProvider.unbindAll()
                        val camera = cameraProvider.bindToLifecycle(
                            lifecycleOwner,
                            cameraSelector,
                            preview,
                            imageAnalysis
                        )
                        cameraControl = camera.cameraControl
                    } catch (e: Exception) {
                        android.util.Log.e("QrScanner", "Camera binding failed", e)
                    }
                }, ContextCompat.getMainExecutor(ctx))

                previewView
            }
        )

        // Overlay with scanning frame cutout & laser animation
        ScannerOverlay(laserProgress = laserProgress)

        // Top Navigation Bar (Close & Flashlight)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(
                onClick = onClose,
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .background(Color.Black.copy(alpha = 0.6f))
            ) {
                Icon(Icons.Default.Close, contentDescription = "Schließen", tint = Color.White)
            }

            Text(
                "QR-Code scannen",
                color = Color.White,
                fontWeight = FontWeight.Bold,
                fontSize = 17.sp
            )

            IconButton(
                onClick = {
                    isTorchOn = !isTorchOn
                    cameraControl?.enableTorch(isTorchOn)
                },
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .background(if (isTorchOn) CyanAccent.copy(alpha = 0.3f) else Color.Black.copy(alpha = 0.6f))
            ) {
                Icon(
                    imageVector = if (isTorchOn) Icons.Default.FlashOn else Icons.Default.FlashOff,
                    contentDescription = "Taschenlampe",
                    tint = if (isTorchOn) CyanAccent else Color.White
                )
            }
        }

        // Bottom Hints & Manual Button
        Column(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .navigationBarsPadding()
                .padding(bottom = 32.dp, start = 24.dp, end = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = Color.Black.copy(alpha = 0.75f),
                border = androidx.compose.foundation.BorderStroke(1.dp, CyanAccent.copy(alpha = 0.4f))
            ) {
                Text(
                    text = "Halte den QR-Code aus dem ComputeMesh Cockpit in den Rahmen",
                    color = Color.White,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp)
                )
            }

        }
    }
}

@Composable
private fun ScannerOverlay(laserProgress: Float) {
    Canvas(modifier = Modifier.fillMaxSize()) {
        val canvasWidth = size.width
        val canvasHeight = size.height

        val boxSize = (canvasWidth * 0.72f).coerceAtMost(320.dp.toPx())
        val left = (canvasWidth - boxSize) / 2f
        val top = (canvasHeight - boxSize) / 2f
        val rect = Rect(left, top, left + boxSize, top + boxSize)

        // Draw translucent dark vignette mask around the cutout
        val backgroundPath = Path().apply {
            addRect(Rect(0f, 0f, canvasWidth, canvasHeight))
        }
        val cutoutPath = Path().apply {
            addRoundRect(RoundRect(rect, CornerRadius(24.dp.toPx(), 24.dp.toPx())))
        }
        val maskPath = Path.combine(
            androidx.compose.ui.graphics.PathOperation.Difference,
            backgroundPath,
            cutoutPath
        )

        drawPath(maskPath, color = Color.Black.copy(alpha = 0.65f))

        // Draw scanner target frame border
        drawRoundRect(
            color = CyanAccent.copy(alpha = 0.8f),
            topLeft = Offset(left, top),
            size = Size(boxSize, boxSize),
            cornerRadius = CornerRadius(24.dp.toPx(), 24.dp.toPx()),
            style = Stroke(width = 3.dp.toPx())
        )

        // Draw animated laser line
        val laserY = top + (boxSize * laserProgress)
        drawLine(
            brush = Brush.horizontalGradient(
                listOf(
                    CyanAccent.copy(alpha = 0f),
                    CyanAccent,
                    Color.White,
                    CyanAccent,
                    CyanAccent.copy(alpha = 0f)
                ),
                startX = left,
                endX = left + boxSize
            ),
            start = Offset(left + 8.dp.toPx(), laserY),
            end = Offset(left + boxSize - 8.dp.toPx(), laserY),
            strokeWidth = 3.dp.toPx()
        )
    }
}

