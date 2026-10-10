# Windows entry point. Run as the ordinary Windows user, not Administrator:
# WSL distributions are registered per user. Elevate only WSL feature setup and the
# firewall rule that lets the assistant inside WSL reach the model server on
# Windows.
#
# Layout produced by this script:
#   Windows checkout  <- you edit skills and commit with a Windows Git GUI
#   WSL /mnt/osint-ai <- that same checkout, mounted at every terminal start
#   WSL /home/osint/osint-ai <- second checkout that owns Pixi and runs everything
#
# Local inference is the exception: llama.cpp runs *natively* on Windows, in the
# Windows checkout's own Pixi environment, outside WSL, where it reaches the GPU
# directly. Pi keeps running inside the private distribution and talks to it over
# the WSL network.
[CmdletBinding()]
param(
    [string]$RepositoryUrl = 'https://github.com/crusaderky/osint-ai.git',
    [string]$Ref = 'main',
    [string]$ProjectPath = (Join-Path $env:USERPROFILE 'osint-ai'),
    [string]$LinuxProjectPath = '/home/osint/osint-ai',
    # MobaXterm is third-party freeware: reuse an existing installation when
    # present, otherwise download this pinned, checksum-verified portable zip.
    [string]$MobaXtermUrl = 'https://download.mobatek.net/2652026082870834/MobaXterm_Portable_v26.5.zip',
    [string]$MobaXtermSha256 = 'a26e7e4e2f7bd47a13fbc6d93d08a2d946f21c3e0d135b9e4f55149842c09ef6',
    [switch]$SkipMobaXterm
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Distro = 'osint-ai'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'osint-ai'
$RootfsName = 'ubuntu-base-24.04.5-base-amd64.tar.gz'
$RootfsUrl = "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/$RootfsName"
$RootfsSha256 = 'e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86'
# Pixi for Windows, for the native llama.cpp environment only. Same version as
# windows/provision-wsl.sh pins for the copy inside WSL, so one release is reviewed
# for both; same download-and-verify shape as the rootfs above.
$PixiVersion = '0.79.0'
$PixiUrl = "https://github.com/prefix-dev/pixi/releases/download/v$PixiVersion/pixi-x86_64-pc-windows-msvc.zip"
$PixiSha256 = '7433e88d4689430cabdbadf70ed0b30148495390389616282dab53f5bba119e1'

function ConvertTo-ShellLiteral([string]$Value) {
    # POSIX single-quote escaping; never interpolate raw Windows paths into sh.
    return "'" + $Value.Replace("'", "'\''") + "'"
}

function Invoke-WslCapture([string]$Script) {
    # Same transport as Invoke-WslScript, but returns what the script printed.
    $normalized = $Script.Replace("`r`n", "`n")
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
    $command = "printf %s $encoded | base64 -d | /bin/bash"
    $output = & wsl.exe --distribution $Distro --user root --exec /bin/bash -c $command
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed (exit $LASTEXITCODE)."
    }
    return ($output | Out-String).Trim()
}

function Install-NativePixi {
    # Pixi on the Windows side. Pi never runs here, so this installation exists for
    # one job: the llama.cpp build that runs natively, in the Windows checkout's own
    # environment. Returns the path to pixi.exe.
    $exe = Join-Path $InstallRoot 'pixi.exe'
    if (Test-Path -LiteralPath $exe) { return $exe }
    $archive = Join-Path $InstallRoot ([IO.Path]::GetFileName(($PixiUrl -split '\?')[0]))
    Write-Host "Downloading Pixi $PixiVersion for Windows (checksum verified)..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $PixiUrl -OutFile $archive
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $PixiSha256) {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        throw 'Pixi download checksum mismatch. Nothing was extracted.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $InstallRoot -Force
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $exe)) { throw 'The Pixi archive did not contain pixi.exe.' }
    return $exe
}

