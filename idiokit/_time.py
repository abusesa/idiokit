from __future__ import absolute_import

import os
import sys
import time
import ctypes
import ctypes.util


def load_lib(name, use_errno=False):
    libc_path = ctypes.util.find_library(name)
    libc = ctypes.CDLL(libc_path, use_errno=use_errno)
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

        lib = load_lib("c")
        mach_timebase_info = lib.mach_timebase_info
        mach_timebase_info.restype = None
        mach_timebase_info.argtypes = [ctypes.POINTER(mach_timebase_info_t)]

        self._timebase = mach_timebase_info_t()
        mach_timebase_info(self._timebase)

        self._mach_absolute_time = lib.mach_absolute_time
        self._mach_absolute_time.restype = ctypes.c_uint64
        self._mach_absolute_time.argtypes = []

        self._start = self._mach_absolute_time()

    def monotonic(self):
        elapsed = self._mach_absolute_time() - self._start
        timestamp = elapsed * self._timebase.numerator / self._timebase.denominator

        sec, nsec = divmod(timestamp, 10 ** 9)
        return sec + nsec * (10 ** -9)


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

        lib = load_lib("rt", use_errno=True)
        self._clock_gettime = lib.clock_gettime
        self._clock_gettime.restype = ctypes.c_int
        self._clock_gettime.argtypes = [ctypes.c_int, ctypes.POINTER(timespec)]

        res = self._clock_gettime(self.CLOCK_MONOTONIC, ctypes.byref(timespec()))
        if res == -1:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))

    def monotonic(self):
        spec = self._timespec()
        res = self._clock_gettime(self.CLOCK_MONOTONIC, ctypes.byref(spec))
        if res == -1:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return spec.tv_sec + spec.tv_nsec * (10 ** -9)


if sys.platform == "darwin":
    _global = DarwinTime()
elif sys.platform.startswith("linux"):
    _global = LinuxTime()
else:
    _global = FallbackTime()
monotonic = _global.monotonic
