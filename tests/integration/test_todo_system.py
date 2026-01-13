"""Integration test: Simulate discovering and managing work via TODO system."""

import subprocess
import sys
import re

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def extract_todo_id(output):
    """Extract TODO ID from CLI output like 'Added TODO #8: ...'"""
    match = re.search(r'#(\d+)', output)
    return int(match.group(1)) if match else None

def test_workflow():
    print("\n=== Integration Test: TODO System Workflow ===")

    # 0. Clean up any existing TODOs for a fresh start
    print("\n0. Cleaning up existing TODOs...")
    cleanup_code = '''
import sys
sys.path.insert(0, ".")
from codestore import CodeStore
store = CodeStore('.loom/store.db')
store.conn.execute('DELETE FROM todos')
store.conn.commit()
store.close()
print("Cleared existing TODOs")
'''
    subprocess.run([sys.executable, '-c', cleanup_code], capture_output=True, text=True)

    # 1. Start with empty queue
    print("\n1. Checking initial state...")
    stdout, _, code = run_cmd('./loom todo stats')
    print(stdout)
    assert 'Pending:     0' in stdout

    # 2. Add several TODOs via CLI
    print("\n2. Adding TODOs via CLI...")
    stdout1, _, _ = run_cmd('./loom todo add "Fix JSON parser" --prompt "Handle nested arrays" --tag bug')
    print(stdout1)
    todo_id_1 = extract_todo_id(stdout1)

    stdout2, _, _ = run_cmd('./loom todo add "Add input validation" --prompt "Validate user data" --tag feature')
    print(stdout2)
    todo_id_2 = extract_todo_id(stdout2)

    stdout3, _, _ = run_cmd('./loom todo add "Update docs" --prompt "Document new API" --tag docs')
    print(stdout3)
    todo_id_3 = extract_todo_id(stdout3)

    print(f"  Created TODOs: #{todo_id_1}, #{todo_id_2}, #{todo_id_3}")

    # 3. List the queue
    print("\n3. Listing TODO queue...")
    stdout, _, _ = run_cmd('./loom todo list')
    print(stdout)
    assert 'JSON parser' in stdout

    # 4. Check what's next
    print("\n4. Getting next TODO...")
    stdout, _, _ = run_cmd('./loom todo next')
    print(stdout)
    assert 'JSON parser' in stdout  # Should be first (FIFO)

    # 5. Add via Python API
    print("\n5. Adding TODO via Python API...")
    test_code = '''
import sys
sys.path.insert(0, ".")
from loom_tools import add_todo, get_todos

id = add_todo("Write tests", "Add unit tests for parser", tags=["test"])
print(f"Added TODO #{id}")
print(get_todos())
'''
    result = subprocess.run([sys.executable, '-c', test_code], capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("stderr:", result.stderr)
    assert result.returncode == 0

    # 6. Start and complete the first TODO
    print("\n6. Starting and completing first TODO...")
    run_cmd(f'./loom todo start {todo_id_1}')
    stdout, _, _ = run_cmd(f'./loom todo done {todo_id_1} --notes "Fixed nested array handling"')
    print(stdout)
    assert 'Completed' in stdout

    # 7. Verify it's marked complete and next item advanced
    print("\n7. Verifying queue state...")
    stdout, _, _ = run_cmd('./loom todo next')
    print(stdout)
    assert 'JSON parser' not in stdout  # Should have moved on to next TODO
    assert 'input validation' in stdout.lower() or 'Add input validation' in stdout

    # 8. Test combining TODOs
    print("\n8. Adding and combining related TODOs...")
    stdout5, _, _ = run_cmd('./loom todo add "Fix validation bug" --prompt "Edge case in validation" --tag bug')
    print(stdout5)
    todo_id_5 = extract_todo_id(stdout5)

    # List before combine
    stdout, _, _ = run_cmd('./loom todo list --all')
    print("Before combine:")
    print(stdout)

    # Combine the two validation-related items (todo_id_2 and todo_id_5)
    stdout, _, _ = run_cmd(f'./loom todo combine {todo_id_2} {todo_id_5} --title "Validation improvements"')
    print(stdout)

    stdout, _, _ = run_cmd('./loom todo list --all')
    print("After combine:")
    print(stdout)
    # The combined TODO should show "Validation improvements" or the merge should be reflected
    assert 'Validation' in stdout

    # 9. Final stats
    print("\n9. Final stats...")
    stdout, _, _ = run_cmd('./loom todo stats')
    print(stdout)
    # Should have: 1 completed, some pending, some combined
    assert 'Completed:   1' in stdout

    print("\n=== All integration tests passed ===")

if __name__ == "__main__":
    test_workflow()
