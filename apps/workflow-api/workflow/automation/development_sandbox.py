"""Per-child Linux isolation for generated diagnostic code; no host policy edits."""
import ctypes
import errno
import os
from pathlib import Path
import platform
import sys


def restrict_child(source, scratch):
    """Fail closed: read-only source/runtime, private scratch, no network/ptrace.

    Landlock and seccomp are inherited across exec/fork. No sudo, namespace
    policy change or production installation is required. Reviewed legacy tests
    retain their existing runner; generated code must use this stronger boundary.
    """
    if platform.machine() != 'x86_64':
        raise RuntimeError('Validated x86_64 development sandbox required')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'No-new-privileges required')
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 1:
        raise RuntimeError('Landlock is required for generated code')
    rights = (1 << 13)-1
    if abi >= 2: rights |= 1 << 13
    if abi >= 3: rights |= 1 << 14
    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]
    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]
    attributes = Ruleset(rights)
    ruleset = libc.syscall(444, ctypes.byref(attributes), ctypes.sizeof(attributes), 0)
    if ruleset < 0: raise OSError(ctypes.get_errno(), 'Landlock ruleset unavailable')
    try:
        readonly = ['/usr', '/lib', '/lib64', '/etc/ld.so.cache', '/etc/localtime',
                    '/dev/null', '/dev/urandom', str(Path(sys.prefix).resolve()), str(Path(source).resolve())]
        for path, allowed in [(p, 13) for p in readonly] + [(str(Path(scratch).resolve()), rights)]:
            p = Path(path)
            if not p.exists(): continue
            if not p.is_dir(): allowed &= 7  # regular file rights only
            fd = os.open(p, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(allowed, fd)
                if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0):
                    raise OSError(ctypes.get_errno(), 'Landlock path rule refused')
            finally: os.close(fd)
        if libc.syscall(446, ruleset, 0):
            raise OSError(ctypes.get_errno(), 'Landlock restriction refused')
    finally: os.close(ruleset)
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                    ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]
    class Program(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]
    # Reject alternate ABIs and x32 syscall numbers before evaluating the list.
    instructions = [(0x20,0,0,4), (0x15,1,0,0xC000003E), (0x06,0,0,0x80000000),
                    (0x20,0,0,0), (0x35,0,1,0x40000000), (0x06,0,0,0x80000000)]
    for number in (41,53,101,165,250,272,298,304,308,310,311,321,425,426,427):
        instructions += [(0x15,0,1,number), (0x06,0,0,0x00050000 | errno.EPERM)]
    instructions.append((0x06,0,0,0x7FFF0000))
    filters = (Filter * len(instructions))(*(Filter(*v) for v in instructions))
    program = Program(len(filters), filters)
    if libc.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise OSError(ctypes.get_errno(), 'Seccomp restriction refused')
