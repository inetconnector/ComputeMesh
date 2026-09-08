package com.computemesh.guard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.util.Log

data class BatteryGuardStatus(
    val isCharging: Boolean,
    val batteryPct: Int,
    val temperatureCelsius: Float,
    val isWifiConnected: Boolean,
    val isComputePermitted: Boolean,
    val restrictionReason: String? = null
)

/**
 * Hardware & Battery Protection Guard for Mobile ComputeMesh Nodes.
 *
 * Ensures compute workloads NEVER drain battery, overheat the device, or use mobile data.
 */
class BatteryPolicyGuard(private val context: Context) {

    companion object {
        private const val TAG = "BatteryPolicyGuard"
        const val MAX_ALLOWED_TEMP_CELSIUS = 42.0f
        const val MIN_BATTERY_FOR_UNPLUGGED_COMPUTE = 80
    }

    fun getStatus(allowUnplugged: Boolean = false): BatteryGuardStatus {
        val batteryStatus: Intent? = IntentFilter(Intent.ACTION_BATTERY_CHANGED).let { filter ->
            context.registerReceiver(null, filter)
        }

        val status: Int = batteryStatus?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val isCharging: Boolean = status == BatteryManager.BATTERY_STATUS_CHARGING
                || status == BatteryManager.BATTERY_STATUS_FULL

        val level: Int = batteryStatus?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale: Int = batteryStatus?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val batteryPct: Int = if (level >= 0 && scale > 0) (level * 100 / scale) else 100

        val rawTemp: Int = batteryStatus?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 250) ?: 250
        val tempCelsius: Float = rawTemp / 10.0f

        val isWifi = isConnectedToWifi()

        var permitted = true
        var reason: String? = null

        if (tempCelsius >= MAX_ALLOWED_TEMP_CELSIUS) {
            permitted = false
            reason = "Akkutemperatur zu hoch (${tempCelsius}°C >= ${MAX_ALLOWED_TEMP_CELSIUS}°C)"
        } else if (!isCharging && !allowUnplugged) {
            permitted = false
            reason = "Gerät nicht am Ladekabel"
        } else if (!isCharging && allowUnplugged && batteryPct < MIN_BATTERY_FOR_UNPLUGGED_COMPUTE) {
            permitted = false
            reason = "Akkustand unter ${MIN_BATTERY_FOR_UNPLUGGED_COMPUTE}% ($batteryPct%)"
        } else if (!isWifi) {
            permitted = false
            reason = "Keine WLAN-Verbindung aktiv"
        }

        return BatteryGuardStatus(
            isCharging = isCharging,
            batteryPct = batteryPct,
            temperatureCelsius = tempCelsius,
            isWifiConnected = isWifi,
            isComputePermitted = permitted,
            restrictionReason = reason
        )
    }

    private fun isConnectedToWifi(): Boolean {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return false
        val activeNetwork = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(activeNetwork) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
    }
}

class PowerConnectionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val guard = BatteryPolicyGuard(context)
        val status = guard.getStatus()
        Log.i("PowerReceiver", "Power state changed: isCharging=${status.isCharging}, computePermitted=${status.isComputePermitted}")
    }
}
