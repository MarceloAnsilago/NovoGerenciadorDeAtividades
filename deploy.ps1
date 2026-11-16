[CmdletBinding()]
param(
    [ValidateSet('Oracle')]
    [string]$Target = 'Oracle',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

throw 'O deploy Oracle via SSH foi desativado. Use o mecanismo local deploy/oracle.sh na Oracle, que consulta somente oracle-production. Veja deploy/README.md. Nenhum push ou deploy foi executado.'
