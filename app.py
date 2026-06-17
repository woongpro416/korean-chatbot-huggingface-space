import json
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL_ID = os.getenv("MODEL_ID", "skt/kogpt2-base-v2")
PORT = int(os.getenv("PORT", "7860"))

tokenizer = None
model = None
device = "cuda" if torch.cuda.is_available() else "cpu"
started_at = time.time()


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="사용자 메시지")
    max_new_tokens: int = Field(80, ge=20, le=180, description="새로 생성할 최대 토큰 수")
    temperature: float = Field(0.7, ge=0.1, le=1.2, description="응답 다양성")
    top_k: int = Field(40, ge=1, le=100, description="샘플링 후보 토큰 수")

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "안녕하세요",
                "max_new_tokens": 80,
                "temperature": 0.7,
                "top_k": 40,
            }
        }
    }


class ChatResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    user_message: str
    bot_response: str
    response_type: Literal["rule", "model"]
    model_used: str
    device: str
    processing_time_ms: float
    tokens_generated: Optional[int] = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str
    model_loaded: bool
    model_used: str
    device: str
    uptime_seconds: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tokenizer, model

    print(f"[STARTUP] Loading model: {MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ID,
        bos_token="</s>",
        eos_token="</s>",
        unk_token="<unk>",
        pad_token="<pad>",
        mask_token="<mask>",
    )
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID).to(device)
    model.eval()
    print(f"[STARTUP] Model loaded on {device}")

    yield

    print("[SHUTDOWN] Cleaning up")
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


app = FastAPI(
    title="Personal Korean Chatbot",
    description="FastAPI와 Hugging Face KoGPT2로 만든 포트폴리오용 한글 챗봇",
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().lower())


def get_rule_based_response(user_input: str) -> Optional[str]:
    text = normalize_text(user_input)

    intent_responses = [
        (
            ["안녕", "하이", "반가워", "hello", "hi"],
            "안녕하세요! 저는 FastAPI와 Hugging Face 모델로 만든 개인 한글 챗봇입니다. 간단한 질문을 입력해보세요.",
        ),
        (
            ["도움", "사용법", "뭐할수", "무엇을할수", "help"],
            "메시지를 입력하면 기본 응답 또는 AI 모델 응답을 제공합니다. 예: '인공지능이 뭐야?', '오늘 할 일 추천해줘'",
        ),
        (
            ["너는누구", "소개", "정체", "무슨챗봇"],
            "저는 포트폴리오와 배포 연습을 위해 만든 개인 챗봇입니다. FastAPI, Transformers, Docker, Hugging Face Spaces로 구성되어 있습니다.",
        ),
        (
            ["배포", "허깅페이스", "huggingface", "space"],
            "이 앱은 Docker 기반 Hugging Face Space로 배포할 수 있습니다. app.py, requirements.txt, Dockerfile, README.md 네 파일이 핵심입니다.",
        ),
        (
            ["깃허브", "github", "포트폴리오"],
            "GitHub에는 코드, README, 배포 매뉴얼, 스크린샷을 함께 올리면 포트폴리오로 설명하기 좋습니다.",
        ),
        (
            ["고마워", "감사"],
            "천만에요. 작은 기능부터 차근차근 개선해가면 충분히 좋은 프로젝트가 됩니다.",
        ),
        (
            ["잘가", "종료", "bye", "goodbye"],
            "대화해주셔서 감사합니다. 좋은 하루 보내세요!",
        ),
    ]

    for keywords, response in intent_responses:
        if any(keyword in text for keyword in keywords):
            return response

    return None


def clean_generated_text(text: str) -> str:
    cleaned = text.replace("<usr>", "").replace("<sys>", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:700].strip()


