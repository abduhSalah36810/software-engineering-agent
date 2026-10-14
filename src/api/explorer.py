"""Safe, read-only repository browsing endpoints for the frontend explorer."""

from __future__ import annotations

from datetime import datetime, timezone
import errno
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import unicodedata

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from src.api.schemas import (
    ErrorResponse,
    RepositoryDirectoryResponse,
    RepositoryEntry,
    RepositoryFileResponse,
)
from src.api.security import validate_repo_path

router = APIRouter(tags=["repository-explorer"])

MAX_DIRECTORY_PAGE_SIZE = 500
DEFAULT_DIRECTORY_PAGE_SIZE = 200
MAX_TEXT_FILE_BYTES = 256 * 1024

_RESTRICTED_DIRECTORIES = {".git", ".ssh", ".aws", ".gnupg", ".kube"}
_RESTRICTED_FILENAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "secrets.json",
    "service-account.json",
    "id_rsa",
    "id_ed25519",
}
_SAFE_ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template", ".env.defaults"}
_RESTRICTED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def _error(code: str, detail: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=code, detail=detail).model_dump(),
    )


def _repo_root(repo_path: str) -> tuple[Path | None, JSONResponse | None]:
    root, error = validate_repo_path(repo_path)
    if error:
        code, detail, status_code = error
        return None, _error(code, detail, status_code)
    return root, None


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    if "\x00" in relative_path or "\\" in relative_path:
        raise ValueError("Path must use repository-relative POSIX separators")
    posix_path = PurePosixPath(relative_path or ".")
    windows_path = PureWindowsPath(relative_path)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("Absolute paths are not allowed")
    parts = tuple(part for part in posix_path.parts if part not in ("", "."))
    if any(part == ".." for part in posix_path.parts):
        raise ValueError("Parent-directory traversal is not allowed")
    return parts


def _relative_display(parts: tuple[str, ...]) -> str:
    return PurePosixPath(*parts).as_posix() if parts else "."


def _modified_at(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _is_restricted(parts: tuple[str, ...]) -> bool:
    lowered_parts = tuple(part.lower() for part in parts)
    if any(part in _RESTRICTED_DIRECTORIES for part in lowered_parts):
        return True

    name = lowered_parts[-1] if lowered_parts else ""
    if name in _SAFE_ENV_EXAMPLES:
        return False
    if name == ".env" or (name.startswith(".env.") and name not in _SAFE_ENV_EXAMPLES):
        return True
    if name in _RESTRICTED_FILENAMES:
        return True
    if Path(name).suffix in _RESTRICTED_SUFFIXES:
        return True
    return False


def _open_directory(root: Path, parts: tuple[str, ...]) -> int:
    """Open a directory by descriptor, refusing symlinks at every component."""
    if (
        not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or os.open not in os.supports_dir_fd
    ):
        raise OSError(errno.ENOTSUP, "Safe descriptor-based browsing is unavailable")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current_fd = os.open(root, flags)
    try:
        for part in parts:
            component_stat = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(component_stat.st_mode):
                raise OSError(errno.ELOOP, "Symbolic links are not traversable")
            if not stat.S_ISDIR(component_stat.st_mode):
                raise NotADirectoryError(errno.ENOTDIR, "Path component is not a directory", part)
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _os_error_response(exc: OSError, target: str) -> JSONResponse:
    if isinstance(exc, FileNotFoundError):
        return _error("not_found", f"Repository path '{target}' does not exist", 404)
    if isinstance(exc, PermissionError):
        return _error("permission_denied", f"Permission denied while accessing '{target}'", 403)
    if exc.errno == errno.ELOOP:
        return _error("symlink_not_allowed", "Symbolic links cannot be traversed by the repository explorer", 403)
    if exc.errno == errno.ENOTSUP:
        return _error("unsupported_platform", "Safe repository browsing is unavailable on this platform", 501)
    if isinstance(exc, NotADirectoryError):
        return _error("not_a_directory", f"Repository path '{target}' is not a directory", 400)
    return _error("filesystem_error", f"Could not access repository path '{target}'", 500)


def _entry_from_name(directory_fd: int, directory_parts: tuple[str, ...], name: str) -> RepositoryEntry:
    relative_parts = (*directory_parts, name)
    relative_path = _relative_display(relative_parts)

    try:
        entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        # The entry may have been removed between listdir and stat.
        return RepositoryEntry(name=name, relative_path=relative_path, kind="other")

    is_symlink = stat.S_ISLNK(entry_stat.st_mode)
    if is_symlink or _is_restricted(relative_parts):
        return RepositoryEntry(
            name=name,
            relative_path=relative_path,
            kind="restricted",
            is_symlink=is_symlink,
        )

    if stat.S_ISDIR(entry_stat.st_mode):
        kind = "directory"
        size_bytes = None
    elif stat.S_ISREG(entry_stat.st_mode):
        kind = "file"
        size_bytes = entry_stat.st_size
    else:
        kind = "other"
        size_bytes = None

    return RepositoryEntry(
        name=name,
        relative_path=relative_path,
        kind=kind,
        size_bytes=size_bytes,
        modified_at=_modified_at(entry_stat.st_mtime),
        is_symlink=False,
    )


@router.get(
    "/tree",
    response_model=RepositoryDirectoryResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        501: {"model": ErrorResponse},
    },
)
def list_repository_directory(
    repo_path: str = Query(..., description="Authorized repository root path"),
    relative_path: str = Query(".", description="Repository-relative directory path"),
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_DIRECTORY_PAGE_SIZE, ge=1, le=MAX_DIRECTORY_PAGE_SIZE),
):
    root, error_response = _repo_root(repo_path)
    if error_response:
        return error_response
    assert root is not None

    try:
        parts = _relative_parts(relative_path)
    except ValueError as exc:
        return _error("invalid_relative_path", str(exc), 400)

    normalized_path = _relative_display(parts)
    if _is_restricted(parts):
        return _error("restricted_path", "This repository path is not available in the explorer", 403)

    directory_fd: int | None = None
    try:
        directory_fd = _open_directory(root, parts)
        names = os.listdir(directory_fd)
        all_entries = [_entry_from_name(directory_fd, parts, name) for name in names]
        all_entries.sort(key=lambda entry: (entry.kind != "directory", entry.name.casefold(), entry.name))
        page = all_entries[offset : offset + limit]
        next_offset = offset + limit if offset + limit < len(all_entries) else None
        parent_parts = parts[:-1]
        return RepositoryDirectoryResponse(
            repo_path=str(root),
            relative_path=normalized_path,
            parent_path=_relative_display(parent_parts) if parts else None,
            entries=page,
            total_entries=len(all_entries),
            next_offset=next_offset,
        )
    except OSError as exc:
        return _os_error_response(exc, normalized_path)
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


