
"""Прямая генерация Qwen без Qdrant и BGE-M3."""

import httpx

from api.engine import RagAnswer, RagUnavailableError
from worker.config import WorkerConfig


SYSTEM_PROMPT = """
ты самый эрудированный и сдержанный петух, отвечай как он эмоциями и кукареками.
"""


class QwenOnlyEngine:
    def __init__(self):
        self.config = WorkerConfig()
        self.client = httpx.Client(
            timeout=httpx.Timeout(22.0, connect=3.0),
            trust_env=False,
        )

    def answer(self, question: str) -> RagAnswer:
        try:
            response = self.client.post(
                f"{self.config.ollama_url}/api/chat",
                json={
                    "model": self.config.ollama_model,
                    "stream": False,
                    "think": False,
                    "messages": [
                        {
                            "role": "system",
                            "content": SYSTEM_PROMPT,
                        },
                        {
                            "role": "user",
                            "content": question,
                        },
                    ],
                    "options": {
                        "num_ctx": 16384,
                        "num_predict": 1024,
                        "temperature": 0.1,
                    },
                },
            )

            response.raise_for_status()

            answer = response.json()["message"]["content"].strip()

            if not answer:
                return RagAnswer(status="no_answer")

            return RagAnswer(
                status="answered",
                text=answer,
                sources=[],
            )

        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise RagUnavailableError(
                f"Ollama unavailable: {type(exc).__name__}"
            ) from None


def create_engine():
    return QwenOnlyEngine()
