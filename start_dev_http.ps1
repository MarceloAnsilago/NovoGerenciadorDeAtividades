$ErrorActionPreference = "Stop"

$hostIp = "127.0.0.2"
$port = 8000
$url = "http://$hostIp`:$port/"

Write-Host "Iniciando Django em $url"
Write-Host "Abrindo navegador no endereco HTTP correto..."
Start-Process $url

python manage.py runserver "$hostIp`:$port"
