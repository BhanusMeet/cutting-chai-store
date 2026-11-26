"""Windows printing with the standard library only (ctypes):
  - which printers Windows knows, and which USB printers are physically plugged in right now
  - sending raw ESC/POS bytes through the Windows print spooler and watching what happens to the job
  - drawing Hindi / Marathi (any non-English) text as a black-and-white image, which receipt printers can print
Import this module only on Windows."""
import ctypes
import time
import winreg
from ctypes import wintypes as W

spool = ctypes.WinDLL("winspool.drv", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
gdi = ctypes.WinDLL("gdi32", use_last_error=True)
user = ctypes.WinDLL("user32", use_last_error=True)


def _fn(dll, name, restype, *argtypes):
    f = getattr(dll, name)
    f.restype, f.argtypes = restype, list(argtypes)
    return f


# ------------------------------------------------------------ spooler
class PRINTER_INFO_2(ctypes.Structure):
    _fields_ = [(n, W.LPWSTR) for n in ("pServerName", "pPrinterName", "pShareName", "pPortName", "pDriverName", "pComment", "pLocation")] + [
        ("pDevMode", ctypes.c_void_p), ("pSepFile", W.LPWSTR), ("pPrintProcessor", W.LPWSTR), ("pDatatype", W.LPWSTR),
        ("pParameters", W.LPWSTR), ("pSecurityDescriptor", ctypes.c_void_p)] + [
        (n, W.DWORD) for n in ("Attributes", "Priority", "DefaultPriority", "StartTime", "UntilTime", "Status", "cJobs", "AveragePPM")]


class DOC_INFO_1(ctypes.Structure):
    _fields_ = [("pDocName", W.LPWSTR), ("pOutputFile", W.LPWSTR), ("pDatatype", W.LPWSTR)]


class JOB_INFO_1(ctypes.Structure):
    _fields_ = [("JobId", W.DWORD)] + [(n, W.LPWSTR) for n in ("pPrinterName", "pMachineName", "pUserName", "pDocument", "pDatatype", "pStatus")] + [
        (n, W.DWORD) for n in ("Status", "Priority", "Position", "TotalPages", "PagesPrinted")] + [("Submitted", W.WORD * 8)]


EnumPrintersW = _fn(spool, "EnumPrintersW", W.BOOL, W.DWORD, W.LPWSTR, W.DWORD, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD))
OpenPrinterW = _fn(spool, "OpenPrinterW", W.BOOL, W.LPWSTR, ctypes.POINTER(W.HANDLE), ctypes.c_void_p)
ClosePrinter = _fn(spool, "ClosePrinter", W.BOOL, W.HANDLE)
StartDocPrinterW = _fn(spool, "StartDocPrinterW", W.DWORD, W.HANDLE, W.DWORD, ctypes.c_void_p)
StartPagePrinter = _fn(spool, "StartPagePrinter", W.BOOL, W.HANDLE)
WritePrinter = _fn(spool, "WritePrinter", W.BOOL, W.HANDLE, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD))
EndPagePrinter = _fn(spool, "EndPagePrinter", W.BOOL, W.HANDLE)
EndDocPrinter = _fn(spool, "EndDocPrinter", W.BOOL, W.HANDLE)
GetJobW = _fn(spool, "GetJobW", W.BOOL, W.HANDLE, W.DWORD, W.DWORD, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD))
SetJobW = _fn(spool, "SetJobW", W.BOOL, W.HANDLE, W.DWORD, W.DWORD, ctypes.c_void_p, W.DWORD)

# printer status bits that mean "do not send now", with words a cashier understands
PRINTER_PROBLEMS = ((0x1, "the printer is paused in Windows"), (0x8, "paper jam"), (0x10, "out of paper"), (0x40, "paper problem"),
                    (0x80, "the printer is offline"), (0x400000, "the printer cover is open"), (0x100000, "the printer needs attention"),
                    (0x2, "the printer reports an error"), (0x1000, "the printer is not available"))
WORK_OFFLINE = 0x400
JOB_PROBLEMS = ((0x40, "out of paper"), (0x20, "the printer is offline"), (0x400, "the printer needs attention"),
                (0x200, "the printer is blocked"), (0x2, "the printer reports an error"), (0x1, "the print job is paused"))
JOB_REMOVED = 0x4 | 0x100
JOB_DONE = 0x80 | 0x1000


