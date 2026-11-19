# Local follow-up collection

This independent cohort adds two training and two validation initialization
groups while the server uses the accepted `drawer_sft_v1` release. It reuses
the frozen `feedback_v4` collector, PandaOmron, paired drawers, cabinet-front
and wrist cameras, 20 Hz control and 7D OSC action interface.

The [collection plan](../configs/data_splits_v5_followup.json) was written
before the rollouts. Seeds and offsets were not selected from their results.
Each group contains all four commands and stays in one split.

| Condition | Seed | Cabinet translation, metres | Split |
|---|---:|---|---|
| train_008 | 708 | (-0.0055, +0.0149) | Train |
| train_009 | 709 | (+0.0129, +0.0051) | Train |
| validation_002 | 802 | (-0.0132, -0.0299) | Validation |
| validation_003 | 803 | (+0.0329, +0.0257) | Validation |

The accepted v1 release, its datasets and statistics, and the server transfer
stay unchanged. The new cohort is exported separately and has passed the
[assisted-review policy](DATA_REVIEW.md) for inclusion in a later explicit
trial or release. The original
40 reserved test conditions remain unexecuted. Cabinet translation is not a
defined robot-relative OOD region.

## Recorded checks

| Check | Result |
|---|---|
| New training candidates | 8 episodes / 2,937 frames; one left and one right initialization |
| New validation candidates | 8 episodes / 2,893 frames; two right-side initializations |
| Stable successes / attempts | 16 / 16 |
| Recorded-action replays | 16 / 16 passed |
| Official LeRobot exact readback | 5,830 frames, both RGB views, state, action, language and timestamp |
| Action-chunk boundary checks | 80 samples, horizon 50, same-episode padding |
| Maximum joint / drawer replay error | 2.91 × 10⁻¹⁰ rad / 3.37 × 10⁻¹⁰ |
| Longest trajectory | 415 / 600 actions |
| Full-length review packets | Four MP4 files; all 1,643 video frames decoded |
| Assisted review | 16 admitted; all keyframes and two complete trajectory samples inspected |
| Human declarations | 16 pending, optional under the new review policy |

All eight prompt pairs have identical initial physics and XML. Seven also
have bit-identical RGB. The opening pair for seed 708 differs at three frontal
pixels by one uint8 level; its wrist images are identical. The strict audit
stopped and its log is retained. A separate audit passed the existing
`lsb_v1` profile for all eight pairs. The rendering cause is not isolated;
neither the controller nor any threshold was changed. The export comparison
still requires exact source pixels.

The current Chinese status page is
`outputs/data_review_followup_v5_assisted/index.html`. The agent inspected
48 keyframe timepoints across the 16 recordings, all 737 observations of two
sampled trajectories, and native-resolution stage-boundary details. The
[assisted-review record](../results/assisted_review_followup_v5.json) binds
the findings to the existing sources. The original human review page at
`outputs/data_review_followup_v5/index.html` remains available for optional
human annotations. Its earlier pending fields are historical, not a remaining
gate under the approved policy. No human viewing declarations were added.

Checks also confirmed that v1's 22 dataset files, its release and acceptance
records, and the frozen collection code remain unchanged. New and old sources,
initial physics hashes, initial RGB hashes and seeds are disjoint; the union
has no cross-split initialization overlap. The active server transfer was not
modified. The new dataset is about 512 MB across 16 files, excluded from Git.

[Data checks](../results/sft_data_followup_v5.json)
· [Review provenance, image differences and release guards](../results/collection_review_followup_v5.json)
· [Current admission and review policy](DATA_REVIEW.md)

## Reproduce

Run from the repository root with the existing environments and new output
paths. The commands refuse to overwrite recordings.

```powershell
$roboticsRoot = Split-Path -Parent (Get-Location).Path
$sim = Join-Path $roboticsRoot 'envs\pi05-sim-win\Scripts\python.exe'
$data = Join-Path $roboticsRoot 'envs\pi05-data-cpu\Scripts\python.exe'

foreach ($id in @('train_008', 'train_009', 'validation_002', 'validation_003')) {
    & scripts\run_pair_pilot.ps1 -SplitPlan configs\data_splits_v5_followup.json `
        -ConditionId $id -OutputRoot "outputs\NEW_FOLLOWUP\$id" `
        -SimPython $sim -DataPython $data -SkipConversion
    if ($LASTEXITCODE -ne 0) { throw "Inspect collection/audit failure: $id" }
}
```

Keep a failed strict RGB reset check and inspect it before separately applying
the existing `lsb_v1` image profile. Physics and XML must match exactly; source
RGB must match its LeRobot export pixel-for-pixel. Every attempt, including a
task failure, remains in the selection report.

If the strict audit stops after a group's four recordings and replays, retain
that completed group and its log. Inspect it, then invoke the runner for the
remaining group IDs without rerunning or overwriting completed outputs. Build
the dataset only after every planned attempt and named audit is present.

Use `prepare_sft_data.py build` for the standalone export and
`make_collection_review.py` / `review_sft_data.py` for the existing Chinese
review page, following the [collection and review guide](TRAINING_DATA_EXTENSION.md).
The cohort's own train statistics apply to its standalone checks. If accepted
data are combined later, that release must explicitly freeze its training
statistics and validation membership; do not silently change the active v1
training run.

For a later data-volume comparison, evaluate both checkpoints on the same
frozen validation version. Report the original v1 validation and these added
groups separately until a new release defines their combined membership.

After inspecting a strict image discrepancy, the original named-profile
export and review commands are:

```powershell
foreach ($id in @('train_008', 'train_009', 'validation_002', 'validation_003')) {
    $root = "outputs\NEW_FOLLOWUP\$id"
    $episodes = @('open_top', 'open_bottom', 'close_top', 'close_bottom') |
        ForEach-Object { Join-Path $root "$_\episode.hdf5" }
    & $data scripts\evaluate_drawer_pair.py @episodes --rgb-reset-check lsb_v1 `
        --output (Join-Path $root 'evaluation_lsb_v1')
    if ($LASTEXITCODE -ne 0) { throw "Named audit failed: $id" }
    & $data scripts\make_collection_review.py --condition $root `
        --output "outputs\NEW_FOLLOWUP\review\$id"
    if ($LASTEXITCODE -ne 0) { throw "Review packet failed: $id" }
}

& $data scripts\prepare_sft_data.py build --plan configs\data_splits_v5_followup.json `
    --raw-root outputs\NEW_FOLLOWUP --output data\lerobot\NEW_FOLLOWUP `
    --report results\NEW_FOLLOWUP.json --audit-subdir evaluation_lsb_v1 --rgb-reset-check lsb_v1
if ($LASTEXITCODE -ne 0) { throw 'Dataset checks failed' }

& $data scripts\review_sft_data.py build `
    --manifest data\lerobot\NEW_FOLLOWUP\selection_manifest.json `
    --review-roots outputs\NEW_FOLLOWUP\review --output outputs\NEW_FOLLOWUP_REVIEW
if ($LASTEXITCODE -ne 0) { throw 'Review index failed' }
```
