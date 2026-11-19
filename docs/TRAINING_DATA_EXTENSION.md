# Training collection and episode review

The training-only supplement adds fresh initialization groups to the
`feedback_v4` recordings. It keeps the original validation dataset and the
40 reserved test conditions. The robot, camera profile, controller, action
interface, success thresholds and 600-action budget are unchanged.

Each initialization contains all four commands. The split remains attached to
the entire group, including any failed attempts. Raw recordings retain the
plan hash used when they were collected; combining candidates does not rewrite
their requests or claim they came from one collection plan.

## Additional conditions

[Frozen training supplement](../configs/data_splits_v4_train_extension.json):

| Condition | Seed | Cabinet translation, metres | Split |
|---|---:|---|---|
| train_004 | 704 | (-0.0135, -0.0399) | Train |
| train_005 | 705 | (+0.0013, -0.0159) | Train |
| train_006 | 706 | (-0.0263, -0.0251) | Train |
| train_007 | 707 | (+0.0011, -0.0392) | Train |

The plan was written before these rollouts. No seed or position is selected
from its result. Base raw recordings, selection, report, and every validation
dataset file are protected by byte hashes. The merge checks those hashes
again after conversion. The union uses fresh training statistics; validation
keeps its existing data path and must use the union's training statistics at
model input time.

These remain `SCRIPTED_PRIVILEGED_STATE` demonstrations. Additional drawer
initializations are coverage within the existing four-command task family.
They do not add object storage, learned language grounding, or a robot-relative
OOD region.

## Collection results

| Check | Additional batch |
|---|---:|
| Stable successes / attempts | 16 / 16 |
| Completed feedback executions | 16 / 16 |
| Recorded action replays passed | 16 / 16 |
| Strict paired-prompt physics, XML and RGB checks | 8 / 8 |
| Recorded action frames | 5,847 |
| Episode lengths | 314–415 actions |
| Robot spawn side, per instruction | 3 left, 1 right |

All attempts remain in the selection records. The original v4 candidates have
not been overwritten. The additional batch introduces four initialization
groups and uses the same four instructions, drawer assets and layout.

| Combined data check | Result |
|---|---|
| Accepted training episodes | 28 episodes, 10,226 frames |
| Accepted validation episodes, original files | 4 episodes, 1,465 frames |
| Training examples per instruction | 7: five left-side, two right-side spawns |
| Stable successes / attempts, both batches | 32 / 32 |
| Recorded action replays, both batches | 32 / 32 passed |
| Official LeRobot exact readback | 11,691 frames across both splits |
| Action-chunk boundaries | 140 training + 20 original validation samples |
| Maximum joint replay error | 1.0775 × 10⁻⁵ rad |
| Maximum drawer-fraction replay error | 1.3190 × 10⁻⁶ |
| Original validation and protected raw files | All byte hashes unchanged |
| Reserved tests | 40 conditions, unchanged and unexecuted |
| Human video decisions | 32 accepted, zero rejected or pending |

The combined training export was checked against all 10,226 raw frames through
the official loader. The original validation export had already passed the
same 1,465-frame comparison; its seven files were verified unchanged before
and after the merge. Validation was not recollected or re-exported. The
160 boundary samples describe the combined training and original validation
checks, without adding the separate supplement checks a second time.

The additional four review MP4 files decoded all 1,637 frames. An agent
inspected 48 keyframe timepoints from the new episodes. The maintainer later
exported acceptance and full-episode viewing declarations for all 32 recordings;
the [acceptance summary](../results/human_acceptance_v4.json) records that
follow-up separately from the original inspection. The review page's Node DOM
fixture and JSON export checks passed, including disabled browser storage. Browser visual preview was
blocked by the automation browser's local-file policy and is not marked as
verified. Missing/duplicate review rows, source mismatch, unnamed or unwatched
acceptance, rejection without a reason, and wrong inventory identity were
rejected. Merge fault checks also refused missing attempts, duplicate raw
episodes, cross-split reset leakage and changed source hashes before creating
an output dataset.

