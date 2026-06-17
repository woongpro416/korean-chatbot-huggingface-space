from fastapi import APIRouter, HTTPException, status

from models.schemas import ChatRequest, ChatResponse, Language
from services.chatbot_service import chatbot_service


router = APIRouter(prefix="/chat", tags=["Chatbot"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        if request.language == Language.korean:
            if chatbot_service.ko_model is None:
                raise HTTPException(status_code=503, detail="한국어 모델이 로드되지 않았습니다.")

            response = chatbot_service.generate_korean_response(
                user_input=request.message,
                max_length=request.max_length,
                temperature=request.temperature,
            )
            model_used = "skt/kogpt2-base-v2"
        else:
            if chatbot_service.en_model is None:
                raise HTTPException(status_code=503, detail="영어 모델이 로드되지 않았습니다.")

            response = chatbot_service.generate_english_response(
                user_input=request.message,
                max_length=request.max_length,
                temperature=request.temperature,
            )
            model_used = "microsoft/DialoGPT-medium"

        return ChatResponse(
            user_message=request.message,
            bot_response=response or "죄송합니다. 응답을 생성하지 못했습니다.",
            language=request.language.value,
            model_used=model_used,
            tokens_generated=len(response.split()) if response else 0,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"챗봇 처리 중 오류 발생: {exc}",
        ) from exc


@router.get("/health")
async def chatbot_health():
    return {
        "en_model_loaded": chatbot_service.en_model is not None,
        "ko_model_loaded": chatbot_service.ko_model is not None,
        "device": chatbot_service.device,
    }
