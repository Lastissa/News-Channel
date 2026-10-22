# TTS render for UNILAG documentary animatic
# Reads UNILAG_DOC\ANIMATIC\txt\scene_NN.txt (UTF-8), renders WAVs at a ~145wpm feel (Rate=-2)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$probe = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = ($probe.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }) -match 'Zira|Hazel|Libby|Sonia|Aria|Serena' | Select-Object -First 1
Write-Output "VOICE: $voice"
$probe.Dispose()

$root = 'C:\Users\Grace\Desktop\SaaS\django-SaaS\NoName\UNILAG_DOC\ANIMATIC'
Get-ChildItem (Join-Path $root 'txt') -Filter 'scene_*.txt' | Sort-Object Name | ForEach-Object {
    $engine = New-Object System.Speech.Synthesis.SpeechSynthesizer
    if ($voice) { $engine.SelectVoice($voice) }
    $engine.Rate = -2
    $engine.Volume = 100
    $wavPath = Join-Path $root (Join-Path 'audio' ($_.BaseName + '.wav'))
    $engine.SetOutputToWaveFile($wavPath)
    $text = [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8)
    $engine.Speak($text)
    $engine.Dispose()
    Write-Output ("OK {0}" -f $_.Name)
}
Write-Output 'TTS COMPLETE'
