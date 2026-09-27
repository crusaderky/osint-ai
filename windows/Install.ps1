# Windows entry point. Run as the ordinary Windows user, not Administrator:
# WSL distributions are registered per user. Elevate only WSL feature setup.
#
# Layout produced by this script:
#   Windows checkout  <- you edit skills and commit with a Windows Git GUI
#   WSL /mnt/osint-ai <- that same checkout, mounted at every terminal start
#   WSL /home/osint/osint-ai <- second checkout that owns Pixi and runs everything
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
if [[ -f /etc/osint-ai-installed ]]; then
    /usr/bin/python3 -I - "$WINDOWS_PROJECT" <<'PY'
import json, sys
from pathlib import Path
config = json.loads(Path('/etc/osint-ai.json').read_text())
if config['windows_project'] != sys.argv[1]:
    sys.exit('This distro belongs to another project folder; refusing to reconfigure it.')
PY
    /usr/local/lib/osint-ai/mount-workspace.py
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
    origin=$(git -c safe.directory=/mnt/osint-ai -C /mnt/osint-ai remote get-url origin)
    [[ "$origin" == "$REPOSITORY" ]] || { echo 'Existing checkout has a different origin; refusing to overwrite it.' >&2; exit 1; }
    echo 'Using the existing Windows checkout without pulling or discarding changes.'
elif [[ -z $(find /mnt/osint-ai -mindepth 1 -maxdepth 1 -print -quit) ]]; then
    GIT_TERMINAL_PROMPT=0 git -c core.autocrlf=false clone --config core.filemode=false --branch "$REF" -- "$REPOSITORY" /mnt/osint-ai
else
    echo 'Project folder is not empty and is not the expected Git checkout. Choose an empty folder.' >&2
    exit 1
fi
exec /bin/bash /mnt/osint-ai/windows/provision-wsl.sh "$WINDOWS_PROJECT" "$REPOSITORY" "$REF" "$LINUX_PROJECT"
'@
    # Prefix escaped assignments once; never run chained replacements over user input.
    $assignments = "WINDOWS_PROJECT=$pathLiteral`nREPOSITORY=$repoLiteral`nREF=$refLiteral`nLINUX_PROJECT=$linuxLiteral`n"
    Invoke-WslScript ($assignments + $script)

    # Reload only our distro so wsl.conf disables automount/Windows interop.
    & wsl.exe --terminate $Distro
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart the OSINT AI distribution.' }
    Invoke-WslScript 'set -e; /usr/local/lib/osint-ai/mount-workspace.py; /usr/local/lib/osint-ai/mount-workspace.py --check'

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
    Write-Host "`nReady. Open 'OSINT AI Terminal' and wait for the chatbot prompt."
    Write-Host 'Local inference needs no extra step; it starts on CPU when no NVIDIA GPU works.'
    Write-Host "Your skills are in $ProjectPath\workspace\.agents. Review and commit them in your Windows Git app."
} catch {
    Write-Host "`nInstallation stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'No existing WSL distributions were removed. Fix the issue and rerun Install.cmd.'
    exit 1
}
