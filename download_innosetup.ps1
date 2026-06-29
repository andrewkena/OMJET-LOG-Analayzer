try {
    Invoke-WebRequest -Uri 'https://jrsoftware.org/download.php/is.exe' -OutFile "$env:USERPROFILE\Downloads\innosetup.exe" -UseBasicParsing
    Write-Output 'OK'
} catch {
    Write-Output ('ERR: ' + $_.Exception.Message)
}
