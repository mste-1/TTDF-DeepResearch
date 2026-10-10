"""OS containment for a research execution, including descendants after root exit."""
import os
import signal
import time

import psutil


def same_process(pid, created):
    if not pid or created is None:
        return None
    try:
        process = psutil.Process(pid)
        if abs(process.create_time() - created) < 0.01 and process.status() != psutil.STATUS_ZOMBIE:
            return process
    except psutil.NoSuchProcess:
        pass
    return None


def _linux_group_members(pid):
    members = []
    for process in psutil.process_iter(["pid", "status"]):
        try:
            if os.getpgid(process.pid) == pid and os.getsid(process.pid) == pid:
                if process.status() != psutil.STATUS_ZOMBIE:
                    members.append(process)
        except (ProcessLookupError, psutil.NoSuchProcess):
            pass
    return members


def stop_process_tree(pid, created):
    """Linux sessions survive their leader. Do not skip the group when it exits.

    The group/session ID remains allocated while descendants are members. A
    recycled live PID with a different birth time means the old group is gone.
    Windows executions use Job objects; the fallback handles pre-registration.
    """
    process = same_process(pid, created)
    if os.name != "nt" and pid:
        try:
            candidate = psutil.Process(pid)
            if abs(candidate.create_time() - created) >= 0.01:
                return
        except psutil.NoSuchProcess:
            pass
        members = _linux_group_members(pid)
        if members:
            os.killpg(pid, signal.SIGKILL)
            deadline = time.monotonic() + 3
            while _linux_group_members(pid):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Research process group has not exited; slot remains reserved")
                time.sleep(0.02)
            return
    if process is None:
        return
    descendants = process.children(recursive=True)
    for target in [*reversed(descendants), process]:
        try:
            target.kill()
        except psutil.NoSuchProcess:
            pass
    _gone, alive = psutil.wait_procs([*descendants, process], timeout=3)
    if any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in alive):
        raise RuntimeError("A research process has not stopped; its execution slot remains reserved")


class WindowsJob:
    """Non-inheritable named Job handle; kernel kills the entire job on close.

    Assign before the startup gate is opened. Normal completion, cancellation,
    and recovery query ActiveProcesses=0 before allowing the slot to be reused.
    """
    def __init__(self, handle, kernel):
        self.handle, self.kernel = handle, kernel

    @staticmethod
    def api():
        import ctypes
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, w.LPCWSTR)
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.OpenJobObjectW.argtypes = (w.DWORD, w.BOOL, w.LPCWSTR)
        kernel.OpenJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD)
        kernel.SetInformationJobObject.restype = w.BOOL
        kernel.QueryInformationJobObject.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p)
        kernel.QueryInformationJobObject.restype = w.BOOL
        kernel.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
        kernel.AssignProcessToJobObject.restype = w.BOOL
        kernel.TerminateJobObject.argtypes = (w.HANDLE, w.UINT)
        kernel.TerminateJobObject.restype = w.BOOL
        kernel.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
        kernel.OpenProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = (w.HANDLE,)
        kernel.CloseHandle.restype = w.BOOL
        return kernel

    @classmethod
    def create(cls, execution_id):
        if os.name != "nt":
            return None
        import ctypes
        from ctypes import wintypes as w

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", w.DWORD), ("min_working", ctypes.c_size_t), ("max_working", ctypes.c_size_t),
                        ("process_limit", w.DWORD), ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", ctypes.c_ulonglong * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        kernel = cls.api()
        handle = kernel.CreateJobObjectW(None, "Local\\wenli-" + execution_id)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        job = cls(handle, kernel)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            job.close()
            raise error
        return job

    @classmethod
    def open(cls, execution_id):
        if os.name != "nt":
            return None
        import ctypes
        kernel = cls.api()
        handle = kernel.OpenJobObjectW(0x0004 | 0x0008, False, "Local\\wenli-" + execution_id)
        if not handle:
            error = ctypes.get_last_error()
            if error == 2:  # Object no longer exists: no execution descendants remain.
                return None
            raise ctypes.WinError(error)
        return cls(handle, kernel)

    def assign(self, pid):
        import ctypes
        process = self.kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel.CloseHandle(process)

    def active(self):
        import ctypes
        from ctypes import wintypes as w

        class Accounting(ctypes.Structure):
            _fields_ = [("user_time", ctypes.c_longlong), ("kernel_time", ctypes.c_longlong),
                        ("period_user", ctypes.c_longlong), ("period_kernel", ctypes.c_longlong),
                        ("page_faults", w.DWORD), ("total_processes", w.DWORD),
                        ("active_processes", w.DWORD), ("terminated_processes", w.DWORD)]
        data = Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(data), ctypes.sizeof(data), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return data.active_processes

    def stop(self):
        import ctypes
        if not self.kernel.TerminateJobObject(self.handle, 75):
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + 3
        while self.active():
            if time.monotonic() >= deadline:
                raise RuntimeError("Research Job descendants have not exited; slot remains reserved")
            time.sleep(0.02)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
