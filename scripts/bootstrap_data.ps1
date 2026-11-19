param(
    [string]$RoboticsRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$BasePython = 'D:\anconda\python.exe',
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$envRoot = Join-Path $RoboticsRoot 'envs\pi05-data-cpu'
$python = Join-Path $envRoot 'Scripts\python.exe'
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Executable $($Arguments -join ' ')" }
}
Push-Location $project
try {
    $env:PIP_CACHE_DIR = Join-Path $RoboticsRoot 'cache\pip'
    $env:HF_HOME = Join-Path $RoboticsRoot 'cache\huggingface'
    if (-not $VerifyOnly) {
        if (-not (Test-Path -LiteralPath $python)) {
            Invoke-Checked $BasePython @('-m', 'venv', $envRoot)
        }
        Invoke-Checked $python @('-m', 'pip', 'install', '--index-url', 'https://download.pytorch.org/whl/cpu', 'torch==2.7.1+cpu', 'torchvision==0.22.1+cpu')
        $requirements = if (Test-Path 'requirements/data-cpu.lock.txt') { 'requirements/data-cpu.lock.txt' } else { 'requirements/data-cpu.txt' }
        Invoke-Checked $python @('-m', 'pip', 'install', '-r', $requirements)
        Invoke-Checked $python @('-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '-e', $project)
    }
    Invoke-Checked $python @('-c', 'import torch; from lerobot.datasets.lerobot_dataset import LeRobotDataset; assert torch.version.cuda is None; print(torch.__version__, LeRobotDataset.__name__)')
    Invoke-Checked $python @('-m', 'pip', 'check')
} finally { Pop-Location }
