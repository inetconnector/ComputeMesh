package com.inetconnector.compumesh.ui.tabs

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.inetconnector.compumesh.guard.BatteryGuardStatus
import com.inetconnector.compumesh.service.MeshNodeService
import com.inetconnector.compumesh.ui.theme.*

@Composable
fun EdgeNodeTab(
    guardStatus: BatteryGuardStatus,
    onStartNode: () -> Unit,
    onStopNode: () -> Unit
) {
    var nodeActive by remember { mutableStateOf(MeshNodeService.isRunning) }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            // Hero Earnings & Token Counter
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(20.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("Berechnete Tokens", color = TextSecondary, fontSize = 13.sp, fontWeight = FontWeight.Medium)
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = CyanAccent.copy(alpha = 0.15f)
                        ) {
                            Text(
                                "Snapdragon 8 ARM64",
                                color = CyanAccent,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        "${MeshNodeService.totalTokensProcessed}",
                        color = CyanAccent,
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 38.sp,
                        fontFamily = FontFamily.Monospace
                    )

                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        "Verdienst: ${MeshNodeService.totalTokensProcessed} CM Credits",
                        color = EmeraldSuccess,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }
            }
        }

        item {
            // Battery & Health Status Guard
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = CardSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CardSurfaceBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Hardware & Akku-Wächter", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 16.sp)

                    HorizontalDivider(color = CardSurfaceBorder, thickness = 1.dp)

                    StatusRow(
                        label = "Akkuladung",
                        value = "${guardStatus.batteryPct}%",
                        statusGood = guardStatus.batteryPct >= 80 || guardStatus.isCharging
                    )
                    StatusRow(
                        label = "Ladekabel",
                        value = if (guardStatus.isCharging) "🔌 AC Ladegerät verbunden" else "🔋 Batteriebetrieb",
                        statusGood = guardStatus.isCharging
                    )
                    StatusRow(
                        label = "Temperatur",
                        value = "${guardStatus.temperatureCelsius} °C (Max 42.0 °C)",
                        statusGood = guardStatus.temperatureCelsius < 42.0f
                    )
                    StatusRow(
                        label = "WLAN-Verbindung",
                        value = if (guardStatus.isWifiConnected) "📶 Heim-WLAN verbunden" else "❌ Kein WLAN",
                        statusGood = guardStatus.isWifiConnected
                    )
                }
            }
        }

        item {
            // Action Button
            Button(
                onClick = {
                    if (nodeActive) {
                        onStopNode()
                        nodeActive = false
                    } else {
                        onStartNode()
                        nodeActive = true
                    }
                },
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (nodeActive) RoseDanger else CyanAccent
                ),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp)
            ) {
                Icon(
                    if (nodeActive) Icons.Default.Stop else Icons.Default.PlayArrow,
                    contentDescription = null,
                    tint = if (nodeActive) Color.White else DeepVoidBg
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = if (nodeActive) "Node Dienst stoppen" else "ComputeMesh Node starten",
                    color = if (nodeActive) Color.White else DeepVoidBg,
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp
                )
            }
        }
    }
}

@Composable
fun StatusRow(label: String, value: String, statusGood: Boolean) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label, color = TextSecondary, fontSize = 13.sp)
        Text(
            value,
            color = if (statusGood) TextPrimary else AmberWarning,
            fontWeight = FontWeight.SemiBold,
            fontSize = 13.sp
        )
    }
}
