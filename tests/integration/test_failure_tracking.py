#!/usr/bin/env python3
"""
Integration test: Simulate debugging a function with failure tracking.
"""
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd):
    """Run a shell command and return output."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def test_workflow():
    """Test a complete debugging workflow with failure tracking."""

    print("\n=== Integration Test: Failure Tracking Workflow ===")

    # 1. Log first failed attempt
    print("\n1. Logging first failed attempt...")
    stdout, stderr, code = run_cmd(
        './loom failure-log "Tried using dict.get() with default value" '
        '--context "KeyError when processing user data" '
        '--file "user_processor.py" '
        '--entity "process_user" '
        '--reason "Still crashes on nested missing keys" '
        '--tag "bug"'
    )
    assert code == 0, f"Failed to log first attempt: {stderr}"
    print(stdout)

    # 2. Log second failed attempt
    print("\n2. Logging second failed attempt...")
    stdout, stderr, code = run_cmd(
        './loom failure-log "Added try/except KeyError block" '
        '--context "KeyError when processing user data" '
        '--file "user_processor.py" '
        '--entity "process_user" '
        '--reason "Too broad, catches unrelated errors" '
        '--tag "bug"'
    )
    assert code == 0, f"Failed to log second attempt: {stderr}"
    print(stdout)

    # 3. Log third failed attempt
    print("\n3. Logging third failed attempt...")
    stdout, stderr, code = run_cmd(
        './loom failure-log "Used hasattr() before accessing" '
        '--file "user_processor.py" '
        '--entity "process_user" '
        '--reason "Doesn\'t work for dict keys, only attributes" '
        '--tag "bug" '
        '--tag "learning"'
    )
    assert code == 0, f"Failed to log third attempt: {stderr}"
    print(stdout)

    # 4. Query what we've tried for this function
    # Note: The CLI uses 'attempted-fixes' directly without 'query' subcommand
    print("\n4. Checking what we've tried for process_user...")
    stdout, stderr, code = run_cmd(
        './loom attempted-fixes --entity "process_user"'
    )
    assert code == 0, f"Failed to query: {stderr}"
    print(stdout)
    assert "dict.get()" in stdout, f"Expected 'dict.get()' in output, got: {stdout}"
    assert "try/except" in stdout, f"Expected 'try/except' in output, got: {stdout}"
    assert "hasattr()" in stdout, f"Expected 'hasattr()' in output, got: {stdout}"

    # 5. Query by file
    print("\n5. Checking all attempts for user_processor.py...")
    stdout, stderr, code = run_cmd(
        './loom attempted-fixes --file "user_processor.py"'
    )
    assert code == 0, f"Failed to query by file: {stderr}"
    print(stdout)

    # 6. Query by tag
    print("\n6. Checking attempts tagged as 'bug'...")
    stdout, stderr, code = run_cmd(
        './loom attempted-fixes --tag "bug"'
    )
    assert code == 0, f"Failed to query by tag: {stderr}"
    print(stdout)

    # 7. Check recent failures
    print("\n7. Checking recent failures...")
    stdout, stderr, code = run_cmd(
        './loom attempted-fixes recent --days 1'
    )
    assert code == 0, f"Failed to get recent: {stderr}"
    print(stdout)

    # 8. Test Python API
    print("\n8. Testing Python API...")
    test_python_api = '''
import sys
sys.path.insert(0, ".")
from loom_tools import what_have_we_tried, recent_failures

print("\\nWhat we tried for process_user:")
print(what_have_we_tried(entity="process_user"))

print("\\nRecent failures:")
print(recent_failures(days=1))
'''
    result = subprocess.run(
        [sys.executable, "-c", test_python_api],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Python API test failed: {result.stderr}"
    print(result.stdout)

    print("\n=== All integration tests passed ===")


if __name__ == "__main__":
    test_workflow()
