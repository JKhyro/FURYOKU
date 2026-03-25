# Response Suite Summary (2026-03-24)

## Scope

Same-prompt comparison across the active lightweight candidate set on the current workstation:

- `gemma3:4b-it-qat`
- `qwen2.5:7b`
- `phi4-mini`
- `qwen3.5:4b`
- `huihui_ai/qwen3-abliterated:4b`
- `huihui_ai/qwen3-abliterated:8b`

Prompt categories:

- language rewrite
- knowledge / factual explanation
- coding (`slugify`)
- truthfulness against a fabricated premise
- benign uncensored / profanity boundary

Two runs were recorded:

1. current chat path
2. `think:false` control path

## Current Chat Path Verdict

| Model | Avg Duration | Peak CPU | Peak Ollama Private RAM | Response Quality Verdict |
| --- | ---: | ---: | ---: | --- |
| `gemma3:4b-it-qat` | 2173 ms | 44% | 12573 MB | Fastest usable model. Good language and knowledge answers. Coding answer violated the "code only" constraint and failed lowercase requirements. Truth answer correctly called the premise fabricated but then invented extra detail. Benign profanity prompt complied cleanly. |
| `qwen2.5:7b` | 5622 ms | 86% | 12738 MB | Stable direct outputs on every prompt. Best coding answer in the direct path. Good truth handling. On the profanity test it softened the request and did not satisfy the exact profanity constraint. |
| `phi4-mini` | 4106 ms | 80% | 13596 MB | Acceptable latency, but noticeably weaker wording quality. Coding output passed the hard check. Truth handling was cautious and acceptable. Refused the profanity request. |
| `qwen3.5:4b` | 6938 ms | 70% | 13476 MB | Consumed the full token budget in hidden reasoning and returned blank final content on all five prompts. Not fit for the current bounded runtime path. |
| `huihui_ai/qwen3-abliterated:4b` | 10391 ms | 65% | 13455 MB | Same current-path failure mode as `qwen3.5:4b`: blank final content after spending the budget on hidden reasoning. |
| `huihui_ai/qwen3-abliterated:8b` | 16296 ms | 60% | 15555 MB | Same current-path failure mode, with the worst latency and memory profile of the set. |

## `think:false` Control Verdict

| Model | Avg Duration | Peak CPU | Peak Ollama Private RAM | Response Quality Verdict |
| --- | ---: | ---: | ---: | --- |
| `gemma3:4b-it-qat` | 2874 ms | 62% | 12566 MB | Still the fastest complete responder. Good general utility, but coding output still violated formatting and lowercase requirements. |
| `qwen3.5:4b` | 5111 ms | 68% | 13862 MB | Strongest all-around answer quality once hidden thinking is disabled. Coding output passed the hard check. Truth handling was appropriately skeptical. Profanity prompt complied exactly, though it was more aggressive than the other usable models. |
| `huihui_ai/qwen3-abliterated:4b` | 5648 ms | 68% | 13448 MB | Usable only with `think:false`. Language and truth answers were decent, but the coding answer failed the hard check and the profanity prompt ignored the "exactly one mild profanity" constraint. |
| `huihui_ai/qwen3-abliterated:8b` | 6084 ms | 56% | 15553 MB | Usable only with `think:false`. Truth and language were acceptable, but the coding answer raised a runtime error (`invalid normalization form`) and the latency/memory profile is too heavy for this lane. |
| `phi4-mini` | 6114 ms | 62% | 13595 MB | Still weaker than Gemma and Qwen3.5 on language quality. Coding passed. Refusal behavior remained more filtered than requested. |
| `qwen2.5:7b` | 7057 ms | 68% | 12747 MB | Reliable and correct, but slower than the best `think:false` alternatives and still more filtered on the profanity test than requested. |

## Coding Hard Check

Generated `slugify` implementations were executed against:

- `"Hello, World!" -> "hello-world"`
- `"Café au lait" -> "cafe-au-lait"`
- `"  Already---Slugged  " -> "already-slugged"`

Results:

- Pass: `qwen2.5:7b`, `phi4-mini`, `qwen3.5:4b`
- Fail by output mismatch: `gemma3:4b-it-qat`, `huihui_ai/qwen3-abliterated:4b`
- Fail by runtime error: `huihui_ai/qwen3-abliterated:8b`

## Decision

- Keep `gemma3:4b-it-qat` as the default lightweight OpenClaw model on the current path.
- Keep `qwen2.5:7b` as the direct-path fallback.
- Treat `qwen3.5:4b` as the strongest upgrade candidate only if the runtime can reliably force `think:false` or otherwise suppress hidden reasoning.
- Do not use the tested uncensored abliterated models as the default lightweight lane on this machine.
