# Chat model-switch probe (design D8b)

Run 2026-10-13 (local) through the live server (old code, explicit `model`), project `probe-routing` (deleted afterwards).

1. `perplexity_chat` send, new chat id 3, `model` `perplexity/sonar`: status completed, answer "Paris", continuation `new`, cost_usd 0.00013 (reported), 2012 ms.
2. `perplexity_chat` send, `chat_id` 3, `model` `openai/gpt-6-luna`: status completed, answer "Rome", continuation `chained`, cost_usd 0.00006 (reported), 1718 ms.

Conclusion: the API accepts a different model on a chained send (previous_response_id), so a tier may change per turn.
