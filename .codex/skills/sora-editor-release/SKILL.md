---
name: sora-editor-release
description: "Release this repository's Sora Editor and Multi-Server Log Viewer: update versions and changelog, rebuild PyInstaller onedir distributions, verify artifacts, and optionally commit, tag, and push when explicitly authorized."
---

# Sora Editor Release

Use this skill for release, distribution, packaging, version-bump, or rebuild requests for this repository. Do not use it for ordinary source edits or for distributing user configuration files.

## Project invariants

- The two applications are released together and normally share one version.
- Canonical version locations are `text_editor.py`, `ssh_log_viewer.py`, `README.md`, `version_info_sora_editor.txt`, and `version_info_ssh_log_viewer.txt`.
- `dist/` and `build/` are ignored build outputs. Do not stage them as source changes.
- The working distribution is PyInstaller **onedir**, built from the existing local `Sora Editor.spec` and `Multi-Server Log Viewer.spec`. The onefile commands in the README are legacy instructions.
- The `.spec` files are ignored by `.gitignore`, but the local custom specs are required for a correct build. If either is absent, stop and report that rather than regenerating a generic spec without checking its data, icon, and version settings.
- `dist/README.md` is a distribution copy of the repository README and should be refreshed after a version/changelog update.
- Never distribute `sora_settings_*.json` or other user JSON files; they may contain FTP or SSH passwords.
- Keep `paramiko` below 5.1.0 unless the target corporate/FIPS environments have been tested. The current compatible constraint is `paramiko>=5.0.1,<5.1.0`.

## Release workflow

1. Inspect `git status --short --branch`, the current version, recent commit style, remotes, and existing tags. Preserve unrelated user changes.
2. Choose the next version. For a bug fix, increment the patch version unless the user specifies another version.
3. Update both application versions, both Windows version-info files, the README version, and the top changelog entry. Update `requirements.txt` when the release depends on a compatibility pin.
4. Verify the custom spec files exist. Build both applications with the available Python environment:

   ```powershell
   python -m PyInstaller --noconfirm --clean "Sora Editor.spec"
   python -m PyInstaller --noconfirm --clean "Multi-Server Log Viewer.spec"
   ```

   If the normal Python command is unavailable, use an explicitly installed project build environment or ask before downloading/installing one.

5. Run `python -m py_compile text_editor.py ssh_log_viewer.py` and `git diff --check`. Check each EXE's Windows `FileVersion`/`ProductVersion` against the release version. Smoke-test both EXEs; do not leave test processes running.
6. Copy the updated `README.md` to `dist/README.md`. Confirm the distribution root contains the README and both application folders, each with its EXE and `_internal` folder. Exclude settings JSON files.
7. Before external mutation, show the intended file list and release summary. Commit, push, and tag only after the user explicitly authorizes those actions in the current request. Use the repository's convention, e.g. `v1.1.29: fix ...`, then push `main` and an annotated `vX.Y.Z` tag. A GitHub Release page is separate and is not created implicitly.
8. Finish by verifying the clean working tree, `origin/main`, and the pushed tag, and report the commit, tag, version, and distribution paths.

## Failure handling

- If a build fails, do not commit version bumps or publish a partial release. Report the exact failing step and keep the source changes available for repair.
- If a target PC reports an import-time Paramiko error, first verify it is using the complete onedir folder and the expected EXE version. Then retain the `<5.1.0` Paramiko pin and rebuild; do not assume a configuration-file problem.
