# Local code and audit release candidate

This is a private, versioned release candidate, not a public release or a submission package. Author approval, public posting and a software-licence decision remain pending. Do not describe the local archive as a public URL.

## Environment

`environment.lock.json` records the Python version and installed package versions used for the analysis. `requirements.lock` pins that environment. The analysis checks those versions before training and checks that the imported toolkit matches the bundled source hash. `vendor/np_pipeline/kit.py` is a byte-preserved copy of the toolkit, not a replacement for the pipeline's review gates. Its two internal bookkeeping hooks are used to register audit outputs and snapshot the already reported numbers; the copy is pinned so their implementation is auditable.

With the Python version in `environment.lock.json`, from the candidate root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r reproducibility/requirements.lock
```

## Data

Raw recordings and archive files are not included in the code/audit archive. Download the original archives at the URLs in `topic.json`, placing them at the exact `data/raw/<key>/<archive-name>` paths in `provenance.json`. Check every archive against the recorded SHA256 before extraction.

Extract each archive under its dataset's `data/raw/<key>/extracted/` folder. For PPG-DaLiA, extract only the outer archive: the analysis reads the synchronised per-person pickles directly from `data/raw/ppg/extracted/data.zip` with the restricted array-only loader. Do not substitute unsynchronised raw wrist exports. Keep the EEG `files/` directory and the original EMG/stress top-level directories exactly as contained in the archives. Original dataset documentation is included as attribution and structure evidence.

## Reproduce

```bash
.venv/bin/python reproducibility/verify.py --data
bash reproducibility/reproduce.sh
```

The runner imports the bundled toolkit, executes the same analysis and then verifies its outputs. No GPU, external model call, account creation or publication is involved. All random design values come from `analysis/config.json`. Within the authoring pipeline, run `npctl analyze .` instead; both routes must use the identical toolkit source.

## Inspect provenance and determinism

- `reproducibility/prereg_locked.md` and `reproducibility/config_locked.json` preserve the original Git-tagged plan and configuration used by the reproduction scripts. The candidate also has pipeline-generated copies at `locks/prereg_locked.md` and `locks/config_locked.json`, with their lock record at `locks/lock.json`.
- The current `analysis/config.json` retains the previously disclosed display constants so numeric macros remain unchanged. Current figure styling is separate in `analysis/figure_style.json`, read through `kit.style()`; the display constants are not new statistical choices.
- `deviations.json` records parser, display and reproducibility-bookkeeping changes.
- `results/manifest.json` is written by the toolkit and hashes the numeric LaTeX macros, generated tables/figure and registered audit outputs.
- `results/reproducibility_manifest.json` hashes analysis and reader code, toolkit copy, environment pins and locked-plan snapshots.
- `results/stable_numbers.json` is the deterministic numeric record without a clock timestamp. Its values must match the toolkit's `results/results.json` numbers exactly.
- `results/*_predictions.json` and `results/*_windows.json` map predictions back to selected training/query indices and raw-file time spans.
- Toolkit result/manifest timestamps, the control-program run log and `results/execution_metadata.json` describe an execution, not a scientific result. Wall-clock time is not a paper macro or part of the deterministic numeric fingerprint.

`verify.py` checks hashes, not the correctness of the statistical design. The independent reviews and manuscript limitations should be read separately.

## Staging is an author-workspace operation

Reproducing a candidate requires only the commands under Reproduce. Do not run `reproducibility/make_release.py` from a candidate root. That helper is retained as author-workspace tooling and requires the manuscript and its built PDF, bibliography and template, which the code/audit candidate intentionally excludes. It now checks for those files and stops with an author-workspace explanation if they are absent.

The revision workflow stages the code/audit candidate after the manuscript gate passes. It includes code, generated numbers/tables/figures, dependencies, original locks, data provenance/documentation and audits, but not the manuscript or its PDF. The follow-on script creates `MANIFEST.json`, `PUBLISH.md` and the `release/candidate.json` pointer; these are staging records, not publication.

In a complete authoring workspace only, after its manuscript gate passes, run `.venv/bin/python reproducibility/make_release.py`. This separate helper builds a content-versioned author-workspace archive that also includes the manuscript. It is not a supported candidate-root operation or the code/audit candidate built by the revision workflow. Neither route uploads anything or marks the paper approved. `npctl package` remains the separate author-review workflow.
