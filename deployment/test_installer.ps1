[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$InstallDirectory
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$installerPath = [System.IO.Path]::GetFullPath($Installer)
$targetPath = [System.IO.Path]::GetFullPath($InstallDirectory)
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "설치 파일을 찾을 수 없습니다: $installerPath"
}
if (Test-Path -LiteralPath $targetPath) {
    throw "설치 테스트 경로가 이미 존재합니다: $targetPath"
}

$install = Start-Process -FilePath $installerPath -ArgumentList @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/NOICONS",
    "/DIR=`"$targetPath`""
) -WindowStyle Hidden -Wait -PassThru
if ($install.ExitCode -ne 0) {
    throw "무인 설치가 종료 코드 $($install.ExitCode)로 실패했습니다."
}

$application = Join-Path $targetPath "YTDownloader.exe"
$uninstaller = Join-Path $targetPath "unins000.exe"
if (-not (Test-Path -LiteralPath $application -PathType Leaf) -or
    -not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
    throw "설치 결과에서 앱 또는 제거 프로그램을 찾을 수 없습니다."
}

$check = Start-Process -FilePath $application -ArgumentList "--check-installation" -WindowStyle Hidden -PassThru
if (-not $check.WaitForExit(60000)) {
    $check.Kill($true)
    throw "설치된 앱의 시작 검사가 제한 시간 안에 끝나지 않았습니다."
}
if ($check.ExitCode -ne 0) {
    throw "설치된 앱의 시작 검사가 종료 코드 $($check.ExitCode)로 실패했습니다."
}

$uninstall = Start-Process -FilePath $uninstaller -ArgumentList @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART"
) -WindowStyle Hidden -Wait -PassThru
if ($uninstall.ExitCode -ne 0) {
    throw "무인 제거가 종료 코드 $($uninstall.ExitCode)로 실패했습니다."
}
if (Test-Path -LiteralPath $targetPath) {
    $remaining = @(Get-ChildItem -LiteralPath $targetPath -Force -ErrorAction SilentlyContinue)
    if ($remaining.Count -gt 0) {
        throw "제거 후 설치 경로에 파일이 남았습니다: $targetPath"
    }
    Remove-Item -LiteralPath $targetPath -Force
}

Write-Output "설치·실행·제거 검사 완료: $installerPath"
