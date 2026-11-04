package com.inetconnector.compumesh.ui.tabs

import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.inetconnector.compumesh.R
import com.inetconnector.compumesh.ui.QrCameraScannerDialog
import com.inetconnector.compumesh.ui.parseQrPayload
import com.inetconnector.compumesh.ui.theme.*

@Composable
fun SetupTab(
    currentOwnerKey: String,
    currentGatewayUrl: String,
    onSaveFleetConfig: (String, String) -> Unit,
    onScanMobileQr: (String) -> Unit,
    mobilePaired: Boolean
) {
    var gatewayUrlInput by remember(currentGatewayUrl) { mutableStateOf(currentGatewayUrl) }
    var directTrafficOnly by remember { mutableStateOf(true) }
    var showAdvancedSettings by remember { mutableStateOf(false) }
    var showQrCameraScanner by remember { mutableStateOf(false) }
    val context = LocalContext.current

    val cleanActiveGateway = currentGatewayUrl.trim().trimEnd('/')
    val isLanConnected = cleanActiveGateway.isNotBlank() && cleanActiveGateway != "https://mesh.inetconnector.com"
    val isFleetBound = mobilePaired
    val isCoupled = isFleetBound

    val pairingBadgeText = if (isFleetBound) "✓ QR-Anmeldung gespeichert" else "Nicht verbunden"
    val pairingStatusSubtitle = if (isFleetBound)
        "QR-Kopplung gespeichert. Online erst nach vom Server bestätigtem Heartbeat."
    else "Öffne auf deinem PC 'Meine Rechner → Handy hinzufügen'. Scanne den QR-Code mit dieser App."

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            Text("Handy verbinden", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Text(
                "Einmal QR-Code auf der ComputeMesh-Webseite scannen. Keine Schlüssel, keine Codes eintippen.",
                color = TextSecondary,
                fontSize = 13.sp
            )
        }

        item {
            // 1-Click QR Pairing Hero Card
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(
                    1.dp,
                    if (isCoupled) EmeraldSuccess.copy(alpha = 0.6f) else CyanAccent.copy(alpha = 0.5f)
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(18.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                Icons.Default.QrCodeScanner,
                                contentDescription = null,
                                tint = if (isCoupled) EmeraldSuccess else CyanAccent,
                                modifier = Modifier.size(24.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("Handy mit QR koppeln", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                        }
                        Surface(
                            shape = RoundedCornerShape(10.dp),
                            color = if (isCoupled) EmeraldSuccess.copy(alpha = 0.15f) else AmberWarning.copy(alpha = 0.15f)
                        ) {
                            Text(
                                text = pairingBadgeText,
                                color = if (isCoupled) EmeraldSuccess else AmberWarning,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))
                    Text(
                        pairingStatusSubtitle,
                        color = TextSecondary,
                        fontSize = 12.sp,
                        lineHeight = 17.sp
                    )

                    Spacer(modifier = Modifier.height(14.dp))

                    Button(
                        onClick = {
                            showQrCameraScanner = true
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) {
                        Icon(Icons.Default.QrCodeScanner, contentDescription = null, tint = DeepVoidBg)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("📷 QR-Code scannen", color = DeepVoidBg, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                    }
                }
            }
        }

        item {
            TextButton(onClick = { showAdvancedSettings = !showAdvancedSettings }) {
                Text(if (showAdvancedSettings) "Technische Einstellungen schließen" else "Weitere technische Einstellungen", color = TextSecondary)
            }
        }
        if (showAdvancedSettings) {
        // No manual Owner-Key enrollment. QR is the only mobile fleet path.
        item {
            OutlinedTextField(
                value = gatewayUrlInput,
                onValueChange = { input ->
                    gatewayUrlInput = input
                    onSaveFleetConfig("", input)
                },
                label = { Text("Control-Plane Gateway / Inferenz-Endpunkt") },
                placeholder = { Text("https://mesh.inetconnector.com oder http://192.168.1.x:8080") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedBorderColor = if (isLanConnected) EmeraldSuccess else CyanAccent,
                    unfocusedBorderColor = CardSurfaceBorder,
                    focusedContainerColor = CardSurface,
                    unfocusedContainerColor = CardSurface
                ),
                trailingIcon = {
                    if (gatewayUrlInput != "https://mesh.inetconnector.com" && gatewayUrlInput.isNotBlank()) {
                        IconButton(onClick = {
                            gatewayUrlInput = "https://mesh.inetconnector.com"
                            onSaveFleetConfig("", "https://mesh.inetconnector.com")
                            Toast.makeText(context, "Auf Standard Cloud-Gateway zurückgesetzt", Toast.LENGTH_SHORT).show()
                        }) {
                            Icon(Icons.Default.Refresh, contentDescription = "Reset", tint = AmberWarning)
                        }
                    }
                },
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth()
            )
        }

        item {
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Strict Privacy Mode", color = TextPrimary, fontWeight = FontWeight.SemiBold)
                        Text("Blockiert jeglichen externen Traffic für Prompts/Tokens", color = TextSecondary, fontSize = 11.sp)
                    }
                    Switch(
                        checked = directTrafficOnly,
                        onCheckedChange = { directTrafficOnly = it },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = CyanAccent,
                            checkedTrackColor = CyanAccent.copy(alpha = 0.3f)
                        )
                    )
                }
            }
        }
        } // advanced settings
    }

    if (showQrCameraScanner) {
        QrCameraScannerDialog(
            currentGateway = gatewayUrlInput,
            onCodeScanned = { result ->
                showQrCameraScanner = false
                if (result.invitation.isNotBlank()) {
                    onScanMobileQr(result.invitation)
                } else {
                    Toast.makeText(context, "Bitte nur den neuen QR-Code aus 'Handy hinzufügen' scannen.", Toast.LENGTH_LONG).show()
                }
            },
            onDismiss = {
                showQrCameraScanner = false
            }
        )
    }
}