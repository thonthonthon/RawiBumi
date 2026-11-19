"""Skip reasons for development-history and private-evidence dependencies."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def missing_git(root=ROOT):
    try:
        result = subprocess.run(['git', '--no-optional-locks', 'rev-parse', '--is-inside-work-tree'],
                                cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        return 'needs a git work tree (absent from a source tarball)'
    if result.returncode or result.stdout.strip() != 'true':
        return 'needs a git work tree (absent from a source tarball)'
    return None


def missing_commit(commit, root=ROOT):
    if reason := missing_git(root):
        return reason
    result = subprocess.run(['git', '--no-optional-locks', 'cat-file', '-e', f'{commit}^{{commit}}'],
                            cwd=root, capture_output=True)
    if result.returncode:
        return f'needs commit {commit} (development history; absent from the public export)'
    return None


def missing_private_path(path, root=ROOT):
    if not (root / path).exists():
        return f'needs private file {path}'
    return None
