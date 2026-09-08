package com.inetconnector.compumesh.util

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import android.util.Base64
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.nio.charset.StandardCharsets

data class AttachmentInfo(
    val uri: Uri,
    val fileName: String,
    val mimeType: String,
    val sizeFormatted: String,
    val textContent: String? = null,
    val base64DataUri: String? = null,
    val thumbnail: Bitmap? = null,
    val isImage: Boolean = false,
    val pageCount: Int = 1
)

object DocumentParser {
    private const val TAG = "DocumentParser"
    private const val MAX_IMAGE_DIMENSION = 1024
    private const val MAX_TEXT_BYTES = 250_000

    suspend fun parseUri(context: Context, uri: Uri): AttachmentInfo? = withContext(Dispatchers.IO) {
        try {
            val contentResolver = context.contentResolver
            var fileName = "document"
            var fileSize = 0L

            contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (cursor.moveToFirst()) {
                    if (nameIndex != -1) fileName = cursor.getString(nameIndex) ?: "document"
                    if (sizeIndex != -1) fileSize = cursor.getLong(sizeIndex)
                }
            }

            val mimeType = contentResolver.getType(uri) ?: getMimeTypeFromExtension(fileName)
            val sizeFormatted = formatFileSize(fileSize)
            val lowerName = fileName.lowercase()

            when {
                // 1. Image processing (JPEG, PNG, WebP)
                mimeType.startsWith("image/") || lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg") ||
                lowerName.endsWith(".png") || lowerName.endsWith(".webp") -> {
                    val bitmap = decodeSampledBitmapFromUri(context, uri, MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION)
                    if (bitmap != null) {
                        val base64 = encodeBitmapToBase64(bitmap)
                        val thumb = Bitmap.createScaledBitmap(bitmap, 96, (96 * bitmap.height / bitmap.width.coerceAtLeast(1)).coerceIn(48, 128), true)
                        return@withContext AttachmentInfo(
                            uri = uri,
                            fileName = fileName,
                            mimeType = mimeType,
                            sizeFormatted = sizeFormatted,
                            base64DataUri = "data:image/jpeg;base64,$base64",
                            thumbnail = thumb,
                            isImage = true
                        )
                    }
                }

                // 2. PDF processing
                mimeType == "application/pdf" || lowerName.endsWith(".pdf") -> {
                    val tempPdf = copyUriToTempFile(context, uri, "temp_doc.pdf")
                    if (tempPdf != null) {
                        val (thumb, pageCount, extractedSnippet) = renderPdfFirstPage(tempPdf)
                        tempPdf.delete()
                        return@withContext AttachmentInfo(
                            uri = uri,
                            fileName = fileName,
                            mimeType = "application/pdf",
                            sizeFormatted = "$sizeFormatted ($pageCount Seiten)",
                            textContent = extractedSnippet,
                            thumbnail = thumb,
                            pageCount = pageCount
                        )
                    }
                }

                // 3. Text and Code files
                isTextOrCodeFile(lowerName, mimeType) -> {
                    val text = readTextFromUri(context, uri, MAX_TEXT_BYTES)
                    return@withContext AttachmentInfo(
                        uri = uri,
                        fileName = fileName,
                        mimeType = mimeType,
                        sizeFormatted = sizeFormatted,
                        textContent = text
                    )
                }

                // 4. Generic binary / other documents
                else -> {
                    val text = readTextFromUri(context, uri, MAX_TEXT_BYTES)
                    return@withContext AttachmentInfo(
                        uri = uri,
                        fileName = fileName,
                        mimeType = mimeType,
                        sizeFormatted = sizeFormatted,
                        textContent = if (text.isNotBlank() && !isBinaryString(text)) text else "[Binärdatei $fileName ($sizeFormatted)]"
                    )
                }
            }
        } catch (e: Throwable) {
            Log.e(TAG, "Failed to parse attachment URI: $uri", e)
        }
        null
    }

    private fun decodeSampledBitmapFromUri(context: Context, uri: Uri, reqWidth: Int, reqHeight: Int): Bitmap? {
        return try {
            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            context.contentResolver.openInputStream(uri)?.use {
                BitmapFactory.decodeStream(it, null, options)
            }

            options.inSampleSize = calculateInSampleSize(options, reqWidth, reqHeight)
            options.inJustDecodeBounds = false

            context.contentResolver.openInputStream(uri)?.use {
                BitmapFactory.decodeStream(it, null, options)
            }
        } catch (e: Throwable) {
            Log.e(TAG, "Bitmap decode error", e)
            null
        }
    }

    private fun calculateInSampleSize(options: BitmapFactory.Options, reqWidth: Int, reqHeight: Int): Int {
        val (height: Int, width: Int) = options.outHeight to options.outWidth
        var inSampleSize = 1
        if (height > reqHeight || width > reqWidth) {
            val halfHeight: Int = height / 2
            val halfWidth: Int = width / 2
            while (halfHeight / inSampleSize >= reqHeight && halfWidth / inSampleSize >= reqWidth) {
                inSampleSize *= 2
            }
        }
        return inSampleSize
    }

    private fun encodeBitmapToBase64(bitmap: Bitmap): String {
        val outputStream = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, 85, outputStream)
        return Base64.encodeToString(outputStream.toByteArray(), Base64.NO_WRAP)
    }

    private fun renderPdfFirstPage(pdfFile: File): Triple<Bitmap?, Int, String> {
        return try {
            val fd = ParcelFileDescriptor.open(pdfFile, ParcelFileDescriptor.MODE_READ_ONLY)
            val renderer = PdfRenderer(fd)
            val pageCount = renderer.pageCount
            var thumb: Bitmap? = null

            if (pageCount > 0) {
                val page = renderer.openPage(0)
                val width = 200
                val height = (width * page.height / page.width.coerceAtLeast(1)).coerceIn(100, 300)
                val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                page.close()
                thumb = bitmap
            }
            renderer.close()
            fd.close()
            Triple(thumb, pageCount, "[PDF Dokument mit $pageCount Seiten]")
        } catch (e: Throwable) {
            Log.e(TAG, "PdfRenderer error", e)
            Triple(null, 1, "[PDF Dokument]")
        }
    }

    private fun readTextFromUri(context: Context, uri: Uri, maxBytes: Int): String {
        return try {
            context.contentResolver.openInputStream(uri)?.use { stream ->
                val buffer = ByteArray(maxBytes)
                val bytesRead = stream.read(buffer)
                if (bytesRead > 0) {
                    String(buffer, 0, bytesRead, StandardCharsets.UTF_8)
                } else ""
            } ?: ""
        } catch (e: Throwable) {
            Log.e(TAG, "Read text error", e)
            ""
        }
    }

    private fun copyUriToTempFile(context: Context, uri: Uri, fileName: String): File? {
        return try {
            val tempFile = File(context.cacheDir, fileName)
            context.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(tempFile).use { output ->
                    input.copyTo(output)
                }
            }
            tempFile
        } catch (e: Throwable) {
            Log.e(TAG, "Copy to temp file error", e)
            null
        }
    }

    private fun isTextOrCodeFile(name: String, mime: String): Boolean {
        if (mime.startsWith("text/")) return true
        val extensions = listOf(
            ".txt", ".csv", ".json", ".md", ".markdown", ".log",
            ".py", ".js", ".ts", ".html", ".css", ".xml", ".yaml", ".yml",
            ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".sql", ".sh", ".bat", ".ps1"
        )
        return extensions.any { name.endsWith(it) }
    }

    private fun isBinaryString(text: String): Boolean {
        val sample = text.take(200)
        val nonPrintable = sample.count { it.code < 32 && it != '\n' && it != '\r' && it != '\t' }
        return nonPrintable > sample.length * 0.15
    }

    private fun getMimeTypeFromExtension(name: String): String {
        val lower = name.lowercase()
        return when {
            lower.endsWith(".pdf") -> "application/pdf"
            lower.endsWith(".jpg") || lower.endsWith(".jpeg") -> "image/jpeg"
            lower.endsWith(".png") -> "image/png"
            lower.endsWith(".webp") -> "image/webp"
            lower.endsWith(".json") -> "application/json"
            lower.endsWith(".csv") -> "text/csv"
            lower.endsWith(".md") -> "text/markdown"
            lower.endsWith(".txt") -> "text/plain"
            else -> "application/octet-stream"
        }
    }

    private fun formatFileSize(bytes: Long): String {
        return when {
            bytes < 1024 -> "$bytes B"
            bytes < 1024 * 1024 -> "${bytes / 1024} KB"
            else -> String.format("%.1f MB", bytes / (1024.0 * 1024.0))
        }
    }
}
