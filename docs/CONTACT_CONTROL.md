# Drawer release and withdrawal

The scripted controller uses simulator handle poses and OSC feedback. It is a
demonstration generator; the measurements below do not involve a learned policy.

## Seed 102: a closed drawer reopened during retreat

In the first frozen collection batch, `Close the bottom drawer.` ended at an
opening of 0.08134. The closing threshold is 0.05. The drawer had reached 0.03121
at the end of release, so a successful intermediate frame did not describe the
complete task.

Replaying the original actions with `--contact-diagnostics` exposed loaded
contact between `gripper0_right_finger2_pad_collision` and the bottom handle at
the end of release and the first two sampled retreat steps. Opening the fingers
had not cleared the lower pad. At release, the tool was about 25 mm above the
nominal handle-height waypoint.

Revision `lower_handle_clearance_v2` adds a 25-step `clear_handle` stage after
release: keep the gripper open and lower the waypoint by 25 mm, then withdraw
horizontally at that height. The full lower closing trajectory takes 570 steps
(28.5 seconds), within the existing 600-step budget. The scene, collision rules,
physics parameters, and success thresholds stay identical to the original run.

| Same seed and scene | Previous controller | Clearance revision |
|---|---:|---:|
| First 505 recorded actions | Identical | Identical |
| Final opening, action replay | 0.08133814 | 0.03105905 |
| Loaded lower-pad/handle samples during retreat | 2 / 40 | 0 / 40 |
| Final task success | False | True |
| Non-target opening drift | 0 | 0 |
| Action replay within tolerance | Passed | Passed |

The new stage had no loaded pad/handle contacts in its 25 samples. Contacts are
sampled at the **last physics substep of each 20 Hz action**; this does not prove
that every intermediate integration step is contact-free. Loaded contact here
means a measured contact-force norm above 0.001 N. Force components are reported
in MuJoCo's contact-local frame.

[Diagnosis and source hashes](../results/withdraw_contact_diagnosis_v2.json)
· [MP4 comparison](../assets/demo/withdraw_clearance_v2.mp4)
· [Video provenance](../results/withdraw_demo_provenance_v2.json)

The video shows source frames 440–569, or simulation time 22.00–28.50 seconds,
at 1× speed. The previous 545-step episode holds its final frame after 27.25
seconds. Both panels use scripted control.

## Reproduce the contact inspection

From the repository root, using the existing simulation environment:

```powershell
$sim = Join-Path (Split-Path -Parent (Get-Location).Path) 'envs\pi05-sim-win\Scripts\python.exe'

# Requires a local raw recording; datasets are excluded from Git.
& $sim scripts\replay_episode.py `
    outputs\data_readiness_v1\train_002\close_bottom\episode.hdf5 `
    --output outputs\NEW_BASELINE_CONTACT_REPLAY --contact-diagnostics

& $sim scripts\scripted_rollout.py --task CloseDrawerPairLite `
    --instruction 'Close the bottom drawer.' --pair-layout spaced `
    --seed 102 --scene-offset 0.0172 0.0088 --front-camera robot_left `
    --output outputs\NEW_CLEARANCE_RUN

& $sim scripts\replay_episode.py outputs\NEW_CLEARANCE_RUN\episode.hdf5 `
    --output outputs\NEW_CLEARANCE_REPLAY --contact-diagnostics
```

The replay writes `contacts.json` alongside `report.json` and `replay.mp4`.
It reads contacts, gripper positions, tool and handle poses without changing
the action stream. Old recordings and their original failure labels are kept.

## Collection versions

Seeds 101 and 102 are development regression conditions after this diagnosis.
Their repeated runs cannot be counted as independent model evaluation.
`configs/withdraw_regression_v2.json` freezes the controller and scene file
hashes for checking all four instructions on both robot spawn sides.

Both sides passed all four tasks: **8/8** final and last-10-step successes,
**8/8** action replays, and **4/4** paired-prompt reset checks. Maximum replay
errors were 0.00048175 rad for arm joints and 0.0000518344 for drawer opening.
These are measured numerical errors within the 0.01 replay tolerance.
[Regression report](../results/withdraw_regression_v2.json).

Further SFT candidates use a fresh collection plan and fresh train/validation
initializations. The original v1 batch remains intact. The 40 reserved test
conditions are carried forward without execution or resampling. New plans can
be frozen with the existing data preparation command:

```powershell
$data = Join-Path (Split-Path -Parent (Get-Location).Path) 'envs\pi05-data-cpu\Scripts\python.exe'
& $data scripts\prepare_sft_data.py plan --previous-plan configs\data_splits_v2.json `
    --train-seeds 501 502 503 --validation-seeds 601 --sampler-seed 2026111903 `
    --front-camera cabinet_front `
    --output configs\data_splits_NEW.json
```

The command rejects reused seeds, overlapping initialization positions, and an
existing output path. The runner checks the frozen collection code before it
records a new batch.

The exact controller/recorder snapshot for the contact regression and v2 plan
is commit `02b1b56`. Collection v2 was stopped during its first condition after
review found that the legacy robot-left view clipped the lower handle. Its
three completed recordings remain development diagnostics; no v2 SFT dataset
was built. The next collection uses a declared `cabinet_front` profile and
fresh seeds. [Retirement record](../results/data_collection_v2_retired.json).

## Pose and contact feedback collector

The later v3 training failures showed that a fixed clearance duration alone
does not cover every initialization. The optional `feedback_v4` collector adds
measured stage gates, nearer pregrasp waypoints and a lower-drawer wrist-roll
choice for left-side robot spawns. Twenty reused development conditions
completed stably; the three diagnosed training failures were re-recorded and
replayed. These checks do not replace the frozen v3 collection results or
measure a learned policy. See the [collector protocol and commands](FEEDBACK_COLLECTOR.md)
and [recorded validation](../results/feedback_controller_v4.json).
