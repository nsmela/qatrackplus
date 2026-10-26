# Your own Python packages

Calculation procedures can use Python packages that QATrack+ does not install
itself, such as pint. List them, one per line, in a file named
`requirements.txt` in this folder, then rebuild the image:

```
pint==0.24.4
```

```bash
docker compose build
docker compose up -d
```

- Pin each version (`==`), so every rebuild installs the same thing.
- QATrack+ already includes numpy, scipy, pandas, matplotlib, pydicom, pylinac
  and others; you don't need to list them. The versions it uses are in `uv.lock`
  at the top of your QATrack+ folder.
- Packages are installed only at versions that work with QATrack+'s own
  dependencies. If one needs a different version of something QATrack+ uses
  (Django, numpy, pylinac, ...), the build stops and says which, rather than
  changing what QATrack+ runs on.
- On a server without internet access, put the packages' `.whl` files in this
  folder too, and add a line `--no-index` at the top of `requirements.txt`.
- Packages that need system libraries the image does not have may fail to build,
  or fail when imported.

`requirements.txt` and any wheel files here are yours: git ignores them, so
`git pull` never changes them. See "Adding Python packages" in the Docker
installation guide for more.
