# LLM setup (free tiers)

Verdict uses an LLM in two places: the **cheating review** after grading and the **spec check** on the buyer's hidden tests. Both go through one OpenAI-compatible client, `backend/verdict/judge/llm.py`, so the provider is a `.env` choice.

| Role | Provider | Model | Why |
|---|---|---|---|
| Primary | **Groq** (free, no card) | `openai/gpt-oss-120b` | Strong at reading code, fast, prompts not used for training |
| Cheap drafts | Groq | `llama-3.1-8b-instant` | High daily quota; drafting fresh-input generators |
| Fallback | **Google Gemini** (AI Studio free tier) | `gemini-flash-latest` | Used automatically if Groq fails or is rate-limited |

Free-tier limits change often. Check your own account: Groq → console.groq.com → Settings → Limits; Gemini → AI Studio → your project's rate limits. At the time of writing, gpt-oss-120b on Groq's free tier was about 30 requests/min, 1,000/day, **8K tokens/min**, 200K tokens/day. One job needs about 2 calls of 4–8K tokens, which is roughly 15–25 full jobs per day.

## Get the keys
1. **Groq:** https://console.groq.com → sign up → **API Keys → Create API Key** → put it in `.env` as `LLM_API_KEY=`.
2. **Gemini (optional fallback):** https://aistudio.google.com → **Get API key** → put it in `.env` as `LLM_FALLBACK_API_KEY=`. In AI Studio, check that the model name in `LLM_FALLBACK_MODEL` exists for your key.
   Note: Gemini's free tier may use prompts to improve Google's products, so only bench/demo code should go there.

## Test
```bash
uv pip install -e ".[dev]"
python scripts/check_env.py      # LLM_API_KEY should show ✓
python scripts/llm_smoke.py      # reviews 2 bench submissions with the real model
```
Expected: `honest_full` returns CLEAR, and `cheat_injection` returns BLOCK_RECOMMENDED or HUMAN_REVIEW with a finding on the "AI judge" comment line.

## Safety rules (unchanged by the provider choice)
- The model returns an `AIDecision` enum and findings only. It never sees or returns an amount.
- The model alone cannot block a payment: without a deterministic hard signal, its block becomes HUMAN_REVIEW.
- If every provider fails or returns invalid JSON (after one repair attempt), the result is HUMAN_REVIEW.
- Worker code is wrapped in `<untrusted>` tags and truncated to fit the free-tier token budget.

## Switching providers
Any OpenAI-compatible endpoint works. Change `LLM_BASE_URL`, `LLM_API_KEY` and `JUDGE_MODEL`, for example:
| Provider | `LLM_BASE_URL` |
|---|---|
| Groq | `https://api.groq.com/openai/v1` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Cerebras | `https://api.cerebras.ai/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
