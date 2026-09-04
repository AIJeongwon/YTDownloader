# Windows 배포

## 배포 형태

사용자에게는 `YTDownloader-Setup.exe` 하나를 제공합니다. 설치 프로그램은 사용자별 경로인 `%LOCALAPPDATA%\Programs\YTDownloader`에 앱을 설치하므로 관리자 권한이 필요하지 않습니다.

설치 폴더에는 다음 항목이 포함됩니다.

- PyInstaller의 폴더형 앱 본체와 동적 Qt 라이브러리
- `bin`의 yt-dlp, FFmpeg, ffprobe, FFmpeg 공유 DLL, Deno
- `licenses`의 YTDownloader 및 제3자 라이선스 전문
- `THIRD_PARTY_NOTICES.md`, `SOURCE-OFFER.txt`, 자산 목록과 빌드 정보

폴더형 구성을 유지하는 이유는 자동 업데이트되는 `yt-dlp.exe`에 쓰기 권한을 제공하고, LGPL이 적용되는 Qt 라이브러리를 사용자가 호환되는 수정 버전으로 교체할 수 있게 하기 위해서입니다.

## 로컬 빌드

PowerShell에서 다음 명령을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -r deployment\requirements.txt -e .
.\deployment\build.ps1
```

공식 GitHub 배포 빌드는 Python 3.13.15를 사용합니다. 로컬 검증 빌드는 자산 목록에 등록된 Python 3.12.13도 허용하며, 그 밖의 패치 버전은 자산 준비 단계에서 거부합니다. 빌드는 테스트 통과 후에만 계속됩니다. `deployment/assets.json`의 HTTPS 주소, 파일 크기와 SHA-256이 모두 일치해야 외부 자산을 사용합니다. Inno Setup도 고정 버전과 SHA-256으로 준비합니다. PyInstaller가 `PATH`에서 잘못 수집할 수 있는 OpenSSL과 libffi DLL은 현재 Python 배포본의 원본으로 교체한 뒤 해시를 재검증합니다.

결과 파일은 다음과 같습니다.

- `dist\YTDownloader-Setup.exe`: 사용자용 설치 파일
- `dist\SHA256SUMS.txt`: 설치 파일 SHA-256
- `dist\YTDownloader`: 설치 전 폴더형 앱

## GitHub Release

`pyproject.toml`의 버전이 `0.2.1`이면 `v0.2.1` 태그를 푸시합니다. `.github/workflows/release.yml`은 태그와 앱 버전이 같은지 확인한 뒤 Windows 설치 파일과 일반 대응 소스 아카이브를 같은 GitHub Release에 게시합니다. 용량이 큰 FFmpeg 의존 라이브러리 대응 소스는 같은 FFmpeg 빌드를 사용하는 동안 검증된 기존 릴리스 자산을 재사용합니다. 릴리스 작업은 다음 검사를 자동으로 수행합니다.

- 단위 테스트와 패키징된 앱 시작 검사
- 설치 프로그램의 무인 설치·실행·제거 검사
- 재사용하는 FFmpeg 대응 소스의 주소·크기·SHA-256을 GitHub 릴리스 메타데이터와 대조
- 릴리스 자산 전체의 SHA-256 생성과 게시 직전 재검증
- 설치 파일과 새로 첨부하는 대응 소스에 대한 GitHub 빌드 출처 증명 생성

```powershell
git tag v0.2.1
git push origin v0.2.1
```

README의 다운로드 버튼은 다음 고정 주소를 사용합니다.

```text
https://github.com/AIJeongwon/YTDownloader/releases/latest/download/YTDownloader-Setup.exe
```

따라서 각 릴리스의 설치 자산 이름을 `YTDownloader-Setup.exe`로 유지해야 합니다.

## FFmpeg 대응 소스 갱신

앱 버전만 바뀌고 `deployment/assets.json`에 고정한 FFmpeg 실행 파일과 FFmpeg-Builds 입력이 같다면 기존 대응 소스를 그대로 재사용합니다. 이 경우 일반 릴리스에서 약 2GB의 대응 소스를 다시 생성하거나 전달하지 않습니다.

FFmpeg 실행 파일이나 빌드 입력을 바꿀 때만 다음 순서로 대응 소스를 갱신합니다.

1. `runtime_assets`와 `source_assets`의 FFmpeg 관련 URL·크기·SHA-256을 갱신합니다.
2. `generated_source_assets`의 출력 파일 이름, 입력 파일 이름과 전용 릴리스 태그를 새 커밋에 맞춥니다.
3. 해당 브랜치에서 `FFmpeg 대응 소스 생성` 워크플로를 수동 실행합니다.
4. 전용 사전 릴리스에 게시된 자산의 URL·크기·SHA-256을 `reusable_source_assets`에 기록합니다.
5. 테스트를 통과시킨 뒤 앱 버전 태그를 게시합니다.

전용 릴리스는 사전 릴리스이므로 앱의 최신 정식 버전 확인 대상이 되지 않습니다. 일반 앱 릴리스는 재사용 자산이 실제로 게시되어 있고 목록의 크기와 GitHub가 제공하는 SHA-256이 일치해야만 계속됩니다. 설치본의 `SOURCE-OFFER.txt`와 릴리스의 `SOURCE-ASSETS.json`에는 재사용 자산의 고정 URL과 SHA-256이 기록됩니다.

## 릴리스 전 확인

- 모든 단위 테스트가 통과했는지 확인합니다.
- 설치 파일을 깨끗한 Windows 10 또는 11 환경에서 설치·실행·제거합니다.
- MP4, MP3, 전체 영상, 다중 구간, 쿠키가 필요한 본인 소유 테스트 영상을 확인합니다.
- `SHA256SUMS.txt`가 게시된 파일과 일치하고 GitHub 빌드 출처 증명을 검증할 수 있는지 확인합니다.
- 설치본의 `SOURCE-OFFER.txt`와 릴리스의 `SOURCE-ASSETS.json` 링크가 열리고 대응 소스 SHA-256이 일치하는지 확인합니다.
- 외부 자산 버전을 바꿨다면 라이선스 전문, 대응 소스, 크기와 SHA-256도 함께 갱신합니다.
- 공개 배포 전 코드 서명 여부와 Windows SmartScreen 동작을 확인합니다. GitHub 빌드 출처 증명은 Authenticode 코드 서명을 대체하지 않습니다.

GitHub 저장소 자체에는 외부 실행 파일을 커밋하지 않습니다. 바이너리는 GitHub Release 자산으로만 배포하며, 소스 저장소와 릴리스 자산의 역할을 분리합니다.

## Inno Setup 사용 안내

Inno Setup은 설치 파일을 만드는 빌드 도구이며 완성된 앱 설치 폴더에는 포함되지 않습니다. Inno Setup 측은 상업적 사용으로 연간 미화 5,000달러를 초과하는 수익을 얻는 조직이나 개인에게 라이선스 구매를 요청하고 있습니다. 공식 설명상 구매가 엄격한 필수 조건은 아니지만, 향후 유료 판매나 일정 규모 이상의 후원을 받는 형태로 바뀐다면 당시 조건을 다시 확인하고 구매하는 것이 좋습니다.
