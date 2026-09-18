# Parse without executing the installer. Works in PowerShell on Linux or Windows.
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$file = Join-Path $PSScriptRoot '../windows/Install.ps1'
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
# The README fetches this file and runs it as a script in a child PowerShell, never
# through `iex`: Windows PowerShell 5.1, the one Windows 11 ships, mishandles a
# script whose text arrives that way and declares parameters or CmdletBinding
# (PowerShell/PowerShell#8778, #8815). The parameter block must survive for the
# developer overrides, and `[ScriptBlock]::Create` is what would be broken by it.
$expression = [ScriptBlock]::Create((Get-Content -LiteralPath $file -Raw))
$parameters = @($expression.Ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
if ($parameters -notcontains 'RepositoryUrl') {
    throw 'The installer lost the parameter block the developer overrides need.'
}
if ([Environment]::OSVersion.Platform -eq [PlatformID]::Unix) {
    $embedded = $ast.Find({param($node)
        $node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
        $node.Value.Contains('set -euo pipefail')
    }, $true).Value
    # .gitattributes keeps *.ps1 CRLF for Windows editors, so the here-string
    # read from disk carries carriage returns. Invoke-WslScript normalizes the
    # script to LF before Bash ever sees it; the check must hand Bash the same
    # bytes the installer does, or it fails on a file that runs fine.
    ($embedded -replace "`r`n", "`n") | & /bin/bash -n
    if ($LASTEXITCODE -ne 0) { throw 'Embedded installer Bash syntax is invalid.' }
}
Write-Host 'PowerShell AST, shell argument escaping, parameter block, and embedded Bash syntax: OK'
