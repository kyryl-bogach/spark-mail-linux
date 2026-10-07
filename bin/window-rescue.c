/* Move Spark windows that lie on no monitor back onto the primary monitor.
   Wine unmaps a visible window whose rectangle is outside the virtual screen,
   for example after a monitor is removed. Windows still reports the window as
   visible, so Spark never shows it again. A move into the screen makes Wine
   map the window again. The prefix runs only Spark, so every Chromium frame
   belongs to Spark. */
#include <windows.h>
#include <string.h>

static BOOL CALLBACK rescue(HWND window, LPARAM unused)
{
    char name[32];
    RECT rect, work;
    MONITORINFO info;
    (void)unused;
    /* Only visible application frames. Skip tool, message, and owned windows. */
    if (!IsWindowVisible(window) || IsIconic(window) || GetWindow(window, GW_OWNER)) return TRUE;
    if ((GetWindowLongA(window, GWL_STYLE) & WS_CAPTION) != WS_CAPTION) return TRUE;
    if (!GetClassNameA(window, name, sizeof(name)) || strcmp(name, "Chrome_WidgetWin_1")) return TRUE;
    if (MonitorFromWindow(window, MONITOR_DEFAULTTONULL) || !GetWindowRect(window, &rect)) return TRUE;
    info.cbSize = sizeof(info);
    if (!GetMonitorInfoA(MonitorFromPoint((POINT){0, 0}, MONITOR_DEFAULTTOPRIMARY), &info)) return TRUE;
    work = info.rcWork;
    SetWindowPos(window, NULL, work.left, work.top,
                 min(rect.right - rect.left, work.right - work.left),
                 min(rect.bottom - rect.top, work.bottom - work.top),
                 SWP_NOZORDER | SWP_NOACTIVATE);
    return TRUE;
}

int main(void)
{
    return EnumWindows(rescue, 0) ? 0 : 1;
}
