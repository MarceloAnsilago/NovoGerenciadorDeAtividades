[CmdletBinding()]
param(
    [ValidateSet('Oracle', 'Fly', 'Ambos')]
    [string]$Target = 'Oracle',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function Invoke-Native {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program falhou (codigo $LASTEXITCODE)." }
}
function Quote-Sh([string]$Value) {
    if ($Value.Contains("'" ) -or $Value.Contains("`n") -or $Value.Contains("`r")) {
        throw 'Configuracao contem caracteres nao permitidos.'
    }
    return "'$Value'"
}

$oracle = $Target -in 'Oracle', 'Ambos'
$fly = $Target -in 'Fly', 'Ambos'
$sshArgs = @()
if ($oracle) {
    Get-Command ssh -ErrorAction Stop | Out-Null
    $configPath = Join-Path $PSScriptRoot 'deploy/oracle.local.json'
    if (!(Test-Path -LiteralPath $configPath)) {
        throw 'Copie deploy/oracle.example.json para deploy/oracle.local.json e preencha User e IdentityFile (ou use um alias SSH em Host).'
    }
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    foreach ($field in 'Host', 'User', 'ProjectPath', 'VenvPath', 'Service') {
        if ([string]::IsNullOrWhiteSpace($config.$field) -or $config.$field -like 'PREENCHER*') {
            throw "Preencha $field em deploy/oracle.local.json."
        }
    }
    if ($config.Host -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.:-]*$' -or $config.User -notmatch '^[a-zA-Z0-9_][a-zA-Z0-9_-]*$') {
        throw 'Host ou User invalido.'
    }
    $sshArgs = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15')
    if ($config.IdentityFile) {
        if (!(Test-Path -LiteralPath $config.IdentityFile -PathType Leaf)) { throw 'Chave SSH nao encontrada.' }
        $sshArgs += @('-i', $config.IdentityFile, '-o', 'IdentitiesOnly=yes')
    }
    $sshArgs += "$($config.User)@$($config.Host)"
}
if ($fly) { Get-Command flyctl -ErrorAction Stop | Out-Null }
Get-Command git -ErrorAction Stop | Out-Null
$dirty = & git status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'Falha ao verificar repositorio.' }
if ($dirty) { throw 'Salve e faca commit das alteracoes antes do deploy, para enviar a mesma versao aos dois servidores.' }
$revision = & git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Falha ao identificar commit.' }
$branch = & git symbolic-ref --quiet --short HEAD
if ($LASTEXITCODE -ne 0) { throw 'Selecione uma branch antes do deploy.' }
if ($CheckOnly) {
    if ($oracle) {
        $probe = 'test -d ' + (Quote-Sh $config.ProjectPath) + ' && test -x ' + (Quote-Sh "$($config.VenvPath)/bin/python") + ' && sudo -n -l /usr/bin/systemctl restart ' + (Quote-Sh $config.Service)
        Invoke-Native ssh ($sshArgs + @($probe))
    }
    if ($fly) { Invoke-Native flyctl @('auth', 'whoami') }
    Write-Host 'Verificacao concluida; nenhum deploy executado.'
    exit 0
}
if ($oracle) {
    # Testar acesso antes de enviar o commit ao GitHub.
    Invoke-Native ssh ($sshArgs + @('true'))
    Invoke-Native git @('push', 'origin', "HEAD:refs/heads/$branch")
    $remoteArgs = @($config.ProjectPath, $config.VenvPath, $config.Service, $revision, $branch) | ForEach-Object { Quote-Sh $_ }
    $command = "tr -d '\r' | bash -s -- " + ($remoteArgs -join ' ')
    $script = (Get-Content (Join-Path $PSScriptRoot 'deploy/oracle.sh') -Raw).Replace("`r`n", "`n")
    $script | & ssh @sshArgs $command
    if ($LASTEXITCODE -ne 0) { throw 'Deploy Oracle falhou. Verifique a saida; o Fly ainda nao foi atualizado nesta execucao.' }
}
if ($fly) { Invoke-Native flyctl @('deploy', '-a', 'gerenciador-de-atividades') }
Write-Host "Deploy concluido: $Target ($revision)."
