"""Confined, atomic snapshot and report file exports."""

import asyncio
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExportResult:
    path: Path
    size_bytes: int


class SnapshotExporter:
    """Write bounded artifacts beneath one trusted export root."""

    def __init__(self, root: Path, *, max_bytes: int = 16 * 1024 * 1024) -> None:
        if not root.is_absolute():
            raise ValueError("export root must be an absolute path")
        self._root = root
        self._max_bytes = max_bytes

    def _destination(self, filename: str) -> Path:
        candidate = Path(filename)
        if not filename or candidate.name != filename or candidate.is_absolute():
            raise ValueError("export destination must be a plain filename")
        if not filename.endswith((".json", ".html", ".csv", ".mp4")):
            raise ValueError("export filename extension must be .json, .html, .csv, or .mp4")
        return self._root / filename

    def validate_filename(self, filename: str) -> None:
        """Validate a confined export filename before performing upstream work."""
        self._destination(filename)

    def _write(self, filename: str, data: bytes) -> ExportResult:
        if len(data) > self._max_bytes:
            raise ValueError("export exceeds the maximum supported size")
        destination = self._destination(filename)
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)
        if destination.is_symlink():
            raise ValueError("export destination must not be an existing symlink")

        descriptor, temporary_name = tempfile.mkstemp(prefix=".unifi-export-", dir=self._root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
                os.fchmod(output.fileno(), 0o600)
            os.replace(temporary, destination)
            directory_fd = os.open(self._root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return ExportResult(path=destination, size_bytes=len(data))

    async def write(self, filename: str, data: bytes) -> ExportResult:
        """Write one export without blocking the event loop on filesystem I/O."""
        return await asyncio.to_thread(self._write, filename, data)

    def _read(self, filename: str) -> bytes:
        destination = self._destination(filename)
        if destination.is_symlink():
            raise ValueError("export destination must not be an existing symlink")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(destination, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("export destination must be a regular file")
            if metadata.st_size > self._max_bytes:
                raise ValueError("export exceeds the maximum supported size")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                data = source.read(self._max_bytes + 1)
            if len(data) > self._max_bytes:
                raise ValueError("export exceeds the maximum supported size")
            return data
        finally:
            os.close(descriptor)

    async def read(self, filename: str) -> bytes:
        """Read one confined regular export for checksum verification."""
        return await asyncio.to_thread(self._read, filename)
