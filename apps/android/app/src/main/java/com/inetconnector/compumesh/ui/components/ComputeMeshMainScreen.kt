package com.inetconnector.compumesh.ui.components

import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.inetconnector.compumesh.guard.BatteryPolicyGuard
import com.inetconnector.compumesh.p2p.DirectLanDiscovery
import com.inetconnector.compumesh.ui.MainActivity
import com.inetconnector.compumesh.ui.tabs.EdgeNodeTab
import com.inetconnector.compumesh.ui.tabs.LanMeshTab
import com.inetconnector.compumesh.ui.tabs.LocalCodeTab
import com.inetconnector.compumesh.ui.tabs.MiniCpmChatTab
import com.inetconnector.compumesh.ui.tabs.SetupTab
import com.inetconnector.compumesh.ui.theme.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
fun ComputeMeshMainScreen(
    guard: BatteryPolicyGuard,
    lanDiscovery: DirectLanDiscovery,
    chatServerPort: Int = MainActivity.CHAT_SERVER_PORT,
    currentOwnerKey: String,
    currentGatewayUrl: String,
    onStartNode: () -> Unit,
    onStopNode: () -> Unit,
    onSaveFleetConfig: (String, String) -> Unit
) {
    val pagerState = rememberPagerState(initialPage = 0, pageCount = { 5 })
    val coroutineScope = rememberCoroutineScope()
    var guardStatus by remember { mutableStateOf(guard.getStatus()) }
    var showQuickMenu by remember { mutableStateOf(false) }
    val context = LocalContext.current

    // Periodic guard status polling
    LaunchedEffect(Unit) {
        while (true) {
            guardStatus = guard.getStatus()
            delay(5000)
        }
    }

    if (showQuickMenu) {
        ModalBottomSheet(
            onDismissRequest = { showQuickMenu = false },
            containerColor = CardSurface,
            scrimColor = Color.Black.copy(alpha = 0.65f),
            shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
                    .padding(bottom = 32.dp)
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Box(
                        modifier = Modifier
                            .size(36.dp)
                            .clip(RoundedCornerShape(10.dp))
                            .background(Brush.linearGradient(listOf(CyanAccent, IndigoAccent))),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            Icons.Default.Memory,
                            contentDescription = null,
                            tint = Color.Black,
                            modifier = Modifier.size(22.dp)
                        )
                    }
                    Spacer(modifier = Modifier.width(12.dp))
                    Column {
                        Text("ComputeMesh Control", fontWeight = FontWeight.Bold, color = TextPrimary, fontSize = 18.sp)
                        Text("Schnellzugriff & Node-Status", color = TextMuted, fontSize = 12.sp)
                    }
                    Spacer(modifier = Modifier.weight(1f))
                    IconButton(onClick = { showQuickMenu = false }) {
                        Icon(Icons.Default.Close, contentDescription = "Schließen", tint = TextMuted)
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))
                HorizontalDivider(color = CardSurfaceBorder)
                Spacer(modifier = Modifier.height(12.dp))

                // Option 1: Meine Chats & Verlauf
                QuickMenuOption(
                    icon = Icons.Default.Forum,
                    title = "Meine Chats & Verlauf",
                    subtitle = "Öffnet die Chat-Historie & Unterhaltungen",
                    tint = IndigoAccent
                ) {
                    showQuickMenu = false
                    coroutineScope.launch {
                        pagerState.animateScrollToPage(0)
                    }
                    MainActivity.globalWebView?.evaluateJavascript(
                        "if (typeof window.__openSidebar === 'function') { window.__openSidebar(); }",
                        null
                    )
                }

                // Option 2: Neuer Chat
                QuickMenuOption(
                    icon = Icons.Default.ChatBubble,
                    title = "Neuer Chat",
                    subtitle = "Startet eine frische Konversation",
                    tint = CyanAccent
                ) {
                    showQuickMenu = false
                    coroutineScope.launch {
                        pagerState.animateScrollToPage(0)
                    }
                    MainActivity.globalWebView?.evaluateJavascript(
                        """(function() {
                            if (typeof window.__startNewChat === 'function') {
                                return window.__startNewChat();
                            }
                            const ta = document.querySelector('textarea');
                            if (ta) ta.value = '';
                            const newChatBtn = document.querySelector('a[href*="new_chat"], button:has(.lucide-square-pen)');
                            if (newChatBtn) newChatBtn.click();
                            else window.location.href = 'http://127.0.0.1:$chatServerPort/?new_chat=true&lang=de#/';
                        })()""",
                        null
                    )
                }

                // Option 3: Edge Node Tab
                QuickMenuOption(
                    icon = Icons.Default.ElectricBolt,
                    title = "Edge Compute Node",
                    subtitle = if (guardStatus.isComputePermitted) "Status: Bereit / Aktiv" else "Status: Standby (Akku/Temperatur)",
                    tint = if (guardStatus.isComputePermitted) EmeraldSuccess else AmberWarning
                ) {
                    showQuickMenu = false
                    coroutineScope.launch {
                        pagerState.animateScrollToPage(1)
                    }
                }

                // Option 4: LAN Mesh Tab
                QuickMenuOption(
                    icon = Icons.Default.Hub,
                    title = "LAN Mesh Netzwerk",
                    subtitle = "Lokale Peer-Geräte & KI-Knoten",
                    tint = IndigoAccent
                ) {
                    showQuickMenu = false
                    coroutineScope.launch {
                        pagerState.animateScrollToPage(2)
                    }
                }

                // Option 5: Setup & Gateway
                QuickMenuOption(
                    icon = Icons.Default.Settings,
                    title = "Einstellungen & Gateway",
                    subtitle = "Gateway: ${currentGatewayUrl.ifBlank { "Standard" }}",
                    tint = TextPrimary
                ) {
                    showQuickMenu = false
                    coroutineScope.launch {
                        pagerState.animateScrollToPage(3)
                    }
                }

                // Option 6: Reload WebUI
                QuickMenuOption(
                    icon = Icons.Default.Refresh,
                    title = "WebUI neu laden",
                    subtitle = "Aktualisiert die Chat-Oberfläche",
                    tint = TextMuted
                ) {
                    showQuickMenu = false
                    MainActivity.globalWebView?.reload()
                }
            }
        }
    }

    Scaffold(
        containerColor = DeepVoidBg,
        topBar = {
            TopAppBar(
                title = {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier
                                .clip(RoundedCornerShape(10.dp))
                                .clickable {
                                    showQuickMenu = true
                                }
                                .padding(vertical = 4.dp, horizontal = 2.dp)
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(28.dp)
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(Brush.linearGradient(listOf(CyanAccent, IndigoAccent))),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(
                                    Icons.Default.Memory,
                                    contentDescription = "ComputeMesh Menü",
                                    tint = Color.Black,
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                            Spacer(modifier = Modifier.width(10.dp))
                            Text("Compute", fontWeight = FontWeight.ExtraBold, color = TextPrimary, fontSize = 20.sp)
                            Text("Mesh", fontWeight = FontWeight.ExtraBold, color = CyanAccent, fontSize = 20.sp)
                        }
                        Spacer(modifier = Modifier.weight(1f))

                        // Meine Chats / Verlauf Icon Button
                        IconButton(
                            onClick = {
                                coroutineScope.launch {
                                    pagerState.animateScrollToPage(0)
                                }
                                MainActivity.globalWebView?.evaluateJavascript(
                                    "if (typeof window.__toggleSidebar === 'function') { window.__toggleSidebar(); }",
                                    null
                                )
                            },
                            modifier = Modifier.size(36.dp)
                        ) {
                            Icon(
                                Icons.Default.Forum,
                                contentDescription = "Meine Chats & Verlauf",
                                tint = TextPrimary,
                                modifier = Modifier.size(20.dp)
                            )
                        }

                        Spacer(modifier = Modifier.width(2.dp))

                        // Neuer Chat Icon Button
                        IconButton(
                            onClick = {
                                coroutineScope.launch {
                                    pagerState.animateScrollToPage(0)
                                }
                                MainActivity.globalWebView?.evaluateJavascript(
                                    """(function() {
                                        if (typeof window.__startNewChat === 'function') {
                                            return window.__startNewChat();
                                        }
                                        const links = Array.from(document.querySelectorAll('a, button'));
                                        const newChat = links.find(el => (el.getAttribute('href') || '').includes('new_chat') || (el.innerText || '').includes('Neuer Chat'));
                                        if (newChat) newChat.click();
                                        else window.location.hash = '#/';
                                    })()""",
                                    null
                                )
                                Toast.makeText(context, "Neuer Chat gestartet", Toast.LENGTH_SHORT).show()
                            },
                            modifier = Modifier.size(36.dp)
                        ) {
                            Icon(
                                Icons.Default.AddComment,
                                contentDescription = "Neuer Chat",
                                tint = CyanAccent,
                                modifier = Modifier.size(20.dp)
                            )
                        }

                        Spacer(modifier = Modifier.width(6.dp))

                        // Status Chip
                        Surface(
                            shape = RoundedCornerShape(20.dp),
                            color = if (guardStatus.isComputePermitted) EmeraldSuccess.copy(alpha = 0.15f) else AmberWarning.copy(alpha = 0.15f),
                            border = androidx.compose.foundation.BorderStroke(
                                1.dp,
                                if (guardStatus.isComputePermitted) EmeraldSuccess.copy(alpha = 0.4f) else AmberWarning.copy(alpha = 0.4f)
                            ),
                            modifier = Modifier.clickable {
                                coroutineScope.launch {
                                    pagerState.animateScrollToPage(1)
                                }
                            }
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                            ) {
                                Box(
                                    modifier = Modifier
                                        .size(7.dp)
                                        .clip(CircleShape)
                                        .background(if (guardStatus.isComputePermitted) EmeraldSuccess else AmberWarning)
                                )
                                Spacer(modifier = Modifier.width(6.dp))
                                Text(
                                    text = if (guardStatus.isComputePermitted) "Aktiv" else "Standby",
                                    color = if (guardStatus.isComputePermitted) EmeraldSuccess else AmberWarning,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = DeepVoidBg)
            )
        },
        bottomBar = {
            NavigationBar(
                containerColor = CardSurface,
                tonalElevation = 8.dp
            ) {
                val tabs = listOf(
                    Triple(0, "KI Chat", Icons.Default.ChatBubble),
                    Triple(1, "Edge Node", Icons.Default.ElectricBolt),
                    Triple(2, "LAN Mesh", Icons.Default.Hub),
                    Triple(3, "LocalCode", Icons.Default.Code),
                    Triple(4, "Setup", Icons.Default.Settings)
                )

                tabs.forEach { (index, label, icon) ->
                    val isSelected = pagerState.currentPage == index
                    NavigationBarItem(
                        icon = { Icon(icon, contentDescription = label) },
                        label = { Text(label, fontSize = 11.sp, fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal) },
                        selected = isSelected,
                        onClick = {
                            coroutineScope.launch {
                                pagerState.animateScrollToPage(index)
                            }
                        },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = CyanAccent,
                            selectedTextColor = CyanAccent,
                            unselectedIconColor = TextMuted,
                            unselectedTextColor = TextMuted,
                            indicatorColor = CyanAccent.copy(alpha = 0.12f)
                        )
                    )
                }
            }
        }
    ) { padding ->
        HorizontalPager(
            state = pagerState,
            userScrollEnabled = pagerState.currentPage != 0,
            beyondBoundsPageCount = 4,
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) { page ->
            when (page) {
                0 -> MiniCpmChatTab(serverPort = chatServerPort)
                1 -> EdgeNodeTab(guardStatus, onStartNode, onStopNode)
                2 -> LanMeshTab(
                    lanDiscovery = lanDiscovery,
                    currentGatewayUrl = currentGatewayUrl,
                    currentOwnerKey = currentOwnerKey,
                    onSaveFleetConfig = onSaveFleetConfig
                )
                3 -> LocalCodeTab(gatewayUrl = currentGatewayUrl)
                4 -> SetupTab(
                    currentOwnerKey = currentOwnerKey,
                    currentGatewayUrl = currentGatewayUrl,
                    onSaveFleetConfig = onSaveFleetConfig
                )
            }
        }
    }
}

@Composable
fun QuickMenuOption(
    icon: ImageVector,
    title: String,
    subtitle: String,
    tint: Color,
    onClick: () -> Unit
) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(12.dp),
        color = CardSurfaceBorder.copy(alpha = 0.4f),
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 12.dp, horizontal = 14.dp)
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(tint.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    icon,
                    contentDescription = null,
                    tint = tint,
                    modifier = Modifier.size(20.dp)
                )
            }
            Spacer(modifier = Modifier.width(14.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(title, fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 15.sp)
                Text(subtitle, color = TextMuted, fontSize = 12.sp)
            }
        }
    }
}
