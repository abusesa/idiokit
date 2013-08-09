from __future__ import absolute_import

import sys
import time
import ctypes
import ctypes.util


def load_libc():
    libc_path = ctypes.util.find_library("libc")
    libc = ctypes.cdll.LoadLibrary(libc_path)
    return libc


class FallbackTime(object):
    _time = staticmethod(time.time)

    def __init__(self):
        self._elapsed = 0
        self._origin = self._time()
        self._previous = self._origin

    def monotonic(self):
        now = self._time()
        if now < self._previous:
            self._elapsed += self._previous - self._origin
            self._origin = now
        self._previous = now
        return self._elapsed + (now - self._origin)


class DarwinTime(object):
    def __init__(self):
        class mach_timebase_info_t(ctypes.Structure):
            _fields_ = [
                ("numerator", ctypes.c_uint32),
                ("denominator", ctypes.c_uint32)
            ]

        libc = load_libc()

        mach_timebase_info = libc.mach_timebase_info
        mach_timebase_info.restype = None
        mach_timebase_info.argtypes = [ctypes.POINTER(mach_timebase_info_t)]

        self._timebase = mach_timebase_info_t()
        mach_timebase_info(self._timebase)

        self._mach_absolute_time = libc.mach_absolute_time
        self._mach_absolute_time.restype = ctypes.c_uint64
        self._mach_absolute_time.argtypes = []

        self._start = self._mach_absolute_time()

    def monotonic(self):
        elapsed = self._mach_absolute_time() - self._start
        ns = elapsed * self._timebase.numerator / self._timebase.denominator
        return ns * (10 ** -9)


class LinuxTime(object):
    CLOCK_MONOTONIC = 1

    def __init__(self):
        time_t = ctypes.c_long

        class timespec(ctypes.Structure):
            _fields_ = [
                ("tv_sec", time_t),
                ("tv_nsec", ctypes.c_long)
            ]
        self._timespec = timespec

        libc = load_libc()
        self._clock_gettime = libc.clock_gettime
        self._clock_gettime.restype = ctypes.c_int
        self._clock_gettime.argtypes = [ctypes.c_int, ctypes.POINTER(timespec)]

        res = self._clock_gettime(self.CLOCK_MONOTONIC, ctypes.byref(timespec()))
        if res == -1:
            raise RuntimeError("can not use CLOCK_MONOTONIC")

    def monotonic(self):
        spec = self._timespec()
        self._clock_gettime(self.CLOCK_MONOTONIC, ctypes.byref(spec))
        return spec.tv_sec + spec.tv_nsec * (10 ** -9)


if sys.platform == "darwin":
    _global = DarwinTime()
elif sys.platform.startswith("linux"):
    _global = LinuxTime()
else:
    _global = FallbackTime()
monotonic = _global.monotonic
