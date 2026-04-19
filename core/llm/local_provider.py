"""
Local HuggingFace model provider.

Loaded lazily on first use and cached as a singleton so the model is only
downloaded/loaded once per container lifetime.

Controlled by .env:
    LOCAL_MODEL=Qwen/Qwen2.5-Coder-14B-Instruct
    LOCAL_MODEL_DEVICE=auto          # auto | cuda | cpu
    LOCAL_MODEL_LOAD_IN_4BIT=true    # 4-bit quantisation (fits 14B in ~7 GB VRAM)
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None
_lock = asyncio.Lock()


async def _ensure_loaded() -> None:
    """Load model + tokenizer once; subsequent calls are instant."""
    global _model, _tokenizer

    if _model is not None:
        return

    async with _lock:
        if _model is not None:          # double-checked locking
            return

        from config import settings     # avoid circular import at module level

        model_name = settings.local_model
        load_4bit = settings.local_model_load_in_4bit
        device = settings.local_model_device

        logger.info("Loading local model %s (4bit=%s, device=%s) …", model_name, load_4bit, device)

        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
            import torch

            logger.info("Downloading/loading tokenizer for %s…", model_name)
            _tokenizer = await asyncio.to_thread(
                AutoTokenizer.from_pretrained,
                model_name,
                trust_remote_code=True,
            )
            logger.info("Tokenizer loaded. Now loading model weights into GPU (this can take 5-10 min on first load)…")

            kwargs: dict = {
                "trust_remote_code": True,
                "device_map": device,
            }

            if load_4bit:
                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                )
            else:
                kwargs["torch_dtype"] = "auto"

            _model = await asyncio.to_thread(
                AutoModelForCausalLM.from_pretrained,
                model_name,
                **kwargs,
            )

            logger.info("Local model %s loaded successfully.", model_name)

        except ImportError as e:
            raise RuntimeError(
                "transformers / bitsandbytes not installed. "
                "Make sure LOCAL provider deps are in requirements.txt and rebuild."
            ) from e


def get_status() -> dict:
    """Return current load state of the local model (no side-effects)."""
    if _model is None:
        return {"state": "not_loaded", "model": None, "vram_gb": None}
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / 1e9
            reserved  = torch.cuda.memory_reserved()  / 1e9
            vram_info = f"{allocated:.1f} GB allocated / {reserved:.1f} GB reserved"
        else:
            vram_info = "CPU only"
    except Exception:
        vram_info = "unknown"
    from config import settings
    return {"state": "loaded", "model": settings.local_model, "vram_gb": vram_info}


async def generate(prompt: str, max_new_tokens: int = 8192) -> str:
    """Run inference with the local model (single-turn). Returns the generated text."""
    await _ensure_loaded()
    messages = [{"role": "user", "content": prompt}]
    return await generate_chat(messages, max_new_tokens=max_new_tokens)


async def generate_chat(messages: list[dict], max_new_tokens: int = 4096) -> str:
    """Run chat inference with the local model using a messages list. Returns the assistant reply."""
    await _ensure_loaded()

    def _run() -> str:
        import torch
        text = _tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = _tokenizer([text], return_tensors="pt").to(_model.device)

        with torch.no_grad():
            generated_ids = _model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,           # greedy — deterministic, best for code
                pad_token_id=_tokenizer.eos_token_id,
            )

        output_ids = generated_ids[0][len(inputs.input_ids[0]):].tolist()
        return _tokenizer.decode(output_ids, skip_special_tokens=True)

    return await asyncio.to_thread(_run)
