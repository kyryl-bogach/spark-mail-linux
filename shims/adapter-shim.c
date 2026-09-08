/* Test-prefix-only shim. Wine's GetAdaptersAddresses data trips a nil
   force-unwrap in Swift Foundation Host._resolveCurrent (ud2 trap after
   Google login). Reporting ERROR_NO_DATA makes Foundation take its
   early-return path; ProcessInfo.hostName then falls back to "localhost". */
__declspec(dllexport) unsigned long __stdcall GetAdaptersAddresses(
    unsigned long family, unsigned long flags, void *reserved,
    void *addresses, unsigned long *size)
{
    (void)family; (void)flags; (void)reserved; (void)addresses; (void)size;
    return 232; /* ERROR_NO_DATA */
}

int __stdcall DllMainCRTStartup(void *instance, unsigned long reason, void *reserved)
{
    (void)instance; (void)reason; (void)reserved;
    return 1;
}
