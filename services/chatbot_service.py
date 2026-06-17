import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class ChatbotService:
    def __init__(self):
        self.en_tokenizer = None
        self.en_model = None
        self.ko_tokenizer = None
        self.ko_model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def load_english_model(self):
        model_id = "microsoft/DialoGPT-medium"
        self.en_tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.en_model = AutoModelForCausalLM.from_pretrained(model_id).to(self.device)
        self.en_model.eval()

    def load_korean_model(self):
        model_id = "skt/kogpt2-base-v2"
        self.ko_tokenizer = AutoTokenizer.from_pretrained(
            model_id,
            bos_token="</s>",
            eos_token="</s>",
            unk_token="<unk>",
            pad_token="<pad>",
            mask_token="<mask>",
        )
        self.ko_model = AutoModelForCausalLM.from_pretrained(model_id).to(self.device)
        self.ko_model.eval()

    def generate_english_response(self, user_input: str, max_length: int = 200, temperature: float = 0.7):
        input_ids = self.en_tokenizer.encode(
            user_input + self.en_tokenizer.eos_token,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            output_ids = self.en_model.generate(
                input_ids,
                max_length=max_length,
                do_sample=True,
                temperature=temperature,
                top_p=0.9,
                repetition_penalty=1.3,
                pad_token_id=self.en_tokenizer.eos_token_id,
            )

        response_ids = output_ids[:, input_ids.shape[-1]:]
        return self.en_tokenizer.decode(response_ids[0], skip_special_tokens=True).strip()

    def generate_korean_response(self, user_input: str, max_length: int = 128, temperature: float = 0.8):
        prompt = f"<usr> {user_input} <sys> "
        input_ids = self.ko_tokenizer.encode(prompt, return_tensors="pt").to(self.device)

        with torch.no_grad():
            output_ids = self.ko_model.generate(
                input_ids,
                max_length=max_length,
                do_sample=True,
                temperature=temperature,
                top_k=50,
                repetition_penalty=2.0,
                pad_token_id=self.ko_tokenizer.pad_token_id,
                eos_token_id=self.ko_tokenizer.eos_token_id,
            )

        generated = self.ko_tokenizer.decode(output_ids[0], skip_special_tokens=True)
        return generated.split("<sys>")[-1].strip() if "<sys>" in generated else generated[len(prompt):].strip()


chatbot_service = ChatbotService()