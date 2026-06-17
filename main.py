from contextlib import asynccontextmanager
import json

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from routers import chatbot
from services.chatbot_service import chatbot_service


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    chatbot_service.load_korean_model()
    # 영어까지 쓰려면 아래 줄도 활성화
    # chatbot_service.load_english_model()
    yield


app = FastAPI(
    title="NLP Chatbot API",
    description="Hugging Face 모델 기반 챗봇 API",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)

app.include_router(chatbot.router)


@app.get("/")
async def root():
    return {"status": "NLP Chatbot Running", "docs": "/docs"}