@router.get(
    "/file",
    response_model=RepositoryFileResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        501: {"model": ErrorResponse},
    },
)
def read_repository_text_file(
    repo_path: str = Query(..., description="Authorized repository root path"),
    file_path: str = Query(..., description="Repository-relative text file path"),
):
    root, error_response = _repo_root(repo_path)
    if error_response:
        return error_response
    assert root is not None

    try:
        parts = _relative_parts(file_path)
    except ValueError as exc:
        return _error("invalid_relative_path", str(exc), 400)
    if not parts:
        return _error("not_a_file", "A repository-relative file path is required", 400)
    if _is_restricted(parts):
        return _error("restricted_file", "This file is not available in the explorer", 403)

    normalized_path = _relative_display(parts)
    parent_fd: int | None = None
    file_fd: int | None = None
    try:
        parent_fd = _open_directory(root, parts[:-1])
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            if stat.S_ISDIR(file_stat.st_mode):
                return _error("not_a_file", "Directories cannot be previewed as files", 400)
            return _error("unsupported_file", "Only regular text files can be previewed", 415)
        if file_stat.st_size > MAX_TEXT_FILE_BYTES:
            return _error(
                "file_too_large",
                f"Files larger than {MAX_TEXT_FILE_BYTES} bytes cannot be previewed",
                413,
            )

        chunks: list[bytes] = []
        bytes_remaining = MAX_TEXT_FILE_BYTES + 1
        while bytes_remaining:
            chunk = os.read(file_fd, min(64 * 1024, bytes_remaining))
            if not chunk:
                break
            chunks.append(chunk)
            bytes_remaining -= len(chunk)
        file_bytes = b"".join(chunks)
        if len(file_bytes) > MAX_TEXT_FILE_BYTES:
            return _error(
                "file_too_large",
                f"Files larger than {MAX_TEXT_FILE_BYTES} bytes cannot be previewed",
                413,
            )
        if b"\x00" in file_bytes:
            return _error("unsupported_file", "Binary files cannot be previewed", 415)
        try:
            content = file_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _error("unsupported_file", "Only UTF-8 text files can be previewed", 415)
        if any(unicodedata.category(char) == "Cc" and char not in "\t\n\r\f" for char in content):
            return _error("unsupported_file", "Files containing binary control data cannot be previewed", 415)

        return RepositoryFileResponse(
            repo_path=str(root),
            relative_path=normalized_path,
            name=parts[-1],
            size_bytes=file_stat.st_size,
            modified_at=_modified_at(file_stat.st_mtime),
            content=content,
        )
    except OSError as exc:
        return _os_error_response(exc, normalized_path)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if parent_fd is not None:
            os.close(parent_fd)
