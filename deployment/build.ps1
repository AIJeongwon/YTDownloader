[CmdletBinding()]
param(
    [string]$PythonCommand = "",
    [string]$RepositoryUrl = "https://github.com/AIJeongwon/YTDownloader",
    [string]$Publisher = "AIJeongwon"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($PythonCommand)) {
    $localPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $PythonCommand = if (Test-Path -LiteralPath $localPython -PathType Leaf) { $localPython } else { "python" }
}
if ($Publisher -notmatch '^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$') {
    throw "게시자 이름은 올바른 GitHub 사용자 이름이어야 합니다."
}

function Invoke-PythonCommand {
    param([Parameter(Mandatory = $true)][string[]]$CommandArguments)

    & $script:PythonCommand @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python 명령이 종료 코드 $LASTEXITCODE(으)로 실패했습니다."
    }
}

function Assert-ProjectChild {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $rootPrefix = $projectRoot.TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "프로젝트 밖의 빌드 경로는 허용하지 않습니다: $fullPath"
    }
    return $fullPath
}

function Reset-BuildDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    $safePath = Assert-ProjectChild -Path $Path
    if (Test-Path -LiteralPath $safePath) {
        Remove-Item -LiteralPath $safePath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $safePath | Out-Null
}

Push-Location $projectRoot
try {
    $distDirectory = Assert-ProjectChild -Path (Join-Path $projectRoot "dist")
    $packageDirectory = Assert-ProjectChild -Path (Join-Path $projectRoot "build\package")
    $pyInstallerDirectory = Assert-ProjectChild -Path (Join-Path $projectRoot "build\pyinstaller")
    $cacheDirectory = Assert-ProjectChild -Path (Join-Path $projectRoot "build\bootstrap")
    $versionFile = Assert-ProjectChild -Path (Join-Path $projectRoot "build\version_info.txt")
    $specFile = Assert-ProjectChild -Path (Join-Path $projectRoot "build\YTDownloader.spec")

    Reset-BuildDirectory -Path $distDirectory
    Reset-BuildDirectory -Path $packageDirectory
    Reset-BuildDirectory -Path $pyInstallerDirectory
    Remove-Item -LiteralPath $specFile -Force -ErrorAction SilentlyContinue

    $version = (& $PythonCommand "deployment/release_metadata.py" "version").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
        throw "프로젝트 버전을 확인하지 못했습니다."
    }
    $runtimeVersion = (& $PythonCommand -c "from ytdownloader import __version__; print(__version__)").Trim()
    if ($LASTEXITCODE -ne 0 -or $runtimeVersion -ne $version) {
        throw "pyproject.toml 버전과 ytdownloader.__version__이 일치하지 않습니다."
    }
    $pythonVersion = (& $PythonCommand -c "import platform; print(platform.python_version())").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pythonVersion)) {
        throw "Python 버전을 확인하지 못했습니다."
    }
    $pythonBase = (& $PythonCommand -c "import sys; print(sys.base_prefix)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $pythonBase "DLLs") -PathType Container)) {
        throw "현재 Python 배포본의 DLL 폴더를 확인하지 못했습니다."
    }

    Invoke-PythonCommand -CommandArguments @("-m", "unittest", "discover", "-s", "tests", "-v")
    Invoke-PythonCommand -CommandArguments @(
        "deployment/prepare_assets.py", "runtime",
        "--manifest", "deployment/assets.json",
        "--cache", $cacheDirectory,
        "--output", (Join-Path $packageDirectory "runtime"),
        "--python-version", $pythonVersion
    )
    Invoke-PythonCommand -CommandArguments @(
        "deployment/release_metadata.py", "version-file",
        "--output", $versionFile,
        "--publisher", $Publisher
    )

    Invoke-PythonCommand -CommandArguments @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--noupx",
        "--name", "YTDownloader",
        "--paths", "src",
        "--distpath", $distDirectory,
        "--workpath", $pyInstallerDirectory,
        "--specpath", (Join-Path $projectRoot "build"),
        "--version-file", $versionFile,
        "deployment/entrypoint.py"
    )

    $bundleDirectory = Assert-ProjectChild -Path (Join-Path $distDirectory "YTDownloader")
    if (-not (Test-Path -LiteralPath (Join-Path $bundleDirectory "YTDownloader.exe") -PathType Leaf)) {
        throw "PyInstaller 실행 파일이 생성되지 않았습니다."
    }
    Invoke-PythonCommand -CommandArguments @(
        "deployment/prune_bundle.py",
        "--bundle", $bundleDirectory,
        "--python-base", $pythonBase
    )

    $runtimeDirectory = Join-Path $packageDirectory "runtime"
    Copy-Item -LiteralPath (Join-Path $runtimeDirectory "bin") -Destination (Join-Path $bundleDirectory "bin") -Recurse
    Copy-Item -LiteralPath (Join-Path $runtimeDirectory "licenses") -Destination (Join-Path $bundleDirectory "licenses") -Recurse
    Copy-Item -LiteralPath (Join-Path $runtimeDirectory "ASSET-MANIFEST.json") -Destination $bundleDirectory
    Copy-Item -LiteralPath "LICENSE" -Destination (Join-Path $bundleDirectory "licenses\YTDownloader-MIT.txt")
    Copy-Item -LiteralPath "README.md" -Destination $bundleDirectory
    Copy-Item -LiteralPath "THIRD_PARTY_NOTICES.md" -Destination $bundleDirectory

    Invoke-PythonCommand -CommandArguments @(
        "deployment/release_metadata.py", "source-offer",
        "--output", (Join-Path $bundleDirectory "SOURCE-OFFER.txt"),
        "--manifest", "deployment/assets.json",
        "--repository-url", $RepositoryUrl,
        "--python-version", $pythonVersion
    )
    Invoke-PythonCommand -CommandArguments @(
        "deployment/release_metadata.py", "build-info",
        "--output", (Join-Path $bundleDirectory "BUILD-INFO.json"),
        "--repository-url", $RepositoryUrl,
        "--python-version", $pythonVersion
    )

    $checkProcess = Start-Process -FilePath (Join-Path $bundleDirectory "YTDownloader.exe") -ArgumentList "--check-installation" -WindowStyle Hidden -PassThru
    if (-not $checkProcess.WaitForExit(60000)) {
        $checkProcess.Kill($true)
        throw "패키징된 실행 파일의 Qt 시작 검사가 제한 시간 안에 끝나지 않았습니다."
    }
    if ($checkProcess.ExitCode -ne 0) {
        throw "패키징된 실행 파일의 Qt 시작 검사가 종료 코드 $($checkProcess.ExitCode)로 실패했습니다."
    }

    $compiler = (& "deployment/bootstrap_inno.ps1").Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
        throw "Inno Setup 컴파일러를 준비하지 못했습니다."
    }
    & $compiler "/DAppVersion=$version" "/DSourceDir=$bundleDirectory" "/DOutputDir=$distDirectory" "/DPublisher=$Publisher" "deployment/installer.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Windows 설치 파일 생성이 종료 코드 $LASTEXITCODE(으)로 실패했습니다."
    }

    $installer = Join-Path $distDirectory "YTDownloader-Setup.exe"
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw "최종 Windows 설치 파일을 찾을 수 없습니다."
    }
    Invoke-PythonCommand -CommandArguments @(
        "deployment/checksums.py",
        "--output", (Join-Path $distDirectory "SHA256SUMS.txt"),
        $installer
    )
    Write-Output "빌드 완료: $installer"
}
finally {
    Pop-Location
}
