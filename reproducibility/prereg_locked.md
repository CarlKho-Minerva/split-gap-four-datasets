# Question

For within-participant-varying biosignal labels, how much higher is accuracy with randomly divided overlapping windows than with another recording of the same person or an unseen person, on identical query windows and with matched per-class training counts? The datasets are EMG Data for Gestures, Wearable Device Dataset from Induced Stress and Structured Exercise Sessions, PPG-DaLiA, and EEG Motor Movement/Imagery Dataset.

This is a conditional, finite-benchmark comparison, not an estimate of all published random-split protocols. Random training is participant-local; new-person training is pooled from the other eligible participants and randomly size-matched. Do not call the gap a causal effect of overlap alone.

## Prior-work check before locking

Searches through npctl covered overlap and subject-dependent wearable evaluation, EEG identity leakage, cross-validation, and EMG session evaluation. Retrieved abstracts describe overlapping versus non-overlapping subject-dependent/independent inertial activity evaluation (Dehghani), segment versus person holdout on disease/seizure EEG datasets (Brookshire), and replicated identity structure and clinical EEG leakage (Ugail). They already establish related evaluation problems. None of these abstracts describes the present matched-training-count, common-query comparison across EMG gestures, wrist session/activity labels and left/right imagery, including same-person recording holdout. We therefore proceed with this narrower extension, without claiming discovery of leakage or first multi-dataset evidence. This check is limited to retrieved abstracts, not an exhaustive novelty guarantee.

# Hypotheses

Six directional primary hypotheses, using the nearest-neighbour classifier:

- H-EMG-recording: mean random minus other-recording accuracy exceeds the configured positive equivalence margin.
- H-EMG-person: mean random minus unseen-person accuracy exceeds that margin.
- H-stress-person: mean random minus unseen-person accuracy exceeds that margin.
- H-PPG-person: mean random minus unseen-person accuracy exceeds that margin.
- H-EEG-recording: mean random minus other-recording accuracy exceeds that margin.
- H-EEG-person: mean random minus unseen-person accuracy exceeds that margin.

Each test is the position of a participant-bootstrap percentile interval relative to the fixed margin, with two-sided Bonferroni tail probabilities using family_alpha / comparisons. No pooling across datasets. A claim applying to every signal requires every unseen-person hypothesis to be supported. Linear discriminant results do not rescue the primary tests.

# Analysis plan

All numeric design choices are in analysis/config.json. Only structure and documentation were inspected before lock; no features, classifier predictions or outcome metrics were computed.

## Eligibility and labels

- EMG: all participant folders and both series; use gesture codes between emg_label_min and emg_label_max. Exclude unmarked and extended-palm data. Window by the provided millisecond timestamps, not an assumed row sampling rate. Never cross a label boundary. The last sample in a label segment defines its observed end; this conservatively drops a trailing partial window. No claimed raw sampling rate.
- Stress: label the entire recording by its folder (stress, aerobic, anaerobic), including baseline and recovery. This is session classification, NOT psychological stress detection or self-report prediction. Use raw ACC, BVP, EDA, TEMP only, never derived HR, IBI, tags or demographics. Exclude S02 entirely because duplication-row interpretation is ambiguous; exclude f07 because two requested sensors were covered; exclude S12 because aerobic is absent; exclude f14 through f18 because they have no exercise sessions. This also disposes of f14's fragmented stress session. Keep early-stop S03 and S07 aerobic and S06 anaerobic, using only observed data. S01's empty IBI file is irrelevant and retained. S11_a/S11_b aerobic and S16_a/S16_b anaerobic share their base participant ID, but fragments remain separate files and no window bridges them. Intersect observed times of all requested channels using each timestamp and sampling-rate header. The remaining participants must have all session classes.
- PPG-DaLiA: restricted array-only unpickling of synchronised SX.pkl files, one participant resident at a time. Use wrist ACC, BVP, EDA, TEMP and the synchronised activity array at activity_rate. Exclude transitions. Exclude S6 entirely before analysis because its valid shortened pickle lacks later activity classes; the task otherwise has the configured complete activity label set. Do not use ECG, heart-rate labels, questionnaire or chest signals.
- EEG: parse EDF+ headers and annotations without an EDF library. Use only configured left/right imagery runs, T1 versus T2; exclude rest and other runs. Structural inspection found nonstandard sample rate and trial duration/count for all selected runs of S088, S092 and S100, and a shortened S104R08. Exclude these entire participants to retain a complete run-holdout design. All others must have eeg_channels signals at eeg_rate, eeg_trials_per_run imagery events, with duration within eeg_trial_tolerance_seconds of eeg_trial_seconds. No amplitude-based rejection or post-outcome participant exclusion. Do not bridge a trial or run boundary.

