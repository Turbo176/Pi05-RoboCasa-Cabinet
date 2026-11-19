# Feedback-gated collection and dataset review

This batch runs the `feedback_v4` collector on fresh initialization conditions.
The controller advances after measured pose and contact gates; the robot still
moves through the same OSC actions and physical drawer contact. All episodes
remain labeled `SCRIPTED_PRIVILEGED_STATE`.

## Collection protocol

[Frozen plan](../configs/data_splits_v4.json), SHA256:

```text
825826bc5db92b3cb275e8c73c016940914bfabc5d19ce4328a8e0c8ef331c75
```

| Split | Seed | Cabinet translation, metres | Instructions |
|---|---:|---|---:|
| Train | 701 | (-0.0153, -0.0264) | 4 |
| Train | 702 | (-0.0306, -0.0241) | 4 |
| Train | 703 | (-0.0057, +0.0247) | 4 |
| Validation | 801 | (+0.0356, -0.0072) | 4 |

The collection source is commit `1272987`. The plan locks the controller,
cabinet-front camera, recording, replay, selection and conversion code, plus
the simulation and CPU data dependency locks. No collector or scoring change
was made after freezing these conditions.

All commands from an initialization stay in one split. Earlier collection and
controller development conditions are retired from this batch. The 40 reserved
test conditions are inherited unchanged and remain unexecuted. Cabinet world
translation does not define a held-out robot-relative position region.

## Recorded results

| Task | Stable successes / attempts |
|---|---:|
| Open top | 4 / 4 |
| Open bottom | 4 / 4 |
| Close top | 4 / 4 |
| Close bottom | 4 / 4 |
| **Total** | **16 / 16** |

| Check | Result |
|---|---|
| Training candidates | 12 episodes, 4,379 frames |
| Validation candidates | 4 episodes, 1,465 frames |
| Official LeRobot exact frame readback | 5,844 frames passed |
| Completed feedback executions | 16 / 16; 308–425 actions |
| Recorded-action replay | 16 / 16 passed |
| Maximum joint replay error | 8.123 × 10⁻¹¹ rad |
| Maximum drawer-fraction replay error | 4.753 × 10⁻¹⁰ |
| Maximum cumulative non-target drift | 3.836 × 10⁻⁹ |
| Action-chunk boundary samples | 80 passed, horizon 50 |
| CPU action / state batch | `[4, 50, 7]` / `[4, 9]` |
| Each RGB batch | `[4, 3, 256, 256]` |

Every training instruction has one right-side and two left-side robot-spawn
examples. Validation has one left-side initialization and one episode per
instruction. No attempt was removed from the denominator; all 16 pass the
automated selection rules. Successful final actions and the preceding nine
actions meet the unchanged opening/closing and non-target criteria.

This is a fresh batch with different seeds and episode lengths from v3. Its
counts measure collection and data integrity, not a controlled comparison of
collectors or learned-policy quality. Previous raw recordings and selection
manifests remain unchanged. Local exports are in
`data/lerobot/sft_readiness_v4/train` and `validation`; datasets are excluded
from Git.

[Full data report](../results/sft_data_readiness_v4.json)
· [Review provenance](../results/collection_review_v4.json)

## Reset image audit

All eight prompt pairs have exactly equal initial simulator state, compiled
XML, and robot spawn. All six training pairs also have bit-identical RGB.
Both validation pairs differ at the same three cabinet-front pixels, each in
one channel by one uint8 level; wrist images are identical. The strict audit
stopped at the first validation pair. Its log is retained, and a separate
measurement report includes both pairs and their exact pixel values.

The second audit uses the existing `lsb_v1` profile, fixed before this batch.
It permits at most 16 differing pixels per view and at most one uint8 level in
any channel. All eight pairs pass this named profile. No threshold was fitted
to validation, and no controller or physics change was made. The rendering
mechanism behind the pixel differences has not been isolated.

[Exact differences and source hashes](../results/rgb_reset_difference_v4.json)
· [Image QA limits](../configs/rgb_reset_audit_v1.json)

## Inspect the actual policy images

