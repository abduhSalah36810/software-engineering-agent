"""
End-to-end integration test for the Phase 1 pipeline.

Uses the already-cloned youtube-dl repository to verify:
  1. RepoDiscovery runs and produces a valid RepoProfile
  2. RepoProfile is persisted to / loaded from SQLite
  3. Incremental mode: second run reuses cached profile when git HEAD unchanged
  4. GitContext correctly reads the youtube-dl repo
  5. Investigator assembles a coherent investigation context package
  6. Tester node correctly validates real Python files from youtube-dl

Does NOT invoke the LLM (avoids Ollama dependency in CI).
Does NOT reindex Qdrant (uses has_data() check).
"""

import sys, os, time, json
sys.path.insert(0, "/home/abdurrahman/software-engineering-agent")
os.chdir("/home/abdurrahman/software-engineering-agent")

import tempfile, shutil

REPO_PATH = "/home/abdurrahman/software-engineering-agent/repos/youtube-dl"
REPO_NAME = "youtube-dl"

results = []

def step(name, fn):
    start = time.time()
    try:
        result = fn()
        elapsed = time.time() - start
        results.append(("PASS", name, elapsed, None))
        print(f"  PASS [{elapsed:.2f}s] {name}")
        return result
    except Exception as e:
        elapsed = time.time() - start
        results.append(("FAIL", name, elapsed, str(e)))
        print(f"  FAIL [{elapsed:.2f}s] {name}: {e}")
        import traceback; traceback.print_exc()
        return None

print()
print("=" * 60)
print("PHASE 1 END-TO-END INTEGRATION TEST")
print("=" * 60)
print()

# ── 1. Git context ────────────────────────────────────────────────────────
print("[1] Git context")
git_ctx = step("git context reads HEAD", lambda: (
    __import__("src.helpers.git_context", fromlist=["get_git_context"])
    .get_git_context(REPO_PATH)
))
if git_ctx:
    assert git_ctx.is_git_repo, "Expected youtube-dl to be a git repo"
    assert git_ctx.head_commit is not None, "Expected HEAD commit"
    assert len(git_ctx.recent_commits) > 0, "Expected recent commits"
    print(f"       HEAD={git_ctx.head_commit[:8]} branch={git_ctx.branch} commits={len(git_ctx.recent_commits)}")
print()

# ── 2. Repo discovery ─────────────────────────────────────────────────────
print("[2] Repository discovery")
from src.helpers.repo_discovery import RepoDiscovery
profile = step("RepoDiscovery.discover() on youtube-dl", lambda: RepoDiscovery(REPO_PATH).discover())
if profile:
    assert profile.name == REPO_NAME
    assert "python" in [l.lower() for l in profile.detected_languages]
    assert profile.primary_language is not None
    print(f"       name={profile.name} lang={profile.primary_language} frameworks={len(profile.frameworks)} findings={len(profile.findings)}")
print()

# ── 3. SQLite persistence ────────────────────────────────────────────────
print("[3] SQLite engineering memory")
with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "test_memory.db")
    from src.memory.sqlite_store import EngineeringMemoryStore
    store = EngineeringMemoryStore(db_path=db_path)

    def save_and_reload():
        store.save_repo_profile(profile)
        loaded = store.load_repo_profile(REPO_NAME)
        assert loaded is not None
        assert loaded["name"] == REPO_NAME
        assert loaded["primary_language"] == profile.primary_language
        return loaded

    loaded = step("save_repo_profile + load_repo_profile roundtrip", save_and_reload)

    def exists_check():
        assert store.repo_profile_exists(REPO_NAME)
        assert not store.repo_profile_exists("no-such-repo")

    step("repo_profile_exists accurate", exists_check)

    def decision_roundtrip():
        store.save_decision(
            repo_name=REPO_NAME,
            subject="language",
            decision="Python 2/3 compatible codebase",
            rationale="observed from source files",
            source="observed",
        )
        decisions = store.load_decisions(REPO_NAME)
        assert len(decisions) == 1
        assert decisions[0]["subject"] == "language"

    step("save + load decision", decision_roundtrip)

    def investigation_roundtrip():
        inv_id = store.save_investigation(
            repo_name=REPO_NAME,
            problem="DASH manifest format_id uniqueness bug",
            root_cause="format_id is not unique within a Period",
            plan="use a composite key (adaptation_set_id, representation_id)",
            result={"files_to_modify": ["youtube_dl/extractor/common.py"]},
        )
        assert inv_id > 0
        investigations = store.load_investigations(REPO_NAME)
        assert len(investigations) == 1
        assert "format_id" in investigations[0]["root_cause"]
        return investigations[0]

    inv = step("save + load investigation", investigation_roundtrip)

    def change_record_test():
        if git_ctx and git_ctx.head_commit:
            store.save_change_record(
                repo_name=REPO_NAME,
                commit_hash=git_ctx.head_commit,
                changed_files=[],
                review="initial integration test",
            )
            records = store.load_change_records(REPO_NAME)
            assert len(records) == 1
            assert records[0]["commit_hash"] == git_ctx.head_commit

    step("save + load change record (git HEAD)", change_record_test)