[Additional-batch report](../results/sft_data_readiness_v4_supplement.json)
· [Combined report](../results/training_extension_v4.json)
· [Video review and guard-check provenance](../results/collection_review_extension_v4.json)

## Accepted SFT release

On November 19, 2026, the review checker passed all 32 source-bound decisions:
28 training and four validation episodes, with no rejections or pending rows.
The [release manifest](../configs/sft_release_v1.json), `drawer_sft_v1`, freezes
the dataset paths, ordered raw-source mapping, 22 file hashes and sizes,
collection plans, collector code and 9D-state / 7D-action policy contract.
The dataset files total 1,030,087,876 bytes and remain local.

| Split | Dataset path | Episodes / frames |
|---|---|---|
| Train | `data/lerobot/sft_readiness_v4_extended/train` | 28 / 10,226 |
| Validation | `data/lerobot/sft_readiness_v4/validation` | 4 / 1,465 |

Both splits must use the training statistics at
`data/lerobot/sft_readiness_v4_extended/train/meta/stats.json`; validation
statistics are diagnostic only. The original review export and checker report
are archived privately at `outputs/human_review_v4_accepted/`. Their hashes are
published without reviewer names or free-text notes. No dataset was rewritten;
earlier reports retain the pending status recorded when they were generated.

To repeat the local acceptance check, use the existing checker with a new
output filename:

```powershell
$roboticsRoot = Split-Path -Parent (Get-Location).Path
$data = Join-Path $roboticsRoot 'envs\pi05-data-cpu\Scripts\python.exe'
& $data scripts\review_sft_data.py check `
    --inventory outputs\data_review_v4_extended\inventory.json `
    --decisions outputs\human_review_v4_accepted\review_decisions.json `
    --output outputs\NEW_ACCEPTANCE_CHECK.json
if ($LASTEXITCODE -ne 0) { throw 'Acceptance verification failed' }
```

The paths above refer to this machine's local artifacts; they are not included
in a Git clone. Run from the repository root with the existing CPU environment.
Acceptance records a human viewing declaration. It does not establish model
performance or sufficient data coverage: validation has one initialization,
the 40 reserved tests are unexecuted, and π0.5 training and rollouts have not run.

## Collect and verify

Use the existing Windows simulation and CPU data environments from the
repository root:

```powershell
$roboticsRoot = Split-Path -Parent (Get-Location).Path
$sim = Join-Path $roboticsRoot 'envs\pi05-sim-win\Scripts\python.exe'
$data = Join-Path $roboticsRoot 'envs\pi05-data-cpu\Scripts\python.exe'

# Bind a new supplement to your existing v4 dataset, before recording it.
# Replace base paths if your reproduced batch uses a different output name.
& $data scripts\extend_sft_data.py plan `
    --base-plan configs\data_splits_v4.json `
    --base-manifest data\lerobot\sft_readiness_v4\selection_manifest.json `
    --base-report results\sft_data_readiness_v4.json `
    --train-seeds 704 705 706 707 --sampler-seed 2026111905 `
    --output configs\NEW_TRAIN_EXTENSION.json
if ($LASTEXITCODE -ne 0) { throw 'Inspect the plan failure' }

foreach ($id in @('train_004', 'train_005', 'train_006', 'train_007')) {
    & scripts\run_pair_pilot.ps1 -SplitPlan configs\NEW_TRAIN_EXTENSION.json `
        -ConditionId $id -OutputRoot "outputs\NEW_EXTENSION\$id" `
        -SimPython $sim -DataPython $data -SkipConversion
    if ($LASTEXITCODE -ne 0) { throw "Inspect collection/audit failure: $id" }
}

# Keep the exact audit. Run the previously defined image profile separately.
foreach ($id in @('train_004', 'train_005', 'train_006', 'train_007')) {
    $root = "outputs\NEW_EXTENSION\$id"
    $episodes = @('open_top', 'open_bottom', 'close_top', 'close_bottom') |
        ForEach-Object { Join-Path $root "$_\episode.hdf5" }
    & $data scripts\evaluate_drawer_pair.py @episodes --rgb-reset-check lsb_v1 `
        --output (Join-Path $root 'evaluation_lsb_v1')
    if ($LASTEXITCODE -ne 0) { throw "Named audit failed: $id" }
}

