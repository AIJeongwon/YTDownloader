[CmdletBinding()]
param(
    [string]$InstallDirectory = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$bootstrapDirectory = Join-Path $projectRoot "build\bootstrap"
if ([string]::IsNullOrWhiteSpace($InstallDirectory)) {
    $InstallDirectory = Join-Path $projectRoot "build\tools\inno"
}
$InstallDirectory = [System.IO.Path]::GetFullPath($InstallDirectory)

function Assert-ProjectChild {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $rootPrefix = $projectRoot.TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "프로젝트 밖의 Inno Setup 설치 경로는 허용하지 않습니다: $fullPath"
    }
}

Assert-ProjectChild -Path $InstallDirectory
$compiler = Join-Path $InstallDirectory "ISCC.exe"
if (Test-Path -LiteralPath $compiler -PathType Leaf) {
    Write-Output $compiler
    exit 0
}

New-Item -ItemType Directory -Force -Path $bootstrapDirectory | Out-Null
$installer = Join-Path $bootstrapDirectory "innosetup-6.7.3.exe"
$expectedHash = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"
# 공식 변경 불가능한 GitHub 릴리스 자산을 사용해 폐기되는 미러 주소에 의존하지 않습니다.
$downloadUrl = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"

if (Test-Path -LiteralPath $installer -PathType Leaf) {
    $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "기존 Inno Setup 설치 파일의 SHA-256이 고정값과 다릅니다."
    }
}
else {
    $temporary = "$installer.part"
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $temporary -UseBasicParsing
        $actualHash = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "다운로드한 Inno Setup 설치 파일의 SHA-256이 고정값과 다릅니다."
        }
        Move-Item -LiteralPath $temporary -Destination $installer
    }
    finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

New-Item -ItemType Directory -Force -Path $InstallDirectory | Out-Null
$process = Start-Process -FilePath $installer -ArgumentList @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/SP-",
    "/CURRENTUSER",
    "/DIR=`"$InstallDirectory`""
) -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "Inno Setup 설치가 종료 코드 $($process.ExitCode)로 실패했습니다."
}
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw "Inno Setup 컴파일러를 설치된 경로에서 찾을 수 없습니다."
}

Write-Output $compiler
