# ComputeMesh Android ProGuard & R8 Optimization Rules

# Keep Native JNI Engine methods
-keepclasseswithmembernames class * {
    native <methods>;
}

-keep class com.inetconnector.compumesh.engine.MiniCpmEngine { *; }
-keep class com.inetconnector.compumesh.guard.BatteryPolicyGuard { *; }
-keep class com.inetconnector.compumesh.service.MeshNodeService { *; }
-keep class com.inetconnector.compumesh.p2p.DirectLanDiscovery { *; }

# Jetpack Compose Rules
-keep class androidx.compose.material3.** { *; }
-keep class androidx.compose.material.icons.** { *; }
-dontwarn androidx.compose.**

# Kotlin Coroutines & Serialization
-keepattributes *Annotation*,InnerClasses,EnclosingMethod
-keepclassmembers class kotlinx.coroutines.** { *; }
-keepclassmembers class * implements kotlinx.serialization.KSerializer {
    public static final ** Companion;
}

# Ktor Network Client & Server Rules
-keep class io.ktor.** { *; }
-dontwarn io.ktor.**