def list_printers():
    """Every printer installed on this computer: name, port, driver and any problem Windows reports."""
    need, count = W.DWORD(0), W.DWORD(0)
    EnumPrintersW(2 | 4, None, 2, None, 0, ctypes.byref(need), ctypes.byref(count))
    if not need.value:
        return []
    buf = ctypes.create_string_buffer(need.value)
    if not EnumPrintersW(2 | 4, None, 2, buf, need.value, ctypes.byref(need), ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    out = []
    for p in (PRINTER_INFO_2 * count.value).from_buffer(buf):
        problem = next((words for bit, words in PRINTER_PROBLEMS if p.Status & bit), "")
        if not problem and p.Attributes & WORK_OFFLINE:
            problem = "the printer is set to 'use offline' in Windows"
        out.append({"name": p.pPrinterName or "", "port": p.pPortName or "", "driver": p.pDriverName or "", "problem": problem})
    return out


# ------------------------------------------------------------ which USB printers are plugged in right now
class GUID(ctypes.Structure):
    _fields_ = [("d1", W.DWORD), ("d2", W.WORD), ("d3", W.WORD), ("d4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("InterfaceClassGuid", GUID), ("Flags", W.DWORD), ("Reserved", ctypes.c_void_p)]


USB_PRINT_TEXT = "{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"
USB_PRINT = GUID(0x28D78FAD, 0x5A12, 0x11D1, (ctypes.c_ubyte * 8)(0xAE, 0x5B, 0x00, 0x00, 0xF8, 0x03, 0xA8, 0xC2))

SetupDiGetClassDevsW = _fn(setupapi, "SetupDiGetClassDevsW", W.HANDLE, ctypes.POINTER(GUID), W.LPCWSTR, W.HWND, W.DWORD)
SetupDiEnumDeviceInterfaces = _fn(setupapi, "SetupDiEnumDeviceInterfaces", W.BOOL, W.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), W.DWORD,
                                  ctypes.POINTER(SP_DEVICE_INTERFACE_DATA))
SetupDiGetDeviceInterfaceDetailW = _fn(setupapi, "SetupDiGetDeviceInterfaceDetailW", W.BOOL, W.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                       ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD), ctypes.c_void_p)
SetupDiDestroyDeviceInfoList = _fn(setupapi, "SetupDiDestroyDeviceInfoList", W.BOOL, W.HANDLE)


def _port_of(path):
    """\\\\?\\usb#vid...#serial#{guid}  ->  'USB001', read from the registry entry of that device."""
    key = r"SYSTEM\CurrentControlSet\Control\DeviceClasses\%s\%s\#\Device Parameters" % (USB_PRINT_TEXT, "##?#" + path[4:])
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            base = winreg.QueryValueEx(k, "Base Name")[0]
            return "%s%03d" % (base, winreg.QueryValueEx(k, "Port Number")[0])
    except OSError:
        return None


def usb_ports_present():
    """One entry per USB printer plugged in now: its port name ('USB001'), or None if Windows gave it none."""
    handle = SetupDiGetClassDevsW(ctypes.byref(USB_PRINT), None, None, 0x2 | 0x10)  # present devices, interfaces
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    ports, index = [], 0
    try:
        while True:
            data = SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not SetupDiEnumDeviceInterfaces(handle, None, ctypes.byref(USB_PRINT), index, ctypes.byref(data)):
                break
            index += 1
            need = W.DWORD(0)
            SetupDiGetDeviceInterfaceDetailW(handle, ctypes.byref(data), None, 0, ctypes.byref(need), None)
            detail = ctypes.create_string_buffer(need.value + 4)
            ctypes.cast(detail, ctypes.POINTER(W.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if SetupDiGetDeviceInterfaceDetailW(handle, ctypes.byref(data), detail, need.value, None, None):
                ports.append(_port_of(ctypes.wstring_at(ctypes.addressof(detail) + 4)))
    finally:
        SetupDiDestroyDeviceInfoList(handle)
    return ports


# ------------------------------------------------------------ sending
class NotSent(Exception):
    """Nothing reached the printer: it is safe to send again."""


class Unsure(Exception):
    """The job was handed to Windows but did not finish: paper may or may not have come out."""


def send_raw(name, data, timeout):
    """Send bytes and wait until Windows says the job is finished. Raises NotSent or Unsure."""
    handle = W.HANDLE()
    if not OpenPrinterW(name, ctypes.byref(handle), None):
        raise NotSent("Windows could not open the printer")
    try:
        doc = DOC_INFO_1("Order slip", None, "RAW")
        job = StartDocPrinterW(handle, 1, ctypes.byref(doc))
        if not job:
            raise NotSent("Windows would not start the print job (error %d)" % ctypes.get_last_error())
        written = W.DWORD(0)
        ok = StartPagePrinter(handle) and WritePrinter(handle, data, len(data), ctypes.byref(written)) and written.value == len(data)
        ok = bool(EndPagePrinter(handle)) and ok
        ok = bool(EndDocPrinter(handle)) and ok
        if not ok:
            SetJobW(handle, job, 0, None, 5)  # delete it, so it cannot come out later by surprise
            raise Unsure("Windows could not pass the whole slip to the printer")
        _wait_for_job(handle, job, timeout)
    finally:
        ClosePrinter(handle)


def _wait_for_job(handle, job, timeout):
    end, problem = time.time() + timeout, ""
    while True:
        need = W.DWORD(0)
        GetJobW(handle, job, 1, None, 0, ctypes.byref(need))
        buf = ctypes.create_string_buffer(max(need.value, 1))
        if not need.value or not GetJobW(handle, job, 1, buf, need.value, ctypes.byref(need)):
            if ctypes.get_last_error() == 87:  # the job has left the queue: Windows has delivered it
                return
        else:
            status = JOB_INFO_1.from_buffer(buf).Status
            if status & JOB_REMOVED:
                raise Unsure("the print job was removed from the Windows queue")
            problem = next((words for bit, words in JOB_PROBLEMS if status & bit), "")
            if status & JOB_DONE and not problem:
                return
        if time.time() >= end:
            SetJobW(handle, job, 0, None, 5)  # cancel, so a reprint cannot produce two slips later
            raise Unsure(problem or "the printer did not finish in time")
        time.sleep(0.3)


# ------------------------------------------------------------ text as an image (for Hindi, Marathi and other scripts)
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD), ("biBitCount", W.WORD),
                ("biCompression", W.DWORD), ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
                ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


CreateCompatibleDC = _fn(gdi, "CreateCompatibleDC", W.HDC, W.HDC)
CreateDIBSection = _fn(gdi, "CreateDIBSection", W.HBITMAP, W.HDC, ctypes.c_void_p, W.UINT, ctypes.POINTER(ctypes.c_void_p), W.HANDLE, W.DWORD)
CreateFontW = _fn(gdi, "CreateFontW", W.HFONT, *([ctypes.c_int] * 5), *([W.DWORD] * 8), W.LPCWSTR)
SelectObject = _fn(gdi, "SelectObject", W.HGDIOBJ, W.HDC, W.HGDIOBJ)
DeleteObject = _fn(gdi, "DeleteObject", W.BOOL, W.HGDIOBJ)
DeleteDC = _fn(gdi, "DeleteDC", W.BOOL, W.HDC)
SetTextColor = _fn(gdi, "SetTextColor", W.DWORD, W.HDC, W.DWORD)
SetBkMode = _fn(gdi, "SetBkMode", ctypes.c_int, W.HDC, ctypes.c_int)
GdiFlush = _fn(gdi, "GdiFlush", W.BOOL)
DrawTextW = _fn(user, "DrawTextW", ctypes.c_int, W.HDC, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.RECT), W.UINT)

STYLES = {"normal": (26, 400), "bold": (28, 700), "big": (52, 700)}  # (height in printer dots, weight)
DT = 0x10 | 0x800 | 0x2000  # wrap words, treat '&' as text, break long words


def raster(lines, width):
    """lines: [(text, style)]. Returns (bytes per row, rows, bit data) with 1 = black dot."""
    dc = CreateCompatibleDC(None)
    fonts = {k: CreateFontW(-h, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 3, 0, "Nirmala UI") for k, (h, weight) in STYLES.items()}
    bitmap = None
    old_bitmap = old_font = None
    try:
        heights = []
        old_font = SelectObject(dc, fonts["normal"])
        for text, style in lines:
            SelectObject(dc, fonts[style])
            r = W.RECT(0, 0, width, 0)
            DrawTextW(dc, text or " ", -1, ctypes.byref(r), DT | 0x400)  # measure only
            heights.append(max(r.bottom, STYLES[style][0]))
        total = sum(heights) + 8
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -total, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bitmap = CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        if not bitmap:
            raise OSError("Windows could not make the slip image")
        old_bitmap = SelectObject(dc, bitmap)
        ctypes.memset(bits, 0xFF, width * total * 4)
        SetTextColor(dc, 0)
        SetBkMode(dc, 1)
        y = 0
        for (text, style), height in zip(lines, heights):
            SelectObject(dc, fonts[style])
            r = W.RECT(0, y, width, y + height)
            DrawTextW(dc, text or " ", -1, ctypes.byref(r), DT)
            y += height
        GdiFlush()
        pixels = ctypes.string_at(bits, width * total * 4)[1::4]  # the green channel is enough for black on white
        stride = (width + 7) // 8
        out = bytearray(stride * total)
        for row in range(total):
            line = pixels[row * width:(row + 1) * width]
            for x, v in enumerate(line):
                if v < 150:
                    out[row * stride + (x >> 3)] |= 0x80 >> (x & 7)
        return stride, total, bytes(out)
    finally:
        if old_bitmap:
            SelectObject(dc, old_bitmap)
        if old_font:
            SelectObject(dc, old_font)
        if bitmap:
            DeleteObject(bitmap)
        for f in fonts.values():
            DeleteObject(f)
        DeleteDC(dc)
