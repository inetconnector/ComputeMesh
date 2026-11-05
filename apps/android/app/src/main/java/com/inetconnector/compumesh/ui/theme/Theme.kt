package com.inetconnector.compumesh.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

// Authentic Luxury Dark Theme (exact ChatGPT palette)
val DeepVoidBg = Color(0xFF000000)        // Pure pitch black canvas
val CardSurface = Color(0xFF171717)       // Matte dark graphite for drawers, bars & bottom sheets
val CardSurfaceBorder = Color(0xFF262626) // Ultra-subtle border
val PillSurface = Color(0xFF212121)       // Dark pill capsules & search bar
val BubbleSurface = Color(0xFF2F2F2F)     // User bubble & active segment pill
val CyanAccent = Color(0xFFFFFFFF)        // Pure white primary action / send button
val CyanGlow = Color(0xFF52525B)          // Muted secondary highlight
val IndigoAccent = Color(0xFFD4D4D8)      // Light clean grey
val EmeraldSuccess = Color(0xFF10A37F)    // OpenAI signature emerald for live node status
val AmberWarning = Color(0xFFF59E0B)
val RoseDanger = Color(0xFFEF4444)
val TextPrimary = Color(0xFFECECEC)       // High contrast soft white
val TextSecondary = Color(0xFFA1A1AA)     // Muted grey text
val TextMuted = Color(0xFF71717A)         // Dim grey labels

private val DarkColorScheme = darkColorScheme(
    primary = CyanAccent,
    onPrimary = Color.Black,
    primaryContainer = PillSurface,
    onPrimaryContainer = TextPrimary,
    secondary = IndigoAccent,
    onSecondary = Color.Black,
    tertiary = EmeraldSuccess,
    background = DeepVoidBg,
    onBackground = TextPrimary,
    surface = CardSurface,
    onSurface = TextPrimary,
    surfaceVariant = PillSurface,
    onSurfaceVariant = TextSecondary,
    outline = CardSurfaceBorder
)

@Composable
fun ComputeMeshTheme(
    darkTheme: Boolean = true,
    content: @Composable () -> Unit
) {
    val colorScheme = DarkColorScheme
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = DeepVoidBg.toArgb()
            window.navigationBarColor = DeepVoidBg.toArgb()
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = false
                isAppearanceLightNavigationBars = false
            }
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        content = content
    )
}
