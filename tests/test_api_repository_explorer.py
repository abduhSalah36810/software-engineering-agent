from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def explorer_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALLOWED_REPO_ROOTS", str(tmp_path))
    repo = tmp_path / "sample-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "README.md").write_text("# Sample repository\n", encoding="utf-8")
    (repo / ".env").write_text("TOKEN=do-not-return\n", encoding="utf-8")
    (repo / "large.txt").write_bytes(b"x" * (256 * 1024 + 1))
    (repo / "image.bin").write_bytes(b"\x00\x01\x02")
    return TestClient(app), repo


def test_directory_listing_returns_real_children_and_metadata(explorer_client):
    client, repo = explorer_client

    response = client.get("/api/project/tree", params={"repo_path": str(repo)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["repo_path"] == str(repo.resolve())
    assert payload["relative_path"] == "."
    assert payload["parent_path"] is None
    assert payload["total_entries"] == 5
    entries = {entry["name"]: entry for entry in payload["entries"]}
    assert entries["src"]["kind"] == "directory"
    assert entries["README.md"]["kind"] == "file"
    assert entries["README.md"]["size_bytes"] == len(b"# Sample repository\n")
    assert entries["README.md"]["modified_at"].endswith("Z")
    assert entries[".env"]["kind"] == "restricted"


def test_directory_listing_supports_relative_navigation_and_pagination(explorer_client):
    client, repo = explorer_client
    (repo / "src" / "another.py").write_text("pass\n", encoding="utf-8")

    first_page = client.get(
        "/api/project/tree",
        params={"repo_path": str(repo), "relative_path": "src", "limit": 1},
    )
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["relative_path"] == "src"
    assert first_payload["parent_path"] == "."
    assert first_payload["total_entries"] == 2
    assert first_payload["next_offset"] == 1

    second_page = client.get(
        "/api/project/tree",
        params={
            "repo_path": str(repo),
            "relative_path": "src",
            "limit": 1,
            "offset": first_payload["next_offset"],
        },
    )
    assert second_page.status_code == 200
    assert second_page.json()["next_offset"] is None
    assert len(second_page.json()["entries"]) == 1


def test_file_preview_returns_utf8_text_and_metadata(explorer_client):
    client, repo = explorer_client

    response = client.get(
        "/api/project/file",
        params={"repo_path": str(repo), "file_path": "src/hello.py"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "print('hello')\n"
    assert response.json()["relative_path"] == "src/hello.py"
    assert response.json()["size_bytes"] == len(b"print('hello')\n")


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "C:/Windows/win.ini", "src\\hello.py"])
def test_browsing_rejects_non_relative_paths(explorer_client, path):
    client, repo = explorer_client

    response = client.get(
        "/api/project/file",
        params={"repo_path": str(repo), "file_path": path},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_relative_path"


def test_browsing_rejects_symlinks(explorer_client, tmp_path: Path):
    client, repo = explorer_client
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("not part of the repo", encoding="utf-8")
    try:
        (repo / "outside-link").symlink_to(outside, target_is_directory=True)
        (repo / "private-link.txt").symlink_to(outside / "private.txt")
    except OSError:
        pytest.skip("Symlink creation is not supported in this environment")

    listing = client.get("/api/project/tree", params={"repo_path": str(repo)})
    assert listing.status_code == 200
    entry = next(item for item in listing.json()["entries"] if item["name"] == "outside-link")
    assert entry["kind"] == "restricted"
    assert entry["is_symlink"] is True

    traversal = client.get(
        "/api/project/tree",
        params={"repo_path": str(repo), "relative_path": "outside-link"},
    )
    assert traversal.status_code == 403

    preview = client.get(
        "/api/project/file",
        params={"repo_path": str(repo), "file_path": "private-link.txt"},
    )
    assert preview.status_code == 403


def test_preview_rejects_directories_secrets_binary_and_oversized_files(explorer_client):
    client, repo = explorer_client

    directory = client.get(
        "/api/project/file",
        params={"repo_path": str(repo), "file_path": "src"},
    )
    assert directory.status_code == 400
    assert directory.json()["error"] == "not_a_file"

    secret = client.get(
        "/api/project/file",
        params={"repo_path": str(repo), "file_path": ".env"},
    )
    assert secret.status_code == 403

    binary = client.get(
        "/api/project/file",
        params={"repo_path": str(repo), "file_path": "image.bin"},
    )
    assert binary.status_code == 415

    oversized = client.get(
        "/api/project/file",
        params={"repo_path": str(repo), "file_path": "large.txt"},
    )
    assert oversized.status_code == 413


def test_browsing_enforces_authorized_repository_roots(explorer_client, tmp_path: Path):
    client, repo = explorer_client
    outside_repo = tmp_path.parent / "outside-repo"
    outside_repo.mkdir()

    response = client.get("/api/project/tree", params={"repo_path": str(outside_repo)})

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
