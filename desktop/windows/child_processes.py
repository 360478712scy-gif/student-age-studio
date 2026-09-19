"""Keep extraction and WebView children tied to the lifetime of this app."""
import ctypes
from ctypes import wintypes


def own_children():
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',wintypes.DWORD),('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),('active',wintypes.DWORD),('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Limits(ctypes.Structure):
        _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
    k.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];k.CreateJobObjectW.restype=wintypes.HANDLE
    k.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    k.GetCurrentProcess.restype=wintypes.HANDLE
    k.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=k.CreateJobObjectW(None,None);limits=Limits();limits.basic.flags=0x2000
    if not handle or not k.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
        error=ctypes.get_last_error()
        if handle:k.CloseHandle(handle)
        raise ctypes.WinError(error)
    if not k.AssignProcessToJobObject(handle,k.GetCurrentProcess()):
        error=ctypes.get_last_error();k.CloseHandle(handle)
        k.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
        k.IsProcessInJob.restype=wintypes.BOOL
        in_job=wintypes.BOOL()
        if error==5 and k.IsProcessInJob(k.GetCurrentProcess(),None,ctypes.byref(in_job)) and in_job.value:
            return None
        raise ctypes.WinError(error)
    # No HANDLE_FLAG_INHERIT: the OS closes our only handle when the app exits.
    return handle
