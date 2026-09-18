# Windows entry point. Run as the ordinary Windows user, not Administrator:
# WSL distributions are registered per user. Elevate only WSL feature setup.
[CmdletBinding()]
param(
    [string]$RepositoryUrl = 'https://github.com/crusaderky/osint-ai.git',
    [string]$Ref = 'main',
    [string]$ProjectPath = (Join-Path $env:USERPROFILE 'osint-ai')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Distro = 'osint-ai'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'osint-ai'
$RootfsName = 'ubuntu-base-24.04.5-base-amd64.tar.gz'
$RootfsUrl = "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/$RootfsName"
$RootfsSha256 = 'e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86'

function ConvertTo-ShellLiteral([string]$Value) {
    # POSIX single-quote escaping; never interpolate raw Windows paths into sh.
    return "'" + $Value.Replace("'", "'\''") + "'"
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
    $script = @'
set -euo pipefail
if [[ -f /etc/osint-ai-installed ]]; then
    /usr/bin/python3 -I - "$WINDOWS_PROJECT" <<'PY'
import json, sys
from pathlib import Path
if json.loads(Path('/etc/osint-ai.json').read_text())['windows_project'] != sys.argv[1]:
    sys.exit('This distro belongs to another project folder; refusing to reconfigure it.')
PY
    /usr/local/lib/osint-ai/mount-workspace.py
    echo 'Already installed. Existing checkout, credentials, and environments were preserved.'
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
mkdir -p /workspace
if ! mountpoint -q /workspace; then
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
    mount --bind "$temporary/drive/$relative" /workspace
    cleanup_drive
    trap - EXIT
fi
if [[ -d /workspace/.git && ! -L /workspace/.git ]]; then
    origin=$(git -c safe.directory=/workspace -C /workspace remote get-url origin)
    [[ "$origin" == "$REPOSITORY" ]] || { echo 'Existing checkout has a different origin; refusing to overwrite it.' >&2; exit 1; }
    echo 'Using existing checkout without pulling or discarding changes.'
elif [[ -z $(find /workspace -mindepth 1 -maxdepth 1 -print -quit) ]]; then
    GIT_TERMINAL_PROMPT=0 git -c core.autocrlf=false clone --config core.filemode=false --branch "$REF" -- "$REPOSITORY" /workspace
else
    echo 'Project folder is not empty and is not the expected Git checkout. Choose an empty folder.' >&2
    exit 1
fi
exec /bin/bash /workspace/scripts/provision-wsl.sh "$WINDOWS_PROJECT"
'@
    # Prefix escaped assignments once; never run chained replacements over user input.
    $assignments = "WINDOWS_PROJECT=$pathLiteral`nREPOSITORY=$repoLiteral`nREF=$refLiteral`n"
    Invoke-WslScript ($assignments + $script)

    # Reload only our distro so wsl.conf disables automount/Windows interop.
    & wsl.exe --terminate $Distro
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart the OSINT AI distribution.' }
    Invoke-WslScript 'set -e; /usr/local/lib/osint-ai/mount-workspace.py; /usr/local/lib/osint-ai/mount-workspace.py --check'

    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcut = $shell.CreateShortcut((Join-Path $desktop 'OSINT AI Terminal.lnk'))
    $shortcut.TargetPath = (Join-Path $env:WINDIR 'System32\wsl.exe')
    $shortcut.Arguments = '--distribution osint-ai --user osint --cd /workspace'
    $shortcut.Save()
    $folder = $shell.CreateShortcut((Join-Path $desktop 'OSINT AI Files.lnk'))
    $folder.TargetPath = $ProjectPath
    $folder.Save()
    Write-Host "`nReady. Open 'OSINT AI Terminal' and type osint-pi."
    Write-Host 'For local NVIDIA inference: start-server, then osint-pi, then /models.'
    Write-Host "Review skills in $ProjectPath\agents. Open this checkout in your Windows Git GUI."
} catch {
    Write-Host "`nInstallation stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'No existing WSL distributions were removed. Fix the issue and rerun Install.cmd.'
    exit 1
}