The review tool reads existing HDF5 recordings. It does not rerun the scene,
controller, or model. Each panel shows the recorded cabinet-front and wrist RGB,
with the OpenGL row convention flipped as in the dataset adapter. Enlarging the
images adds no detail. Instructions, stages, measured openings and success
labels are display overlays only.

The MP4 retains every post-action observation at 20 FPS. It shows four
independent episodes at 1× simulation speed; a shorter episode holds its final
frame. The keyframe sheet shows the first action, end of grasp, and final action
for each command. The tool records exact source hashes and frame indices.

Full-episode human acceptance remains a separate step. Automated success,
faithful replay, and a few inspected images do not establish smooth contact or
sufficient training coverage. Keep any rejected episodes and their reasons;
never relabel scripted recordings as human demonstrations or π0.5 rollouts.

[Four-command MP4, seed 701](../assets/demo/feedback_four_commands_v4.mp4)
· [GIF preview](../assets/demo/feedback_four_commands_v4.gif)

Local full-length review packets for every condition are saved under
`outputs/data_readiness_v4/review_final/<condition_id>/`: `four_commands.mp4`,
`keyframes.png`, `preview.png`, and `report.json`. The review report records
an agent inspection of 48 keyframe timepoints from all 16 episodes; it does not
mark the videos as accepted by a human.

## Reproduce

Run from the repository root with the existing environments. Use new output
directories; the runner refuses to overwrite recordings. The collection files
must match the frozen hashes.

```powershell
$roboticsRoot = Split-Path -Parent (Get-Location).Path
$sim = Join-Path $roboticsRoot 'envs\pi05-sim-win\Scripts\python.exe'
$data = Join-Path $roboticsRoot 'envs\pi05-data-cpu\Scripts\python.exe'

foreach ($id in @('train_001', 'train_002', 'train_003', 'validation_001')) {
    & scripts\run_pair_pilot.ps1 -SplitPlan configs\data_splits_v4.json `
        -ConditionId $id -OutputRoot "outputs\NEW_V4_BATCH\$id" `
        -SimPython $sim -DataPython $data -SkipConversion
    # The strict audit can stop after all recordings and replays have completed.
    # If it fails, inspect the log before proceeding with the named image audit.
    if ($LASTEXITCODE -ne 0) { throw "Inspect collection/audit failure: $id" }
}

# Retain strict outputs. Run the pre-existing image profile separately.
foreach ($id in @('train_001', 'train_002', 'train_003', 'validation_001')) {
    $root = "outputs\NEW_V4_BATCH\$id"
    $episodes = @('open_top', 'open_bottom', 'close_top', 'close_bottom') |
        ForEach-Object { Join-Path $root "$_\episode.hdf5" }
    & $data scripts\evaluate_drawer_pair.py @episodes --rgb-reset-check lsb_v1 `
        --output (Join-Path $root 'evaluation_lsb_v1')
    if ($LASTEXITCODE -ne 0) { throw "Named audit failed: $id" }
}

& $data scripts\prepare_sft_data.py build --plan configs\data_splits_v4.json `
    --raw-root outputs\NEW_V4_BATCH --output data\lerobot\NEW_V4_CANDIDATES `
    --report results\NEW_V4_READINESS.json `
    --audit-subdir evaluation_lsb_v1 --rgb-reset-check lsb_v1
if ($LASTEXITCODE -ne 0) { throw 'Dataset verification failed' }

& $data scripts\make_collection_review.py `
    --condition outputs\NEW_V4_BATCH\train_001 `
    --output outputs\NEW_V4_REVIEW\train_001 --gif
```

The build requires all 16 attempts, same-hash action replays, exact paired
physics/XML, the explicitly declared RGB profile, unchanged task thresholds,
and complete feedback stages. Raw-to-LeRobot RGB readback still requires
pixel-for-pixel equality.
The official LeRobot loader compares every selected frame with the raw source.
Action chunks have horizon 50 and pad with the same episode's last action.
Only training statistics may normalize future training and validation inputs.

The dataset is a small collection and pipeline check. Model processors,
forward/backward passes, checkpoint recovery, and learned-policy rollouts
require the [server validation stage](SERVER_AND_RL.md).
