# Cabinet-front collection and SFT candidates

The collection uses the existing Windows simulation and CPU data environments.
It generates scripted demonstrations through physical robot contact, records
both RGB views, replays the recorded actions, and exports successful candidates
with the official LeRobot API. No model weights or public demonstration data
are downloaded.

## Frozen conditions

[Collection plan](../configs/data_splits_v3.json), SHA256:

```text
eea6f89da02b2a1292554863a58c010025def75d24878a237f58acdd5d13016e
```

| Split | Seed | Cabinet translation, metres | Instructions |
|---|---:|---|---:|
| Train | 501 | (+0.0128, -0.0151) | 4 |
| Train | 502 | (+0.0142, +0.0198) | 4 |
| Train | 503 | (+0.0350, +0.0347) | 4 |
| Validation | 601 | (-0.0234, +0.0038) | 4 |

All four commands for one initialization remain in the same split. The plan
records SHA256 hashes of collection, replay, audit, conversion, selection,
adapters, and both dependency lock files. The collection runner rejects a source
file changed after freezing. JSON plans and reports retain their stored bytes
in Git so Windows line-ending conversion cannot invalidate their hashes; new
plans are written with LF line endings.

The 40 unexecuted test conditions are inherited unchanged from v1 through v2.
They are neither collected nor exported here. World-coordinate cabinet
translation remains a camera/placement stress condition; this collection does
not establish a held-out robot-relative OOD region.

## Why the camera profile changed

Review of the legacy robot-left images found the lower handle frequently
outside the image. A physically successful trajectory alone is insufficient
for RGB-conditioned learning. Collection v2 was stopped during its first
condition, preserving three completed recordings and any interrupted replay as
development diagnostics. No v2 SFT dataset was built.

The new `cabinet_front` camera is fixed at world position `(1.0, -1.8, 1.4)` m,
looks at `(1.0, -0.1, 0.9)` m, and uses a 50° vertical field of view. The wrist
camera and 256×256 resolution are retained. Camera placement does not depend on
the instruction or handle state. Checks on development seeds 101 and 102 found
both handles in frame on both robot spawn sides; changing camera profiles kept
the initial physics state identical. Legacy action replay still passed.

[Camera checks](../results/camera_framing_v3.json)
· [Policy RGB examples](../assets/demo/policy_views_v3.png)
· [Retired v2 collection](../results/data_collection_v2_retired.json)

The adapter keeps the same `observation.images.front` and
`observation.images.wrist` policy keys, but resolves their raw camera names
explicitly. Conversion rejects mixed front-camera profiles within one dataset.
Training and inference must use the same profile. The legacy profile remains
available through `--front-camera robot_left` for historical replay.

## Selection and verification

The selection rules retain the existing task thresholds: opening ≥0.95 or
closing ≤0.05, cumulative non-target drift ≤0.05, and success for the final 10
control steps. The budget is 600 actions at 20 Hz. Lower-drawer closing uses the
570-step clearance revision; other trajectories take 415 or 545 steps.

Every attempted episode is retained, including failures. Selection checks raw
T/T+1 alignment, source hashes, task outcomes recomputed from drawer
measurements, paired-prompt reset equality, and action replay. Training and
validation are exported separately. Official loading compares every exported
RGB pixel, state, action, instruction, and timestamp with its source. Action
chunks have length 50, and boundary checks require padding with the same
episode's last action rather than the next episode's actions.

Only training statistics may be used for normalization in future training and
validation processors. Successful candidates still need full-episode human
visual review. This batch verifies the data pipeline; it does not validate a
π0.5 processor, model forward/backward pass, checkpoint, or learned-policy
rollout.

## Reproduce

Run from a fresh checkout of the source version matching the plan hashes, using
existing environments. All output paths must be new; original recordings are
excluded from Git and must not be overwritten.

```powershell
$roboticsRoot = Split-Path -Parent (Get-Location).Path
$sim = Join-Path $roboticsRoot 'envs\pi05-sim-win\Scripts\python.exe'
$data = Join-Path $roboticsRoot 'envs\pi05-data-cpu\Scripts\python.exe'

foreach ($id in @('train_001', 'train_002', 'train_003', 'validation_001')) {
    & scripts\run_pair_pilot.ps1 -SplitPlan configs\data_splits_v3.json `
        -ConditionId $id -OutputRoot "outputs\NEW_V3_BATCH\$id" `
        -SimPython $sim -DataPython $data -SkipConversion
    if ($LASTEXITCODE -ne 0) { throw "Collection failed: $id" }
}

& $data scripts\prepare_sft_data.py build --plan configs\data_splits_v3.json `
    --raw-root outputs\NEW_V3_BATCH --output data\lerobot\NEW_V3_CANDIDATES `
    --report results\NEW_V3_READINESS.json
```

The existing v1 and contact-regression source snapshots remain available at
commits `3ab7a7d` and `02b1b56`, respectively. v1 and retired v2 conditions are
excluded from the new batch. Re-running development seeds must not be counted
as independent validation or learned-policy performance.
