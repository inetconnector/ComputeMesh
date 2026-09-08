package com.computemesh.ui

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.computemesh.engine.MiniCpmEngine
import com.computemesh.guard.BatteryPolicyGuard
import com.computemesh.service.MeshNodeService
import kotlinx.coroutines.launch

// Custom Dark Mesh Theme Palette
val BgDark = Color(0xFF0B0F17)
val CardDark = Color(0xFF131B2A)
val AccentCyan = Color(0xFF38BDF8)
val AccentIndigo = Color(0xFF818CF8)
val EmeraldGreen = Color(0xFF10B981)
val AmberOrange = Color(0xFFF59E0B)

data class ChatMessage(val role: String, val content: String)

class MainActivity : ComponentActivity() {

    private lateinit var batteryGuard: BatteryPolicyGuard
    private lateinit var engine: MiniCpmEngine

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        batteryGuard = BatteryPolicyGuard(this)
        engine = MiniCpmEngine.getInstance(this)

        setContent {
            ComputeMeshApp(
                guard = batteryGuard,
                engine = engine,
                onStartNode = { startNodeService() },
                onStopNode = { stopNodeService() }
            )
        }
    }

    private fun startNodeService() {
        val intent = Intent(this, MeshNodeService::class.java).apply {
            action = MeshNodeService.ACTION_START
        }
        startForegroundService(intent)
    }

    private fun stopNodeService() {
        val intent = Intent(this, MeshNodeService::class.java).apply {
            action = MeshNodeService.ACTION_STOP
        }
        startService(intent)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ComputeMeshApp(
    guard: BatteryPolicyGuard,
    engine: MiniCpmEngine,
    onStartNode: () -> Unit,
    onStopNode: () -> Unit
) {
    var selectedTab by remember { mutableStateOf(0) }
    var guardStatus by remember { mutableStateOf(guard.getStatus()) }
    val scope = rememberCoroutineScope()

    Scaffold(
        containerColor = BgDark,
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "Compute",
                            fontWeight = FontWeight.Bold,
                            color = Color.White,
                            fontSize = 20.sp
                        )
                        Text(
                            "Mesh",
                            fontWeight = FontWeight.Bold,
                            color = AccentCyan,
                            fontSize = 20.sp
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Surface(
                            shape = RoundedCornerShape(12.dp),
                            color = if (guardStatus.isComputePermitted) EmeraldGreen.copy(alpha = 0.2f) else AmberOrange.copy(alpha = 0.2f)
                        ) {
                            Text(
                                text = if (guardStatus.isComputePermitted) "🟢 Aktiv" else "🟡 Standby",
                                color = if (guardStatus.isComputePermitted) EmeraldGreen else AmberOrange,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                            )
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = BgDark)
            )
        },
        bottomBar = {
            NavigationBar(containerColor = CardDark) {
                NavigationBarItem(
                    icon = { Icon(Icons.Default.Chat, contentDescription = "Chat") },
                    label = { Text("MiniCPM KI") },
                    selected = selectedTab == 0,
                    onClick = { selectedTab = 0 },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = AccentCyan,
                        selectedTextColor = AccentCyan,
                        indicatorColor = AccentCyan.copy(alpha = 0.15f)
                    )
                )
                NavigationBarItem(
                    icon = { Icon(Icons.Default.Memory, contentDescription = "Node") },
                    label = { Text("Edge Node") },
                    selected = selectedTab == 1,
                    onClick = {
                        guardStatus = guard.getStatus()
                        selectedTab = 1
                    },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = AccentCyan,
                        selectedTextColor = AccentCyan,
                        indicatorColor = AccentCyan.copy(alpha = 0.15f)
                    )
                )
                NavigationBarItem(
                    icon = { Icon(Icons.Default.Settings, contentDescription = "Settings") },
                    label = { Text("Setup") },
                    selected = selectedTab == 2,
                    onClick = { selectedTab = 2 },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = AccentCyan,
                        selectedTextColor = AccentCyan,
                        indicatorColor = AccentCyan.copy(alpha = 0.15f)
                    )
                )
            }
        }
    ) { padding ->
        Box(modifier = Modifier.padding(padding)) {
            when (selectedTab) {
                0 -> ChatScreen(engine)
                1 -> NodeScreen(guardStatus, onStartNode, onStopNode)
                2 -> SettingsScreen()
            }
        }
    }
}

