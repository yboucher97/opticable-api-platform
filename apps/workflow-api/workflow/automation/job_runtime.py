"""Per-job kernel lock. A stale pathname is harmless; lock dies with process."""
from contextlib import contextmanager
import fcntl,os,stat

@contextmanager
def job_lock(path):
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    held=False
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid()
                or stat.S_IMODE(info.st_mode)!=0o600):raise ValueError('Untrusted job lock')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);held=True
        except BlockingIOError:pass
        yield held
    finally:os.close(fd)
