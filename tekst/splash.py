"""An instant stand-in window (Windows), shown ~0.3 s after Python starts.

Teksting's real window needs ~2 s before it can appear (.NET + WebView2 load first). This plain Win32 window
(ctypes only, nothing to import) shows at once with the same size, place, colour, icon, title and title bar,
so clicking the shortcut opens a window right away. When the real window is shown, it takes over in the
same spot and this one closes.

Size and place copy what pywebview/WinForms do with Teksting's window: a system-DPI-aware process,
1440 x 900 logical pixels times the system scale, centred on the working area of the screen under the
mouse (WinForms CenterScreen), never above or left of that area.
"""
import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32")

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

WS_OVERLAPPEDWINDOW = 0x00CF0000
WM_DESTROY, WM_CLOSE, WM_SETCURSOR = 0x0002, 0x0010, 0x0020
IDC_APPSTARTING = 32650  # arrow with a small busy circle: "starting"
SW_SHOWNORMAL = 1


def layout(width=1440, height=900):
    """Where both windows go: (logical x, y, w, h) for pywebview and the same rectangle in physical pixels.

    1440 x 900 (logical), but never larger than the usable screen (on a 1920 x 1080 laptop at 125 % that size
    is 1800 x 1125 physical, taller than the 1020 px above the taskbar), centred on the screen under the mouse.
    pywebview turns logical into physical with int(v * scale) for a system-DPI-aware process, so the physical
    rectangle is computed the same way: both windows land on exactly the same pixels.
    """
    user32.SetProcessDPIAware()  # pywebview does the same before creating its window
    try:
        scale = user32.GetDpiForSystem() / 96
    except AttributeError:  # Windows 8.1 and older
        hdc = user32.GetDC(None)
        scale = gdi32.GetDeviceCaps(hdc, 88) / 96  # LOGPIXELSX
        user32.ReleaseDC(None, hdc)
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromPoint(pt, 2), ctypes.byref(mi))  # 2 = nearest monitor
    wa = mi.rcWork
    lw = min(width, int((wa.right - wa.left) / scale))
    lh = min(height, int((wa.bottom - wa.top) / scale))
    lx = round((wa.left + (wa.right - wa.left - lw * scale) / 2) / scale)
    ly = round((wa.top + (wa.bottom - wa.top - lh * scale) / 2) / scale)
    logical = (lx, ly, lw, lh)
    physical = tuple(int(v * scale) for v in logical)
    return logical, physical


class Splash:
    def __init__(self, background="#edf1f4", dark=False, icon=None, title="Teksting"):
        self.hwnd = None
        self.rect = None      # physical pixels
        self.logical = None   # the same, in logical pixels (what pywebview is given)
        self._ready = threading.Event()
        threading.Thread(target=self._run, args=(background, dark, icon, title), daemon=True).start()
        self._ready.wait(2)

    def _run(self, background, dark, icon, title):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            r, g, b = (int(background[i:i + 2], 16) for i in (1, 3, 5))
            cursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_APPSTARTING))

            def proc(hwnd, msg, wp, lp):
                if msg == WM_SETCURSOR and (lp & 0xFFFF) == 1:  # over the window body: busy arrow
                    user32.SetCursor(cursor)
                    return 1
                if msg == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wp, lp)

            self._proc = WNDPROC(proc)  # keep a reference: Windows calls it for the window's whole life
            hicon = user32.LoadImageW(None, icon, 1, 0, 0, 0x10 | 0x40) if icon else None  # IMAGE_ICON, from file, default size
            wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._proc, hInstance=hinst,
                             hIcon=hicon, hIconSm=hicon, hCursor=user32.LoadCursorW(None, ctypes.c_void_p(32512)),
                             hbrBackground=gdi32.CreateSolidBrush(r | g << 8 | b << 16), lpszClassName="TekstingSplash")
            user32.RegisterClassExW(ctypes.byref(wc))
            self.logical, self.rect = layout()
            x, y, w, h = self.rect
            self.hwnd = user32.CreateWindowExW(0, "TekstingSplash", title, WS_OVERLAPPEDWINDOW, x, y, w, h,
                                               None, None, hinst, None)
            # the same title bar as the real window (pywebview: immersive dark mode + Mica backdrop)
            dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
            for attr, val in ((20, 1 if dark else 0), (38, 2 if dark else 1)):
                v = ctypes.c_int(val)
                dwm(wintypes.HWND(self.hwnd), attr, ctypes.byref(v), 4)
            user32.ShowWindow(self.hwnd, SW_SHOWNORMAL)
            user32.UpdateWindow(self.hwnd)
        except Exception as e:  # never let the stand-in window stop the app from starting
            print("splash failed:", e)
            self.hwnd = None
        finally:
            self._ready.set()
        if not self.hwnd:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.hwnd = None


APP_ID = "Teksting.Teksting"  # same ID on the shortcuts (lag-snarveier.ps1) -> one taskbar button, pinnable
_MUTEX = []


def dark_mode():
    """Windows app theme, so the windows start in the right colour (no white flash in dark mode)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def own_mutex(timeout_ms=0):
    """Try to own the "Teksting is running" mutex (waiting up to timeout_ms). The owner keeps it for its whole
    life; when it exits, Windows hands it over (WAIT_ABANDONED), so a start that waits gets it the moment the
    old copy is gone - even if that copy was still shutting down when the icon was clicked again."""
    if not _MUTEX or not _MUTEX[0]:
        return True
    k32 = ctypes.WinDLL("kernel32")
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    return k32.WaitForSingleObject(_MUTEX[0], timeout_ms) in (0, 0x80)  # WAIT_OBJECT_0, WAIT_ABANDONED


def make_splash(dark):
    import os
    if os.environ.get("TEKSTING_NO_SPLASH") == "1":
        return None
    icon = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "teksting.ico")
    return Splash("#10171d" if dark else "#edf1f4", dark, icon)


def early():
    """The first thing app mode does (server.py, before any other import): returns (first, splash, dark).

    first: no other Teksting is running - this process now owns a named mutex (an instant check, unlike asking
    the port, which costs up to 0.3 s). When one is running, no stand-in window is shown; tekst/launch.py
    brings the running one forward, or waits for it to finish closing.
    """
    import os
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        port = os.environ.get("TEKSTING_PORT", "8765")  # one Teksting per port (a test copy on another port may run)
        _MUTEX.append(k32.CreateMutexW(None, False, "Local\\Teksting.window." + port))
    except Exception:
        pass
    first = own_mutex(0)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)  # one taskbar button for both windows
    except Exception:
        pass
    dark = dark_mode()
    splash = make_splash(dark) if first else None
    return first, splash, dark
