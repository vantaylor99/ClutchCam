description: Stop Python bytecode artifacts from dirtying the working tree
prereq: 
files: .gitignore, ai-stream-director/src/__pycache__/, ai-stream-director/tests/__pycache__/
----
Running the local Python test suite on the dev machine modified tracked
`__pycache__/*.pyc` files under `ai-stream-director/src/` and
`ai-stream-director/tests/`. Generated Python bytecode should not appear as
source changes after normal validation.

Expected behavior:

- `__pycache__/` and `*.pyc` files should be ignored.
- Any currently tracked Python bytecode artifacts should be removed from source
  control without deleting source files.
- After running `python -m unittest discover -s tests -v`, `git status` should
  not show modified Python bytecode files.
