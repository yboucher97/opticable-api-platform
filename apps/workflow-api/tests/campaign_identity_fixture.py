"""Explicit identities for fake campaign tests; no host accounts are required."""
from contextlib import contextmanager
import os
from types import SimpleNamespace
from unittest.mock import patch


@contextmanager
def campaign_identities(module):
    identities = {
        "optibrain": SimpleNamespace(pw_name="optibrain", pw_uid=os.getuid(), pw_gid=os.getgid()),
        "opticable-workflow-api": SimpleNamespace(pw_name="opticable-workflow-api", pw_uid=os.getuid() + 1, pw_gid=os.getgid() + 1),
    }
    # Scope only constructor lookup. Real campaign CLI identity checks are unchanged.
    with patch.object(module.pwd, "getpwnam", side_effect=identities.__getitem__):
        yield
