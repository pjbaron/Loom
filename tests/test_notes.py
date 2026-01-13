import pytest
import tempfile
import os
from codestore import CodeStore

@pytest.fixture
def cs():
    with tempfile.TemporaryDirectory() as td:
        store = CodeStore(os.path.join(td, 'test.db'))
        # Add some test entities using the add_entity method (which handles IDs properly)
        store.add_entity('test_function', 'function')
        store.add_entity('TestClass', 'class')
        store.add_entity('module.TestClass.method', 'method')
        yield store

def test_add_note(cs):
    note_id = cs.add_note('Test content', note_type='analysis', title='Test')
    assert note_id is not None

def test_add_note_with_link(cs):
    note_id = cs.add_note('Bug in test_function', note_type='bug',
                          linked_entities=['test_function'])
    notes = cs.get_entity_notes('test_function')
    assert len(notes) == 1
    assert notes[0]['id'] == note_id

def test_get_notes_by_type(cs):
    cs.add_note('Analysis 1', note_type='analysis')
    cs.add_note('Bug 1', note_type='bug')
    cs.add_note('Analysis 2', note_type='analysis')

    analysis = cs.get_notes(note_type='analysis')
    bugs = cs.get_notes(note_type='bug')

    assert len(analysis) == 2
    assert len(bugs) == 1

def test_hypothesis_workflow(cs):
    h_id = cs.add_note('I think X is broken', note_type='hypothesis')

    # Check initial status
    notes = cs.get_notes(note_type='hypothesis')
    assert notes[0]['status'] == 'active'

    # Resolve it
    cs.update_note_status(h_id, 'confirmed')
    notes = cs.get_notes(note_type='hypothesis')
    assert notes[0]['status'] == 'confirmed'

def test_note_stats(cs):
    cs.add_note('Analysis', note_type='analysis', linked_entities=['test_function'])
    cs.add_note('Bug', note_type='bug')
    cs.add_note('Hypothesis', note_type='hypothesis')

    stats = cs.get_note_stats()
    assert stats['total'] == 3
    assert stats['linked'] == 1
    assert stats['by_type']['analysis'] == 1
    assert stats['by_type']['bug'] == 1

def test_search_notes(cs):
    cs.add_note('The semantic search has duplicate results', title='Duplicate bug')
    cs.add_note('Performance is slow during ingestion', title='Perf issue')
    cs.generate_embeddings()

    results = cs.search_notes('duplicate')
    assert len(results) > 0
    assert 'duplicate' in results[0]['title'].lower() or 'duplicate' in results[0]['content'].lower()

def test_qualified_entity_linking(cs):
    # Test linking with qualified method name
    note_id = cs.add_note('Issue with method', note_type='bug',
                          linked_entities=['module.TestClass.method'])
    notes = cs.get_entity_notes('module.TestClass.method')
    assert len(notes) == 1


def test_get_note(cs):
    note_id = cs.add_note('Test content', note_type='analysis', title='Test Title')
    note = cs.get_note(note_id)
    assert note is not None
    assert note['content'] == 'Test content'
    assert note['title'] == 'Test Title'
    assert note['type'] == 'analysis'

    # Test non-existent note
    assert cs.get_note('nonexistent-id') is None


def test_update_note_content(cs):
    note_id = cs.add_note('Original content', title='Original title')

    # Update content only
    success = cs.update_note(note_id, content='Updated content')
    assert success

    note = cs.get_note(note_id)
    assert note['content'] == 'Updated content'
    assert note['title'] == 'Original title'  # Unchanged


def test_update_note_title(cs):
    note_id = cs.add_note('Content', title='Old title')

    # Update title only
    success = cs.update_note(note_id, title='New title')
    assert success

    note = cs.get_note(note_id)
    assert note['title'] == 'New title'
    assert note['content'] == 'Content'  # Unchanged


def test_update_note_entities(cs):
    note_id = cs.add_note('Content', linked_entities=['test_function'])

    # Verify initial link
    notes = cs.get_entity_notes('test_function')
    assert len(notes) == 1

    # Add link to TestClass
    cs.update_note(note_id, add_entities=['TestClass'])
    notes = cs.get_entity_notes('TestClass')
    assert len(notes) == 1

    # Remove link from test_function
    cs.update_note(note_id, remove_entities=['test_function'])
    notes = cs.get_entity_notes('test_function')
    assert len(notes) == 0


def test_update_nonexistent_note(cs):
    success = cs.update_note('nonexistent-id', content='New content')
    assert not success


def test_delete_note(cs):
    note_id = cs.add_note('To be deleted', linked_entities=['test_function'])

    # Verify note exists
    note = cs.get_note(note_id)
    assert note is not None

    # Verify link exists
    notes = cs.get_entity_notes('test_function')
    assert any(n['id'] == note_id for n in notes)

    # Delete the note
    success = cs.delete_note(note_id)
    assert success

    # Verify note is gone
    note = cs.get_note(note_id)
    assert note is None

    # Verify link is gone
    notes = cs.get_entity_notes('test_function')
    assert not any(n['id'] == note_id for n in notes)


def test_delete_nonexistent_note(cs):
    success = cs.delete_note('nonexistent-id')
    assert not success


def test_consolidate_notes(cs):
    id1 = cs.add_note('First content', note_type='analysis', title='First')
    id2 = cs.add_note('Second content', note_type='analysis', title='Second')
    id3 = cs.add_note('Third content', note_type='bug', title='Third')

    # Get initial count
    initial_stats = cs.get_note_stats()
    initial_count = initial_stats['total']

    # Consolidate
    new_id = cs.consolidate_notes([id1, id2, id3], 'Consolidated', summarize=True)

    # Verify new note exists
    note = cs.get_note(new_id)
    assert note is not None
    assert note['title'] == 'Consolidated'
    assert 'First content' in note['content']
    assert 'Second content' in note['content']
    assert 'Third content' in note['content']

    # Verify originals are deleted
    assert cs.get_note(id1) is None
    assert cs.get_note(id2) is None
    assert cs.get_note(id3) is None

    # Verify count changed correctly (3 removed, 1 added = -2)
    new_stats = cs.get_note_stats()
    assert new_stats['total'] == initial_count - 2


def test_consolidate_with_entity_links(cs):
    id1 = cs.add_note('Note 1', linked_entities=['test_function'])
    id2 = cs.add_note('Note 2', linked_entities=['TestClass'])

    new_id = cs.consolidate_notes([id1, id2], 'Combined')

    # Verify both entity links transferred
    notes_func = cs.get_entity_notes('test_function')
    notes_class = cs.get_entity_notes('TestClass')

    assert any(n['id'] == new_id for n in notes_func)
    assert any(n['id'] == new_id for n in notes_class)


def test_consolidate_invalid_notes(cs):
    with pytest.raises(ValueError, match="No valid notes"):
        cs.consolidate_notes(['bad-id-1', 'bad-id-2'], 'Should Fail')
