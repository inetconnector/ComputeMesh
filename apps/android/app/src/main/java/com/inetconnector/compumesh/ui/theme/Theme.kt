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

val DeepVoidBg = Color(0xFF070B12)
val CardSurface = Color(0xFF0F172A)
val CardSurfaceBorder = Color(0xFF1E293B)
val CyanAccent = Color(0xFF38BDF8)
val CyanGlow = Color(0xFF0284C7)
val IndigoAccent = Color(0xFF818CF8)
val EmeraldSuccess = Color(0xFF10B981)
val AmberWarning = Color(0xFFF59E0B)
val RoseDanger = Color(0xFFF43F5E)
val TextPrimary = Color(0xFFF8FAFC)
val TextSecondary = Color(0xFF94A3B8)
val TextMuted = Color(0xFF64748B)

private val DarkColorScheme = darkColorScheme(
    primary = CyanAccent,
    onPrimary = Color.Black,
    primaryContainer = CardSurface,
    onPrimaryContainer = CyanAccent,
    secondary = IndigoAccent,
    onSecondary = Color.Black,
    tertiary = EmeraldSuccess,
    background = DeepVoidBg,
    onBackground = TextPrimary,
    surface = CardSurface,
    onSurface = TextPrimary,
    surfaceVariant = CardSurfaceBorder,
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
