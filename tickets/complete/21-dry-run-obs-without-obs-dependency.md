description: Completed dry-run OBS import without obsws-python dependency
prereq: 
files: ai-stream-director/src/obs_controller.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/README.md
----
Dry-run OBS mode can now import and run without `obsws-python` installed.

Built:

- Removed the module-scope `obsws_python` import from `obs_controller.py`.
- Added lazy loading of `obsws_python` inside the real `OBSController.connect()`
  path.
- Converted a missing real OBS dependency into a clear `RuntimeError` that
  points to installing requirements or setting `DRY_RUN_OBS=true`.
- Kept `DryRunOBSController` standard-library-only.
- Added import-isolation tests that simulate missing `obsws_python` while
  importing `obs_controller` and `main`, then exercising dry-run connect/switch.
- Added a real OBS missing-dependency test for the lazy import error.
- Updated README dry-run wording to explain that dry-run does not require
  `obsws-python`, while real OBS mode does.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_dry_run_obs -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
git diff --check
```

Result:

- Targeted dry-run tests: 17 passed.
- Full Python unit suite: 76 passed.
- `git diff --check`: passed; only CRLF normalization warnings were reported.
