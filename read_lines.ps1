$lines = Get-Content HOME/tests.py
for ($i = 1679; $i -lt 1749; $i++) {
    if ($lines[$i] -match "sitemap") {
        Write-Output "$($i+1): $($lines[$i])"
    }
}
for ($i = 1680; $i -le 1710; $i++) {
    Write-Output "$($i+1): $($lines[$i])"
}
