# 외부 도구

이 폴더의 실행 파일은 개발 환경에서 사용하며 `.gitignore`에 따라 Git 저장소에 포함되지 않습니다.

| 파일 | 개발 환경 준비 방식 | 용도 |
| --- | --- | --- |
| `yt-dlp.exe` | 앱이 공식 안정판을 자동 설치·검증 | 영상 정보 확인과 다운로드 |
| `ffmpeg.exe` | 동일 배포본의 ffprobe와 함께 직접 배치 | 영상 병합, MP3 변환, 구간 처리 |
| `ffprobe.exe` | 동일 배포본의 ffmpeg와 함께 직접 배치 | 미디어 정보 확인과 후처리 지원 |
| `deno.exe` | 필요할 때 직접 배치 | YouTube JavaScript 처리 지원 |

공식 Windows 설치 파일은 `deployment/assets.json`에 고정된 자산을 별도로 내려받고 크기와 SHA-256을 검증하여 포함합니다. 로컬 `bin`의 파일을 그대로 복사해 릴리스하지 않습니다.

각 프로젝트의 원본, 라이선스와 재배포 조건은 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)를 확인하세요.
