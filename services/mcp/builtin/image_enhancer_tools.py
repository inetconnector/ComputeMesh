# SPDX-License-Identifier: Apache-2.0
"""Image Enhancement, Cropping, and Visual Inspection Tool Suite for ComputeMesh MCP."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageEnhance, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def enhance_and_crop_image(
    image_path: str,
    output_path: Optional[str] = None,
    crop_box: Optional[List[int]] = None,
    rotate_degrees: Optional[float] = None,
    contrast_factor: Optional[float] = None,
    brightness_factor: Optional[float] = None,
    sharpness_factor: Optional[float] = None,
    grayscale: bool = False,
    auto_contrast: bool = False,
    max_dimension: Optional[int] = None,
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Crops, rotates, enhances contrast/sharpness, or converts image scans for high-precision OCR / visual reading."""
    if not PIL_AVAILABLE:
        return {"error": "Pillow (PIL) ist in der Python-Umgebung nicht verfügbar.", "success": False}
        
    root = os.path.abspath(workspace_root or ".")
    abs_input = os.path.abspath(os.path.join(root, image_path)) if not os.path.isabs(image_path) else image_path
    
    if not os.path.exists(abs_input):
        return {"error": f"Bilddatei '{image_path}' existiert nicht.", "success": False}
        
    try:
        img = Image.open(abs_input)
        orig_width, orig_height = img.size
        orig_format = img.format or "PNG"
        
        # 1. Crop if specified: [left, upper, right, lower]
        if crop_box and len(crop_box) == 4:
            left, upper, right, lower = crop_box
            left = max(0, min(left, orig_width))
            upper = max(0, min(upper, orig_height))
            right = max(left + 1, min(right, orig_width))
            lower = max(upper + 1, min(lower, orig_height))
            img = img.crop((left, upper, right, lower))
            
        # 2. Rotate if specified
        if rotate_degrees:
            img = img.rotate(rotate_degrees, expand=True)
            
        # 3. Grayscale
        if grayscale:
            img = ImageOps.grayscale(img)
            
        # 4. Auto-Contrast
        if auto_contrast:
            if img.mode != "RGB" and img.mode != "L":
                img = img.convert("RGB")
            img = ImageOps.autocontrast(img)
            
        # 5. Contrast Enhancement
        if contrast_factor is not None and contrast_factor > 0:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(float(contrast_factor))
            
        # 6. Brightness Enhancement
        if brightness_factor is not None and brightness_factor > 0:
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(float(brightness_factor))
            
        # 7. Sharpness Enhancement
        if sharpness_factor is not None and sharpness_factor > 0:
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(float(sharpness_factor))
            
        # 8. Max dimension resize (maintaining aspect ratio)
        if max_dimension and max_dimension > 0:
            w, h = img.size
            if max(w, h) > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                
        # Target output path
        if not output_path:
            base, ext = os.path.splitext(abs_input)
            out_file = f"{base}_enhanced.png"
        else:
            out_file = os.path.abspath(os.path.join(root, output_path)) if not os.path.isabs(output_path) else output_path
            
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        save_format = "PNG" if out_file.lower().endswith(".png") else "JPEG"
        if save_format == "JPEG" and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        img.save(out_file, format=save_format, quality=95)
        
        final_w, final_h = img.size
        return {
            "success": True,
            "input_path": os.path.relpath(abs_input, root),
            "output_path": os.path.relpath(out_file, root),
            "original_dimensions": [orig_width, orig_height],
            "final_dimensions": [final_w, final_h],
            "output_size_bytes": os.path.getsize(out_file),
        }
    except Exception as e:
        return {"error": f"Fehler bei der Bildverarbeitung von '{image_path}': {str(e)}", "success": False}


def create_contact_sheet(
    image_paths: List[str],
    output_path: str = "contact_sheet.png",
    columns: int = 3,
    thumb_size: int = 400,
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Combines multiple document images/scans into a structured contact sheet for overview analysis."""
    if not PIL_AVAILABLE:
        return {"error": "Pillow (PIL) ist nicht verfügbar.", "success": False}
        
    root = os.path.abspath(workspace_root or ".")
    valid_images: List[Image.Image] = []
    
    for ip in image_paths:
        abs_p = os.path.abspath(os.path.join(root, ip)) if not os.path.isabs(ip) else ip
        if os.path.exists(abs_p):
            try:
                im = Image.open(abs_p)
                im.thumbnail((thumb_size, thumb_size), Image.Resampling.LANCZOS)
                valid_images.append(im)
            except Exception:
                continue
                
    if not valid_images:
        return {"error": "Keine gültigen Bilddateien gefunden.", "success": False}
        
    cols = max(1, min(10, int(columns)))
    rows = (len(valid_images) + cols - 1) // cols
    
    cell_w = thumb_size + 20
    cell_h = thumb_size + 20
    sheet_w = cols * cell_w + 20
    sheet_h = rows * cell_h + 20
    
    sheet = Image.new("RGB", (sheet_w, sheet_h), color=(15, 23, 42))
    
    for idx, img in enumerate(valid_images):
        c = idx % cols
        r = idx // cols
        x = 20 + c * cell_w + (thumb_size - img.width) // 2
        y = 20 + r * cell_h + (thumb_size - img.height) // 2
        
        if img.mode in ("RGBA", "P"):
            sheet.paste(img.convert("RGB"), (x, y))
        else:
            sheet.paste(img, (x, y))
            
    abs_out = os.path.abspath(os.path.join(root, output_path)) if not os.path.isabs(output_path) else output_path
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    sheet.save(abs_out, format="PNG")
    
    return {
        "success": True,
        "output_path": os.path.relpath(abs_out, root),
        "total_images": len(valid_images),
        "grid": f"{cols}x{rows}",
        "sheet_dimensions": [sheet_w, sheet_h],
    }
