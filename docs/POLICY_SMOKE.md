# Four-command model smoke run

`scripts/run_policy_smoke.py` runs all four commands on the existing frozen
`validation_001` initialization: seed 801, spaced drawers, cabinet-front camera,
cabinet offset `(0.0356, -0.0072)` metres. It reuses
`remote_policy_rollout.py` and the existing action-chunk protocol.

This is a functional smoke run on one known validation initialization. It is
not an independent task-success benchmark or an OOD evaluation. Reserved tests
remain unused. The runner binds its initialization plan and immutable
simulation/data code to the v1 release before starting.

## Actual model endpoint

First complete the server processor, short-training and checkpoint-loading
checks in the [server checklist](SERVER_FIRST_RUN.md). The endpoint must run
actual π0.5 weights with their matching pre/postprocessors and frozen training
statistics. Its declared checkpoint ID must match the client argument.
The client cannot attest weight loading solely from an echoed string; retain
the server's loading and processor reports.

Run from the repository root in the existing simulation environment. Replace
the endpoint with the address already reachable from this machine and use the
actual server checkpoint ID. No network or forwarding is configured by this
command.

```powershell
$sim = 'D:\Robotics\envs\pi05-sim-win\Scripts\python.exe'
$endpoint = 'http://127.0.0.1:8765/predict' # Replace with the reachable forwarded endpoint.
$checkpoint = 'REPLACE_WITH_ACTUAL_SERVER_CHECKPOINT_ID'

# Print the four commands without creating files, stepping simulation or connecting.
& $sim scripts\run_policy_smoke.py --endpoint $endpoint `
    --checkpoint-id $checkpoint --dry-run --output outputs\NEW_PI05_SMOKE

# Run only once the real model service is ready.
& $sim scripts\run_policy_smoke.py --endpoint $endpoint `
    --checkpoint-id $checkpoint --output outputs\NEW_PI05_SMOKE
if ($LASTEXITCODE -ne 0) { throw 'Inspect the smoke report and client logs' }
```

Default settings are prediction horizon 50, execution of five actions per
observation update, 20 Hz simulation, at most 600 actions per command and a
30-second request timeout. Model runs stop at ten consecutive successful
steps or the action budget. Success uses the existing target and non-target
drawer checks. Simulation stays paused while waiting for a response.

Each command writes `report.json`, `requests.jsonl` and `rollout.mp4`.
The runner adds a batch request, a summary JSON and a Markdown table.
Transport or provenance errors stop the batch and retain partial results.
A completed task failure remains in the results and does not prevent the next
command. The process exit code describes infrastructure completion; inspect
`all_four_stable_successes` separately. Existing output directories are refused.

## Recorded-action diagnostic

Before a model exists, use the exact frozen validation recordings with the
existing replay endpoint and checks:

```powershell
& $sim scripts\run_policy_smoke.py `
    --replay-condition outputs\data_readiness_v4\validation_001 `
    --output outputs\NEW_FOUR_COMMAND_REPLAY
```

This mode verifies raw source hashes and calls the existing
`check_remote_chunks.run_check` for every recording. It uses each recording's
identity and limits execution to its original length. All reports say
`RECORDED_ACTION_CHUNKS`, `learned_policy=false`. The recorded server selects
actions by step, not from images. These runs add no demonstrations and establish
no model success. Raw HDF5 files are local and excluded from Git.

Local diagnostic measurements and checks are recorded in
[the runner validation report](../results/four_command_smoke_runner_v1.json).
The PI05 branch still needs its first actual model run on the server endpoint.
