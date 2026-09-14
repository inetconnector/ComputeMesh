package com.inetconnector.compumesh.util

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import android.util.Log
import androidx.core.content.FileProvider
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.atomic.AtomicInteger

/**
 * High-performance, lightweight image pre-compression utility for camera & photo uploads.
 *
 * Scales high-resolution mobile photos down to optimal vision-model dimensions (e.g. max 1024px)
 * with JPEG 85 compression, corrects EXIF orientation, and returns lightweight FileProvider URIs.
 */
object ImageUploadOptimizer {

    private const val TAG = "ImageUploadOptimizer"
    private const val DEFAULT_MAX_DIMENSION = 1024
    private const val DEFAULT_JPEG_QUALITY = 85
    private val counter = AtomicInteger(0)

    fun optimizeImageUri(
        context: Context,
        sourceUri: Uri,
        maxDimension: Int = DEFAULT_MAX_DIMENSION,
        quality: Int = DEFAULT_JPEG_QUALITY
    ): Uri {
        return try {
            val contentResolver = context.contentResolver
            val mimeType = contentResolver.getType(sourceUri) ?: ""
            val isImage = mimeType.startsWith("image/") || isImageUriPath(sourceUri)

            if (!isImage) {
                return sourceUri
            }

            // 1. Read EXIF orientation before decoding
            val orientation = try {
                contentResolver.openInputStream(sourceUri)?.use { input ->
                    val exif = ExifInterface(input)
                    exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
                } ?: ExifInterface.ORIENTATION_NORMAL
            } catch (_: Throwable) {
                ExifInterface.ORIENTATION_NORMAL
            }

            // 2. Decode image bounds
            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            contentResolver.openInputStream(sourceUri)?.use { input ->
                BitmapFactory.decodeStream(input, null, options)
            }

            val origWidth = options.outWidth
            val origHeight = options.outHeight
            if (origWidth <= 0 || origHeight <= 0) {
                return sourceUri
            }

            // 3. Compute inSampleSize for memory-efficient decoding
            var inSampleSize = 1
            while (origWidth / inSampleSize > maxDimension * 2 || origHeight / inSampleSize > maxDimension * 2) {
                inSampleSize *= 2
            }

            val decodeOptions = BitmapFactory.Options().apply {
                this.inSampleSize = inSampleSize
                inPreferredConfig = Bitmap.Config.ARGB_8888
            }

            val rawBitmap: Bitmap = contentResolver.openInputStream(sourceUri)?.use { input ->
                BitmapFactory.decodeStream(input, null, decodeOptions)
            } ?: return sourceUri

            // 4. Downscale precisely to maxDimension bounding box
            val currentMax = maxOf(rawBitmap.width, rawBitmap.height)
            val scale = if (currentMax > maxDimension) {
                maxDimension.toFloat() / currentMax.toFloat()
            } else {
                1.0f
            }

            val matrix = Matrix()
            if (scale < 1.0f) {
                matrix.postScale(scale, scale)
            }

            // 5. Apply EXIF rotation
            when (orientation) {
                ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
                ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
                ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
                ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
                ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.postScale(1f, -1f)
            }

            val finalBitmap: Bitmap = Bitmap.createBitmap(
                rawBitmap,
                0,
                0,
                rawBitmap.width,
                rawBitmap.height,
                matrix,
                true
            )

            // 6. Save optimized JPEG to application cache directory
            val optFile = File(
                context.cacheDir,
                "opt_upload_${System.currentTimeMillis()}_${counter.incrementAndGet()}.jpg"
            )
            FileOutputStream(optFile).use { outStream ->
                finalBitmap.compress(Bitmap.CompressFormat.JPEG, quality, outStream)
                outStream.flush()
            }

            if (finalBitmap != rawBitmap) {
                try { rawBitmap.recycle() } catch (_: Throwable) {}
            }

            val optUri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                optFile
            )

            Log.i(TAG, "Optimized image from ${origWidth}x${origHeight} to ${finalBitmap.width}x${finalBitmap.height} (${optFile.length() / 1024} KB)")
            optUri
        } catch (e: Throwable) {
            Log.w(TAG, "Image optimization failed for $sourceUri: ${e.message}, using original URI")
            sourceUri
        }
    }

    fun optimizeImageUris(context: Context, uris: List<Uri>): List<Uri> {
        return uris.map { optimizeImageUri(context, it) }
    }

    private fun isImageUriPath(uri: Uri): Boolean {
        val path = uri.path?.lowercase() ?: ""
        return path.endsWith(".jpg") || path.endsWith(".jpeg") ||
                path.endsWith(".png") || path.endsWith(".webp") ||
                path.endsWith(".heic") || path.endsWith(".heif")
    }
}
