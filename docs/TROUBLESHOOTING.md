# Troubleshooting

## Hugging Face Spaces에서 답변이 한 번에 표시됨

### 증상

- 서버 로그에는 `[STREAM CHUNK]`가 여러 번 나뉘어 출력된다.
- 브라우저 화면에서는 답변이 실시간으로 누적되지 않고 마지막에 한 번에 표시된다.

### 확인한 내용

- 앱 시작과 모델 로딩은 정상이다.
- `/chat` 요청은 정상 처리된다.
- `TextIteratorStreamer`를 통해 모델 응답 chunk가 생성된다.
- `StreamingResponse`는 `text/event-stream`으로 반환한다.
- 서버 응답은 SSE 형식인 `data: ...\n\n` 형태로 정리했다.
- 프론트는 `fetch().body.getReader()`로 stream body를 읽고, `data:` 이벤트를 파싱한다.

### 시도한 조치

- `/chat` 응답을 SSE 포맷으로 변경했다.
- 프론트에서 SSE 이벤트를 파싱하도록 수정했다.
- `Cache-Control: no-cache` 헤더를 추가했다.
- `X-Accel-Buffering: no` 헤더를 추가했다.
- 서버 로그에 `[STREAM CHUNK]`를 출력해 백엔드 chunk 생성을 확인했다.

### 현재 판단

백엔드에서는 응답이 chunk 단위로 생성되고 있다.
Hugging Face Spaces 화면에서만 한 번에 표시되므로, 앱 코드보다 Spaces 프록시 또는 브라우저 렌더링 경로의 버퍼링 가능성이 높다.

포트폴리오용 미니프로젝트 범위에서는 서버 스트리밍 구조를 구현하고 한계를 확인한 것으로 정리한다.

## 새 답변에 피드백 버튼이 표시되지 않음

### 원인

- 피드백 버튼은 assistant message id가 있을 때만 표시된다.
- 스트리밍 응답 직후 프론트는 새 assistant message id를 알지 못했다.

### 조치

- 스트리밍 완료 후 `loadHistory()`를 다시 호출했다.
- 서버에 저장된 메시지를 다시 받아오면서 assistant message id를 확보했다.
- 이후 새 답변에도 피드백 버튼이 표시된다.

## 브라우저 JavaScript가 실행되지 않음

### 증상

- Hugging Face 로그에 `GET /`만 찍히고 `/health`, `/history`, `/chat` 요청이 찍히지 않았다.

### 원인

- Python 문자열 안의 JavaScript에서 `"\n\n"`을 그대로 사용해 브라우저에 깨진 JavaScript가 전달될 수 있었다.

### 조치

- JavaScript 문자열 구분자를 `split("\\n\\n")` 형태로 수정했다.