function Invoke-Pixi([string]$Pixi, [string[]]$Arguments) {
    # `--locked` everywhere: the Windows checkout is the one the assistant may edit
    # and commit to, so a manifest that no longer matches pixi.lock has to fail
    # loudly here instead of quietly installing whatever it now names.
    & $Pixi @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "pixi $($Arguments -join ' ') failed (exit $LASTEXITCODE)."
    }
}

function Set-InferenceFirewall {
    # WSL is a separate network namespace: reaching a server on Windows from inside
    # it is *inbound* traffic on the WSL virtual adapter, and Windows blocks that by
    # default because that adapter is in the Public profile. The rule is bound to
    # that adapter and to the local subnet, so the rest of the network still cannot
    # reach the model server. One permission prompt, once.
    $adapters = @(
        Get-NetAdapter -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'vEthernet (WSL*' } |
            Select-Object -ExpandProperty Name
    )
    $interface = ''
    if ($adapters.Count -gt 0) {
        $quoted = ($adapters | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ','
        $interface = "-InterfaceAlias $quoted"
    }
    # An existing rule is reusable only while it still names the current WSL
    # adapter: a WSL update renames that adapter, and a rule bound to the old name
    # admits nothing. Checking costs no prompt; recreating costs one.
    $existing = @(Get-NetFirewallRule -DisplayName 'OSINT AI local inference' -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        $bound = @(
            $existing[0] | Get-NetFirewallInterfaceFilter |
                Select-Object -ExpandProperty InterfaceAlias
        )
        $current = $true
        foreach ($name in $bound) {
            if ($adapters -notcontains $name) { $current = $false }
        }
        if ($current) { return $true }
    }
    $result = Join-Path $InstallRoot 'firewall-result.txt'
    Remove-Item -LiteralPath $result -Force -ErrorAction SilentlyContinue
    $script = @"
try {
    Remove-NetFirewallRule -DisplayName 'OSINT AI local inference' -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName 'OSINT AI local inference' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080 -RemoteAddress LocalSubnet -Profile Any $interface | Out-Null
    Set-Content -LiteralPath '$result' -Value 'ok'
} catch {
    Set-Content -LiteralPath '$result' -Value `$_.Exception.Message
}
"@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    Write-Host 'Windows will ask for permission to let the assistant reach local inference.'
    try {
        $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList @(
            '-NoProfile', '-EncodedCommand', $encoded
        )
    } catch {
        Write-Host "The firewall rule was not added: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $result)) { return $false }
    $message = (Get-Content -LiteralPath $result -Raw).Trim()
    if ($message -eq 'ok') { return $true }
    Write-Host "The firewall rule was not added: $message" -ForegroundColor Yellow
    return $false
}

function Get-InferenceReachability {
    # The acceptance check that matters here: the assistant lives inside WSL and
    # llama.cpp lives on Windows, so the two have to reach each other through the
    # firewall rule. The address comes from the launcher, which is the single
    # implementation of that rule; loopback is not offered as a fallback, because
    # loopback inside WSL is a different machine.
    #
    # 'ok' | 'unreachable' | 'unknown'. 'unknown' means the installed launcher is too
    # old to name the address - an installation from before this design, which the
    # launcher freeze cannot update in place - and is reported as itself instead of
    # being blamed on the firewall.
    $probe = @'
import json, sys, time, urllib.request
url = sys.argv[1]
for _ in range(20):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if json.load(opener.open(url + "/health", timeout=2)).get("status") == "ok":
            print("ok")
            raise SystemExit(0)
    except Exception:
        pass
    time.sleep(1)
print("no answer on " + url)
raise SystemExit(1)
'@
    try {
        $url = Invoke-WslCapture 'set -e; /usr/bin/python3 -I /usr/local/lib/osint-ai/sandbox.py --wsl --inference-url'
    } catch {
        return 'unknown'
    }
    if (-not $url) { return 'unknown' }
    $command = '/usr/bin/python3 -I -c ' + (ConvertTo-ShellLiteral $probe) + ' ' + (ConvertTo-ShellLiteral $url)
    try {
        if ((Invoke-WslCapture $command) -eq 'ok') { return 'ok' }
    } catch {
        return 'unreachable'
    }
    return 'unreachable'
}

function Invoke-WslScript([string]$Script) {
    $normalized = $Script.Replace("`r`n", "`n")
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
    $command = "printf %s $encoded | base64 -d | /bin/bash"
    & wsl.exe --distribution $Distro --user root --exec /bin/bash -c $command
    if ($LASTEXITCODE -ne 0) {
        throw "WSL setup failed (exit $LASTEXITCODE). No sandbox bypass was enabled."
    }
}

function Assert-NoReparseParents([string]$Path) {
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Choose a local folder without junctions, symlinks, or cloud placeholders: $current"
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Get-MobaXterm {
    # Existing installation wins: MobaXterm is freeware, not something to copy
    # around a network without checking its licence.
    $candidates = @()
    $key = Get-Command MobaXterm.exe -ErrorAction SilentlyContinue
    if ($key) { $candidates += $key.Source }
    foreach ($hive in @(
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )) {
        if (!(Test-Path $hive)) { continue }
        foreach ($entry in Get-ChildItem $hive -ErrorAction SilentlyContinue) {
            $item = Get-ItemProperty $entry.PSPath -ErrorAction SilentlyContinue
            if (-not $item) { continue }
            # Select-Object tolerates a missing value; strict mode does not.
            $location = $item | Select-Object -ExpandProperty InstallLocation -ErrorAction SilentlyContinue
            if ($location) { $candidates += (Join-Path $location 'MobaXterm.exe') }
            $icon = $item | Select-Object -ExpandProperty DisplayIcon -ErrorAction SilentlyContinue
            if ($icon) { $candidates += ($icon -replace ',\d+$', '') }
        }
    }
    $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\MobaXterm\MobaXterm.exe')
    $candidates += (Get-ChildItem -Path $InstallRoot -Filter 'MobaXterm*.exe' -Recurse -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName)
    $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}

function Install-MobaXterm {
    # Returns the path to MobaXterm.exe, or $null when it is unavailable.
    $existing = Get-MobaXterm
    if ($existing) {
        Write-Host "Using the MobaXterm installation already on this PC: $existing"
        return $existing
    }
    if ($SkipMobaXterm) { return $null }
    $folder = Join-Path $InstallRoot 'MobaXterm'
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $found = Get-ChildItem -Path $folder -Filter 'MobaXterm*.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $found) {
        Write-Host 'Downloading MobaXterm (portable, checksum verified)...'
        Write-Host 'MobaXterm is third-party software; its own licence applies:'
        Write-Host '  https://mobaxterm.mobatek.net/license.html'
        $archive = Join-Path $folder ([IO.Path]::GetFileName(($MobaXtermUrl -split '\?')[0]))
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri $MobaXtermUrl -OutFile $archive
            if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $MobaXtermSha256) {
                throw 'Checksum mismatch. Nothing was extracted.'
            }
            Expand-Archive -LiteralPath $archive -DestinationPath $folder -Force
        } catch {
            # A rotting download URL must not stop the actual installation.
            Write-Host "MobaXterm was not installed: $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host 'Install MobaXterm yourself and rerun, or use the basic shortcut.'
            Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
            return $null
        }
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        $found = Get-ChildItem -Path $folder -Filter 'MobaXterm*.exe' -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    if (-not $found) { return $null }
    return $found.FullName
}

