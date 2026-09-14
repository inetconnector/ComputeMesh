package com.inetconnector.compumesh.ui.models

import com.inetconnector.compumesh.util.AttachmentInfo

data class ChatMessage(
    val role: String,
    var content: String,
    var speed: String = "",
    val attachment: AttachmentInfo? = null,
    var isStreaming: Boolean = false
)
