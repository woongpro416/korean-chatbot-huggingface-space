# File Guide

## Hugging Face Spaces 업로드 대상

현재 Docker 배포 기준으로 필요한 파일은 아래와 같다.

- `app.py`
- `Dockerfile`
- `requirements.txt`
- `README.md`
- `static/`
- `.gitattributes`

## GitHub 포트폴리오 포함 대상

GitHub에는 실행 파일과 학습 기록을 함께 남긴다.

- `app.py`
- `Dockerfile`
- `requirements.txt`
- `README.md`
- `static/`
- `docs/`
- `.gitignore`

## 현재 배포에서 사용하지 않는 파일

아래 파일과 디렉토리는 이전 분리 구조의 흔적이다.
현재 `Dockerfile`은 `python app.py`를 실행하므로 Hugging Face 배포에는 필요하지 않다.

- `main.py`
- `routers/`
- `services/`
- `models/`

삭제해도 실행에는 영향이 없지만, 학습 과정 기록으로 남길 수 있다.
정리할 때는 GitHub에는 남기고 Hugging Face에는 올리지 않는 방식을 우선한다.

## 업로드하지 않을 파일

아래 항목은 로컬 개발 환경 또는 생성물이므로 업로드하지 않는다.

- `venv/`
- `__pycache__/`
- `.env`
- `data/`
- `.cache/`
- `hf_cache/`
- `model_cache/`
- `*.log`