try {
    if ([Environment]::OSVersion.Version.Build -lt 22000) {
        throw 'This skeleton supports Windows 11 x64. Windows 10 and ARM are not supported.'
    }
    if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
        throw 'Use 64-bit PowerShell on an x64 Windows PC. ARM is not supported.'
    }
    if ($RepositoryUrl -notmatch '^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$') {
        throw 'RepositoryUrl must be an HTTPS GitHub repository URL, without credentials.'
    }
    if ($Ref.StartsWith('-') -or $Ref -match '[\r\n]') { throw 'Invalid repository ref.' }
    if ($LinuxProjectPath -notmatch '^/[A-Za-z0-9._/-]+$' -or $LinuxProjectPath -match '\.\.') {
        throw 'LinuxProjectPath must be a simple absolute path inside WSL, for example /home/osint/osint-ai.'
    }
    $ProjectPath = [IO.Path]::GetFullPath($ProjectPath)
    if ($ProjectPath -notmatch '^[A-Za-z]:\\.+' -or $ProjectPath -match '[\r\n]') {
        throw 'ProjectPath must be a local folder, not a drive root or network share.'
    }
    Assert-NoReparseParents $ProjectPath
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($ProjectPath))
    if ($drive.DriveFormat -ne 'NTFS') { throw 'The Windows checkout must be on NTFS.' }

    Write-Host 'OSINT AI setup: your files stay on Windows; runtime stays inside WSL.'
    & wsl.exe --status *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Windows needs to enable/update WSL. Approve the Windows administrator prompt.'
        $enable = 'wsl.exe --install --no-distribution; exit $LASTEXITCODE'
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($enable))
        $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList @(
            '-NoProfile', '-EncodedCommand', $encoded
        )
        if ($process.ExitCode -notin @(0, 3010)) {
            throw 'Windows could not install WSL. Check virtualization settings or contact your administrator.'
        }
        Write-Host 'Restart Windows, then double-click Install.cmd again. Your installation will continue.'
        exit 3010
    }

    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $distros = @(& wsl.exe --list --quiet) | ForEach-Object { ($_ -replace "`0", '').Trim() }
    if ($LASTEXITCODE -ne 0) { throw 'Could not list WSL distributions.' }
    if ($distros -notcontains $Distro) {
        $archive = Join-Path $InstallRoot $RootfsName
        if (!(Test-Path -LiteralPath $archive) -or
            (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $RootfsSha256) {
            Write-Host 'Downloading verified Ubuntu base image...'
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri $RootfsUrl -OutFile $archive
        }
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $RootfsSha256) {
            throw 'Ubuntu download checksum mismatch. Installation stopped.'
        }
        & wsl.exe --import $Distro (Join-Path $InstallRoot 'wsl') $archive --version 2
        if ($LASTEXITCODE -ne 0) { throw 'WSL import failed. Check disk space and hardware virtualization.' }
        Invoke-WslScript 'set -e; touch /etc/osint-ai-installing'
    }

    # Only the private distro created by this installer may be provisioned.
    Invoke-WslScript 'set -e; test -f /etc/osint-ai-installing || { echo "This WSL distro was not created by OSINT AI; refusing to modify it." >&2; exit 1; }'
    New-Item -ItemType Directory -Force -Path $ProjectPath | Out-Null
    $pathLiteral = ConvertTo-ShellLiteral $ProjectPath
    $repoLiteral = ConvertTo-ShellLiteral $RepositoryUrl
    $refLiteral = ConvertTo-ShellLiteral $Ref
    $linuxLiteral = ConvertTo-ShellLiteral $LinuxProjectPath
    $script = @'
