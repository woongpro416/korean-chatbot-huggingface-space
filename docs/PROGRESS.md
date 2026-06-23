# Personal Korean Chatbot Progress

## 현재 실행 기준

- Hugging Face Spaces 배포는 `Dockerfile` 기준으로 `python app.py`를 실행한다.
- 실제 앱 기능은 대부분 `app.py`에 들어 있다.
- `main.py`, `routers/`, `services/`, `models/`는 현재 Docker 배포 경로에서는 사용되지 않는 이전 분리 구조다.
- 실행에 필요한 배포 파일은 `app.py`, `Dockerfile`, `requirements.txt`, `README.md`, `static/`이다.

## 구현 완료

- FastAPI 기반 브라우저 채팅 UI
- Hugging Face `Qwen/Qwen2.5-0.5B-Instruct` 모델 로딩
- SQLite 기반 세션, 메시지, 피드백 저장
- `/chat` 채팅 API
- `/history/{session_id}` 세션별 대화 기록 조회
- `/feedback` 좋아요/싫어요 및 코멘트 저장
- `/admin` 피드백 검토 화면
- `/admin/feedback` 피드백 목록 API
- `/training-data.jsonl` 긍정 피드백 기반 학습 데이터 export
- `/health` 상태 확인 API
- 답변 생성 중 `탐색중... n초` 표시
- SSE 형식의 스트리밍 응답 전송 시도
- 스트리밍 완료 후 대화 기록을 다시 불러와 피드백 버튼 표시

## 최근 확인한 이슈

### Hugging Face Spaces에서 화면 출력이 한 번에 표시됨

- 서버에서는 `[STREAM CHUNK]` 로그가 여러 번 나뉘어 출력된다.
- FastAPI 백엔드는 모델 응답을 chunk 단위로 생성하고 있다.
- `StreamingResponse`는 `text/event-stream`과 `data: ...\n\n` 형태의 SSE 포맷으로 정리했다.
- `Cache-Control: no-cache`, `X-Accel-Buffering: no` 헤더를 추가했다.
- 하지만 Hugging Face Spaces 화면에서는 응답이 마지막에 한 번에 표시되는 현상이 남아 있다.
- 현재 판단으로는 앱 코드보다 Hugging Face Spaces 프록시, 브라우저, 또는 배포 환경의 버퍼링 가능성이 높다.

## 현재 판단

이 프로젝트는 포트폴리오용 미니프로젝트이므로 실시간 출력 최적화에 과도하게 시간을 쓰지 않는다.
서버 스트리밍 구조를 구현하고 로그로 chunk 생성을 확인한 상태로 기록한다.

## 다음 작업

1. README를 현재 배포 파일 구조 기준으로 정리한다.
2. `DEV_LOG.md`에 스트리밍 트러블슈팅 결과를 기록한다.
3. Hugging Face에는 실행에 필요한 파일만 업로드한다.
4. GitHub에는 `docs/`를 포함해 학습 과정과 문제 해결 기록을 남긴다.
5. 다음 미니프로젝트는 엣지비전 주제로 작게 시작한다.
