"""Plugin state I/O that never follows a symlink (ADR 0102).

A checkout is untrusted input, and git commits symlinks. So every writer of plugin state goes
through here, whatever the settings say:

* a full write is a temp file in the same directory plus ``os.replace``, which replaces a name and
  never writes through one;
* an append opens with ``O_NOFOLLOW`` and takes regular files only;
* both first refuse a symlink anywhere below ``anchor``, the directory the caller trusts, and a path
  or parent of the wrong type. Links above it are the operator's own: ``/tmp`` and home directories
  often are links.

A refusal is a :class:`StateWriteRefused`, an ``OSError``, so a writer that already survives an
unwritable disk survives this too. It says the checkout's shape is why nothing was written, so a
hook can treat it as a record not kept, where another ``OSError`` is reported. Stdlib only: hooks
import this under a bare ``python3``.
"""

from __future__ import annotations

import errno
import os
import secrets
import stat
from pathlib import Path

__all__ = [
    "StateWriteRefused",
    "append_text",
    "readable",
    "refuse_unsafe",
    "symlink_below",
    "write_bytes",
    "write_text",
]


class StateWriteRefused(OSError):
    """The path crosses a symlink, lies outside its anchor, or is the wrong type. Nothing was
    written."""


def symlink_below(path: Path, anchor: Path) -> Path | None:
    """The first symlink among the components of ``path`` below ``anchor``, or ``None``.

    ``path`` itself is checked and ``anchor`` is not. The walk is lexical, as the OS would take it.
    Raises ``ValueError`` if ``path`` is not under ``anchor``; a ``..`` component counts as that."""
    current = anchor
    for part in path.relative_to(anchor).parts:
        if part == "..":
            raise ValueError(f"{path} leaves {anchor}")
        current = current / part
        if current.is_symlink():
            return current
    return None


def readable(path: Path, anchor: Path) -> bool:
    """True if ``path`` is a regular file reached without crossing a symlink below ``anchor``."""
    try:
        if symlink_below(path, anchor) is not None:
            return False
        return stat.S_ISREG(os.lstat(path).st_mode)
    except (OSError, ValueError):
        return False


def refuse_unsafe(path: Path, anchor: Path) -> None:
    """Raise :class:`StateWriteRefused` unless ``path`` could be written safely: under ``anchor``,
    crossing no symlink below it, and absent or a regular file. Writes nothing."""
    try:
        link = symlink_below(path, anchor)
    except ValueError:
        raise StateWriteRefused(errno.EINVAL, "outside the allowed directory", str(path)) from None
    if link is not None:
        raise StateWriteRefused(errno.ELOOP, "refusing to follow a symlink", str(link))
    try:
        mode = os.lstat(path).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return  # absent; a parent that is not a directory is _prepare's to report
    if not stat.S_ISREG(mode):
        code = errno.EISDIR if stat.S_ISDIR(mode) else errno.EINVAL
        raise StateWriteRefused(code, "not a regular file", str(path))


def _prepare(path: Path, anchor: Path) -> None:
    """Refuse an unsafe ``path``, then create its directory. The check comes first because ``mkdir``
    through a symlinked directory would itself write at the target."""
    refuse_unsafe(path, anchor)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except (FileExistsError, NotADirectoryError):
        raise StateWriteRefused(errno.ENOTDIR, "a parent is not a directory", str(path)) from None


def _final_mode(path: Path) -> int:
    """The mode a replacement of ``path`` should end with: an existing regular file's own, else what
    a new file would get under the umask. The umask can only be read by setting it, hence the
    restrictive value for that instant."""
    try:
        current = os.lstat(path)
        if stat.S_ISREG(current.st_mode):  # a link's own mode is 0o777: not a mode to copy
            return stat.S_IMODE(current.st_mode)
    except FileNotFoundError:
        pass
    umask = os.umask(0o077)
    os.umask(umask)
    return 0o666 & ~umask


def write_bytes(path: Path, data: bytes, *, anchor: Path) -> None:
    """Replace ``path`` atomically with ``data``. A failure leaves ``path`` as it was and no temp
    file behind. The temp file is private until it has its final mode, and that is set before any
    content is written, so a private file's content is never readable under a wider mode. Its name
    has a fixed length, so that a name that fits also fits here, and the directory has to be
    writable, even if the file is."""
    _prepare(path, anchor)
    mode = _final_mode(path)
    tmp = path.with_name(f".af-{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), mode)
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_text(path: Path, text: str, *, anchor: Path) -> None:
    """:func:`write_bytes` for UTF-8 text."""
    write_bytes(path, text.encode("utf-8"), anchor=anchor)


def append_text(path: Path, text: str, *, anchor: Path) -> None:
    """Append ``text`` to ``path``, creating it if absent. ``O_NOFOLLOW`` covers a link that appears
    after the check, and ``O_NONBLOCK`` with the ``fstat`` a pipe that does: an error rather than a
    hung hook."""
    _prepare(path, anchor)
    flags = (
        os.O_WRONLY
        | os.O_APPEND
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(path, flags, 0o666)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise StateWriteRefused(errno.EINVAL, "not a regular file", str(path))
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(text)