set -euo pipefail

# Git for the checkout the user and the assistant work in. The assistant may
# write only on the one development branch, `staging`, so every run of this
# installer leaves that checkout on `staging`, up to date with origin, without
# touching anything unpublished.
windows_git=(git -c safe.directory=/mnt/osint-ai -C /mnt/osint-ai)
sync_staging() {
    if [[ ! -d /mnt/osint-ai/.git || -L /mnt/osint-ai/.git ]]; then
        echo 'No Git checkout is mounted; the staging branch was not checked out.' >&2
        return 1
    fi
    origin=$("${windows_git[@]}" remote get-url origin)
    [[ "$origin" == "$REPOSITORY" ]] || {
        echo 'Existing checkout has a different origin; refusing to overwrite it.' >&2
        return 1
    }
    # `clone --branch` fetches one branch only, which would also hide `staging`
    # from the assistant's own `git fetch`. Ask for every branch, on every run.
    "${windows_git[@]}" remote set-branches origin '*' || return 1
    if ! GIT_TERMINAL_PROMPT=0 "${windows_git[@]}" fetch --quiet --prune origin; then
        "${windows_git[@]}" show-ref --verify --quiet refs/heads/staging || {
            echo 'Could not reach origin and this checkout has no staging branch. Check your network, or fetch the staging branch in your Git app, then rerun Install.cmd.' >&2
            return 1
        }
        echo 'Could not reach origin; using the staging branch already in this checkout.' >&2
    fi
    if "${windows_git[@]}" show-ref --verify --quiet refs/heads/staging; then
        "${windows_git[@]}" checkout --quiet staging || {
            echo 'Uncommitted changes block switching to the staging branch. Commit them in your Git app, then rerun Install.cmd.' >&2
            return 1
        }
    else
        "${windows_git[@]}" checkout --quiet -b staging origin/staging || {
            echo 'The repository has no staging branch yet. Ask the maintainer to publish it, then rerun Install.cmd.' >&2
            return 1
        }
    fi
    if [[ -n $("${windows_git[@]}" status --porcelain) ]]; then
        echo 'Uncommitted changes are kept; the staging branch was left as it is.'
    else
        "${windows_git[@]}" merge --ff-only origin/staging ||
            echo 'Your staging branch and the one on GitHub have both moved on; push or merge them in your Git app.' >&2
    fi
    return 0
}

