# Parse without executing the installer. Works in PowerShell on Linux or Windows.
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$file = Join-Path $PSScriptRoot '../wsl/Install.ps1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$function = $ast.Find({param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'ConvertTo-ShellLiteral'
}, $true)
. ([ScriptBlock]::Create($function.Extent.Text))
if ((ConvertTo-ShellLiteral 'plain text') -cne "'plain text'") { throw 'Space escaping failed.' }
if ((ConvertTo-ShellLiteral "O'Brien") -cne "'O'\''Brien'") { throw 'Quote escaping failed.' }
if ((ConvertTo-ShellLiteral '$HOME; $(echo bad)') -cne "'`$HOME; `$(echo bad)'") {
    throw 'Shell metacharacters were expanded.'
}
if ([Environment]::OSVersion.Platform -eq [PlatformID]::Unix) {
    $embedded = $ast.Find({param($node)
        $node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
        $node.Value.Contains('set -euo pipefail')
    }, $true).Value
    $embedded | & /bin/bash -n
    if ($LASTEXITCODE -ne 0) { throw 'Embedded installer Bash syntax is invalid.' }
}
Write-Host 'PowerShell AST, shell argument escaping, and embedded Bash syntax: OK'
