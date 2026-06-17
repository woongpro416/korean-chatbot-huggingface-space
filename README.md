---
title: Personal Korean Chatbot
emoji: 🤖
colorFrom: purple
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: FastAPI, SQLite, Feedback 기반 실무형 한글 챗봇
models:
  - Qwen/Qwen2.5-0.5B-Instruct
---

# Personal Korean Chatbot

FastAPI, SQLite, Hugging Face Transformers, Docker를 사용해 만든 실무 연습용 한글 챗봇입니다.
브라우저 채팅 UI와 REST API를 제공하며, 대화 히스토리와 사용자 피드백을 서버에 저장합니다.

## Live Demo

- App: https://devwoong-mychatbot.hf.space/
- Space: https://huggingface.co/spaces/devwoong/myChatBot
- API Docs: https://devwoong-mychatbot.hf.space/docs

## 주요 기능

- 브라우저 기반 채팅 UI
- `POST /chat` 챗봇 API
- `GET /history/{session_id}` 세션별 대화 기록 조회
- `POST /feedback` 답변 좋아요/싫어요 저장
- `GET /admin` 피드백 검토용 관리자 화면
- `GET /admin/feedback` 피드백 목록 API
- `GET /training-data.jsonl` 긍정 피드백 기반 학습 데이터 export
- `GET /health` 상태 확인
- SQLite 기반 대화/피드백 저장
- `Qwen/Qwen2.5-0.5B-Instruct` 기반 instruction/chat 응답
- Docker 기반 Hugging Face Spaces 배포

## 기술 스택

- Python
- FastAPI
- Pydantic
- SQLite
- PyTorch
- Hugging Face Transformers
- Docker
- Hugging Face Spaces

## 로컬 실행

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

브라우저:

```txt
http://localhost:7860
```

API 문서:

```txt
http://localhost:7860/docs
```

관리자 화면:

```txt
http://localhost:7860/admin
```

기본 관리자 토큰은 `devwoong416`입니다. 실제 배포에서는 Space Settings의 `ADMIN_TOKEN` 환경변수로 관리하세요.

## API 예시

### Chat

```json
{
  "session_id": null,
  "user_id": "anonymous",
  "message": "안녕하세요",
  "max_new_tokens": 160,
  "temperature": 0.6,
  "top_p": 0.9
}
```

응답에는 사용된 모델이 `llm_name` 필드로 표시됩니다.

### Feedback

```json
{
  "message_id": "assistant-message-id",
  "rating": "up",
  "comment": "답변이 자연스러웠습니다."
}
```

### Admin Feedback

`X-Admin-Token` 헤더가 필요합니다.

```txt
GET /admin/feedback?rating=up&limit=100
```

## Hugging Face Spaces 배포

1. Hugging Face에서 새 Space를 만든다.
2. SDK는 `Docker`를 선택한다.
3. Docker template은 `Blank`를 선택한다.
4. `Files` 탭에서 아래 파일을 업로드한다.
   - `app.py`
   - `requirements.txt`
   - `Dockerfile`
   - `README.md`
5. `Commit changes to main`을 클릭한다.
6. Space Settings에서 `ADMIN_TOKEN` 환경변수를 설정한다.
7. 빌드가 끝나고 `Running` 상태가 되면 `App` 탭에서 테스트한다.

## GitHub 포트폴리오 메모

GitHub에는 코드와 README 중심으로 올립니다.
로컬 배포 매뉴얼 txt 파일은 `.gitignore`에 등록되어 있어 GitHub에는 포함하지 않습니다.

## 한계와 개선 계획

현재 앱은 대화 중 즉시 모델을 학습하지 않습니다.
대신 대화와 피드백을 SQLite에 저장하고, 긍정 피드백 데이터를 `training-data.jsonl` 형태로 export할 수 있게 구성했습니다.

추가 개선 후보:

- 인증 적용
- 관리자용 피드백 대시보드
- RAG 기반 개인 문서 질의응답
- LoRA fine-tuning 파이프라인
- 테스트 코드와 GitHub Actions CI
