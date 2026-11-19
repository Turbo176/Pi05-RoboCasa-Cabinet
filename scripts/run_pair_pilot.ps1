param(
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [int]$Seed = 0,
    [ValidateSet('compact','spaced')][string]$PairLayout = 'spaced',
    [double[]]$SceneOffset = @(0.0, 0.0),
    [string]$SplitPlan,
    [string]$ConditionId,
    [switch]$SkipConversion,
    [string]$SimPython = 'D:\Robotics\envs\pi05-sim-win\Scripts\python.exe',
    [string]$DataPython = 'D:\Robotics\envs\pi05-data-cpu\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if ([bool]$SplitPlan -ne [bool]$ConditionId) { throw 'SplitPlan and ConditionId must be supplied together' }
if ($SplitPlan) {
    foreach ($name in @('Seed', 'PairLayout', 'SceneOffset')) {
        if ($PSBoundParameters.ContainsKey($name)) { throw "With SplitPlan, $name is fixed by the plan" }
    }
    $plan = Get-Content -LiteralPath $SplitPlan -Raw | ConvertFrom-Json
    if ($plan.schema -ne 'cabinet_split_plan_v1') { throw 'Unknown split plan schema' }
    $condition = @($plan.conditions | Where-Object { $_.id -eq $ConditionId })
    if ($condition.Count -ne 1) { throw "Condition must occur exactly once: $ConditionId" }
    $condition = $condition[0]
    if ($condition.split -notin @('train', 'validation')) {
        throw 'This collection command leaves held-out tests unexecuted'
    }
    foreach ($entry in $plan.collection_code_sha256.PSObject.Properties) {
        $actual = (Get-FileHash -LiteralPath $entry.Name -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $entry.Value) { throw "Collection code changed after the plan was frozen: $($entry.Name)" }
    }
    $Seed = [int]$condition.seed
    $SceneOffset = @([double]$condition.scene_offset[0], [double]$condition.scene_offset[1])
    $PairLayout = $plan.pair_layout
    $planHash = (Get-FileHash -LiteralPath $SplitPlan -Algorithm SHA256).Hash.ToLowerInvariant()
}
if ($SceneOffset.Length -ne 2) { throw 'SceneOffset requires two values in metres' }
foreach ($python in @($SimPython, $DataPython)) {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Existing Python environment missing: $python" }
}
if (Test-Path -LiteralPath $OutputRoot) { throw "OutputRoot must be new: $OutputRoot" }
$root = (New-Item -ItemType Directory -Path $OutputRoot).FullName
if ($SplitPlan) {
    @{
        schema='cabinet_collection_request_v1'; plan_sha256=$planHash;
        condition_id=$ConditionId; split=$condition.split; seed=$Seed;
        scene_offset=$SceneOffset; pair_layout=$PairLayout;
        source='SCRIPTED_PRIVILEGED_STATE'; learned_policy=$false
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $root 'collection_request.json') -Encoding UTF8
}
$cases = @(
    @{Task='OpenDrawerPairLite'; Instruction='Open the top drawer.'; Name='open_top'},
    @{Task='OpenDrawerPairLite'; Instruction='Open the bottom drawer.'; Name='open_bottom'},
    @{Task='CloseDrawerPairLite'; Instruction='Close the top drawer.'; Name='close_top'},
    @{Task='CloseDrawerPairLite'; Instruction='Close the bottom drawer.'; Name='close_bottom'}
)
$episodes = @()
$invariant = [System.Globalization.CultureInfo]::InvariantCulture
$dx = $SceneOffset[0].ToString($invariant)
$dy = $SceneOffset[1].ToString($invariant)
foreach ($case in $cases) {
    $output = Join-Path $root $case.Name
    & $SimPython scripts\scripted_rollout.py --task $case.Task --instruction $case.Instruction --pair-layout $PairLayout --seed $Seed --scene-offset $dx $dy --output $output
    if ($LASTEXITCODE -ne 0) { throw "Rollout failed to record: $($case.Name)" }
    $episodes += Join-Path $output 'episode.hdf5'
    & $SimPython scripts\replay_episode.py (Join-Path $output 'episode.hdf5') --output (Join-Path $root "replay_$($case.Name)")
    if ($LASTEXITCODE -ne 0) { throw "Replay validation failed: $($case.Name)" }
}
& $DataPython scripts\evaluate_drawer_pair.py @episodes --output (Join-Path $root 'evaluation')
if ($LASTEXITCODE -ne 0) { throw 'Pilot audit failed' }
# A scripted pipeline check, including any failed episodes with source labels;
# this does not select or publish a successful SFT dataset.
if (-not $SkipConversion) {
    & $DataPython scripts\convert_lerobot.py @episodes --allow-scripted --output (Join-Path $root 'lerobot_pipeline_check')
    if ($LASTEXITCODE -ne 0) { throw 'LeRobot conversion or loader verification failed' }
}
Write-Output "Recorded actions, replay videos and independent pilot audit: $root"