@Composable
fun ChatScreen(engine: MiniCpmEngine) {
    var inputMessage by remember { mutableStateOf("") }
    val messages = remember {
        mutableStateListOf(
            ChatMessage("assistant", "Hallo! Ich bin dein lokaler On-Device KI-Assistent mit MiniCPM5-2B. Wie kann ich dir helfen?")
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            items(messages) { msg ->
                val isUser = msg.role == "user"
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start
                ) {
                    Surface(
                        shape = RoundedCornerShape(14.dp),
                        color = if (isUser) AccentIndigo.copy(alpha = 0.25f) else CardDark,
                        border = androidx.compose.foundation.BorderStroke(
                            1.dp,
                            if (isUser) AccentIndigo.copy(alpha = 0.5f) else Color.White.copy(alpha = 0.1f)
                        ),
                        modifier = Modifier.widthIn(max = 300.dp)
                    ) {
                        Text(
                            text = msg.content,
                            color = Color.White,
                            modifier = Modifier.padding(12.dp),
                            fontSize = 14.sp
                        )
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(10.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedTextField(
                value = inputMessage,
                onValueChange = { inputMessage = it },
                placeholder = { Text("Nachricht eingeben...", color = Color.Gray) },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = Color.White,
                    unfocusedTextColor = Color.White,
                    focusedBorderColor = AccentCyan,
                    unfocusedBorderColor = Color.White.copy(alpha = 0.2f),
                    focusedContainerColor = CardDark,
                    unfocusedContainerColor = CardDark
                ),
                shape = RoundedCornerShape(20.dp),
                modifier = Modifier.weight(1f)
            )
            Spacer(modifier = Modifier.width(8.dp))
            IconButton(
                onClick = {
                    if (inputMessage.isNotBlank()) {
                        val userText = inputMessage
                        messages.add(ChatMessage("user", userText))
                        inputMessage = ""
                        messages.add(ChatMessage("assistant", "MiniCPM5-2B antwortet direkt auf deinem Gerät."))
                    }
                },
                colors = IconButtonDefaults.iconButtonColors(containerColor = AccentCyan)
            ) {
                Icon(Icons.Default.Send, contentDescription = "Send", tint = Color.Black)
            }
        }
    }
}

@Composable
fun NodeScreen(
    guardStatus: com.computemesh.guard.BatteryGuardStatus,
    onStartNode: () -> Unit,
    onStopNode: () -> Unit
) {
    var nodeActive by remember { mutableStateOf(MeshNodeService.isRunning) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Telemetry Overview Card
        Card(
            colors = CardDefaults.cardColors(containerColor = CardDark),
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("Device & Battery Status", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                Spacer(modifier = Modifier.height(12.dp))

                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Akkustand:", color = Color.Gray, fontSize = 14.sp)
                    Text("${guardStatus.batteryPct}%", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                }
                Spacer(modifier = Modifier.height(6.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Ladekabel:", color = Color.Gray, fontSize = 14.sp)
                    Text(if (guardStatus.isCharging) "🔌 Angeschlossen" else "🔋 Akkubetrieb", color = Color.White, fontSize = 14.sp)
                }
                Spacer(modifier = Modifier.height(6.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Temperatur:", color = Color.Gray, fontSize = 14.sp)
                    Text("${guardStatus.temperatureCelsius} °C", color = Color.White, fontSize = 14.sp)
                }
                Spacer(modifier = Modifier.height(6.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("WLAN:", color = Color.Gray, fontSize = 14.sp)
                    Text(if (guardStatus.isWifiConnected) "📶 Verbunden" else "❌ Kein WLAN", color = Color.White, fontSize = 14.sp)
                }
            }
        }

        // Token Counter Card
        Card(
            colors = CardDefaults.cardColors(containerColor = CardDark),
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("Tokens Berechnet", color = Color.Gray, fontSize = 13.sp)
                Text(
                    "${MeshNodeService.totalTokensProcessed}",
                    color = AccentCyan,
                    fontWeight = FontWeight.Bold,
                    fontSize = 32.sp,
                    fontFamily = FontFamily.Monospace
                )
                Text("Verdiente Credits: ${MeshNodeService.totalTokensProcessed} CM", color = EmeraldGreen, fontSize = 13.sp)
            }
        }

        // Node Toggle Button
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
                containerColor = if (nodeActive) Color.Red.copy(alpha = 0.8f) else AccentCyan
            ),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().height(48.dp)
        ) {
            Text(
                text = if (nodeActive) "Node Dienst stoppen" else "Edge Node Dienst starten",
                color = if (nodeActive) Color.White else Color.Black,
                fontWeight = FontWeight.Bold
            )
        }
    }
}

@Composable
fun SettingsScreen() {
    var ownerKeyInput by remember { mutableStateOf(MeshNodeService.ownerKey) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Text("Flotten-Kopplung", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        Text(
            "Trage deinen Owner Key ein, um dieses Smartphone mit deinem ComputeMesh Cockpit zu verbinden.",
            color = Color.Gray,
            fontSize = 13.sp
        )

        OutlinedTextField(
            value = ownerKeyInput,
            onValueChange = {
                ownerKeyInput = it
                MeshNodeService.ownerKey = it
            },
            label = { Text("Owner Key / Flotten-Secret") },
            colors = OutlinedTextFieldDefaults.colors(
                focusedTextColor = Color.White,
                unfocusedTextColor = Color.White,
                focusedBorderColor = AccentCyan,
                unfocusedBorderColor = Color.White.copy(alpha = 0.2f),
                focusedContainerColor = CardDark,
                unfocusedContainerColor = CardDark
            ),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth()
        )
    }
}
