"""Windows' built-in OCR engine (Windows.Media.Ocr): local, and much better than
Tesseract on the game's condensed UI font for words and names."""

import asyncio

import numpy as np
from PIL import Image
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

_engine = None


def _bitmap(img: Image.Image) -> SoftwareBitmap:
    rgba = np.asarray(img.convert("RGBA"))
    bgra = rgba[:, :, [2, 1, 0, 3]].tobytes()
    writer = DataWriter()
    writer.write_bytes(bgra)
    return SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                  img.width, img.height)


def lines(img: Image.Image) -> list[dict]:
    """OCR an image. Returns [{"text", "words": [{"text", "x", "y", "w", "h"}]}] in pixels."""
    global _engine
    _engine = _engine or OcrEngine.try_create_from_user_profile_languages()
    result = asyncio.run(_recognize(_bitmap(img)))
    out = []
    for line in result.lines:
        words = [{"text": w.text, "x": w.bounding_rect.x, "y": w.bounding_rect.y,
                  "w": w.bounding_rect.width, "h": w.bounding_rect.height} for w in line.words]
        out.append({"text": line.text, "words": words})
    return out


async def _recognize(bmp):
    return await _engine.recognize_async(bmp)


def text(img: Image.Image) -> str:
    return " ".join(l["text"] for l in lines(img))
