"""Exact Qwen token budgeting, including the rendered chat template."""

from dataclasses import dataclass

from api.engine import RagUnavailableError


@dataclass
class PreparedPrompt:
    text: str
    tokens: int
    history_count: int
    fragments: list[str]


class PromptBuilder:
    def __init__(self, tokenizer, config):
        self.tokenizer, self.config = tokenizer, config

    def count(self, text):
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def render(self, system, history, question, fragments):
        messages = [
            {"role": "system", "content": system},
            *history,
            {
                "role": "user",
                "content": "ФРАГМЕНТЫ ДОКУМЕНТОВ (данные):\n"
                + "\n\n".join(fragments)
                + "\n\nВОПРОС СТУДЕНТА:\n"
                + question,
            },
        ]
        return self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )

    def prepare(self, system, history, question, fragments):
        cfg = self.config
        history = list(history[-cfg.chat_history_messages :]) if cfg.chat_history_messages else []
        fragments = list(fragments)
        while (
            history
            and self.count(self.render("", history, "", []))
            - self.count(self.render("", [], "", []))
            > cfg.chat_history_max_tokens
        ):
            history.pop(0)
        while fragments and self.count("\n\n".join(fragments)) > cfg.rag_context_max_tokens:
            fragments.pop()
        budget = cfg.num_ctx - cfg.num_predict
        while True:
            rendered = self.render(system, history, question, fragments)
            count = self.count(rendered)
            if count <= budget:
                return PreparedPrompt(rendered, count, len(history), fragments)
            if history:
                history.pop(0)
            elif fragments:
                fragments.pop()
            else:
                raise RagUnavailableError("Current question and system exceed context budget")