& $data scripts\prepare_sft_data.py build --plan configs\NEW_TRAIN_EXTENSION.json `
    --raw-root outputs\NEW_EXTENSION --output data\lerobot\NEW_SUPPLEMENT `
    --report results\NEW_SUPPLEMENT.json `
    --audit-subdir evaluation_lsb_v1 --rgb-reset-check lsb_v1
if ($LASTEXITCODE -ne 0) { throw 'Supplement verification failed' }

& $data scripts\extend_sft_data.py merge --plan configs\NEW_TRAIN_EXTENSION.json `
    --supplement-manifest data\lerobot\NEW_SUPPLEMENT\selection_manifest.json `
    --supplement-report results\NEW_SUPPLEMENT.json `
    --output data\lerobot\NEW_TRAIN_UNION --report results\NEW_TRAIN_UNION.json
if ($LASTEXITCODE -ne 0) { throw 'Union verification failed' }
```

Every output must be new. If the exact reset-image audit stops, retain its
log and inspect the discrepancy before running the named audit. Physical
state and compiled XML must always match exactly. Raw-to-LeRobot comparison
still requires exact RGB equality for every selected frame.

The checked-in plan binds this machine's original recordings. For a fresh
reproduction, first build a v4 batch using [the v4 commands](DATA_READINESS_V4.md),
then generate an extension plan tied to that batch. Raw byte hashes are
provenance, not a promise that different installations emit identical files.
`prepare_sft_data.py plan --previous-plan` retires older collection conditions;
use the append command above when retaining the base candidates and validation.

## Review complete recordings

`make_collection_review.py` creates the existing four-command policy-view
packet. Reuse a packet when it is already present. Build an offline index
across both collection roots:

```powershell
foreach ($id in @('train_004', 'train_005', 'train_006', 'train_007')) {
    & $data scripts\make_collection_review.py `
        --condition "outputs\data_extension_v4\$id" `
        --output "outputs\data_extension_v4\review\$id"
    if ($LASTEXITCODE -ne 0) { throw "Review packet failed: $id" }
}

& $data scripts\review_sft_data.py build `
    --manifest data\lerobot\sft_readiness_v4_extended\selection_manifest.json `
    --review-roots outputs\data_readiness_v4\review_final outputs\data_extension_v4\review `
    --output outputs\NEW_REVIEW_INDEX
if ($LASTEXITCODE -ne 0) { throw 'Review inventory failed' }

Start-Process outputs\NEW_REVIEW_INDEX\index.html
```

Watch every complete episode in the cabinet-front and wrist views. Check
visibility, grasp, drawer contact, unintended movement, release, retreat, and
the final state. The page lists automated checks separately. It starts all
human decisions at `pending`; it never infers acceptance from success or
keyframes. Browser preview through an automation tool may disallow local
files; the page itself is an offline HTML file for a normal local browser.

Enter your reviewer name, confirm full-episode viewing, choose `accept` or
`reject`, and export the JSON. Rejection requires a reason. Browser storage
preserves the form where supported; the exported file is the portable record.
It is a viewing declaration, not proof that the video was watched.

```powershell
& $data scripts\review_sft_data.py check `
    --inventory outputs\NEW_REVIEW_INDEX\inventory.json `
    --decisions outputs\review_decisions.json `
    --output outputs\NEW_HUMAN_REVIEW_CHECK.json
```

The check rejects missing or duplicate rows, changed source or video hashes,
decisions tied to another inventory, unnamed approvals, unwatched approvals,
and rejections without reasons. It records the declarations without changing
the original datasets or their automatic selection. Future training must use
episodes that pass both automatic selection and human acceptance. Keep
rejections and their reasons when preparing the final training manifest.

The local review page uses Chinese labels and task translations. It preserves
the original English task strings, export values (`pending`, `accept`,
`reject`), inventory hash and browser storage key, so existing progress and
annotation files remain compatible. The recorded videos retain their original
overlays.
