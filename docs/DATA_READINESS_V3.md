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

## Recorded results

| Task | Stable successes / attempts |
|---|---:|
| Open top drawer | 3 / 4 |
| Open bottom drawer | 3 / 4 |
| Close top drawer | 4 / 4 |
| Close bottom drawer | 3 / 4 |
| **All tasks** | **13 / 16** |

Training candidates contain **9 episodes / 4,305 frames**. Validation contains
**4 episodes / 1,945 frames**. The official loader compared all **6,250 frames**
with raw observations and actions, with exact image pixels. All **16 action
replays** passed, including failed tasks; maximum joint error was
0.0008451102 rad and maximum drawer-opening error was 0.0001124070, within the
existing 0.01 replay tolerances. **65 action-chunk boundary samples** passed at
horizon 50. CPU batches are action `[4, 50, 7]`, state `[4, 9]`, and
`[4, 3, 256, 256]` for each RGB view.

All four successful prompts occur on both left and right robot spawn sides in
the training candidates. Counts remain small and uneven: left-side top closing
has two examples; other side/prompt combinations have one. Validation has one
right-side initialization. These candidates are not a completed training
corpus, a policy benchmark, or evidence of unseen-position generalization.

Seed 502's lower opening never formed bilateral pad contact and did not open
the drawer. Its lower closing reached 0.01672 at clearance, then reopened to
0.12415 during retreat. Contact replay shows the lower pad still loading the
handle; the tool remained above its clearance waypoint. Seed 503's upper
opening also failed without a bilateral handle grasp. The complete trajectories
are retained, and none is truncated to a successful intermediate frame. Exact
posture and tracking causes need a separate controller revision; this batch
remains frozen.

[Complete readiness report](../results/sft_data_readiness_v3.json)
· [Failure stages](../results/data_readiness_failure_stages_v3.json)
· [Contact diagnostics](../results/contact_failures_seed502_v3.json)

Full-episode human visual acceptance is still pending. Scripted actions use
privileged handle poses; no π0.5 policy generated these demonstrations.

## Selection and verification

The selection rules retain the existing task thresholds: opening ≥0.95 or
closing ≤0.05, cumulative non-target drift ≤0.05, and success for the final 10
control steps. The budget is 600 actions at 20 Hz. Lower-drawer closing uses the
570-step clearance revision; other trajectories take 415 or 545 steps.

Initial XML, simulator state, and robot spawn must match **exactly** across a
paired target prompt. The initial image audit also attempted exact equality.
Train seed 502's closing pair failed that image check: three pixels each had
one channel differing by one uint8 level, while physics and XML were identical.
The discrepancy is recorded in [the RGB diagnostic](../results/rgb_reset_difference_v3.json);
its rendering mechanism has not been established.

The separately frozen [RGB audit profile](../configs/rgb_reset_audit_v1.json),
`lsb_v1`, permits at most 16 differing pixels per 256×256 view and at most one
uint8 level in any channel. It was calibrated during data QA using that training
condition, not set before collection. The default audit remains `exact`;
`lsb_v1` must be requested explicitly and reports actual differences. A two-level
change or 17 differing pixels is rejected. Strict audit outputs are retained,
and the second audit writes to a new directory. This changes image reset QA
only; it does not relax physical initialization, task success, replay error,
or exact raw-to-LeRobot pixel comparison.

Every attempted episode is retained, including failures. Selection checks raw
T/T+1 alignment, source hashes, task outcomes recomputed from drawer
measurements, exact paired-prompt physics equality, explicit image QA, and action replay. Training and
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

# Run once per condition with the frozen collection revision.
# The strict image audit can reject one closing pair after recording all
# four episodes and their replays; retain its output and use the second audit.
& scripts\run_pair_pilot.ps1 -SplitPlan configs\data_splits_v3.json `
    -ConditionId train_001 -OutputRoot outputs\NEW_V3_BATCH\train_001 `
    -SimPython $sim -DataPython $data -SkipConversion
# Repeat with train_002, train_003 and validation_001 into their own directories.

# Keep the original strict audit. Re-audit to a new directory with the named
# image QA profile; task thresholds and exact physics checks remain the same.
foreach ($id in @('train_001', 'train_002', 'train_003', 'validation_001')) {
    $root = "outputs\NEW_V3_BATCH\$id"
    $episodes = @('open_top', 'open_bottom', 'close_top', 'close_bottom') |
        ForEach-Object { Join-Path $root "$_\episode.hdf5" }
    & $data scripts\evaluate_drawer_pair.py @episodes --rgb-reset-check lsb_v1 `
        --output (Join-Path $root 'evaluation_lsb_v1')
    if ($LASTEXITCODE -ne 0) { throw "Audit failed: $id" }
}

& $data scripts\prepare_sft_data.py build --plan configs\data_splits_v3.json `
    --raw-root outputs\NEW_V3_BATCH --output data\lerobot\NEW_V3_CANDIDATES `
    --report results\NEW_V3_READINESS.json `
    --audit-subdir evaluation_lsb_v1 --rgb-reset-check lsb_v1
```

The recorded v3 collection snapshot is commit `de92aa6`; the explicit image
audit and selection code is recorded separately in the readiness report. Its
audit was added after raw collection, without changing source recordings.
For exact collection-code verification, collect with `de92aa6`, then update to
the data QA revision for the second audit and export. The existing v1 and
contact-regression source snapshots remain available at commits `3ab7a7d` and
`02b1b56`, respectively. v1 and retired v2 conditions are
excluded from the new batch. Re-running development seeds must not be counted
as independent validation or learned-policy performance.
