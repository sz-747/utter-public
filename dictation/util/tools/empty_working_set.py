# coding: utf-8
"""
Windows memory management

Empties a process's working set to free physical memory.
Windows only.
"""

import ctypes
from typing import Optional


def empty_working_set(pid: int) -> None:
    """
    Empty the physical memory working set of a process

    Uses the Windows API to release the physical memory the process uses,
    moving it to the page file to reduce memory use.

    Args:
        pid: process ID

    Note:
        Windows only; the call fails on other platforms.
    """
    # Open the process (PROCESS_ALL_ACCESS = 0x1F0FFF)
    handle = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)

    if handle:
        # Empty the working set
        ctypes.windll.psapi.EmptyWorkingSet(handle)

        # Close the process handle
        ctypes.windll.kernel32.CloseHandle(handle)


def empty_current_working_set() -> None:
    """
    Empty the physical memory working set of the current process

    Gets the current process ID and empties its working set.
    Usually called once startup is done, to free the memory used while starting.
    """
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    empty_working_set(pid)
