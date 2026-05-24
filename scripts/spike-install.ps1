<#
.SYNOPSIS
    Install / restore the claude-prospector plugin for the self-audit Stop-hook spike (#129).

.DESCRIPTION
    This branch (self-audit-spike-129) ships:
      1. hooks/hooks.json with session-audit-prompt.py registered as a Stop hook
      2. .claude-plugin/marketplace.json declaring a local marketplace
         'claude-prospector-spike' that points at this worktree as its sole plugin

    Persistent install is achieved by adding the worktree as a marketplace, then
    installing the plugin from that marketplace. The release marketplace
    (glitchwerks) stays registered; we just temporarily install the spike copy
    instead of the released one.

    Subcommands:
      install  - Add this worktree as the 'claude-prospector-spike' marketplace,
                 uninstall any currently-installed claude-prospector, and install
                 the spike copy.
      status   - Show the active claude-prospector install and the configured
                 marketplaces so you can verify which copy is live.
      restore  - Uninstall the spike copy, remove the 'claude-prospector-spike'
                 marketplace, and reinstall claude-prospector from the
                 'glitchwerks' marketplace. Run when the spike concludes.

.NOTES
    The worktree root is resolved relative to this script's location, so the
    script works regardless of cwd.

    Issue: https://github.com/glitchwerks/claude-prospector/issues/129
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('install', 'status', 'restore')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'

$WorktreeRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PluginName = 'claude-prospector'
$SpikeMarketplace = 'claude-prospector-spike'
$ReleaseMarketplace = 'glitchwerks'

# Plugin venv path follows the setup-prospector slug convention:
#   plugin id "claude-prospector@claude-prospector-spike" -> directory
#   "claude-prospector-claude-prospector-spike" (every char outside
#   [a-zA-Z0-9_-] replaced by a hyphen). CLAUDE_PLUGIN_DATA may override.
$SpikePluginData = if ($env:CLAUDE_PLUGIN_DATA) {
    $env:CLAUDE_PLUGIN_DATA
} else {
    Join-Path $HOME '.claude\plugins\data\claude-prospector-claude-prospector-spike'
}

function Write-Step($msg) {
    Write-Host ">> $msg" -ForegroundColor Cyan
}

function Invoke-Claude {
    param([Parameter(Mandatory = $true)][string[]]$ClaudeArgs)
    Write-Host "   claude $($ClaudeArgs -join ' ')" -ForegroundColor DarkGray
    & claude @ClaudeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "claude $($ClaudeArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Invoke-ClaudeIgnoreFail {
    param([Parameter(Mandatory = $true)][string[]]$ClaudeArgs, [string]$WarnMsg)
    Write-Host "   claude $($ClaudeArgs -join ' ')" -ForegroundColor DarkGray
    & claude @ClaudeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   $WarnMsg" -ForegroundColor DarkYellow
    }
}

switch ($Action) {
    'install' {
        Write-Step "Spike worktree: $WorktreeRoot"

        Write-Step "Adding spike marketplace '$SpikeMarketplace' (idempotent)..."
        Invoke-ClaudeIgnoreFail -ClaudeArgs @('plugin', 'marketplace', 'add', $WorktreeRoot) `
            -WarnMsg "(marketplace add failed; may already be registered, continuing)"

        Write-Step "Uninstalling any current $PluginName install..."
        Invoke-ClaudeIgnoreFail -ClaudeArgs @('plugin', 'uninstall', $PluginName) `
            -WarnMsg "(no existing install to remove, continuing)"

        Write-Step "Installing $PluginName from $SpikeMarketplace..."
        Invoke-Claude -ClaudeArgs @('plugin', 'install', "${PluginName}@${SpikeMarketplace}")

        # The plugin install above wires hooks + skills but does NOT install
        # the claude_prospector Python package -- /setup-prospector handles
        # that, defaulting to a PyPI install. Spikes are local-only and not
        # published to PyPI, so PyPI default ships the wrong (stale) wheel.
        # Reinstall editable from this worktree so the spike's actual code
        # runs. See issues #145, #146, #147.
        $VenvWindowsPython = Join-Path $SpikePluginData 'venv\Scripts\python.exe'
        $VenvPosixPython = Join-Path $SpikePluginData 'venv/bin/python'
        $VenvPy = if (Test-Path $VenvWindowsPython) {
            $VenvWindowsPython
        } elseif (Test-Path $VenvPosixPython) {
            $VenvPosixPython
        } else {
            $null
        }

        if ($VenvPy) {
            Write-Step "Reinstalling claude_prospector editable from spike worktree..."
            Write-Host "   uv pip install --python $VenvPy --force-reinstall -e $WorktreeRoot" -ForegroundColor DarkGray
            & uv pip install --python $VenvPy --force-reinstall -e $WorktreeRoot
            if ($LASTEXITCODE -ne 0) {
                Write-Host "   Editable install failed; dashboard may render stale code. Re-run after fixing." -ForegroundColor DarkYellow
            }
        } else {
            Write-Host "   Spike plugin venv not found at $SpikePluginData\venv." -ForegroundColor DarkYellow
            Write-Host "   Run /setup-prospector in a Claude Code session, then re-run this script" -ForegroundColor DarkYellow
            Write-Host "   to install claude_prospector editable from the spike worktree." -ForegroundColor DarkYellow
        }

        Write-Step "Done. Verify with: .\scripts\spike-install.ps1 status"
        Write-Step "Open a new Claude Code session; the Stop hook fires at session end."
    }

    'status' {
        Write-Step "Configured marketplaces:"
        Invoke-Claude -ClaudeArgs @('plugin', 'marketplace', 'list')

        Write-Step "Active $PluginName install:"
        & claude plugin list | Select-String -Pattern $PluginName -Context 0, 2
        if ($LASTEXITCODE -ne 0) {
            throw "claude plugin list failed with exit code $LASTEXITCODE"
        }
    }

    'restore' {
        Write-Step "Uninstalling spike copy of $PluginName..."
        Invoke-ClaudeIgnoreFail -ClaudeArgs @('plugin', 'uninstall', $PluginName) `
            -WarnMsg "(no existing install to remove, continuing)"

        Write-Step "Removing spike marketplace '$SpikeMarketplace'..."
        Invoke-ClaudeIgnoreFail -ClaudeArgs @('plugin', 'marketplace', 'remove', $SpikeMarketplace) `
            -WarnMsg "(marketplace not present, continuing)"

        Write-Step "Reinstalling release $PluginName from '$ReleaseMarketplace'..."
        Invoke-Claude -ClaudeArgs @('plugin', 'install', "${PluginName}@${ReleaseMarketplace}")

        Write-Step "Done. Release copy active; spike hook is no longer registered."
    }
}
