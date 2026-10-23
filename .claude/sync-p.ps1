# Espelha as pastas locais do projeto em P:\phati. Direção única: local -> P:. Nunca P: -> local.
# Uso: sync-p.ps1 [-Simular]
param([switch]$Simular)

$origem = Split-Path -Parent $PSScriptRoot
$destino = 'P:\phati'
$pastas = '.githooks', '.specify', 'docs', 'sessoes', 'specs'
$arquivos = 'DEFINICAO.md'

if (-not (Test-Path $destino)) { Write-Error "Destino $destino indisponível."; exit 1 }

$extra = if ($Simular) { '/L' } else { @() }
$codigo = 0
foreach ($p in $pastas) {
    if (-not (Test-Path "$origem\$p")) { continue }
    robocopy "$origem\$p" "$destino\$p" /MIR /XJ /R:2 /W:2 /NP /NJH /NJS /NDL @extra | Out-Null
    $codigo = [Math]::Max($codigo, $LASTEXITCODE)
}
foreach ($a in $arquivos) {
    if (-not (Test-Path "$origem\$a")) { continue }
    robocopy $origem $destino $a /R:2 /W:2 /NP /NJH /NJS /NDL @extra | Out-Null
    $codigo = [Math]::Max($codigo, $LASTEXITCODE)
}
# robocopy: 0-7 = sucesso; 8+ = falha
if ($codigo -ge 8) { Write-Error "robocopy falhou (código $codigo)."; exit $codigo }
exit 0
