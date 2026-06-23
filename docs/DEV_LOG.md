# 개발 일지

## 2026-06-23

### 작업 내용

- Hugging Face Spaces 배포 파일 구조를 점검했다.
- 현재 배포 기준 실행 파일이 `app.py`임을 확인했다.
- `main.py`, `routers/`, `services/`, `models/`는 현재 Docker 배포에서는 사용되지 않는 이전 구조임을 구분했다.
- `/chat` 응답 스트리밍 방식을 점검했다.
- 기존 응답이 브라우저 화면에서 한 번에 표시되는 문제를 확인했다.
- SSE 형식에 맞게 서버 응답을 `data: ...\n\n` 형태로 수정했다.
- 프론트에서 SSE 이벤트를 파싱하도록 수정했다.
- 스트리밍 완료 후 `loadHistory()`를 호출해 저장된 메시지 id를 다시 가져오도록 수정했다.
- 새 답변에도 피드백 버튼이 표시되는 것을 확인했다.
- Hugging Face Spaces 로그에서 `[STREAM CHUNK]`가 여러 번 나뉘어 출력되는 것을 확인했다.

### 알게 된 점

- `text/event-stream`은 단순 문자열이 아니라 SSE 형식에 맞는 이벤트 형태로 보내야 한다.
- SSE 이벤트는 보통 `data: ...\n\n` 형태로 전달된다.
- 브라우저에서 `fetch().body.getReader()`를 사용하면 응답 body를 chunk 단위로 읽을 수 있다.
- Python 문자열 안에 JavaScript를 작성할 때 `\n`은 실제 줄바꿈으로 변환될 수 있어 `\\n\\n`처럼 이스케이프가 필요하다.
- 스트리밍 응답과 피드백 버튼 문제는 서로 다른 문제다.
- 피드백 버튼은 서버에 저장된 assistant message id가 있어야 표시할 수 있다.
- Dockerfile에 복사하지 않은 파일은 Hugging Face Spaces 컨테이너 안에 포함되지 않는다.

### 확인 결과

- 서버 로그에서는 모델 응답이 chunk 단위로 생성되는 것을 확인했다.
- Hugging Face Spaces 화면에서는 응답이 마지막에 한 번에 표시되는 현상이 남아 있다.
- `Cache-Control: no-cache`, `X-Accel-Buffering: no` 헤더를 추가했지만 화면 출력 방식은 개선되지 않았다.
- 현재는 Hugging Face Spaces 프록시 또는 브라우저 렌더링 경로의 버퍼링 가능성이 높다고 판단했다.

### 다음 작업

- README를 현재 배포 구조에 맞게 정리한다.
- Hugging Face에는 실행에 필요한 파일만 올린다.
- GitHub에는 `docs/`를 포함해 진행 상황과 트러블슈팅 기록을 남긴다.
- 실시간 출력 문제는 미니프로젝트 범위에서 과도하게 파고들지 않고 문서화한다.
