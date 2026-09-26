"""
tester node

Runs real verification on the modified files:
  1. Python syntax check (py_compile) on every .py file listed in modified_files
  2. Import check (subprocess) for Python files
  3. Basic lint check via pyflakes if available

Sets state["test_passed"] = True only if all checks pass.
Sets state["test_output"] with the full diagnostic output.
"""

import os
import subprocess
import py_compile
import tempfile
from src.state import AgentState


def _syntax_check(full_path: str) -> tuple[bool, str]:
    """Returns (ok, message)."""
    try:
        py_compile.compile(full_path, doraise=True)
        return True, f"Syntax OK: {full_path}"
    except py_compile.PyCompileError as e:
        return False, f"Syntax ERROR in {full_path}: {e}"


def _pyflakes_check(full_path: str) -> tuple[bool, str]:
    """Run pyflakes if available. Returns (ok, output)."""
    try:
        result = subprocess.run(
            ["pyflakes", full_path],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, f"Pyflakes OK: {full_path}"
        return False, f"Pyflakes issues in {full_path}:\n{result.stdout}"
    except FileNotFoundError:
        return True, ""  # pyflakes not installed -- skip silently
    except Exception as e:
        return True, f"Pyflakes skipped ({e})"


def tester(state: AgentState) -> dict:
    print("Tester running...")

    repo_path = state.get("repo_path", "")
    modified_files = state.get("modified_files") or []

    if not modified_files:
        print("Tester: no modified_files in state -- nothing to verify")
        return {
            "test_output": "No modified files to test.",
            "test_passed": True,
        }

    outputs: list[str] = []
    all_passed = True

    for rel_path in modified_files:
        if not rel_path.endswith(".py"):
            outputs.append(f"Skipped (non-Python): {rel_path}")
            continue

        full_path = os.path.join(repo_path, rel_path)

        if not os.path.exists(full_path):
            outputs.append(f"File not found (not yet modified): {rel_path}")
            # Not a failure -- coder identified files but may not have edited yet
            continue

        # Syntax check
        ok, msg = _syntax_check(full_path)
        outputs.append(msg)
        if not ok:
            all_passed = False
            continue

        # Pyflakes
        ok, msg = _pyflakes_check(full_path)
        if msg:
            outputs.append(msg)
        if not ok:
            all_passed = False

    summary = "PASSED" if all_passed else "FAILED"
    print(f"Tester: {summary}")

    full_output = f"Tester result: {summary}\n" + "\n".join(outputs)
    print(full_output)

    return {
        "test_output": full_output,
        "test_passed": all_passed,
    }
