/* Wine maps an XWayland image/png selection to the registered PNG clipboard
   format, while Spark's Chromium paste path needs CF_DIB. Add a 32-bit DIB
   only when PNG is the sole clipboard format: EmptyClipboard would otherwise
   discard text, HTML, or other formats from the original copy operation. */
#include <windows.h>
#include <objidl.h>
#include <gdiplus.h>
#include <stdint.h>
#include <string.h>

static int convert_once(void)
{
    const UINT png_format = RegisterClipboardFormatW(L"PNG");
    HGLOBAL source, png_copy = NULL, dib = NULL;
    IStream *stream = NULL;
    GpBitmap *bitmap = NULL;
    BitmapData bits = {0};
    Rect rect = {0};
    UINT width = 0, height = 0;
    SIZE_T png_size, image_size, dib_size;
    BYTE *read_ptr, *write_ptr;
    UINT format = 0, format_count = 0;
    int result = 0;

    if (!IsClipboardFormatAvailable(png_format) || IsClipboardFormatAvailable(CF_DIB))
        return 0;
    if (!OpenClipboard(GetDesktopWindow())) return 1;
    while ((format = EnumClipboardFormats(format)) != 0) ++format_count;
    /* EmptyClipboard would discard every other format, so only convert a
       clipboard that offers PNG alone. */
    if (format_count != 1) goto done;
    source = GetClipboardData(png_format);
    if (!source || !(png_size = GlobalSize(source)) || png_size > 64 * 1024 * 1024) goto done;
    png_copy = GlobalAlloc(GMEM_MOVEABLE, png_size);
    if (!png_copy) goto done;
    read_ptr = GlobalLock(source);
    write_ptr = GlobalLock(png_copy);
    if (!read_ptr || !write_ptr) {
        if (write_ptr) GlobalUnlock(png_copy);
        if (read_ptr) GlobalUnlock(source);
        goto done;
    }
    memcpy(write_ptr, read_ptr, png_size);
    GlobalUnlock(png_copy);
    GlobalUnlock(source);

    if (CreateStreamOnHGlobal(png_copy, FALSE, &stream) != S_OK) goto done;
    if (GdipCreateBitmapFromStream(stream, &bitmap) != Ok) goto done;
    if (GdipGetImageWidth((GpImage *)bitmap, &width) != Ok ||
        GdipGetImageHeight((GpImage *)bitmap, &height) != Ok ||
        !width || !height || width > 8192 || height > 8192) goto done;
    image_size = (SIZE_T)width * height * 4;
    dib_size = sizeof(BITMAPINFOHEADER) + image_size;
    if (image_size > 128 * 1024 * 1024) goto done;
    dib = GlobalAlloc(GMEM_MOVEABLE, dib_size);
    if (!dib) goto done;
    write_ptr = GlobalLock(dib);
    if (!write_ptr) goto done;
    BITMAPINFOHEADER *header = (BITMAPINFOHEADER *)write_ptr;
    memset(header, 0, sizeof(*header));
    header->biSize = sizeof(*header);
    header->biWidth = width;
    header->biHeight = height;
    header->biPlanes = 1;
    header->biBitCount = 32;
    header->biCompression = BI_RGB;
    header->biSizeImage = image_size;
    rect.Width = width;
    rect.Height = height;
    if (GdipBitmapLockBits(bitmap, &rect, ImageLockModeRead,
                           PixelFormat32bppARGB, &bits) != Ok) {
        GlobalUnlock(dib);
        goto done;
    }
    for (UINT y = 0; y < height; ++y) {
        const BYTE *row = (const BYTE *)bits.Scan0 + (ptrdiff_t)y * bits.Stride;
        memcpy(write_ptr + sizeof(*header) + (SIZE_T)(height - 1 - y) * width * 4,
               row, (SIZE_T)width * 4);
    }
    GdipBitmapUnlockBits(bitmap, &bits);
    GlobalUnlock(dib);
    GdipDisposeImage((GpImage *)bitmap);
    bitmap = NULL;
    stream->lpVtbl->Release(stream);
    stream = NULL;

    /* Decode and allocate everything before taking ownership of clipboard
       data. The host still owns the original selection until this point. */
    if (!EmptyClipboard()) goto done;
    if (SetClipboardData(png_format, png_copy)) png_copy = NULL;
    if (SetClipboardData(CF_DIB, dib)) dib = NULL;
    if (!png_copy && !dib) result = 2;

done:
    if (bitmap) GdipDisposeImage((GpImage *)bitmap);
    if (stream) stream->lpVtbl->Release(stream);
    if (png_copy) GlobalFree(png_copy);
    if (dib) GlobalFree(dib);
    CloseClipboard();
    return result;
}

int main(void)
{
    ULONG_PTR token;
    struct GdiplusStartupInput input = {1, NULL, FALSE, FALSE};
    if (GdiplusStartup(&token, &input, NULL) != Ok) return 1;
    int result = convert_once();
    GdiplusShutdown(token);
    return result;
}
