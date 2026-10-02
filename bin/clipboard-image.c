/* Add CF_DIB to an image-only Windows clipboard selection for Spark. Keep the
   original format; never replace text, HTML, or file lists. */
#include <windows.h>
#include <objidl.h>
#include <gdiplus.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

static uint32_t crc32_bytes(const BYTE *data, SIZE_T size)
{
    uint32_t crc = 0xffffffffu;
    for (SIZE_T i = 0; i < size; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320u & -(crc & 1u));
    }
    return ~crc;
}

static HGLOBAL read_png_stdin(void)
{
    const SIZE_T limit = 64 * 1024 * 1024;
    SIZE_T used = 0, capacity = 64 * 1024;
    BYTE *buffer = malloc(capacity);
    HGLOBAL result = NULL;
    if (!buffer) return NULL;
    for (;;) {
        DWORD got = 0;
        if (used == capacity) {
            BYTE *next;
            if (capacity == limit) break;
            capacity *= 2;
            if (capacity > limit) capacity = limit;
            next = realloc(buffer, capacity);
            if (!next) break;
            buffer = next;
        }
        if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), buffer + used,
                      (DWORD)(capacity - used), &got, NULL)) break;
        if (!got) {
            if (used) {
                result = GlobalAlloc(GMEM_MOVEABLE, used);
                if (result) {
                    BYTE *ptr = GlobalLock(result);
                    if (ptr) { memcpy(ptr, buffer, used); GlobalUnlock(result); }
                    else { GlobalFree(result); result = NULL; }
                }
            }
            break;
        }
        used += got;
    }
    free(buffer);
    return result;
}

static int convert_once(int argc, char **argv)
{
    const UINT png_format = RegisterClipboardFormatW(L"PNG");
    const UINT jpeg_format = RegisterClipboardFormatW(L"JFIF");
    const UINT gif_format = RegisterClipboardFormatW(L"GIF");
    HGLOBAL source, source_copy = NULL, decode_copy = NULL, dib = NULL;
    IStream *stream = NULL;
    GpBitmap *bitmap = NULL;
    BitmapData bits = {0};
    Rect rect = {0};
    UINT width = 0, height = 0;
    SIZE_T source_size, image_size, dib_size;
    BYTE *read_ptr, *write_ptr;
    UINT format = 0, format_count = 0, source_format = 0;
    int result = 0;
    BOOL host_png = argc == 5 && !strcmp(argv[1], "--host-png");
    unsigned long expected_size = 0, expected_crc = 0;
    char *end;

    if (host_png) {
        expected_size = strtoul(argv[3], &end, 10);
        if (*end || !expected_size || expected_size > 64 * 1024 * 1024) return 1;
        expected_crc = strtoul(argv[4], &end, 16);
        if (*end) return 1;
        decode_copy = read_png_stdin();
        if (!decode_copy) return 1;
    }

    if (IsClipboardFormatAvailable(CF_DIB)) { if (decode_copy) GlobalFree(decode_copy); return 0; }
    if (!OpenClipboard(GetDesktopWindow())) { if (decode_copy) GlobalFree(decode_copy); return 1; }
    while ((format = EnumClipboardFormats(format)) != 0) {
        ++format_count;
        source_format = format;
    }
    /* EmptyClipboard discards every other format, so accept one image only. */
    if (format_count != 1 ||
        (host_png ? source_format != RegisterClipboardFormatA(argv[2]) :
         (source_format != png_format && source_format != jpeg_format &&
          source_format != gif_format && source_format != CF_TIFF))) goto done;
    source = GetClipboardData(source_format);
    if (!source || !(source_size = GlobalSize(source)) || source_size > 64 * 1024 * 1024) goto done;
    source_copy = GlobalAlloc(GMEM_MOVEABLE, source_size);
    if (!source_copy) goto done;
    read_ptr = GlobalLock(source);
    write_ptr = GlobalLock(source_copy);
    if (!read_ptr || !write_ptr) {
        if (write_ptr) GlobalUnlock(source_copy);
        if (read_ptr) GlobalUnlock(source);
        goto done;
    }
    memcpy(write_ptr, read_ptr, source_size);
    if (host_png && (source_size != expected_size ||
                     crc32_bytes(read_ptr, source_size) != (uint32_t)expected_crc)) {
        GlobalUnlock(source_copy);
        GlobalUnlock(source);
        goto done;
    }
    GlobalUnlock(source_copy);
    GlobalUnlock(source);

    if (CreateStreamOnHGlobal(host_png ? decode_copy : source_copy, FALSE, &stream) != S_OK) goto done;
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
    if (SetClipboardData(source_format, source_copy)) source_copy = NULL;
    if (SetClipboardData(CF_DIB, dib)) dib = NULL;
    if (!source_copy && !dib) result = 2;

done:
    if (bitmap) GdipDisposeImage((GpImage *)bitmap);
    if (stream) stream->lpVtbl->Release(stream);
    if (source_copy) GlobalFree(source_copy);
    if (decode_copy) GlobalFree(decode_copy);
    if (dib) GlobalFree(dib);
    CloseClipboard();
    return result;
}

int main(int argc, char **argv)
{
    ULONG_PTR token;
    struct GdiplusStartupInput input = {1, NULL, FALSE, FALSE};
    if (GdiplusStartup(&token, &input, NULL) != Ok) return 1;
    int result = convert_once(argc, argv);
    GdiplusShutdown(token);
    return result;
}
