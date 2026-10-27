
from pathlib import Path

path = Path("tests/test_phase7_persistence.py")
source = path.read_text(encoding="utf-8")

old_import = "from memory_assistant.ai import process_note"
new_import = (
    "from memory_assistant.ai import process_note\n"
    "from memory_assistant.pipeline import prepare_schema"
)

old_setup = """        storage.init_db()
        init_jobs()"""

new_setup = """        storage.init_db()
        prepare_schema()
        init_jobs()"""

if source.count(old_import) != 1:
    raise SystemExit("Import not found exactly once. No changes made.")

if source.count(old_setup) != 1:
    raise SystemExit("Test setup not found exactly once. No changes made.")

source = source.replace(old_import, new_import, 1)
source = source.replace(old_setup, new_setup, 1)

compile(source, str(path), "exec")
path.write_text(source, encoding="utf-8")

print("Phase 7 test schema initialization fixed.")

