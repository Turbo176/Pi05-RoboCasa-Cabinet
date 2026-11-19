# Pose and contact feedback for demonstration collection

`feedback_v4` is an optional scripted collector. It uses simulator handle poses
and contact measurements to generate demonstrations through the existing OSC
action interface. It does not load or run π0.5. The default remains `fixed_v2`,
so historical collection commands retain their controller choice.

## Why fixed stage durations failed

The frozen v3 batch contains three failed training episodes: seed 502 opening
and closing the lower drawer, and seed 503 opening the upper drawer. Their full
recordings and failure labels remain intact.

For seed 503, the fixed script began grasping before the tool reached the
handle. An extended alignment and reach diagnostic produced bilateral pad
contact. Waiting alone did not resolve seed 502's lower grasp: Panda joint 2
was near its lower limit of −1.7628 rad, and the rigid finger contacted the bar
while the tool remained above its waypoint. This is measured posture and
contact evidence; it does not isolate every contribution to the tracking error.

The revised collector combines three changes:

- Use nearer pregrasp waypoints. For the lower drawer, descend outside the
  upper handle before approaching the target.
- For lower tasks with the robot on the left, roll the symmetric gripper by
  180° about its forward axis. Its closing axis remains vertical, while the
  arm follows a different posture.
- Advance alignment, reach, grasp, manipulation and clearance stages using
  measured conditions. A missed gate stops recording the attempted trajectory
  rather than starting the next manipulation stage.

Alignment requires position error below 18 mm and rotation error below 0.1 rad;
reach permits 25 mm before grasping. Grasp then requires loaded contact from
both pads. Clearance requires an open gripper, no loaded pad/handle contact,
position error below 25 mm, and rotation error below 0.1 rad. Gates must hold
for five consecutive sampled control steps, with at least ten steps in a gated
stage. Fixed approach, hold, release and retreat stages retain bounded durations.
The entire trajectory remains limited to 600 actions at 20 Hz.

Loaded contact means force norm above 0.001 N at the **final physics substep**
of a control action. These measurements do not cover every integration step.
Task thresholds, non-target drift limits, collisions, joint limits and physics
parameters are unchanged. The combined revision was tested as a whole; the
results below are not an ablation of wrist roll alone.

## Recorded checks

| Check | Result |
|---|---:|
| Reused train/development conditions, four commands each | 20 / 20 complete and stable |
| Longest controller execution | 419 / 600 actions |
| Previously failed episodes re-recorded with both RGB views | 3 / 3 stable |
| Recorded-action replays of those episodes | 3 / 3 within tolerance |
| Official LeRobot exact readback | 1,147 frames |
| Action-chunk boundary samples, horizon 50 | 15 passed |
| Suppressed pad-contact feedback | Stopped at grasp; zero pull actions |

| Training condition | Original final opening | Revised final opening | Revised actions |
|---|---:|---:|---:|
| Seed 502, open bottom | 0.000096 | 0.970497 | 408 |
| Seed 502, close bottom | 0.124155 | 0.005647 | 416 |
| Seed 503, open top | 0.000148 | 0.978227 | 323 |

These are **development regressions on already inspected initializations**.
Seeds 101, 102, 501, 502 and 503 were reused. Validation seed 601 and the 40
reserved test conditions were not run. No learned-policy performance or
unseen-position generalization is measured here.

The three re-recordings were converted into a separate local pipeline-check
dataset. They were not merged into v3 or declared a new SFT split. The v3
selection manifest and its 9 training / 4 validation candidates remain
unchanged. Full-episode human visual acceptance remains separate from the
automated checks.

[Validation and source hashes](../results/feedback_controller_v4.json)
· [All control regressions and reset checks](../results/feedback_regression_v4.json)

## Reset serialization check

All ten paired resets had identical simulator state vectors and initial RGB
pixels in the reused-process diagnostic. Nine had byte-identical compiled XML.
For the first seed-101 pair, 71 mesh elements differed only in the serialized
`content_type` attribute. The serializer/cache mechanism has not been established.

Repeating that pair in two fresh processes produced identical XML, state and
RGB hashes. This matches `run_pair_pilot.ps1`, which already launches each
recording in its own process. Exact XML checks remain enabled; the in-process
failure is retained in the regression report.

## Run a single episode

From the repository root, using the existing simulation environment:

```powershell
$sim = Join-Path (Split-Path -Parent (Get-Location).Path) 'envs\pi05-sim-win\Scripts\python.exe'

& $sim scripts\scripted_rollout.py --task CloseDrawerPairLite `
    --instruction 'Close the bottom drawer.' --pair-layout spaced `
    --seed 502 --scene-offset 0.0142 0.0198 --front-camera cabinet_front `
    --controller feedback_v4 --output outputs\NEW_FEEDBACK_CLOSE

& $sim scripts\replay_episode.py outputs\NEW_FEEDBACK_CLOSE\episode.hdf5 `
    --output outputs\NEW_FEEDBACK_CLOSE_REPLAY --contact-diagnostics
```

The recording stores executed stage lengths, gate results, wrist-roll choice
and any stop reason in `controller_execution`. A timed-out attempt can have a
successful intermediate or final task measurement; SFT selection also requires
the controller to have completed every declared stage.

## Freeze the next collection

Use fresh train/validation conditions after controller development. Declare
the controller in the plan, then collect through the existing runner:

```powershell
$data = Join-Path (Split-Path -Parent (Get-Location).Path) 'envs\pi05-data-cpu\Scripts\python.exe'

& $data scripts\prepare_sft_data.py plan --previous-plan configs\data_splits_v3.json `
    --train-seeds 701 702 703 --validation-seeds 801 --sampler-seed 2026111904 `
    --front-camera cabinet_front --controller feedback_v4 `
    --output configs\data_splits_NEXT.json

& scripts\run_pair_pilot.ps1 -SplitPlan configs\data_splits_NEXT.json `
    -ConditionId train_001 -OutputRoot outputs\NEW_FEEDBACK_BATCH\train_001 `
    -SimPython $sim -DataPython $data -SkipConversion
```

Output paths must be new. Old plans retain their original bytes and source
hashes. New plans lock both the controller choice and collection files; the
runner rejects overrides, and SFT selection rejects a mismatched controller
or incomplete feedback execution. Review the next small batch before expanding
collection. The server SFT and policy rollout stages follow the existing
[training and evaluation contract](SERVER_AND_RL.md).

The subsequent [v4 collection](DATA_READINESS_V4.md) ran fresh seeds
701, 702, 703 and 801 with this frozen controller. All 16 trajectories completed
and replayed, and 5,844 exported frames passed official LeRobot readback. Those
collection results are separate from the reused development regressions above.
