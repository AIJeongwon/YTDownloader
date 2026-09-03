# 오픈 소스 및 제3자 소프트웨어 고지

YTDownloader는 아래 오픈 소스 소프트웨어를 사용하거나 외부 프로그램으로 실행합니다. 이 문서는 각 프로젝트의 원본 위치와 라이선스 확인 경로를 안내하기 위한 것이며, 각 라이선스 전문을 대체하지 않습니다.

기본 `.gitignore` 설정은 `bin` 폴더의 실행 파일을 소스 저장소에서 제외합니다. 공식 `YTDownloader-Setup.exe`에는 아래에 명시한 고정 버전의 실행 파일과 라이브러리가 포함됩니다. 설치 폴더의 `licenses`에는 라이선스 전문이, `SOURCE-OFFER.txt`에는 해당 설치본과 대응하는 소스 다운로드 주소가 들어갑니다. 대응 소스 아카이브와 SHA-256 목록은 설치 파일과 같은 GitHub Release에 게시합니다.

## PySide6 및 Qt for Python

- 용도: Windows GUI
- 프로젝트: [Qt for Python](https://doc.qt.io/qtforpython-6/)
- 소스 코드: [pyside-setup 저장소](https://code.qt.io/cgit/pyside/pyside-setup.git/)
- 라이선스: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`
- 라이선스 안내: [Qt for Python 라이선스](https://doc.qt.io/qtforpython-6/licenses.html)
- LGPL 준수 안내: [Qt의 GPL 및 LGPL 의무](https://www.qt.io/development/open-source-lgpl-obligations)

이 프로젝트는 `PySide6`, `PySide6_Addons`, `PySide6_Essentials`, `shiboken6` 버전 6.11.2를 설치하도록 고정하고 있습니다.

PySide6와 Qt 라이브러리를 실행 파일 또는 설치 프로그램에 포함해 배포할 경우 다음 사항을 확인해야 합니다.

- 애플리케이션이 Qt 및 PySide6를 사용한다는 사실을 고지합니다.
- GNU GPLv3와 LGPLv3 라이선스 전문을 배포본에 포함합니다.
- 배포한 Qt 라이브러리에 정확히 대응하는 전체 소스와 수정 사항을 함께 제공하거나, 배포자가 관리하는 위치에서 받을 수 있도록 유효한 서면 안내를 제공합니다.
- LGPL 적용 라이브러리를 동적으로 연결하고, 이용자가 호환되는 수정 버전으로 교체하여 실행할 수 있게 합니다.
- 해당 교체와 디버깅을 위한 리버스 엔지니어링을 이용약관으로 금지하지 않습니다.

Qt 공식 안내에 따르면 단순한 Qt 공식 소스 링크만 제공하는 것으로는 배포자의 소스 제공 의무를 충족하지 못할 수 있습니다. 독립 실행형 배포본은 Qt DLL을 교체할 수 있는 폴더형 구성을 권장합니다.

## yt-dlp

- 용도: 영상 정보 확인 및 다운로드
- 프로젝트: [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- 기본 소스 라이선스: [The Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE)
- 배포 파일별 라이선스 안내: [yt-dlp README의 Licensing 항목](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#licensing)
- 제3자 라이선스: [THIRD_PARTY_LICENSES.txt](https://github.com/yt-dlp/yt-dlp/blob/master/THIRD_PARTY_LICENSES.txt)
- 공식 릴리스: [yt-dlp 릴리스](https://github.com/yt-dlp/yt-dlp/releases)

YTDownloader는 소스 저장소에 `yt-dlp.exe`를 포함하지 않습니다. 공식 설치본에는 배포 시점에 검증한 공식 Windows 실행 파일을 포함하며, 실행 후에는 앱이 공식 GitHub 안정판의 크기와 SHA-256을 검증하여 업데이트합니다.

yt-dlp의 기본 소스는 The Unlicense로 제공되지만 공식 PyInstaller 실행 파일에는 다른 프로젝트의 코드가 포함되므로 결합된 실행 파일은 GPLv3 이상 조건이 적용됩니다. `yt-dlp.exe`를 설치 프로그램이나 압축 파일에 포함해 재배포할 경우 다음 사항을 확인해야 합니다.

- GNU GPLv3 이상 라이선스 전문과 yt-dlp의 제3자 라이선스 문서를 포함합니다.
- 배포하는 실행 파일에 정확히 대응하는 전체 소스와 빌드에 필요한 자료를 GPLv3가 허용하는 방식으로 제공합니다.
- 이용자가 GPL로 받은 권리를 제한하는 추가 조건을 두지 않습니다.

## FFmpeg 및 ffprobe

- 용도: 영상·음성 병합, 변환 및 구간 처리
- 프로젝트: [FFmpeg](https://ffmpeg.org/)
- 소스 및 공식 다운로드 안내: [FFmpeg 다운로드](https://ffmpeg.org/download.html)
- 라이선스와 준수 안내: [FFmpeg Legal](https://ffmpeg.org/legal.html)
- GNU GPLv3 전문: [GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)
- 공식 설치본의 Windows 빌드 제공처: [yt-dlp FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds)

FFmpeg의 적용 라이선스는 빌드 옵션에 따라 달라집니다. 공식 설치본은 `deployment/assets.json`에 기록된 yt-dlp FFmpeg-Builds의 64비트 GPL 공유 빌드를 사용합니다. `ffmpeg.exe`, `ffprobe.exe`와 필요한 DLL은 모두 같은 배포본에서 가져옵니다. 정확한 빌드 태그, 바이너리 SHA-256, FFmpeg 커밋과 빌드 스크립트 커밋은 해당 자산 목록과 릴리스의 소스 목록에서 확인할 수 있습니다. 릴리스 자동화는 고정한 FFmpeg-Builds 스크립트로 GPL 공유 빌드에 실제 포함되는 의존 라이브러리를 판별하고, 그 의존 소스 아카이브와 내부 SHA-256 목록을 `ffmpeg-dependencies-ea2ec3c0-source.tar`로 함께 게시합니다.

이 실행 파일을 설치 프로그램이나 압축 파일에 포함해 재배포할 경우 다음 사항을 확인해야 합니다.

- GNU GPLv3 라이선스 전문과 저작권 고지를 포함합니다.
- 배포하는 바이너리에 정확히 대응하는 FFmpeg 및 포함 라이브러리의 소스, 수정 사항과 빌드 설정을 함께 제공하거나 GPLv3가 허용하는 방식으로 동등하게 제공합니다.
- 다운로드 페이지가 있다면 바이너리와 대응 소스를 같은 수준으로 쉽게 받을 수 있게 안내하고, 바이너리를 제공하는 동안 그 소스도 계속 제공될 수 있게 관리합니다.
- 이용자의 GPL 권리나 라이선스 대상 코드의 리버스 엔지니어링을 금지하는 조건을 두지 않습니다.

## Deno

- 용도: YouTube JavaScript 처리 지원
- 프로젝트 및 소스 코드: [Deno](https://github.com/denoland/deno)
- 라이선스: [MIT License](https://github.com/denoland/deno/blob/main/LICENSE.md)
- 공식 릴리스: [Deno 릴리스](https://github.com/denoland/deno/releases)

`deno.exe`는 소스 저장소에는 포함하지 않지만 공식 설치본에는 YouTube JavaScript 처리 지원을 위해 포함합니다. 설치본에는 Deno의 저작권 고지와 MIT 라이선스 전문을 함께 넣으며, 같은 릴리스에 정확한 버전의 소스 아카이브를 게시합니다.

## Python

- 용도: 애플리케이션 실행 환경
- 프로젝트: [Python](https://www.python.org/)
- 라이선스: [Python 라이선스와 연혁](https://docs.python.org/3/license.html)
- 재배포 안내: [Python Software Foundation 라이선스 FAQ](https://wiki.python.org/moin/PythonSoftwareFoundationLicenseFaq)

소스 저장소는 Python 인터프리터를 포함하지 않습니다. 공식 GitHub 설치본은 Python 3.13.15와 PyInstaller로 Python 실행 환경을 묶으며 PSF 라이선스 전문을 설치 폴더에, 정확히 대응하는 Python 소스 아카이브를 같은 릴리스에 제공합니다. 로컬 검증 빌드에는 자산 목록에 등록한 Python 3.12.13도 사용할 수 있습니다.

## PyInstaller

- 용도: Python 애플리케이션의 Windows 폴더형 실행 파일 생성
- 프로젝트 및 소스 코드: [PyInstaller](https://github.com/pyinstaller/pyinstaller)
- 라이선스: GPL-2.0-or-later 및 배포 산출물에 대한 특별 예외
- 라이선스 전문: [PyInstaller COPYING.txt](https://github.com/pyinstaller/pyinstaller/blob/v6.22.2/COPYING.txt)

공식 설치본은 PyInstaller 6.22.2로 생성합니다. PyInstaller의 특별 예외는 PyInstaller로 만든 산출물을 YTDownloader의 라이선스에 따라 배포할 수 있도록 허용합니다. 설치본에는 PyInstaller 라이선스 전문을 함께 넣습니다.

## YTDownloader 자체 라이선스

YTDownloader의 자체 소스 코드는 [MIT 라이선스](LICENSE)로 제공되며 저작권자는 `AIJeongwon`입니다. MIT 라이선스는 이 저장소에서 개발한 코드에 적용되며, 위에 나열한 제3자 소프트웨어의 라이선스를 변경하지 않습니다.

외부 프로그램을 명령행으로 실행하거나 라이브러리로 연결하는 방식에 따라 YTDownloader 자체 코드에 미치는 라이선스 효과가 달라질 수 있습니다. 상업 배포 또는 실행 파일 묶음 배포를 계획한다면 실제 배포 형태를 기준으로 별도 검토가 필요합니다.

설치 파일 생성에는 Inno Setup을 빌드 도구로 사용하지만 완성된 설치 폴더에는 Inno Setup 자체를 포함하지 않습니다. Inno Setup 프로젝트는 상업적 사용자가 라이선스를 구매해 개발을 지원해 달라고 요청하고 있으며, 자세한 기준은 [공식 구매 안내](https://jrsoftware.org/isorder.php)를 확인할 수 있습니다.

## 콘텐츠 이용 조건

위 라이선스들은 각 소프트웨어를 사용할 권한에 관한 것입니다. 영상이나 음원을 다운로드할 권한을 부여하지는 않습니다. YTDownloader는 다운로드 권한이 있는 콘텐츠에만 사용하고 대상 서비스의 이용약관과 저작권을 확인해야 합니다.
