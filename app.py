import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import torch
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL_ID = os.getenv("MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct")
PORT = int(os.getenv("PORT", "7860"))
DB_PATH = Path(os.getenv("DB_PATH", "data/chatbot.sqlite3"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "devwoong416")
SYSTEM_PROMPT = (
    "?? ?????? ?? ?? ????. "
    "??? ????, ?? ???? ??. "
    "??? ??? ???? ?? ???? ???."
)
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
    session_id: Optional[str] = Field(None, description="대화 세션 ID. 없으면 새로 생성")
    user_id: str = Field("anonymous", max_length=80, description="사용자 식별자")
    message: str = Field(..., min_length=1, max_length=800, description="사용자 메시지")
    max_new_tokens: int = Field(160, ge=20, le=300, description="새로 생성할 최대 토큰 수")
    temperature: float = Field(0.6, ge=0.1, le=1.2, description="응답 다양성")
    top_p: float = Field(0.9, ge=0.1, le=1.0, description="누적 확률 샘플링 값")

    model_config = {
        "json_schema_extra": {
            "example": {
                "session_id": None,
                "user_id": "anonymous",
                "message": "안녕하세요",
                "max_new_tokens": 160,
                "temperature": 0.6,
                "top_p": 0.9,
            }
        }
    }


class ChatResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    session_id: str
    message_id: str
    user_message: str
    bot_response: str
    response_type: Literal["rule", "model"]
    llm_name: str
    device: str
    processing_time_ms: float
    tokens_generated: Optional[int] = None


class FeedbackRequest(BaseModel):
    message_id: str = Field(..., description="평가할 챗봇 응답 message_id")
    rating: Literal["up", "down"] = Field(..., description="좋아요 또는 싫어요")
    comment: Optional[str] = Field(None, max_length=500, description="선택 피드백 메모")


class FeedbackResponse(BaseModel):
    ok: bool
    feedback_id: str
    message: str


class HistoryMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    response_type: Optional[str] = None
    llm_name: Optional[str] = None
    processing_time_ms: Optional[float] = None
    tokens_generated: Optional[int] = None
    feedback_rating: Optional[int] = None
    created_at: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


class FeedbackItem(BaseModel):
    feedback_id: str
    message_id: str
    session_id: str
    rating: Literal["up", "down"]
    comment: Optional[str] = None
    user_message: Optional[str] = None
    bot_response: str
    response_type: Optional[str] = None
    llm_name: Optional[str] = None
    feedback_created_at: str
    message_created_at: str


class AdminFeedbackResponse(BaseModel):
    total: int
    items: list[FeedbackItem]


class HealthResponse(BaseModel):
    status: str
    loaded: bool
    llm_name: str
    device: str
    database_path: str
    uptime_seconds: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                response_type TEXT,
                model_used TEXT,
                processing_time_ms REAL,
                tokens_generated INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
                comment TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_created
            ON messages(session_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_feedback_message
            ON feedback(message_id);
            """
        )


def ensure_session(session_id: Optional[str], user_id: str) -> str:
    init_db()
    sid = session_id or str(uuid.uuid4())
    now = utc_now()
    with get_db() as conn:
        row = conn.execute("SELECT id FROM sessions WHERE id = ?", (sid,)).fetchone()
        if row:
            conn.execute(
                "UPDATE sessions SET updated_at = ?, user_id = ? WHERE id = ?",
                (now, user_id, sid),
            )
        else:
            conn.execute(
                "INSERT INTO sessions (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (sid, user_id, now, now),
            )
    return sid


def save_message(
    session_id: str,
    role: Literal["user", "assistant"],
    content: str,
    response_type: Optional[str] = None,
    model_used: Optional[str] = None,
    processing_time_ms: Optional[float] = None,
    tokens_generated: Optional[int] = None,
) -> str:
    init_db()
    message_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO messages (
                id, session_id, role, content, response_type, model_used,
                processing_time_ms, tokens_generated, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                role,
                content,
                response_type,
                model_used,
                processing_time_ms,
                tokens_generated,
                utc_now(),
            ),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (utc_now(), session_id))
    return message_id


def get_recent_history(session_id: str, limit: int = 8) -> list[dict[str, str]]:
    init_db()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()

    messages = []
    for row in reversed(rows):
        role = "assistant" if row["role"] == "assistant" else "user"
        messages.append({"role": role, "content": row["content"]})
    return messages


def require_admin_token(x_admin_token: Optional[str]) -> None:
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="관리자 토큰이 올바르지 않습니다.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tokenizer, model

    init_db()
    print(f"[STARTUP] Loading model: {MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    ).to(device)
    model.eval()
    print(f"[STARTUP] Model loaded on {device}")

    yield

    print("[SHUTDOWN] Cleaning up")
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


app = FastAPI(
    title="Personal Korean Chatbot",
    description="FastAPI, SQLite, Feedback, Hugging Face Instruct 모델 기반 실무형 챗봇",
    version="3.0.0",
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
            "안녕하세요! 저는 FastAPI와 Hugging Face Instruct 모델로 만든 개인 한글 챗봇입니다. 대화 내용과 피드백을 저장해 개선 데이터로 활용할 수 있습니다.",
        ),
        (
            ["도움", "사용법", "뭐할수", "무엇을할수", "help"],
            "질문을 입력하면 세션별 대화 기록을 참고해 답변합니다. 답변 아래의 좋아요/싫어요 버튼으로 피드백도 남길 수 있습니다.",
        ),
        (
            ["너는누구", "소개", "정체", "무슨챗봇"],
            "저는 포트폴리오용 실무 연습 챗봇입니다. FastAPI, SQLite, Transformers, Docker, Hugging Face Spaces로 구성되어 있습니다.",
        ),
        (
            ["학습", "파인튜닝", "finetuning", "fine-tuning", "lora"],
            "현재 앱은 즉석 학습을 하지는 않지만, 대화와 피드백을 SQLite에 저장합니다. 이 데이터는 나중에 LoRA나 fine-tuning 데이터셋으로 정리할 수 있습니다.",
        ),
        (
            ["깃허브", "github", "포트폴리오"],
            "GitHub에는 코드, README, Dockerfile, requirements.txt, 스크린샷을 올리면 좋습니다. 로컬 배포 매뉴얼 txt는 .gitignore로 제외했습니다.",
        ),
        (
            ["고마워", "감사"],
            "천만에요. 피드백이 쌓일수록 어떤 답변을 개선해야 하는지 더 명확해집니다.",
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


def build_chat_messages(session_id: str, user_input: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(get_recent_history(session_id, limit=8))
    messages.append({"role": "user", "content": user_input.strip()})
    return messages


def clean_generated_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:1000].strip()


def generate_model_response(
    session_id: str,
    user_input: str,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
) -> str:
    if model is None or tokenizer is None:
        raise RuntimeError("모델이 아직 로드되지 않았습니다.")

    messages = build_chat_messages(session_id, user_input)

    if getattr(tokenizer, "chat_template", None):
        inputs = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(device)
    else:
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\nassistant:"
        inputs = tokenizer(prompt, return_tensors="pt").to(device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=1.15,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )

    generated_ids = output_ids[0][inputs["input_ids"].shape[-1] :]
    response = tokenizer.decode(generated_ids, skip_special_tokens=True)
    return clean_generated_text(response) or "죄송합니다. 답변을 생성하지 못했습니다. 질문을 조금 다르게 입력해주세요."


def generate_response(
    session_id: str,
    user_input: str,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
) -> tuple[str, Literal["rule", "model"]]:
    rule_response = get_rule_based_response(user_input)
    if rule_response:
        return rule_response, "rule"
    return generate_model_response(session_id, user_input, max_new_tokens, temperature, top_p), "model"


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
    :root {
      --bg: #f6f2ff;
      --panel: rgba(255, 255, 255, 0.76);
      --panel-strong: rgba(255, 255, 255, 0.92);
      --line: rgba(116, 79, 173, 0.16);
      --text: #272038;
      --muted: #756b88;
      --soft: #3a304d;
      --violet: #8b5cf6;
      --violet-strong: #6d28d9;
      --mint: #13bfa4;
      --amber: #d88a2d;
      --danger: #d94b6a;
      --shadow: 0 24px 60px rgba(87, 58, 139, 0.16);
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, Arial, "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
      color: var(--text);
      background:
        linear-gradient(135deg, rgba(139, 92, 246, 0.28), transparent 36%),
        linear-gradient(315deg, rgba(19, 191, 164, 0.16), transparent 33%),
        linear-gradient(180deg, #fbf8ff 0%, #f2ecff 48%, #eefaf8 100%);
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      z-index: -1;
      pointer-events: none;
      background:
        repeating-linear-gradient(90deg, rgba(99, 74, 142, 0.055) 0 1px, transparent 1px 84px),
        repeating-linear-gradient(0deg, rgba(99, 74, 142, 0.04) 0 1px, transparent 1px 84px);
      mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.55), transparent 88%);
    }
    .shell {
      width: min(1000px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 26px 0;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }
    h1 {
      margin: 0;
      font-size: 26px;
      line-height: 1.2;
      font-weight: 760;
      letter-spacing: 0;
    }
    .subtitle {
      margin: 7px 0 0;
      color: var(--muted);
      font-size: 14px;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-width: max-content;
      padding: 9px 11px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.72);
      color: var(--soft);
      font-size: 13px;
      box-shadow: 0 10px 30px rgba(87, 58, 139, 0.1);
    }
    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #757083;
    }
    .dot.ready {
      background: var(--mint);
      box-shadow: 0 0 0 4px rgba(69, 214, 181, 0.14);
    }
    .layout {
      display: grid;
      grid-template-columns: 1fr 260px;
      gap: 14px;
    }
    .chat-panel {
      display: grid;
      grid-template-rows: minmax(430px, 62vh) auto;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }
    #chat {
      overflow-y: auto;
      padding: 18px;
      scrollbar-color: rgba(139, 92, 246, 0.42) rgba(116, 79, 173, 0.08);
    }
    .message {
      display: grid;
      gap: 6px;
      max-width: 82%;
      margin: 0 0 15px;
    }
    .message.user {
      margin-left: auto;
      justify-items: end;
    }
    .label {
      color: var(--muted);
      font-size: 12px;
    }
    .bubble {
      padding: 12px 13px;
      border-radius: 8px;
      line-height: 1.55;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: rgba(255, 255, 255, 0.76);
      border: 1px solid rgba(116, 79, 173, 0.13);
      color: var(--soft);
    }
    .message.user .bubble {
      background: linear-gradient(135deg, rgba(124, 58, 237, 0.95), rgba(72, 93, 220, 0.95));
      border-color: rgba(255, 255, 255, 0.16);
      color: #ffffff;
    }
    .meta {
      color: #837592;
      font-size: 12px;
    }
    .feedback {
      display: flex;
      gap: 6px;
    }
    .message.pending .bubble {
      color: var(--muted);
      border-style: dashed;
      background: rgba(255, 255, 255, 0.58);
    }
    .thinking {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .pulse {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--violet);
      box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.32);
      animation: pulse 1.2s infinite;
    }
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.32); }
      70% { box-shadow: 0 0 0 8px rgba(139, 92, 246, 0); }
      100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0); }
    }
    .feedback button {
      min-width: 42px;
      min-height: 30px;
      padding: 4px 8px;
      font-size: 13px;
      color: var(--soft);
    }
    .composer {
      display: grid;
      grid-template-columns: 1fr 44px 52px;
      gap: 8px;
      padding: 12px;
      border-top: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.62);
    }
    input {
      width: 100%;
      min-width: 0;
      padding: 12px;
      border: 1px solid rgba(116, 79, 173, 0.2);
      border-radius: 6px;
      outline: none;
      background: rgba(255, 255, 255, 0.82);
      color: var(--text);
      font-size: 16px;
    }
    input::placeholder {
      color: #9388a3;
    }
    input:focus {
      border-color: rgba(159, 122, 234, 0.9);
      box-shadow: 0 0 0 3px rgba(159, 122, 234, 0.16);
    }
    button {
      min-width: 0;
      padding: 0 14px;
      border: 1px solid rgba(116, 79, 173, 0.18);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.7);
      color: var(--text);
      font-size: 15px;
      cursor: pointer;
      transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
    }
    button:hover {
      transform: translateY(-1px);
      border-color: rgba(159, 122, 234, 0.72);
      background: rgba(255, 255, 255, 0.94);
    }
    button.primary {
      border-color: rgba(159, 122, 234, 0.95);
      background: linear-gradient(135deg, var(--violet-strong), #4f46e5);
      color: #ffffff;
    }
    button:disabled {
      transform: none;
      border-color: rgba(148, 163, 184, 0.35);
      background: rgba(148, 163, 184, 0.28);
      color: rgba(255, 255, 255, 0.78);
      cursor: wait;
    }
    aside {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.68);
      padding: 14px;
      align-self: start;
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }
    aside h2 {
      margin: 0 0 10px;
      color: #2d2540;
      font-size: 16px;
      letter-spacing: 0;
    }
    .side-text {
      margin: 0 0 12px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .chips {
      display: grid;
      gap: 8px;
    }
    .chip {
      min-width: 0;
      min-height: 38px;
      padding: 8px 10px;
      color: var(--soft);
      font-size: 13px;
      text-align: left;
    }
    .chip:nth-child(2) {
      border-color: rgba(69, 214, 181, 0.34);
    }
    .chip:nth-child(4) {
      border-color: rgba(240, 184, 110, 0.32);
    }
    @media (max-width: 760px) {
      header {
        align-items: stretch;
        flex-direction: column;
      }
      .layout {
        grid-template-columns: 1fr;
      }
      .message {
        max-width: 94%;
      }
      .composer {
        grid-template-columns: 1fr 44px 52px;
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
        <p class="subtitle">Violet workspace for focused Korean chat</p>
      </div>
      <div class="status"><span id="dot" class="dot"></span><span id="statusText">상태 확인 중</span></div>
    </header>

    <div class="layout">
      <section class="chat-panel">
        <div id="chat"></div>
        <form id="form" class="composer">
          <input id="message" placeholder="메시지를 입력하세요" autocomplete="off" />
          <button id="clear" type="button" title="새 세션">↺</button>
          <button id="send" class="primary" type="submit" title="전송">↑</button>
        </form>
      </section>

      <aside>
        <h2>Prompt Palette</h2>
        <p class="side-text">오늘의 대화를 가볍게 시작해보세요.</p>
        <div class="chips">
          <button class="chip" type="button">안녕하세요</button>
          <button class="chip" type="button">도움말</button>
          <button class="chip" type="button">너는 누구야?</button>
          <button class="chip" type="button">학습 기능이 있어?</button>
          <button class="chip" type="button">인공지능을 쉽게 설명해줘</button>
        </div>
      </aside>
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
    const sessionKey = "personal-korean-chatbot-session-id";
    let sessionId = localStorage.getItem(sessionKey) || crypto.randomUUID();
    localStorage.setItem(sessionKey, sessionId);

    function addMessage(type, label, text, options = {}) {
      const wrapper = document.createElement("div");
      wrapper.className = `message ${type}${options.pending ? " pending" : ""}`;
      if (options.messageId) wrapper.dataset.messageId = options.messageId;

      const labelEl = document.createElement("div");
      labelEl.className = "label";
      labelEl.textContent = label;

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text;

      wrapper.appendChild(labelEl);
      wrapper.appendChild(bubble);

      if (options.meta) {
        const metaEl = document.createElement("div");
        metaEl.className = "meta";
        metaEl.textContent = options.meta;
        wrapper.appendChild(metaEl);
      }

      if (type === "bot" && options.messageId) {
        const feedback = document.createElement("div");
        feedback.className = "feedback";
        feedback.innerHTML = `
          <button type="button" data-rating="up">좋아요</button>
          <button type="button" data-rating="down">싫어요</button>
        `;
        feedback.querySelectorAll("button").forEach((button) => {
          button.addEventListener("click", () => sendFeedback(options.messageId, button.dataset.rating, feedback));
        });
        wrapper.appendChild(feedback);
      }

      chat.appendChild(wrapper);
      chat.scrollTop = chat.scrollHeight;
      return wrapper;
    }

    function addPendingMessage() {
      const pending = addMessage("bot", "챗봇", "탐색중... 0초", { pending: true });
      const bubble = pending.querySelector(".bubble");
      bubble.innerHTML = `<span class="thinking"><span class="pulse"></span><span>탐색중... 0초</span></span>`;
      const text = bubble.querySelector(".thinking span:last-child");
      const startedAt = Date.now();
      const timer = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        text.textContent = `탐색중... ${seconds}초`;
      }, 1000);
      return {
        element: pending,
        stop() {
          clearInterval(timer);
          pending.remove();
        }
      };
    }

    async function loadHistory() {
      try {
        const response = await fetch(`/history/${sessionId}`);
        const data = await response.json();
        chat.innerHTML = "";
        if (!data.messages.length) {
          addMessage("bot", "챗봇", "안녕하세요! 이제 대화 기록과 피드백이 서버에 저장됩니다.");
          return;
        }
        data.messages.forEach((message) => {
          if (message.role === "user") {
            addMessage("user", "나", message.content);
          } else {
            const meta = `${message.response_type || "assistant"} · ${message.processing_time_ms || 0}ms`;
            addMessage("bot", "챗봇", message.content, { messageId: message.id, meta });
          }
        });
      } catch (error) {
        addMessage("bot", "챗봇", "대화 기록을 불러오지 못했습니다. 새 대화로 시작합니다.");
      }
    }

    async function checkHealth() {
      try {
        const response = await fetch("/health");
        const data = await response.json();
        dot.classList.toggle("ready", data.loaded);
        statusText.textContent = data.loaded ? `Running · ${data.llm_name}` : "모델 로딩 중";
      } catch (error) {
        dot.classList.remove("ready");
        statusText.textContent = "연결 확인 필요";
      }
    }

    async function sendFeedback(messageId, rating, container) {
      container.querySelectorAll("button").forEach((button) => button.disabled = true);
      try {
        const response = await fetch("/feedback", {
          method: "POST",
          headers: {"Content-Type": "application/json; charset=utf-8"},
          body: JSON.stringify({ message_id: messageId, rating })
        });
        if (!response.ok) throw new Error("feedback failed");
        container.textContent = rating === "up" ? "좋아요가 저장되었습니다." : "싫어요가 저장되었습니다.";
      } catch (error) {
        container.textContent = "피드백 저장에 실패했습니다.";
      }
    }

    async function sendMessage(message) {
      addMessage("user", "나", message);
      input.value = "";
      send.disabled = true;
      const pending = addPendingMessage();

      try {
        const response = await fetch("/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json; charset=utf-8"},
          body: JSON.stringify({
            session_id: sessionId,
            user_id: "browser-user",
            message,
            max_new_tokens: 160,
            temperature: 0.6,
            top_p: 0.9
          })
        });

        const data = await response.json();
        pending.stop();
        if (!response.ok) {
          addMessage("bot", "챗봇", data.detail || "요청 처리 중 오류가 발생했습니다.");
          return;
        }

        sessionId = data.session_id;
        localStorage.setItem(sessionKey, sessionId);
        const meta = `${data.response_type} · ${data.processing_time_ms}ms`;
        addMessage("bot", "챗봇", data.bot_response, { messageId: data.message_id, meta });
      } catch (error) {
        pending.stop();
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
      sessionId = crypto.randomUUID();
      localStorage.setItem(sessionKey, sessionId);
      chat.innerHTML = "";
      addMessage("bot", "챗봇", "새 세션을 시작했습니다.");
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


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Chatbot Feedback Admin</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Arial, "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
      color: #29213b;
      background:
        linear-gradient(135deg, rgba(139, 92, 246, 0.22), transparent 36%),
        linear-gradient(315deg, rgba(19, 191, 164, 0.12), transparent 34%),
        linear-gradient(180deg, #fbf8ff 0%, #f4efff 52%, #effaf7 100%);
    }
    main {
      width: min(1120px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 28px 0;
    }
    header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }
    h1 { margin: 0; font-size: 26px; letter-spacing: 0; }
    p { margin: 7px 0 0; color: #756b88; }
    .controls {
      display: grid;
      grid-template-columns: 1fr 160px 120px;
      gap: 8px;
      margin-bottom: 14px;
      padding: 12px;
      border: 1px solid rgba(116, 79, 173, 0.16);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.72);
      box-shadow: 0 20px 50px rgba(87, 58, 139, 0.13);
    }
    input, select, button {
      min-height: 42px;
      border: 1px solid rgba(116, 79, 173, 0.2);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.86);
      color: #29213b;
      font-size: 15px;
    }
    input { padding: 0 12px; }
    select { padding: 0 10px; }
    button {
      cursor: pointer;
      background: linear-gradient(135deg, #6d28d9, #4f46e5);
      color: white;
      border-color: rgba(109, 40, 217, 0.7);
    }
    .summary {
      margin: 0 0 12px;
      color: #756b88;
      font-size: 14px;
    }
    .list {
      display: grid;
      gap: 12px;
    }
    .card {
      padding: 14px;
      border: 1px solid rgba(116, 79, 173, 0.14);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.78);
      box-shadow: 0 12px 32px rgba(87, 58, 139, 0.1);
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
      color: #756b88;
      font-size: 13px;
    }
    .pill {
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(139, 92, 246, 0.1);
      color: #5b21b6;
    }
    .pill.down {
      background: rgba(217, 75, 106, 0.1);
      color: #b42349;
    }
    .qa {
      display: grid;
      gap: 9px;
    }
    .label {
      display: block;
      margin-bottom: 4px;
      color: #756b88;
      font-size: 12px;
      font-weight: 700;
    }
    .box {
      padding: 10px 11px;
      border: 1px solid rgba(116, 79, 173, 0.12);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.68);
      line-height: 1.55;
      white-space: pre-wrap;
    }
    .empty {
      padding: 22px;
      text-align: center;
      color: #756b88;
      border: 1px dashed rgba(116, 79, 173, 0.26);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.55);
    }
    @media (max-width: 720px) {
      header { align-items: stretch; flex-direction: column; }
      .controls { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Feedback Admin</h1>
        <p>챗봇 응답에 남겨진 좋아요/싫어요 피드백을 검토합니다.</p>
      </div>
    </header>

    <section class="controls">
      <input id="token" type="password" placeholder="관리자 토큰" autocomplete="off" />
      <select id="rating">
        <option value="">전체</option>
        <option value="up">좋아요</option>
        <option value="down">싫어요</option>
      </select>
      <button id="load" type="button">불러오기</button>
    </section>

    <p id="summary" class="summary">관리자 토큰을 입력하고 피드백을 불러오세요.</p>
    <section id="list" class="list"></section>
  </main>

  <script>
    const token = document.getElementById("token");
    const rating = document.getElementById("rating");
    const load = document.getElementById("load");
    const summary = document.getElementById("summary");
    const list = document.getElementById("list");
    const tokenKey = "chatbot-admin-token";

    token.value = localStorage.getItem(tokenKey) || "";

    function renderItem(item) {
      const card = document.createElement("article");
      card.className = "card";
      const ratingText = item.rating === "up" ? "좋아요" : "싫어요";
      card.innerHTML = `
        <div class="meta">
          <span class="pill ${item.rating === "down" ? "down" : ""}">${ratingText}</span>
          <span>${item.feedback_created_at}</span>
          <span>${item.response_type || "assistant"}</span>
          <span>${item.llm_name || ""}</span>
        </div>
        <div class="qa">
          <div><span class="label">사용자 질문</span><div class="box"></div></div>
          <div><span class="label">챗봇 답변</span><div class="box"></div></div>
          <div><span class="label">코멘트</span><div class="box"></div></div>
        </div>
      `;
      const boxes = card.querySelectorAll(".box");
      boxes[0].textContent = item.user_message || "(질문을 찾지 못했습니다)";
      boxes[1].textContent = item.bot_response;
      boxes[2].textContent = item.comment || "(코멘트 없음)";
      return card;
    }

    async function loadFeedback() {
      localStorage.setItem(tokenKey, token.value);
      list.innerHTML = "";
      summary.textContent = "불러오는 중...";

      const params = new URLSearchParams({ limit: "100" });
      if (rating.value) params.set("rating", rating.value);

      try {
        const response = await fetch(`/admin/feedback?${params.toString()}`, {
          headers: { "X-Admin-Token": token.value }
        });
        const data = await response.json();
        if (!response.ok) {
          summary.textContent = data.detail || "피드백을 불러오지 못했습니다.";
          return;
        }
        summary.textContent = `총 ${data.total}개의 피드백`;
        if (!data.items.length) {
          list.innerHTML = `<div class="empty">아직 표시할 피드백이 없습니다.</div>`;
          return;
        }
        data.items.forEach((item) => list.appendChild(renderItem(item)));
      } catch (error) {
        summary.textContent = "서버와 통신하지 못했습니다.";
      }
    }

    load.addEventListener("click", loadFeedback);
  </script>
</body>
</html>
"""


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start = time.time()
    session_id = ensure_session(request.session_id, request.user_id)
    save_message(session_id, "user", request.message)

    try:
        response, response_type = generate_response(
            session_id=session_id,
            user_input=request.message,
            max_new_tokens=request.max_new_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
        )
        elapsed_ms = (time.time() - start) * 1000
        tokens_generated = len(response.split())
        assistant_message_id = save_message(
            session_id=session_id,
            role="assistant",
            content=response,
            response_type=response_type,
            model_used=MODEL_ID,
            processing_time_ms=round(elapsed_ms, 2),
            tokens_generated=tokens_generated,
        )

        return ChatResponse(
            session_id=session_id,
            message_id=assistant_message_id,
            user_message=request.message,
            bot_response=response,
            response_type=response_type,
            llm_name=MODEL_ID,
            device=device,
            processing_time_ms=round(elapsed_ms, 2),
            tokens_generated=tokens_generated,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"챗봇 처리 중 오류 발생: {exc}") from exc


@app.get("/history/{session_id}", response_model=HistoryResponse)
async def history(session_id: str):
    init_db()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                m.id, m.role, m.content, m.response_type,
                m.model_used AS llm_name,
                m.processing_time_ms, m.tokens_generated, m.created_at,
                (
                    SELECT f.rating
                    FROM feedback f
                    WHERE f.message_id = m.id
                    ORDER BY f.created_at DESC
                    LIMIT 1
                ) AS feedback_rating
            FROM messages m
            WHERE m.session_id = ?
            ORDER BY m.created_at ASC
            """,
            (session_id,),
        ).fetchall()

    return HistoryResponse(
        session_id=session_id,
        messages=[HistoryMessage(**dict(row)) for row in rows],
    )


@app.post("/feedback", response_model=FeedbackResponse)
async def feedback(request: FeedbackRequest):
    init_db()
    rating_value = 1 if request.rating == "up" else -1
    feedback_id = str(uuid.uuid4())

    with get_db() as conn:
        message = conn.execute(
            "SELECT id, role FROM messages WHERE id = ?",
            (request.message_id,),
        ).fetchone()
        if not message:
            raise HTTPException(status_code=404, detail="메시지를 찾을 수 없습니다.")
        if message["role"] != "assistant":
            raise HTTPException(status_code=400, detail="챗봇 응답에만 피드백을 남길 수 있습니다.")

        conn.execute(
            "INSERT INTO feedback (id, message_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?)",
            (feedback_id, request.message_id, rating_value, request.comment, utc_now()),
        )

    return FeedbackResponse(ok=True, feedback_id=feedback_id, message="피드백이 저장되었습니다.")


@app.get("/admin/feedback", response_model=AdminFeedbackResponse)
async def admin_feedback(
    rating: Optional[Literal["up", "down"]] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    x_admin_token: Optional[str] = Header(None),
):
    require_admin_token(x_admin_token)
    init_db()

    params: list[object] = []
    rating_filter = ""
    if rating:
        rating_filter = "WHERE f.rating = ?"
        params.append(1 if rating == "up" else -1)

    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS count FROM feedback f {rating_filter}",
            params,
        ).fetchone()["count"]

        rows = conn.execute(
            f"""
            SELECT
                f.id AS feedback_id,
                f.message_id,
                f.rating,
                f.comment,
                f.created_at AS feedback_created_at,
                assistant.session_id,
                assistant.content AS bot_response,
                assistant.response_type,
                assistant.model_used AS llm_name,
                assistant.created_at AS message_created_at,
                (
                    SELECT user.content
                    FROM messages user
                    WHERE user.session_id = assistant.session_id
                      AND user.role = 'user'
                      AND user.created_at < assistant.created_at
                    ORDER BY user.created_at DESC
                    LIMIT 1
                ) AS user_message
            FROM feedback f
            JOIN messages assistant ON assistant.id = f.message_id
            {rating_filter}
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()

    items = []
    for row in rows:
        data = dict(row)
        data["rating"] = "up" if data["rating"] == 1 else "down"
        items.append(FeedbackItem(**data))

    return AdminFeedbackResponse(total=total, items=items)


@app.get("/training-data.jsonl", response_class=PlainTextResponse)
async def training_data():
    init_db()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                assistant.id AS assistant_id,
                user.content AS instruction,
                assistant.content AS output,
                feedback.rating AS rating
            FROM feedback
            JOIN messages assistant ON assistant.id = feedback.message_id
            JOIN messages user
              ON user.session_id = assistant.session_id
             AND user.role = 'user'
             AND user.created_at = (
                SELECT MAX(prev.created_at)
                FROM messages prev
                WHERE prev.session_id = assistant.session_id
                  AND prev.role = 'user'
                  AND prev.created_at < assistant.created_at
             )
            WHERE feedback.rating = 1
            ORDER BY feedback.created_at ASC
            """
        ).fetchall()

    lines = []
    for row in rows:
        lines.append(
            json.dumps(
                {
                    "instruction": row["instruction"],
                    "output": row["output"],
                    "metadata": {
                        "assistant_message_id": row["assistant_id"],
                        "rating": row["rating"],
                        "source": "chatbot_feedback",
                    },
                },
                ensure_ascii=False,
            )
        )
    return PlainTextResponse("\n".join(lines), media_type="application/jsonl; charset=utf-8")


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="healthy",
        loaded=model is not None,
        llm_name=MODEL_ID,
        device=device,
        database_path=str(DB_PATH),
        uptime_seconds=int(time.time() - started_at),
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT)
