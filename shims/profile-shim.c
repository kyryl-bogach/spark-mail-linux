/* Replaces Foundation's USERENV import. Wine's
   GetAllUsersProfileDirectoryW is a stub that returns FALSE and never
   writes the required size. Foundation decrements that zero unchecked,
   underflows to 0xffffffff, and attempts an 8 GB copy. This shim returns
   C:\ProgramData and implements the documented sizing behavior.
   GetProfilesDirectoryW forwards to Wine's own userenv via the .def file. */
typedef unsigned short WCHAR;
typedef unsigned long DWORD;
__declspec(dllimport) void __stdcall SetLastError(DWORD error);

int __stdcall GetAllUsersProfileDirectoryW(WCHAR *buffer, DWORD *size)
{
    static const WCHAR path[] = L"C:\\ProgramData";
    const DWORD required = sizeof(path) / sizeof(path[0]);
    if (!size) {
        SetLastError(87); /* ERROR_INVALID_PARAMETER */
        return 0;
    }
    DWORD capacity = *size;
    *size = required;
    if (!buffer || capacity < required) {
        SetLastError(122); /* ERROR_INSUFFICIENT_BUFFER */
        return 0;
    }
    for (DWORD i = 0; i < required; ++i)
        buffer[i] = path[i];
    return 1;
}
