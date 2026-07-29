$ErrorActionPreference = "Stop"

$CodexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
$Dest = Join-Path $CodexRoot "pets\hildegard"

if (Test-Path $Dest) {
    Remove-Item -Recurse -Force $Dest
    Write-Host "Removed Hildegard from $Dest"
} else {
    Write-Host "Hildegard is not installed at $Dest"
}

