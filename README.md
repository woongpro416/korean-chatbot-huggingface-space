---
title: Personal Korean Chatbot
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: FastAPI와 Hugging Face 기반 개인 한글 챗봇
models:
  - skt/kogpt2-base-v2
---

# Personal Korean Chatbot

FastAPI, Hugging Face Transformers, Docker를 사용해 만든 개인 한글 챗봇입니다.
Hugging Face Spaces에 배포할 수 있으며, 브라우저 채팅 화면과 REST API를 함께 제공합니다.

## 주요 기능

- 브라우저 기반 채팅 UI
- `POST /chat` 챗봇 API
- `GET /health` 상태 확인 API
- 인사, 도움말, 배포, GitHub 관련 기본 규칙 응답
- 그 외 메시지는 `skt/kogpt2-base-v2` 모델로 생성
- Docker 기반 Hugging Face Spaces 배포

## 기술 스택

- Python
- FastAPI
- Pydantic
- PyTorch
- Hugging Face Transformers
- Docker
- Hugging Face Spaces

## 로컬 실행

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

브라우저에서 접속:

```txt
http://localhost:7860
```

API 문서:

```txt
http://localhost:7860/docs
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
6. 빌드가 끝나고 `Running` 상태가 되면 `App` 탭에서 테스트한다.

자세한 절차는 `HUGGINGFACE_DEPLOY_MANUAL.txt`를 참고한다.

## API 예시

요청:

```json
{
  "message": "안녕하세요",
  "max_new_tokens": 80,
  "temperature": 0.7,
  "top_k": 40
}
```

응답:

```json
{
  "user_message": "안녕하세요",
  "bot_response": "안녕하세요! 저는 FastAPI와 Hugging Face 모델로 만든 개인 한글 챗봇입니다. 간단한 질문을 입력해보세요.",
  "response_type": "rule",
  "model_used": "skt/kogpt2-base-v2",
  "device": "cpu",
  "processing_time_ms": 1.23,
  "tokens_generated": 12
}
```

## 한계와 개선 계획

현재 기본 모델인 `skt/kogpt2-base-v2`는 지시를 정확히 따르는 챗 모델이라기보다 한국어 문장 생성 모델에 가깝습니다.
따라서 실무형 챗봇으로 발전시키려면 아래 개선이 필요합니다.

- instruction/chat 모델로 교체
- 서버 측 대화 히스토리 저장
- 사용자 인증 추가
- 질문/답변 로그 저장
- RAG 기반 개인 문서 질의응답 추가
- 테스트 코드와 CI 추가