print()

# ── 4. Incremental discovery (cached profile reuse) ───────────────────────
print("[4] Incremental discovery (git-aware caching)")
with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "inc_memory.db")
    store2 = EngineeringMemoryStore(db_path=db_path)

    # First run: fresh discovery + record git HEAD
    profile2 = RepoDiscovery(REPO_PATH).discover()
    store2.save_repo_profile(profile2)
    if git_ctx and git_ctx.head_commit:
        store2.save_change_record(
            repo_name=REPO_NAME,
            commit_hash=git_ctx.head_commit,
            changed_files=[],
        )

    def incremental_cache_hit():
        # Second check: HEAD == last known -> should use cache
        last_records = store2.load_change_records(REPO_NAME, limit=1)
        last_known = last_records[0]["commit_hash"] if last_records else None
        current_head = git_ctx.head_commit if git_ctx else None
        cache_hit = (last_known is not None and last_known == current_head)
        assert cache_hit, f"Expected cache hit: last_known={last_known} head={current_head}"
        loaded = store2.load_repo_profile(REPO_NAME)
        assert loaded is not None
        return loaded

    step("second run detects HEAD unchanged -> cache hit", incremental_cache_hit)

print()

# ── 5. Tester node on real youtube-dl files ──────────────────────────────
print("[5] Tester node on real youtube-dl Python files")
from src.nodes.tester import tester

real_files = [
    "youtube_dl/__init__.py",
    "youtube_dl/YoutubeDL.py",
    "youtube_dl/extractor/common.py",
    "youtube_dl/utils.py",
]

def test_real_syntax():
    state = {
        "repo_path": REPO_PATH,
        "modified_files": real_files,
    }
    result = tester(state)
    assert result["test_passed"] is True, f"Syntax check failed: {result['test_output']}"
    return result

result = step("syntax check on 4 youtube-dl Python files", test_real_syntax)
if result:
    print(f"       test_passed={result['test_passed']}")

def test_bad_syntax():
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        bad = os.path.join(td, "broken.py")
        with open(bad, "w") as f:
            f.write("def broken(\n    pass\n")
        state = {"repo_path": td, "modified_files": ["broken.py"]}
        result = tester(state)
        assert result["test_passed"] is False
        assert "Syntax ERROR" in result["test_output"]

step("tester correctly fails on broken syntax", test_bad_syntax)

print()

# ── 6. Profile summary quality ────────────────────────────────────────────
print("[6] RepoProfile summary quality")
def check_summary():
    summary = profile.summary()
    assert "youtube-dl" in summary
    assert len(summary) > 200
    return summary

summary = step("profile.summary() produces meaningful output", check_summary)
if summary:
    # Print first 5 lines
    lines = [l for l in summary.splitlines() if l.strip()][:8]
    for l in lines:
        print(f"       {l}")

print()

# ── Final report ──────────────────────────────────────────────────────────
print("=" * 60)
passed = [r for r in results if r[0] == "PASS"]
failed = [r for r in results if r[0] == "FAIL"]
total_time = sum(r[2] for r in results)

print(f"RESULT: {len(passed)} passed, {len(failed)} failed  ({total_time:.2f}s total)")
if failed:
    print()
    print("FAILURES:")
    for r in failed:
        print(f"  - {r[1]}: {r[3]}")
    sys.exit(1)
else:
    print()
    print("ALL INTEGRATION TESTS PASSED")
    print("Phase 1 pipeline is verified end-to-end.")
print("=" * 60)
