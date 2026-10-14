"""
Security boundaries and repository access validation for the API layer.

Ensures that the API cannot be used as an arbitrary filesystem explorer
or to inspect paths outside of explicitly permitted roots.
"""

import os
import re
from pathlib import Path


def get_allowed_repo_roots() -> list[Path]:
    """
    Determines permitted filesystem roots for repository inspection.

    Allowed roots:
      1. Explicitly configured ALLOWED_REPO_ROOTS environment variable
         (colon, semicolon, or comma delimited).
      2. The cloned repos directory configured by PATH_TO_CLONED_REPO
         (defaults to ./repos).
      3. The current workspace / application root directory.
    """
    roots: list[Path] = []

    # 1. Explicit environment variable override
    env_roots = os.getenv("ALLOWED_REPO_ROOTS")
    if env_roots:
        for r in re.split(r"[:;,]", env_roots):
            r_clean = r.strip()
            if r_clean:
                try:
                    p = Path(r_clean).resolve()
                    if p.exists() and p.is_dir():
                        roots.append(p)
                except Exception:
                    pass

    # 2. Cloned repositories storage location
    cloned_base = os.getenv("PATH_TO_CLONED_REPO", "./repos")
    try:
        p_cloned = Path(cloned_base).resolve()
        if p_cloned.exists() and p_cloned.is_dir():
            roots.append(p_cloned)
    except Exception:
        pass

    # 3. Current working directory / workspace root
    try:
        cwd = Path.cwd().resolve()
        roots.append(cwd)
    except Exception:
        pass

    # Deduplicate while preserving resolution order
    seen: set[Path] = set()
    deduped: list[Path] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            deduped.append(r)

    return deduped


def validate_repo_path(repo_path: str | None) -> tuple[Path | None, tuple[str, str, int] | None]:
    """
    Validates and canonicalizes an untrusted repo_path input.

    Returns:
        (resolved_path, None) on success.
        (None, (error_code, error_message, http_status_code)) on validation failure.
    """
    if not repo_path or not repo_path.strip():
        return None, ("missing_parameter", "Query parameter 'repo_path' is required", 400)

    # Disallow null bytes
    if "chr(0)" in repo_path:
        return None, ("invalid_path", "Repository path contains invalid characters", 400)

    try:
        resolved = Path(repo_path.strip()).resolve()
    except Exception:
        return None, ("invalid_path", "Could not resolve repository path", 400)

    if not resolved.exists():
        return None, ("not_found", "Repository directory does not exist", 404)

    if not resolved.is_dir():
        return None, ("not_a_directory", "Repository path must be a directory", 400)

    allowed_roots = get_allowed_repo_roots()
    is_allowed = any(resolved == root or resolved.is_relative_to(root) for root in allowed_roots)

    if not is_allowed:
        return None, ("forbidden", "Repository path is outside permitted repository roots", 403)

    return resolved, None
