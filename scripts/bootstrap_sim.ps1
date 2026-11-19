param(
    [string]$RoboticsRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$BasePython = '',
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$envRoot = Join-Path $RoboticsRoot 'envs\pi05-sim-win'
$python = Join-Path $envRoot 'Scripts\python.exe'
$upstream = Join-Path $RoboticsRoot 'upstream'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable $($Arguments -join ' ')" }
}

Push-Location $project
try {
    if (-not $VerifyOnly) {
        New-Item -ItemType Directory -Force $envRoot, $upstream, (Join-Path $RoboticsRoot 'cache\pip') | Out-Null
        $env:PIP_CACHE_DIR = Join-Path $RoboticsRoot 'cache\pip'
        if (-not (Test-Path -LiteralPath $python)) {
            if (-not $BasePython) { $BasePython = (& py -3.11 -c 'import sys; print(sys.executable)').Trim() }
            Invoke-Checked $BasePython @('-m', 'venv', $envRoot)
        }
        Invoke-Checked $python @('-m', 'pip', 'install', '-r', 'requirements/sim-win.lock.txt')
        $repos = @(
            @{Name='robosuite'; Url='https://github.com/ARISE-Initiative/robosuite.git'; Commit='5ce6643f3092639d08f7b0f90ed1c6a84f50552c'},
            @{Name='robocasa'; Url='https://github.com/robocasa/robocasa.git'; Commit='425684d332f135f5b30a40b321f52d15a0fe9250'}
        )
        foreach ($repo in $repos) {
            $checkout = Join-Path $upstream $repo.Name
            if (-not (Test-Path -LiteralPath $checkout)) {
                Invoke-Checked 'git' @('clone', '--filter=blob:none', '--no-checkout', $repo.Url, $checkout)
                Invoke-Checked 'git' @('-C', $checkout, 'checkout', '--detach', $repo.Commit)
            }
            $head = (& git -C $checkout rev-parse HEAD).Trim()
            if ($head -ne $repo.Commit) { throw "Unexpected upstream HEAD: $checkout ($head). Existing checkout kept intact." }
            $dirty = & git -C $checkout status --porcelain --untracked-files=no
            if ($dirty) { throw "Upstream has local tracked changes: $checkout" }
            Invoke-Checked $python @('-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '-e', $checkout)
        }
        Invoke-Checked $python @('-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '-e', $project)
    }
    if (-not (Test-Path -LiteralPath $python)) { throw "Missing environment: $envRoot" }
    Invoke-Checked $python @('scripts/mujoco_smoke.py', '--output', 'outputs/native_smoke', '--viewer-seconds', '4')
    Invoke-Checked $python @('scripts/scene_smoke.py', '--output', 'outputs/scene_smoke')
} finally {
    Pop-Location
}
