"""The install lock reproduces the installed Python tool and application stack."""
from importlib import metadata
from pathlib import Path
import re
from packaging.utils import canonicalize_name


def test_installed_requirements_have_exact_versions_and_hashes():
    lock = Path(__file__).resolve().parents[2] / 'requirements.lock'
    entries = {}
    for line in lock.read_text().replace('\\\n', ' ').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==(\S+)\s+((?:--hash=sha256:[0-9a-f]{64}\s*)+)', line)
        assert match, line
        entries[canonicalize_name(match[1])] = match[2]
    assert entries
    for distribution in metadata.distributions():
        name = canonicalize_name(distribution.metadata['Name'])
        assert entries.get(name) == distribution.version, name
