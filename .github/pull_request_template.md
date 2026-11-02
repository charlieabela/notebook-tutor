## What changes and why

<!-- One or two sentences: the problem, and what this pull request does about it. -->

## Effect on students

<!-- What students see or must do (git pull, reinstall, a changed button or message). Do notebooks they already added still open and run? Write "none" if nothing changes for them. -->

## Checked

- [ ] Server, kernel and kit tests pass (`pytest -q --ignore=tests/test_ui.py`)
- [ ] Page tests in a headless browser pass (`pytest -q tests/test_ui.py`), with screenshots looked at if the page changed
- [ ] The ai-learning-kit version it bundles (`pyproject.toml`) exists as a release, and the version is bumped in `pyproject.toml`, `__init__.py` and the README install lines
- [ ] A real session notebook run through the tutor, if the kernel, data or notebook handling changed (say which)
- [ ] No links to Drive, OneDrive or SharePoint, no personal data, no attribution lines

## Not verified

<!-- What could not be run or checked, and why. Write "nothing" if everything was checked. -->

## After merging

- [ ] Release `vX.Y.Z` on main (Releases › Draft a new release › tag `vX.Y.Z`, *Create new tag on publish*, target `main`)
- [ ] `git pull` in your own clone; tell students to do the same if the effect above is not "none"