if [[ -f /etc/osint-ai-installed ]]; then
    /usr/bin/python3 -I - "$WINDOWS_PROJECT" <<'PY'
import json, sys
from pathlib import Path
config = json.loads(Path('/etc/osint-ai.json').read_text())
if config['windows_project'] != sys.argv[1]:
    sys.exit('This distro belongs to another project folder; refusing to reconfigure it.')
PY
    /usr/local/lib/osint-ai/mount-workspace.py
    sync_staging || exit 1
    echo 'Already installed. Existing checkouts, credentials, and environments were preserved.'
    exit 0
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates git python3 util-linux
/usr/bin/python3 -I - "$WINDOWS_PROJECT" <<'PY'
import json, sys
from pathlib import Path
config = Path('/etc/osint-ai.json')
expected = {'windows_project': sys.argv[1]}
if config.exists() and json.loads(config.read_text()) != expected:
    sys.exit('An interrupted installation used another project folder; refusing to switch it.')
config.write_text(json.dumps(expected) + '\n')
PY
mkdir -p /mnt/osint-ai
if ! mountpoint -q /mnt/osint-ai; then
    # DrvFS accepts a drive root. Bind the selected folder, then remove the
    # temporary drive mount before any user/agent process is launched.
    temporary=$(mktemp -d /run/osint-bootstrap-drive.XXXXXX)
    mkdir "$temporary/drive"
    cleanup_drive() {
        if mountpoint -q "$temporary/drive"; then
            umount "$temporary/drive" || return
        fi
        # Non-recursive removal only: never risk deleting a mounted drive.
        rmdir "$temporary/drive" "$temporary"
    }
    trap cleanup_drive EXIT
    drive=${WINDOWS_PROJECT:0:2}
    relative=${WINDOWS_PROJECT:3}
    relative=${relative//\\//}
    mount -t drvfs -o uid=1000,gid=1000,umask=022 "$drive" "$temporary/drive"
    mount --bind "$temporary/drive/$relative" /mnt/osint-ai
    cleanup_drive
    trap - EXIT
fi
if [[ -d /mnt/osint-ai/.git && ! -L /mnt/osint-ai/.git ]]; then
    echo 'Using the existing Windows checkout.'
elif [[ -z $(find /mnt/osint-ai -mindepth 1 -maxdepth 1 -print -quit) ]]; then
    GIT_TERMINAL_PROMPT=0 git -c core.autocrlf=false clone --config core.filemode=false --branch "$REF" -- "$REPOSITORY" /mnt/osint-ai
else
    echo 'Project folder is not empty and is not the expected Git checkout. Choose an empty folder.' >&2
    exit 1
fi
# The assistant must never commit to `main`, so the checkout is put on `staging`
# before provisioning reads anything out of it, and before the agent can start.
sync_staging || exit 1
exec /bin/bash /mnt/osint-ai/windows/provision-wsl.sh "$WINDOWS_PROJECT" "$REPOSITORY" "$REF" "$LINUX_PROJECT"
'@
    # Prefix escaped assignments once; never run chained replacements over user input.
    $assignments = "WINDOWS_PROJECT=$pathLiteral`nREPOSITORY=$repoLiteral`nREF=$refLiteral`nLINUX_PROJECT=$linuxLiteral`n"
    Invoke-WslScript ($assignments + $script)

    # Reload only our distro so wsl.conf disables automount/Windows interop.
    & wsl.exe --terminate $Distro
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart the OSINT AI distribution.' }
    Invoke-WslScript 'set -e; /usr/local/lib/osint-ai/mount-workspace.py; /usr/local/lib/osint-ai/mount-workspace.py --check'

    # Local inference runs natively here, outside WSL: llama.cpp on Windows reaches
    # the GPU directly, which is the whole point of the move. Pi keeps running inside
    # the distribution and talks to it over the WSL network.
    $pixi = Install-NativePixi
    $manifest = Join-Path $ProjectPath 'pixi.toml'
    if (-not (Test-Path -LiteralPath $manifest)) {
        throw "The Windows checkout has no pixi.toml at $manifest. Update it in your Windows Git app and rerun."
    }
    Write-Host 'Installing the native llama.cpp build for Windows (one time, several hundred MB)...'
    try {
        Invoke-Pixi $pixi @('install', '--locked', '-e', 'llamacpp-binary-vulkan', '--manifest-path', $manifest)
    } catch {
        throw "Local inference could not be installed: $($_.Exception.Message) Update the checkout in your Windows Git app and rerun Install.cmd."
    }
    $firewall = Set-InferenceFirewall
    $reachability = 'unreachable'
    try {
        # Start it once, prove the assistant reaches it from inside WSL, then stop it:
        # an installation that leaves a background server running would be a surprise.
        Invoke-Pixi $pixi @('run', '--locked', '-e', 'llamacpp-binary-vulkan', '--manifest-path', $manifest, '_server', 'start')
        $reachability = Get-InferenceReachability
    } catch {
        Write-Host "Local inference did not start: $($_.Exception.Message)" -ForegroundColor Yellow
    } finally {
        try {
            Invoke-Pixi $pixi @('run', '--locked', '-e', 'llamacpp-binary-vulkan', '--manifest-path', $manifest, '_server', 'stop')
        } catch {
            Write-Host "Local inference was left running: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    if ($reachability -eq 'ok') {
        Write-Host 'Checked: the assistant inside WSL reaches the model server on Windows.'
    } elseif ($reachability -eq 'unknown') {
        Write-Host 'This installation is older than this installer, so local inference could not be checked.' -ForegroundColor Yellow
        Write-Host 'Back up your project folder, then reinstall from scratch to finish the update (docs/development.md).'
    } else {
        Write-Host 'The assistant could not reach local inference from inside WSL.' -ForegroundColor Yellow
        if (-not $firewall) {
            Write-Host 'Rerun Install.cmd and approve the Windows permission prompt, or ask your IT team to allow inbound TCP 8080 from the WSL network.'
        } else {
            Write-Host 'Share the message above with your maintainer.'
        }
        Write-Host 'Online models are unaffected.'
    }
    # Plain wrappers, outside the checkout: the desktop icons stay identical no
    # matter which commit the Windows checkout is on.
    $startInference = Join-Path $InstallRoot 'start-inference.cmd'
    $stopInference = Join-Path $InstallRoot 'stop-inference.cmd'
    foreach ($pair in @(@($startInference, 'start'), @($stopInference, 'stop'))) {
        $wrapper, $action = $pair
        Set-Content -LiteralPath $wrapper -Encoding ASCII -Value @(
            '@echo off',
            'setlocal',
            "`"$pixi`" run --locked -e llamacpp-binary-vulkan --manifest-path `"$manifest`" _server $action",
            'if errorlevel 1 (',
            '    echo.',
            "    echo Local inference did not $action.",
            '    echo The assistant still works with an online model; see the README.',
            '    pause',
            ')'
        )
    }

    $moba = Install-MobaXterm
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath('Desktop')
    if ($moba) {
        # MobaXterm opens a local terminal tab and runs the WSL client in it.
        $basic = '-newtab "/cygdrive/c/WINDOWS/System32/wsl.exe -d {0} -u osint -e /usr/local/bin/osint-terminal"' -f $Distro
        $terminal = $shell.CreateShortcut((Join-Path $desktop 'OSINT AI Terminal.lnk'))
        $terminal.TargetPath = $moba
        $terminal.Arguments = $basic
        $terminal.WorkingDirectory = Split-Path -Parent $moba
        $terminal.Description = 'Start MobaXterm and open the OSINT AI chatbot.'
        $terminal.Save()
        $fallback = $shell.CreateShortcut((Join-Path $desktop 'OSINT AI Terminal (basic).lnk'))
        $fallback.TargetPath = (Join-Path $env:WINDIR 'System32\wsl.exe')
        $fallback.Arguments = "-d $Distro -u osint -e /usr/local/bin/osint-terminal"
        $fallback.Description = 'Start the OSINT AI chatbot in a plain Windows console.'
        $fallback.Save()
    } else {
        Write-Host 'MobaXterm was not installed; using a plain Windows console shortcut.'
        $terminal = $shell.CreateShortcut((Join-Path $desktop 'OSINT AI Terminal.lnk'))
        $terminal.TargetPath = (Join-Path $env:WINDIR 'System32\wsl.exe')
        $terminal.Arguments = "-d $Distro -u osint -e /usr/local/bin/osint-terminal"
        $terminal.Description = 'Start the OSINT AI chatbot.'
        $terminal.Save()
    }
    $folder = $shell.CreateShortcut((Join-Path $desktop 'OSINT AI Files.lnk'))
    $folder.TargetPath = $ProjectPath
    $folder.Save()
    # Local inference: llama.cpp runs on Windows, so these two icons are how the
    # user starts and stops it. They run the same task the Linux deployment runs.
    $start = $shell.CreateShortcut((Join-Path $desktop 'Start llama.cpp.lnk'))
    $start.TargetPath = $startInference
    $start.Description = 'Start the local AI model server that runs on Windows.'
    $start.Save()
    $stop = $shell.CreateShortcut((Join-Path $desktop 'Stop llama.cpp.lnk'))
    $stop.TargetPath = $stopInference
    $stop.Description = 'Stop the local AI model server.'
    $stop.Save()
    Write-Host "`nReady. Open 'OSINT AI Terminal' and wait for the chatbot prompt."
    Write-Host "Local models run on Windows itself: click 'Start llama.cpp', then choose one with /model. No GPU is required; without a Vulkan-capable one it uses the processor and is slower."
    Write-Host "Your skills are in $ProjectPath\workspace\.agents. Review and commit them in your Windows Git app."
} catch {
    Write-Host "`nInstallation stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'No existing WSL distributions were removed. Fix the issue and rerun Install.cmd.'
    exit 1
}
