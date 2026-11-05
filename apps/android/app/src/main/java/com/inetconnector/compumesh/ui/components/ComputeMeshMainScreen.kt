package com.inetconnector.compumesh.ui.components

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.inetconnector.compumesh.guard.BatteryPolicyGuard
import com.inetconnector.compumesh.p2p.DirectLanDiscovery
import com.inetconnector.compumesh.ui.MainActivity
import com.inetconnector.compumesh.ui.tabs.ChatTab
import com.inetconnector.compumesh.ui.tabs.EdgeNodeTab
import com.inetconnector.compumesh.ui.tabs.LanMeshTab
import com.inetconnector.compumesh.ui.tabs.SetupTab
import com.inetconnector.compumesh.ui.theme.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

enum class MainNavigationScreen {
    CHAT,
    EDGE_NODE,
    LAN_MESH,
    SETUP
}

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
    onSaveFleetConfig: (String, String) -> Unit,
    onScanMobileQr: (String) -> Unit,
    mobilePaired: Boolean
) {
    val coroutineScope = rememberCoroutineScope()
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    var currentScreen by remember { mutableStateOf(if (mobilePaired) MainNavigationScreen.CHAT else MainNavigationScreen.CHAT) }
    var guardStatus by remember { mutableStateOf(guard.getStatus()) }
    val context = LocalContext.current

    // Periodic battery/compute policy polling
    LaunchedEffect(Unit) {
        while (true) {
            guardStatus = guard.getStatus()
            delay(5000)
        }
    }

    // Modal Navigation Drawer (Exact ChatGPT Sidebar Menu Parity: `02_sidebar_menu.png`)
    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = currentScreen == MainNavigationScreen.CHAT,
        drawerContent = {
            ModalDrawerSheet(
                drawerContainerColor = CardSurface,
                drawerShape = RoundedCornerShape(topEnd = 0.dp, bottomEnd = 0.dp),
                modifier = Modifier
                    .width(310.dp)
                    .fillMaxHeight()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .statusBarsPadding()
                        .navigationBarsPadding()
                ) {
                    // Top Row: + Neuer Chat Pill & Search Button
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 10.dp)
                    ) {
                        // + Neuer Chat Button
                        Surface(
                            onClick = {
                                currentScreen = MainNavigationScreen.CHAT
                                coroutineScope.launch { drawerState.close() }
                            },
                            shape = RoundedCornerShape(20.dp),
                            color = PillSurface,
                            modifier = Modifier.weight(1f)
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)
                            ) {
                                Icon(
                                    Icons.Default.Add,
                                    contentDescription = null,
                                    tint = TextPrimary,
                                    modifier = Modifier.size(18.dp)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = "Neuer Chat",
                                    fontWeight = FontWeight.SemiBold,
                                    fontSize = 13.5.sp,
                                    color = TextPrimary
                                )
                            }
                        }

                        Spacer(modifier = Modifier.width(8.dp))

                        // Search Button
                        IconButton(
                            onClick = {
                                // Search filter action
                            },
                            modifier = Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(PillSurface)
                        ) {
                            Icon(
                                Icons.Default.Search,
                                contentDescription = "Suche",
                                tint = TextSecondary,
                                modifier = Modifier.size(20.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(6.dp))

                    // Scrollable Drawer List
                    LazyColumn(
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp)
                    ) {
                        // SECTION: CHATS & HISTORIE
                        item {
                            Text(
                                text = "Angeheftet",
                                color = TextMuted,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(start = 8.dp, top = 8.dp, bottom = 4.dp)
                            )
                        }

                        val recentChats = listOf(
                            "ComputeMesh Cluster Setup",
                            "Security Gate & Test Receipt",
                            "Inferenz Benchmark (qwen2.5)",
                            "P2P LAN Mesh Routing"
                        )

                        items(recentChats) { chatTitle ->
                            DrawerItemRow(
                                icon = Icons.Default.ChatBubbleOutline,
                                title = chatTitle,
                                isSelected = currentScreen == MainNavigationScreen.CHAT && chatTitle.startsWith("ComputeMesh")
                            ) {
                                currentScreen = MainNavigationScreen.CHAT
                                coroutineScope.launch { drawerState.close() }
                            }
                        }

                        // SECTION: AGENT WORKSPACES (PC Node)
                        item {
                            Spacer(modifier = Modifier.height(14.dp))
                            Text(
                                text = "Agent Workspaces (mifcoms)",
                                color = TextMuted,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(start = 8.dp, top = 8.dp, bottom = 4.dp)
                            )
                        }

                        val workspaces = listOf(
                            "ComputeMesh-ControlPlane",
                            "MICA",
                            "NOMA",
                            "Momentum",
                            "SmartXChain"
                        )

                        items(workspaces) { ws ->
                            DrawerItemRow(
                                icon = Icons.Default.Folder,
                                title = ws,
                                isSelected = false
                            ) {
                                currentScreen = MainNavigationScreen.CHAT
                                coroutineScope.launch { drawerState.close() }
                            }
                        }

                        // SECTION: MESH-FLOTTE & HARDWARE
                        item {
                            Spacer(modifier = Modifier.height(14.dp))
                            Text(
                                text = "Hardware & Mesh",
                                color = TextMuted,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(start = 8.dp, top = 8.dp, bottom = 4.dp)
                            )
                        }

                        item {
                            DrawerItemRow(
                                icon = Icons.Default.ElectricBolt,
                                title = "Edge Compute Node",
                                subtitle = if (guardStatus.isComputePermitted) "Status: Aktiv / Bereit" else "Status: Standby",
                                isSelected = currentScreen == MainNavigationScreen.EDGE_NODE,
                                statusColor = if (guardStatus.isComputePermitted) EmeraldSuccess else AmberWarning
                            ) {
                                currentScreen = MainNavigationScreen.EDGE_NODE
                                coroutineScope.launch { drawerState.close() }
                            }
                        }

                        item {
                            DrawerItemRow(
                                icon = Icons.Default.Hub,
                                title = "LAN Mesh Netzwerk",
                                subtitle = "Lokale Peer-Geräte & P2P",
                                isSelected = currentScreen == MainNavigationScreen.LAN_MESH
                            ) {
                                currentScreen = MainNavigationScreen.LAN_MESH
                                coroutineScope.launch { drawerState.close() }
                            }
                        }

                        item {
                            DrawerItemRow(
                                icon = Icons.Default.Settings,
                                title = "Setup & Flotte",
                                subtitle = "Gateway: ${currentGatewayUrl.ifBlank { "Standard" }}",
                                isSelected = currentScreen == MainNavigationScreen.SETUP
                            ) {
                                currentScreen = MainNavigationScreen.SETUP
                                coroutineScope.launch { drawerState.close() }
                            }
                        }
                    }

                    HorizontalDivider(color = CardSurfaceBorder, thickness = 1.dp)

                    // Bottom Row: Profile / Node Status & Settings
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                currentScreen = MainNavigationScreen.SETUP
                                coroutineScope.launch { drawerState.close() }
                            }
                            .padding(horizontal = 14.dp, vertical = 12.dp)
                    ) {
                        Box(
                            modifier = Modifier
                                .size(34.dp)
                                .clip(CircleShape)
                                .background(BubbleSurface),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                Icons.Default.Memory,
                                contentDescription = null,
                                tint = EmeraldSuccess,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Box(
                                    modifier = Modifier
                                        .size(6.dp)
                                        .clip(CircleShape)
                                        .background(EmeraldSuccess)
                                )
                                Spacer(modifier = Modifier.width(6.dp))
                                Text(
                                    text = "cm-win-mifcom-rtx3080",
                                    fontWeight = FontWeight.SemiBold,
                                    fontSize = 12.5.sp,
                                    color = TextPrimary
                                )
                            }
                            Text(
                                text = "RTX 3080 10GB • Bereit",
                                fontSize = 11.sp,
                                color = TextMuted
                            )
                        }
                        IconButton(
                            onClick = {
                                currentScreen = MainNavigationScreen.SETUP
                                coroutineScope.launch { drawerState.close() }
                            },
                            modifier = Modifier.size(32.dp)
                        ) {
                            Icon(
                                Icons.Default.Settings,
                                contentDescription = "Einstellungen",
                                tint = TextSecondary,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                    }
                }
            }
        }
    ) {
        // Main Screen Viewport based on currentScreen
        when (currentScreen) {
            MainNavigationScreen.CHAT -> {
                ChatTab(
                    gatewayUrl = currentGatewayUrl,
                    ownerKey = currentOwnerKey,
                    lanDiscovery = lanDiscovery,
                    onOpenDrawer = { coroutineScope.launch { drawerState.open() } },
                    onOpenLanMesh = { currentScreen = MainNavigationScreen.LAN_MESH },
                    onOpenSetup = { currentScreen = MainNavigationScreen.SETUP }
                )
            }
            MainNavigationScreen.EDGE_NODE -> {
                SubScreenContainer(
                    title = "Edge Compute Node",
                    onBack = { currentScreen = MainNavigationScreen.CHAT }
                ) {
                    EdgeNodeTab(guardStatus, onStartNode, onStopNode)
                }
            }
            MainNavigationScreen.LAN_MESH -> {
                SubScreenContainer(
                    title = "LAN Mesh Netzwerk",
                    onBack = { currentScreen = MainNavigationScreen.CHAT }
                ) {
                    LanMeshTab(
                        lanDiscovery = lanDiscovery,
                        currentGatewayUrl = currentGatewayUrl,
                        currentOwnerKey = currentOwnerKey,
                        onSaveFleetConfig = onSaveFleetConfig
                    )
                }
            }
            MainNavigationScreen.SETUP -> {
                SubScreenContainer(
                    title = "Setup & Flotte",
                    onBack = { currentScreen = MainNavigationScreen.CHAT }
                ) {
                    SetupTab(
                        currentOwnerKey = currentOwnerKey,
                        currentGatewayUrl = currentGatewayUrl,
                        onSaveFleetConfig = onSaveFleetConfig,
                        onScanMobileQr = onScanMobileQr,
                        mobilePaired = mobilePaired
                    )
                }
            }
        }
    }
}

