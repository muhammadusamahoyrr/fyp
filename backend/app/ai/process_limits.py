"""Hard memory cap for the CURRENT process. Called by a child, on itself.

The extraction child already has a hard wall-clock limit (the parent kills its
whole process tree on timeout). This adds the other resource a hostile file
can exhaust: memory. A decompression bomb or a pathological PDF that gets past
the declared-size checks then fails with MemoryError inside the child -- which
the parent sees as a failed extraction -- instead of taking the host down.

  POSIX    RLIMIT_AS (address space) via `resource.setrlimit`.
  Windows  a Job Object with JOB_OBJECT_LIMIT_PROCESS_MEMORY, assigned to this
           process (and inherited by anything it spawns, e.g. Tesseract).

Opt-in: nothing calls this unless the parent passes AAI_CHILD_MEMORY_LIMIT_MB,
so the intake path is unchanged. Stdlib only (ctypes / resource), because the
extraction child must stay cheap to start.
"""
from __future__ import annotations

import os
import sys

ENV_VAR = "AAI_CHILD_MEMORY_LIMIT_MB"


def apply_memory_limit(limit_mb: int) -> str:
    """Cap this process at `limit_mb` MiB. Returns the mechanism used.

    Raises OSError if the platform refuses: a caller that asked for a cap
    must not silently run without one.
    """
    if limit_mb <= 0:
        raise ValueError("memory limit must be positive")
    limit = int(limit_mb) * 1024 * 1024
    if sys.platform == "win32":
        _windows_job_limit(limit)
        return "windows_job_object"
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    return "rlimit_as"


def apply_from_env() -> str | None:
    raw = os.environ.get(ENV_VAR)
    if not raw:
        return None
    return apply_memory_limit(int(raw))


def _windows_job_limit(limit: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JobObjectExtendedLimitInformation = 9

    # Signatures declared explicitly: GetCurrentProcess returns the pseudo-
    # handle -1, which ctypes cannot pass as a default C int.
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                 ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = limit
    if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    # The handle is deliberately never closed: the job (and its limit) must
    # live as long as this process does.
