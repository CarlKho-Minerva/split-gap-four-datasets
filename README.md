# Muscle, Wrist and Scalp Signal Accuracy on Random Windows, Separate Recordings and New People

Code, locked analysis plan, deviations and audits for the paper of the same title by Carl Vincent Kho (2026).

The question: when a program that labels muscle, wrist or scalp signals is tested on windows from people it has already seen, how much higher does its accuracy look than on another recording of the same person, or on a new person? The analysis answers it on four open datasets (EMG Data for Gestures, a wrist stress and exercise dataset, PPG-DaLiA, and the EEG Motor Movement/Imagery Dataset).

- `analysis/`: the analysis script and its configuration. Every number in the paper comes from it.
- `locks/`: the plan as locked before any model was trained.
- `results/`: exported results, predictions and window audits.
- `reproducibility/`: how to rerun it. The raw recordings stay at their own repositories; download them from the URLs in the provenance records.
- `RELEASE_NOTES.md`: what is in this release and what was left out.

Code is MIT licensed (LICENSE). The datasets keep their own licences.