@Composable
fun DrawerItemRow(
    icon: ImageVector,
    title: String,
    subtitle: String? = null,
    isSelected: Boolean = false,
    statusColor: Color? = null,
    onClick: () -> Unit
) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(10.dp),
        color = if (isSelected) BubbleSurface else Color.Transparent,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 9.dp)
        ) {
            Icon(
                icon,
                contentDescription = null,
                tint = if (isSelected) TextPrimary else TextSecondary,
                modifier = Modifier.size(18.dp)
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
                    fontSize = 13.5.sp,
                    color = if (isSelected) TextPrimary else TextSecondary,
                    maxLines = 1
                )
                if (!subtitle.isNullOrBlank()) {
                    Text(
                        text = subtitle,
                        fontSize = 11.sp,
                        color = TextMuted,
                        maxLines = 1
                    )
                }
            }
            if (statusColor != null) {
                Box(
                    modifier = Modifier
                        .size(7.dp)
                        .clip(CircleShape)
                        .background(statusColor)
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SubScreenContainer(
    title: String,
    onBack: () -> Unit,
    content: @Composable () -> Unit
) {
    Scaffold(
        containerColor = DeepVoidBg,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = title,
                        fontSize = 17.sp,
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Zurück zum Chat",
                            tint = TextPrimary
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = CardSurface)
            )
        }
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            content()
        }
    }
}
