# Espelha as pastas locais do projeto em P:\phati. Direção única: local -> P:. Nunca P: -> local.
# Uso: sync-p.ps1 [-Simular] [-Destino <pasta>]
#
# Atômico em duas fases. (1) Copia tudo para uma pasta temporária ao lado do destino. (2) Só se TODAS as cópias da fase 1
# deram certo, espelha o destino a partir dela. Falha na fase 1 apaga a temporária e não toca no destino: o backup
# anterior fica intacto. Antes, o /MIR ia direto do local para P:, e uma leitura parcial apagava em P: o que faltou.
# shortcut: falha na fase 2 (escrita em P:) pode deixar o destino parcial; a temporária é apagada no fim. Subir para
# manter a temporária e retomar se isso acontecer de fato.
param([switch]$Simular, [string]$Destino = 'P:\phati')

$origem = Split-Path -Parent $PSScriptRoot
$pastas = '.githooks', '.specify', 'docs', 'sessoes', 'specs'
$arquivos = 'DEFINICAO.md'
$robo = @('/XJ', '/R:2', '/W:2', '/NP', '/NJH', '/NJS', '/NDL')

if (-not (Test-Path $Destino)) { Write-Error "Destino $Destino indisponível."; exit 1 }

$codigo = 0
if ($Simular) {
    # Só lista: nada é escrito no destino.
    foreach ($p in $pastas) {
        if (-not (Test-Path "$origem\$p")) { continue }
        robocopy "$origem\$p" "$Destino\$p" /MIR /L @robo | Out-Null
        $codigo = [Math]::Max($codigo, $LASTEXITCODE)
    }
    foreach ($a in $arquivos) {
        if (-not (Test-Path "$origem\$a")) { continue }
        robocopy $origem $Destino $a /L @robo | Out-Null
        $codigo = [Math]::Max($codigo, $LASTEXITCODE)
    }
    # robocopy: 0-7 = sucesso; 8+ = falha
    if ($codigo -ge 8) { Write-Error "robocopy falhou (código $codigo)."; exit $codigo }
    exit 0
}

$temporaria = "$Destino.tmp-$([guid]::NewGuid().ToString('N'))"
$saida = 0
try {
    New-Item -ItemType Directory -Path $temporaria | Out-Null

    # Fase 1: cópia completa para a temporária. Destino não é tocado aqui.
    $falhou = $false
    foreach ($p in $pastas) {
        if (-not (Test-Path "$origem\$p")) { continue }
        robocopy "$origem\$p" "$temporaria\$p" /E @robo | Out-Null
        $codigo = [Math]::Max($codigo, $LASTEXITCODE)
        if ($LASTEXITCODE -ge 8) { $falhou = $true }
    }
    foreach ($a in $arquivos) {
        if (-not (Test-Path "$origem\$a")) { continue }
        robocopy $origem $temporaria $a @robo | Out-Null
        $codigo = [Math]::Max($codigo, $LASTEXITCODE)
        if ($LASTEXITCODE -ge 8) { $falhou = $true }
    }

    if ($falhou) {
        Write-Error "cópia para a temporária falhou (código $codigo); destino mantido como estava."
        $saida = $codigo
    }
    else {
        # Fase 2: só agora o destino é espelhado, a partir da cópia completa.
        foreach ($p in $pastas) {
            if (-not (Test-Path "$temporaria\$p")) { continue }
            robocopy "$temporaria\$p" "$Destino\$p" /MIR @robo | Out-Null
            $codigo = [Math]::Max($codigo, $LASTEXITCODE)
        }
        foreach ($a in $arquivos) {
            if (-not (Test-Path "$temporaria\$a")) { continue }
            robocopy $temporaria $Destino $a @robo | Out-Null
            $codigo = [Math]::Max($codigo, $LASTEXITCODE)
        }
        # robocopy: 0-7 = sucesso; 8+ = falha
        if ($codigo -ge 8) { Write-Error "espelhamento em P: falhou (código $codigo)."; $saida = $codigo }
    }
}
catch {
    Write-Error "sincronização falhou: $($_.Exception.Message)"
    $saida = 1
}
finally {
    if (Test-Path $temporaria) { Remove-Item $temporaria -Recurse -Force }
}
exit $saida
