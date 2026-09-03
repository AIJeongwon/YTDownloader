# YTDownloader

YouTube 영상을 MP4 또는 MP3로 저장할 수 있는 Windows용 GUI 애플리케이션입니다. 전체 영상과 여러 구간 다운로드를 지원하며, 각 구간에 별도의 파일 제목을 지정할 수 있습니다.

[![Windows 설치 파일 다운로드](https://img.shields.io/badge/Windows-설치%20파일%20다운로드-2563EB?style=for-the-badge&logo=windows11&logoColor=white)](https://github.com/AIJeongwon/YTDownloader/releases/latest/download/YTDownloader-Setup.exe)

버튼은 최신 GitHub Release의 `YTDownloader-Setup.exe`로 바로 연결됩니다. 아직 릴리스가 게시되지 않았다면 링크가 활성화되지 않습니다. 다른 버전과 SHA-256은 [전체 릴리스 목록](https://github.com/AIJeongwon/YTDownloader/releases)에서 확인할 수 있습니다.

## 주요 기능

- 영상 MP4 또는 오디오 MP3 다운로드
- 최고 화질 또는 최대 2160p·1440p·1080p·720p·480p 선택
- 여러 구간을 등록하고 구간별 파일 제목 지정
- 다운로드 진행률과 상태 로그 표시
- 실행 중인 다운로드 취소
- 저장 폴더 기억
- 선택적인 Netscape 형식 쿠키 파일 사용
- `.ytdjob` 작업 파일 저장·불러오기 및 드래그 앤 드롭
- 시작 시 `yt-dlp` 자동 업데이트
- 시작 시 YTDownloader 새 버전 알림 및 버전별 알림 제외

## 설치

Windows 10 64비트 이상에서 위의 다운로드 버튼을 누른 뒤 `YTDownloader-Setup.exe`를 실행합니다. 설치본에는 실행에 필요한 Python, PySide6/Qt, `yt-dlp`, FFmpeg, ffprobe와 Deno가 포함됩니다.

현재 설치 파일은 코드 서명이 되어 있지 않으므로 Windows에서 게시자를 확인할 수 없다는 경고가 표시될 수 있습니다. 릴리스에 함께 게시되는 `SHA256SUMS.txt`로 파일 무결성을 확인할 수 있으며, GitHub Actions에서 생성한 빌드 출처 증명도 함께 제공합니다.

## 사용법

YouTube 영상 주소와 저장 폴더를 입력하고 형식과 화질을 선택한 다음 `다운로드`를 누릅니다. 유효한 저장 폴더는 다음 실행에서도 유지됩니다.

앱을 실행하면 GitHub의 최신 정식 릴리스를 확인합니다. 현재보다 새 버전이 있으면 다운로드 페이지를 열 수 있는 알림을 표시하며, `이 버전의 업데이트 알림을 다시 표시하지 않기`를 선택하면 같은 버전은 다시 알리지 않습니다. 이후 더 새로운 버전이 게시되면 다시 알림을 표시합니다.

구간 표를 비워 두면 전체 영상을 저장합니다. 일부 구간만 저장하려면 `+ 구간 추가`를 누르고 파일 제목, 시작 시간과 종료 시간을 입력합니다. 등록한 구간은 위에서부터 차례대로 각각 다른 파일로 저장됩니다.

시간은 다음 형식으로 입력할 수 있습니다.

- `분:초`
- `시:분:초`
- 콜론 없는 숫자: 오른쪽부터 초 2자리, 분 2자리, 나머지를 시간으로 해석

예를 들어 `123`은 `00:01:23`, `13033`은 `01:30:33`으로 변환됩니다. 입력 가능한 시간은 `1000:00:00` 미만입니다.

한 화면에는 구간 6개가 표시되며 더 추가한 구간은 표를 스크롤해 확인할 수 있습니다. 구간별 저장 옆의 `?` 버튼에서 입력 방법을 확인할 수 있습니다.

창의 최소 크기는 `760×640`입니다. 화면이 작은 경우 전체 화면을 스크롤해 아래쪽 상태와 다운로드 버튼으로 이동할 수 있습니다.

## 쿠키 파일

쿠키 파일은 로그인이 필요하거나 연령 제한이 있는 영상을 받을 때 선택적으로 사용합니다. Netscape 형식의 `cookies.txt` 파일을 선택할 수 있으며, 일반 공개 영상에는 필요하지 않습니다. 쿠키에는 로그인 정보가 포함될 수 있으므로 다른 사람과 공유하지 마세요.

## 작업 파일

`작업 저장`을 누르면 현재 YouTube 주소와 구간 목록을 `.ytdjob` 파일로 저장합니다. `작업 불러오기`를 누르거나 `.ytdjob` 파일 하나를 앱 창으로 끌어다 놓으면 다시 불러올 수 있습니다.

저장 폴더와 쿠키 파일은 작업 파일에 포함되지 않습니다.

```json
{
  "version": 1,
  "url": "https://www.youtube.com/watch?v=...",
  "segments": [
    {
      "title": "도입, 인사",
      "start": "00:01:23",
      "end": "00:02:30"
    },
    {
      "title": "주요 장면",
      "start": "01:30:33",
      "end": "01:35:00"
    }
  ]
}
```

## 소스에서 실행

Python 3.11 이상이 필요합니다.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e .
.\.venv\Scripts\pythonw.exe -m ytdownloader
```

설치 후에는 `run.cmd`를 더블클릭해 실행할 수도 있습니다. 개발 환경의 `bin` 폴더에 필요한 외부 도구가 없으면 `yt-dlp`만 자동으로 설치되며, FFmpeg와 ffprobe는 별도로 준비해야 합니다.

## 테스트와 Windows 설치 파일 빌드

```powershell
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -r deployment\requirements.txt -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\deployment\build.ps1
```

공식 GitHub 배포 빌드는 Python 3.13.15로 고정합니다. 로컬에서는 자산 목록에 등록한 Python 3.12.13도 검증용 빌드에 사용할 수 있습니다. 빌드 스크립트는 버전을 고정한 공식 외부 자산을 내려받아 크기와 SHA-256을 검증하고 `dist\YTDownloader-Setup.exe`를 만듭니다. 릴리스 절차와 대응 소스 구성은 [배포 문서](docs/DISTRIBUTION.md)를 확인하세요.

## 오픈 소스 및 라이선스

YTDownloader의 자체 소스 코드는 [MIT 라이선스](LICENSE)로 공개됩니다. 설치 파일에 포함되는 제3자 프로그램과 라이브러리에는 각 프로젝트의 라이선스가 그대로 적용됩니다.

원본 프로젝트 링크, 포함 버전, 라이선스 및 재배포 안내는 [제3자 소프트웨어 고지](THIRD_PARTY_NOTICES.md)에 정리되어 있습니다. 설치 폴더의 `licenses`에는 라이선스 전문이, `SOURCE-OFFER.txt`에는 해당 설치본과 대응하는 소스 다운로드 주소가 들어갑니다.

다운로드 권한이 있는 콘텐츠에만 사용하고 대상 서비스의 이용약관과 저작권을 확인하세요.
