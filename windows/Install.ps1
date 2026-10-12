# Windows entry point. Run as the ordinary Windows user, not Administrator:
# WSL distributions are registered per user. Elevate only WSL feature setup and the
# firewall rule that lets the assistant inside WSL reach the model server on
# Windows.
#
# There is no installation package. The project README hands the user one line that
# downloads this file into a temporary folder and runs it as a script, with the
# same flags the old double-click wrapper used:
#
#   $p = "$env:TEMP\osint-ai-install.ps1"; irm https://raw.githubusercontent.com/<owner>/<repository>/main/windows/Install.ps1 -OutFile $p; powershell -NoProfile -ExecutionPolicy Bypass -File $p
#
# So this file runs from a temporary folder rather than from a checkout, and must
# not depend on the directory it was loaded from, which is why nothing here uses
# $PSScriptRoot. It runs in a child process, so the user's own PowerShell window
# stays open: the printed text and the exit status are both results, and the
# message above a stop is readable instead of disappearing with the window.
#
# Layout produced by this script:
#   Windows checkout  <- you edit skills and commit with a Windows Git GUI
#   WSL /mnt/osint-ai <- that same checkout, mounted at every terminal start
#   WSL /home/osint/osint-ai <- second checkout that owns Pixi and runs everything
#   /usr/local/lib/osint-ai  <- root-owned runtime inside the distro, installed
#                               here and refreshed by the Update OSINT AI icon
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
    [string]$LinuxProjectPath = '/home/osint/osint-ai'
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
    # Same transport as Invoke-WslScript, but returns what the script printed, and
    # runs as the ordinary WSL user instead of root: the reachability check asks the
    # launcher for the address the *assistant* uses, and the launcher refuses to run
    # as root, so as root the answer was always "this installation is too old to
    # name the address" - which is exactly what the check exists to rule out.
    $normalized = $Script.Replace("`r`n", "`n")
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
    $command = "printf %s $encoded | base64 -d | /bin/bash"
    $output = & wsl.exe --distribution $Distro --user osint --exec /bin/bash -c $command
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
        Write-Host 'Restart Windows, then run the install command from the README again. Your installation will continue.'
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

