# One-shot Madden 20 run: launch Build exe with the Madden mod root, wait, snapshot log, summarize, stop.
# -Seconds 0 = play session: no time limit, the game is never killed by this script.
# PERF (10-14): gameplay 5 FPS under cdb vs 30 FPS (= the game's own cap) with this runner. Use this for play.
param(
    [int]$Seconds = 150,
    [string]$Tag = "run",
    [string[]]$Extra = @(),
    [switch]$Play   # the owner playing: borderless fullscreen on the main (1440p) monitor, no move to monitor 2
)
$ErrorActionPreference = "Continue"
$exe  = "C:\madden20_online\core_src\Build\madden-RelWithDebInfo\shadps4.exe"
$game = "C:\games\CUSA13265\eboot.bin"
$log  = Join-Path $env:APPDATA "shadPS4\log\shad_log.txt"
$outDir = "C:\madden20_online\runs"
New-Item -ItemType Directory -Force $outDir | Out-Null

Get-Process shadps4 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

$env:NBA2K14_MOD_ROOT = "C:\madden20_online\modroot"
$fs = if ($Play) { "true" } else { "false" }
$p = Start-Process -FilePath $exe -ArgumentList (@("-g", "`"$game`"", "-f", $fs) + $Extra) `
        -WorkingDirectory (Split-Path $exe) -PassThru
Write-Output "launched pid=$($p.Id) tag=$Tag wait=${Seconds}s"
# PS4 Pro mode (per-game config "General.neo_mode"): Madden renders 3200x1800 for its 4K output; res_poke.py caps
# GameRenderSettings.ResolutionScale to 2560/3840 at boot = native 2560x1440 rendering (fewer hitches, 10-17).
$cfg = Join-Path $env:APPDATA "shadPS4\custom_configs\CUSA13265.json"
try { $neo = (Get-Content $cfg -Raw | ConvertFrom-Json).General.neo_mode } catch { $neo = $false }
if ($neo) {
    Start-Process -FilePath python -ArgumentList @("-I", "C:\madden20_online\tools\res_poke.py") `
        -RedirectStandardOutput "$outDir\res_poke.log" -WindowStyle Hidden
}
# the owner works on the main monitor: the game window always goes to monitor 2 (no focus steal).
if (-not $Play) {
    Start-Process -FilePath python -ArgumentList @("-I", "C:\madden20_online\tools\to_monitor2.py", "--wait", "120") -WindowStyle Hidden
}

if ($Seconds -le 0) {
    $p.WaitForExit()
    Write-Output "game exited code=$($p.ExitCode)"
    exit 0
}
$t0 = Get-Date
while (((Get-Date) - $t0).TotalSeconds -lt $Seconds) {
    Start-Sleep -Seconds 5
    if ($p.HasExited) { Write-Output "process exited early code=$($p.ExitCode) at $([int]((Get-Date)-$t0).TotalSeconds)s"; break }
}

$stamp = Get-Date -Format "MMdd_HHmmss"
$snap = Join-Path $outDir "shad_log_${Tag}_$stamp.txt"
Copy-Item $log $snap -Force
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Write-Output "snapshot=$snap"