Any unexpected structural failure aborts for correction and a recorded deviation before a rerun, or abandonment if it prevents the question from being answered.

## Windows and features

Overlap is overlap_fraction for every dataset. Window durations differ by signal: short EMG windows, trial-contained EEG windows, the PPG README's window duration (but not its recommended shift), and a prespecified longer stress session window. No stress-documentation convention is asserted. Window starts restart at every label segment or file boundary. Drop partial trailing windows and any window with nonfinite values in requested raw signals; log their counts. No feature is fit to the population before splitting.

EMG per-channel features: mean absolute value, root mean square, standard deviation, and mean absolute successive difference. Wrist per-channel features: mean, standard deviation, root mean square, and mean absolute successive difference. EEG per-channel features: log power in the half-open theta, alpha and beta bands defined by config, using a demeaned window, Hann taper, real FFT and mean squared spectral magnitude in each band, floored by numeric_floor. Use every available requested channel and no channel selection. Standardise every feature using only the selected training data; a constant feature has unit scale.

## Paired query and training design

For every eligible participant and each split repetition, randomly select test_fraction (floor, at least min_test_per_class) of windows in each class from their last EMG series or last EEG imagery run. For wrist datasets select from their complete available session data, because repeat recordings for the same label are absent. The selected windows are the identical queries for all protocols and both classifiers in that repetition. Remaining query-recording windows are available only to the random-window protocol.

Candidate training pools: (a) random-window: all non-query windows of that participant, across available recordings; (b) other-recording: all their earlier series/runs, never the query recording; (c) new-person: all windows of every other eligible participant, no data from the query participant. For each class use the same training count in every permitted protocol, the minimum candidate count across protocols capped by max_train_per_class. Sample without replacement uniformly per class. Training counts are balanced across protocols, not necessarily between classes. Never include a query itself in training. This matching intentionally estimates small-training-budget transfer; it is not full-data leave-one-person-out accuracy. Repetitions change query selection and training subsamples but are averaged within participant before inference. Seed all random operations from seed and deterministically spawned per-dataset generators.

Models: configured nearest_neighbors Euclidean nearest neighbour, primary, and linear discriminant analysis with analytic automatic covariance shrinkage, sensitivity. No tuning or model selection. Training standardisation is separate for each protocol; this includes distributional shifts as part of the comparison.

## Metrics and intervals

Ordinary query accuracy, first averaged across split_repeats within participant and then equally across participants. For each comparison, subtract accuracies within each participant first. Resample participants with replacement, preserving all repeats and protocols together, for bootstrap_resamples replicates. Report Bonferroni-adjusted percentile intervals for the six primary gaps, nominal intervals for the linear discriminant gaps (unadjusted sensitivity, not a second confirmatory family), and nominal accuracy intervals. Reuse shared bootstrap indices per dataset. Report uniform-guess chance (inverse task class count) and the query majority-class constant prediction accuracy, not a claim that chance controls all imbalance. Bootstrap intervals describe variability among fixed participant scores; shared donor pools and training stochasticity beyond configured repeats are not fully propagated. No hypothesis p-values are planned.

# Decision rules

For each primary gap: pre-registered and supported if its entire adjusted interval exceeds +equivalence_margin; pre-registered and not supported (practical equivalence) if its entire interval lies inside [-equivalence_margin, +equivalence_margin]; pre-registered and not supported (opposite direction) if the whole interval is below -equivalence_margin; otherwise pre-registered and inconclusive. Boundaries are strict. A mere interval excluding zero but intersecting the margin is inconclusive. Absence of significance is never proof of no effect.

# Exploratory analyses

Only descriptive overlap audit: the fraction of query windows sharing any raw sample/time span with an actually selected random-training window from the same file. Check that other-recording and new-person training have zero such overlaps. Report an unadjusted participant interval if useful. This is a mechanism check, not an overlap-only causal analysis. The planned linear discriminant sensitivity has nominal, unadjusted intervals and no confirmatory decision labels. No data-driven window choice, feature selection, classifier tuning, dataset pooling, per-dataset follow-up paper, or post-lock rescue analysis.