# Git for the checkout the user and the assistant work in. Every run of this
# installer leaves that checkout on `staging`, the one branch the assistant may
# commit to, and brings the published `main` into it first: the code this
# installation runs - provisioning, the runtime, the guided sandbox - is read out
# of that checkout, so it must be installed from after the last publish and not
# from before it.
# Hooks, the fsmonitor command and the pager all come from a `.git` the
# assistant can write in this deployment; switch them off, as the branch
# helper does.
windows_git=(git -c safe.directory=/mnt/osint-ai -c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.pager=cat -C /mnt/osint-ai)
sync_branches() {
    if [[ ! -d /mnt/osint-ai/.git || -L /mnt/osint-ai/.git ]]; then
        echo 'No Git checkout is mounted; it was not brought up to date.' >&2
        return 1
    fi
    # `clone --branch` fetches one branch only, which would also hide `staging`
    # from the assistant's own `git fetch`. Ask for every branch, on every run.
    "${windows_git[@]}" remote set-branches origin '*' || return 1
    if ! GIT_TERMINAL_PROMPT=0 "${windows_git[@]}" fetch --quiet --prune origin; then
        echo 'Could not reach the repository, so the checkout could not be brought up to date and nothing was installed from it. Check your network, then run the install command from the README again.' >&2
        return 1
    fi
    # The rule itself is scripts/git-branches.sh, the same helper the Update
    # OSINT AI icon runs: fast-forward `main`, fast-forward `staging`, merge `main`
    # into `staging` - and refuse, changing nothing, rather than resolve a
    # conflict, discard a commit or leave a detached checkout. It is read out of
    # the fetched `main` rather than taken from the checkout, because the checkout
    # is the thing being repaired: its own copy is exactly what is out of date when
    # a repair is needed, and a stale copy is how this installer came to install a
    # checkout that had never been brought forward.
    helper=/run/osint-git-branches.sh
    if ! "${windows_git[@]}" show origin/main:scripts/git-branches.sh > "$helper" 2>/dev/null; then
        rm -f "$helper"
        echo 'The published repository has no scripts/git-branches.sh on main, so the program could not be brought up to date before it was installed. Ask your maintainer to publish it, then run the install command from the README again.' >&2
        return 1
    fi
    # `safe.directory`: this runs as root, before the `osint` user exists, against
    # a checkout on a DrvFS mount that Git does not consider root's own. Its exit
    # status matters: 2 means it did what it could but something above needs a
    # human, and a checkout in that state is not installed from either.
    status=0
    GIT_TERMINAL_PROMPT=0 \
        GIT_CONFIG_COUNT=1 \
        GIT_CONFIG_KEY_0=safe.directory \
        GIT_CONFIG_VALUE_0=/mnt/osint-ai \
        /bin/bash -p "$helper" /mnt/osint-ai "$REPOSITORY" \
        || status=$?
    rm -f "$helper"
    if ((status != 0)); then
        echo 'The checkout was not brought fully up to date, so nothing was installed from it. Fix what it named above, then run the install command from the README again.' >&2
        return 1
    fi
    # That helper also fast-forwards a checkout whose repository has no `staging`
    # branch at all and says so; the assistant works on `staging`, so that is a
    # refusal here, not a state to install from.
    "${windows_git[@]}" show-ref --verify --quiet refs/heads/staging || {
        echo 'The repository has no staging branch yet. Ask the maintainer to publish it, then run the install command from the README again.' >&2
        return 1
    }
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
    sync_branches || exit 1
    # The runtime below is installed from the Linux checkout, and only the Update
    # OSINT AI icon otherwise moves that one. A rerun of the installer is the
    # documented way to repair an installation, so bring that checkout forward here
    # too - the same `pixi r update-project` step the icon runs, as the user that
    # owns it - before installing the runtime out of it. A checkout too old to
    # carry that script is used as it is, exactly as it is when it carries no
    # installer: the fallback below installs from the Windows checkout, which the
    # branch update above just brought up to date.
    linux_update=$LINUX_PROJECT/scripts/update-project.sh
    if [[ -f $linux_update ]]; then
        linux_status=0
        runuser -u osint -- env -i HOME=/home/osint PATH=/usr/local/bin:/usr/bin:/bin \
            /bin/bash -p "$linux_update" || linux_status=$?
        if ((linux_status != 0)); then
            echo "The Linux checkout at $LINUX_PROJECT was not brought fully up to date, so the installed runtime was left as it is. Fix what it named above, then run the install command from the README again." >&2
            exit 1
        fi
    else
        echo "The Linux checkout at $LINUX_PROJECT is too old to update itself; the runtime is installed from the Windows checkout instead." >&2
    fi
    # The root-owned runtime is installed once, so a PC that predates a change
    # keeps running what it installed until something refreshes it. Prefer the
    # Linux checkout: the sandbox mounts it read-only and the assistant cannot
    # write it. A checkout old enough to have no installer at all falls back to the
    # checkout this run came from, which is the trust provisioning already has.
    runtime_installer=$LINUX_PROJECT/windows/install-runtime.sh
    runtime_source=$LINUX_PROJECT
    if [[ ! -f $runtime_installer ]]; then
        runtime_installer=/mnt/osint-ai/windows/install-runtime.sh
        runtime_source=/mnt/osint-ai
    fi
    if [[ -f $runtime_installer ]]; then
        /bin/bash "$runtime_installer" "$runtime_source"
    else
        echo 'Neither checkout has windows/install-runtime.sh, so the installed runtime was left as it is.' >&2
        echo 'Pull the newest version in your Git app, then run the install command from the README again.' >&2
    fi
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
# The assistant must never commit to `main`, so the checkout is brought up to
# date and put on `staging` before provisioning reads anything out of it, and
# before the agent can start.
sync_branches || exit 1
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
        throw "Local inference could not be installed: $($_.Exception.Message) Update the checkout in your Windows Git app and run the install command from the README again."
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
            Write-Host 'Run the install command from the README again and approve the Windows permission prompt, or ask your IT team to allow inbound TCP 8080 from the WSL network.'
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

    # The Update icon: one click brings the two checkouts up to date, refreshes the
    # root-owned runtime inside WSL, and reinstalls the native llama.cpp build. A
    # plain wrapper outside the checkout, like the two above, so it stays identical
    # no matter which commit the Windows checkout is on.
    $updateWrapper = Join-Path $InstallRoot 'update-osint-ai.cmd'
    Set-Content -LiteralPath $updateWrapper -Encoding ASCII -Value @(
        '@echo off',
        'setlocal',
        'echo Updating OSINT AI. The newest program is fetched from GitHub.',
        'echo.',
        "wsl.exe -d $Distro -u root -e /bin/bash /usr/local/lib/osint-ai/update-installation.sh",
        'set "wsl_status=%ERRORLEVEL%"',
        'echo.',
        'echo Stopping the local model server so that its build can be replaced...',
        "`"$pixi`" run --locked -e llamacpp-binary-vulkan --manifest-path `"$manifest`" _server stop",
        'echo.',
        'echo Updating the local llama.cpp build...',
        "`"$pixi`" install --locked -e llamacpp-binary-vulkan --manifest-path `"$manifest`"",
        'set "build_status=%ERRORLEVEL%"',
        'echo.',
        'if not "%build_status%"=="0" goto failed',
        'if "%wsl_status%"=="0" goto done',
        'if "%wsl_status%"=="2" goto attention',
        'goto failed',
        ':done',
        'echo Updated. Click "Start llama.cpp" when you want local models again.',
        'goto end',
        ':attention',
        'echo Updated, but something above needs your attention. Fix it, then run Update OSINT AI again.',
        'goto end',
        ':failed',
        'echo The update did not finish. Read the messages above, fix what they name, then run Update OSINT AI again.',
        ':end',
        'echo.',
        'pause'
    )

    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath('Desktop')
    # One terminal shortcut, and it is a plain Windows console: the assistant is a
    # full-screen terminal program, and a console window is a terminal. MobaXterm
    # was tried first and is gone: `-newtab "<command>"` gives the command pipes
    # instead of a terminal - no stdin, no tty - so Pi could print its startup
    # lines and never take a keystroke. `wsl.exe` in a console window gives the
    # distribution a pty, which is what the assistant needs, and it is present on
    # every Windows 11 PC.
    $terminal = $shell.CreateShortcut((Join-Path $desktop 'OSINT AI Terminal.lnk'))
    $terminal.TargetPath = (Join-Path $env:WINDIR 'System32\wsl.exe')
    $terminal.Arguments = "-d $Distro -u osint -e /usr/local/bin/osint-terminal"
    $terminal.Description = 'Start the OSINT AI chatbot.'
    $terminal.Save()
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
    # Updating the program: the checkouts, the runtime inside WSL and the local
    # model server. A deliberate click, never a startup path.
    $update = $shell.CreateShortcut((Join-Path $desktop 'Update OSINT AI.lnk'))
    $update.TargetPath = $updateWrapper
    $update.Description = 'Fetch the newest OSINT AI program, and update the local model server.'
    $update.Save()
    Write-Host "`nReady. Open 'OSINT AI Terminal' and wait for the chatbot prompt."
    Write-Host "Local models run on Windows itself: click 'Start llama.cpp', then choose one with /model. No GPU is required; without a Vulkan-capable one it uses the processor and is slower."
    Write-Host "For program updates click 'Update OSINT AI': it fetches the newest version into both checkouts and updates the local model server."
    Write-Host "Your skills are in $ProjectPath\workspace\.agents. Review and commit them in your Windows Git app."
} catch {
    Write-Host "`nInstallation stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'No existing WSL distributions were removed. Fix the issue and run the install command from the README again.'
    exit 1
}