def generate_model_response(
    user_input: str,
    max_new_tokens: int,
    temperature: float,
    top_k: int,
) -> str:
    if model is None or tokenizer is None:
        raise RuntimeError("모델이 아직 로드되지 않았습니다.")

    prompt = f"<usr> {user_input.strip()} <sys> "
    input_ids = tokenizer.encode(prompt, return_tensors="pt").to(device)

    with torch.no_grad():
        output_ids = model.generate(
            input_ids,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_k=top_k,
            repetition_penalty=1.8,
            no_repeat_ngram_size=3,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )

    generated = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    response = generated.split("<sys>")[-1] if "<sys>" in generated else generated[len(prompt) :]
    response = clean_generated_text(response)
    return response or "죄송합니다. 답변을 생성하지 못했습니다. 다른 문장으로 다시 입력해주세요."


def generate_response(
    user_input: str,
    max_new_tokens: int,
    temperature: float,
    top_k: int,
) -> tuple[str, Literal["rule", "model"]]:
    rule_response = get_rule_based_response(user_input)
    if rule_response:
        return rule_response, "rule"

    return generate_model_response(user_input, max_new_tokens, temperature, top_k), "model"


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Personal Korean Chatbot</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
      background: #f4f6f8;
      color: #1f2933;
    }
    .shell {
      width: min(960px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 24px 0;
    }
    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }
    h1 {
      margin: 0;
      font-size: 26px;
      line-height: 1.25;
    }
    .subtitle {
      margin: 6px 0 0;
      color: #52606d;
      font-size: 14px;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-width: max-content;
      padding: 8px 10px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #ffffff;
      color: #334155;
      font-size: 13px;
    }
    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #94a3b8;
    }
    .dot.ready { background: #16a34a; }
    .chat-panel {
      display: grid;
      grid-template-rows: minmax(420px, 62vh) auto;
      overflow: hidden;
      border: 1px solid #d7dee8;
      border-radius: 8px;
      background: #ffffff;
    }
    #chat {
      overflow-y: auto;
      padding: 18px;
    }
    .message {
      display: grid;
      gap: 6px;
      max-width: 78%;
      margin: 0 0 14px;
    }
    .message.user {
      margin-left: auto;
      justify-items: end;
    }
    .label {
      color: #64748b;
      font-size: 12px;
    }
    .bubble {
      padding: 12px 13px;
      border-radius: 8px;
      line-height: 1.55;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #eef2f7;
    }
    .message.user .bubble {
      background: #2563eb;
      color: #ffffff;
    }
    .meta {
      color: #64748b;
      font-size: 12px;
    }
    .composer {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 8px;
      padding: 12px;
      border-top: 1px solid #e2e8f0;
      background: #f8fafc;
    }
    input {
      width: 100%;
      min-width: 0;
      padding: 12px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      font-size: 16px;
    }
    button {
      min-width: 82px;
      padding: 0 14px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #ffffff;
      color: #1f2933;
      font-size: 15px;
      cursor: pointer;
    }
    button.primary {
      border-color: #2563eb;
      background: #2563eb;
      color: #ffffff;
    }
    button:disabled {
      border-color: #94a3b8;
      background: #94a3b8;
      color: #ffffff;
      cursor: wait;
    }
    .examples {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    .chip {
      min-width: 0;
      padding: 8px 10px;
      border: 1px solid #cbd5e1;
      background: #ffffff;
      color: #334155;
      font-size: 13px;
    }
    @media (max-width: 640px) {
      header {
        align-items: stretch;
        flex-direction: column;
      }
      .message {
        max-width: 92%;
      }
      .composer {
        grid-template-columns: 1fr;
      }
      button {
        min-height: 42px;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1>Personal Korean Chatbot</h1>
        <p class="subtitle">FastAPI + Hugging Face + Docker 배포 연습용 챗봇</p>
      </div>
      <div class="status"><span id="dot" class="dot"></span><span id="statusText">상태 확인 중</span></div>
    </header>

    <section class="chat-panel">
      <div id="chat"></div>
      <form id="form" class="composer">
        <input id="message" placeholder="메시지를 입력하세요" autocomplete="off" />
        <button id="clear" type="button">초기화</button>
        <button id="send" class="primary" type="submit">전송</button>
      </form>
    </section>

    <div class="examples">
      <button class="chip" type="button">안녕하세요</button>
      <button class="chip" type="button">도움말</button>
      <button class="chip" type="button">너는 누구야?</button>
      <button class="chip" type="button">인공지능이 뭐야?</button>
    </div>
  </main>

  <script>
    const chat = document.getElementById("chat");
    const form = document.getElementById("form");
    const input = document.getElementById("message");
    const send = document.getElementById("send");
    const clear = document.getElementById("clear");
    const dot = document.getElementById("dot");
    const statusText = document.getElementById("statusText");
    const storageKey = "personal-korean-chatbot-history";

    function saveHistory() {
      localStorage.setItem(storageKey, chat.innerHTML);
    }

    function loadHistory() {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        chat.innerHTML = saved;
      } else {
        addMessage("bot", "챗봇", "안녕하세요! 배포 테스트가 끝났다면 이제 간단한 대화를 시도해보세요.");
      }
      chat.scrollTop = chat.scrollHeight;
    }

    function addMessage(type, label, text, meta = "") {
      const wrapper = document.createElement("div");
      wrapper.className = `message ${type}`;

      const labelEl = document.createElement("div");
      labelEl.className = "label";
      labelEl.textContent = label;

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text;

      wrapper.appendChild(labelEl);
      wrapper.appendChild(bubble);

      if (meta) {
        const metaEl = document.createElement("div");
        metaEl.className = "meta";
        metaEl.textContent = meta;
        wrapper.appendChild(metaEl);
      }

      chat.appendChild(wrapper);
      chat.scrollTop = chat.scrollHeight;
      saveHistory();
    }

    async function checkHealth() {
      try {
        const response = await fetch("/health");
        const data = await response.json();
        dot.classList.toggle("ready", data.model_loaded);
        statusText.textContent = data.model_loaded ? `Running · ${data.model_used}` : "모델 로딩 중";
      } catch (error) {
        dot.classList.remove("ready");
        statusText.textContent = "연결 확인 필요";
      }
    }

    async function sendMessage(message) {
      addMessage("user", "나", message);
      input.value = "";
      send.disabled = true;

      try {
        const response = await fetch("/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json; charset=utf-8"},
          body: JSON.stringify({
            message,
            max_new_tokens: 80,
            temperature: 0.7,
            top_k: 40
          })
        });

        const data = await response.json();
        if (!response.ok) {
          addMessage("bot", "챗봇", data.detail || "요청 처리 중 오류가 발생했습니다.");
          return;
        }

        const meta = `${data.response_type} · ${data.processing_time_ms}ms`;
        addMessage("bot", "챗봇", data.bot_response, meta);
      } catch (error) {
        addMessage("bot", "챗봇", "서버와 통신하지 못했습니다. 잠시 후 다시 시도해주세요.");
      } finally {
        send.disabled = false;
        input.focus();
      }
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const message = input.value.trim();
      if (message) sendMessage(message);
    });

    clear.addEventListener("click", () => {
      localStorage.removeItem(storageKey);
      chat.innerHTML = "";
      addMessage("bot", "챗봇", "대화 내용을 초기화했습니다. 다시 시작해볼까요?");
      input.focus();
    });

    document.querySelectorAll(".chip").forEach((button) => {
      button.addEventListener("click", () => {
        input.value = button.textContent;
        input.focus();
      });
    });

    loadHistory();
    checkHealth();
    setInterval(checkHealth, 15000);
  </script>
</body>
</html>
"""


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()

    try:
        response, response_type = generate_response(
            user_input=request.message,
            max_new_tokens=request.max_new_tokens,
            temperature=request.temperature,
            top_k=request.top_k,
        )
        elapsed_ms = (time.time() - start) * 1000

        return ChatResponse(
            user_message=request.message,
            bot_response=response,
            response_type=response_type,
            model_used=MODEL_ID,
            device=device,
            processing_time_ms=round(elapsed_ms, 2),
            tokens_generated=len(response.split()),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"챗봇 처리 중 오류 발생: {exc}") from exc


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="healthy",
        model_loaded=model is not None,
        model_used=MODEL_ID,
        device=device,
        uptime_seconds=int(time.time() - started_at),
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT)
