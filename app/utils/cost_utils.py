from dataclasses import dataclass, field
from typing import Literal

ModelName = Literal['deepgram', 'gpt-4.1-mini', 'gpt-4o']

PRICES: dict[str, dict[str, float]] = {
    'deepgram': {
        'per_min_audio': 0.0043,
    },
    'gpt-4.1-mini': {
        'in_token_usd_per_million': 0.15,
        'out_token_usd_per_million': 0.60,
    },
    'gpt-4o': {
        'in_token_usd_per_million': 2.50,
        'out_token_usd_per_million': 10.00,
    },
}


@dataclass
class CostItem:
    model: str
    minutes_audio: float = 0.0
    in_tokens: int = 0
    out_tokens: int = 0

    def cost_usd(self) -> float:
        model_prices = PRICES.get(self.model, {})

        if self.minutes_audio > 0:
            return self.minutes_audio * model_prices.get('per_min_audio', 0.0)

        cost_in = (self.in_tokens / 1_000_000) * model_prices.get('in_token_usd_per_million', 0.0)
        cost_out = (self.out_tokens / 1_000_000) * model_prices.get('out_token_usd_per_million', 0.0)
        return cost_in + cost_out


@dataclass
class CostTracker:
    """Acumula costos de transcripción y LLM por audio."""

    items: dict[str, list[CostItem]] = field(default_factory=dict)

    def add_transcription(self, audio_key: str, model: str, minutes: float) -> None:
        self.items.setdefault(audio_key, []).append(
            CostItem(model=model, minutes_audio=minutes)
        )

    def add_llm_usage(self, audio_key: str, model: str, in_tokens: int, out_tokens: int) -> None:
        self.items.setdefault(audio_key, []).append(
            CostItem(model=model, in_tokens=in_tokens, out_tokens=out_tokens)
        )

    def get_summary(self, audio_key: str) -> dict:
        parts = self.items.get(audio_key, [])

        total_usd = 0.0
        by_model: dict[str, float] = {}
        tokens: dict[str, dict[str, int]] = {}
        minutes: dict[str, float] = {}

        for part in parts:
            cost = part.cost_usd()
            total_usd += cost
            by_model[part.model] = by_model.get(part.model, 0.0) + cost

            if part.in_tokens > 0 or part.out_tokens > 0:
                if part.model not in tokens:
                    tokens[part.model] = {'in': 0, 'out': 0}
                tokens[part.model]['in'] += part.in_tokens
                tokens[part.model]['out'] += part.out_tokens

            if part.minutes_audio > 0:
                minutes[part.model] = minutes.get(part.model, 0.0) + part.minutes_audio

        return {
            'total_usd': round(total_usd, 6),
            'by_model': {k: round(v, 6) for k, v in by_model.items()},
            'tokens': tokens,
            'minutes': {k: round(v, 2) for k, v in minutes.items()},
        }

    def get_total_cost(self) -> float:
        total = sum(self.get_summary(key)['total_usd'] for key in self.items)
        return round(total, 6)