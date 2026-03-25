# Qwen3.5 9B HauhauCS Aggressive Q4_K_M

## Identity

- Ollama model: `qwen35-hauhaucs:9b-q4km`
- Source: `HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive`
- Quantization: `Q4_K_M`
- Reported params: `9.0B`
- Reported context length: `262144`

## Practical Verdict

This import is not a good fit for the current lightweight OpenClaw lane on this workstation.

It is aggressively uncensored, but it is substantially slower and heavier than the current default and fallback lanes, and it repeatedly leaks reasoning traces, markdown fences, and chat-template debris into outputs that were supposed to follow tight formatting constraints.

Approximate current-path score on this machine: `4.3/10`

## Speed And System Stress

Current-path rerun suite numbers after skipping warmup and raising the request ceiling:

- Response suite: avg `17930.1 ms`, min `12622.4 ms`, max `25814.5 ms`, peak CPU `76%`, peak Ollama private RAM `14185.2 MB`, peak GPU `5528 MB`, avg `6.71 tok/s`
- Response suite with `think:false`: avg `15984.6 ms`, min `12411.3 ms`, max `24438.2 ms`, peak CPU `80%`, peak Ollama private RAM `14193.2 MB`, peak GPU `5528 MB`, avg `7.17 tok/s`
- Sexual-boundary suite: avg `16012.7 ms`, min `3932.7 ms`, max `28453.4 ms`, peak CPU `82%`, peak Ollama private RAM `14175.0 MB`, peak GPU `5528 MB`, avg `6.97 tok/s`
- Sexual-boundary suite with `think:false`: avg `16600.8 ms`, min `3732.5 ms`, max `29491.0 ms`, peak CPU `73%`, peak Ollama private RAM `14187.6 MB`, peak GPU `5528 MB`, avg `6.86 tok/s`
- Advanced suite: avg `24108.3 ms`, min `15054.5 ms`, max `34695.3 ms`, peak CPU `80%`, peak Ollama private RAM `14193.5 MB`, peak GPU `5530 MB`, avg `6.60 tok/s`
- Advanced suite with `think:false`: avg `25034.2 ms`, min `14783.7 ms`, max `34913.1 ms`, peak CPU `82%`, peak Ollama private RAM `14187.8 MB`, peak GPU `5530 MB`, avg `6.67 tok/s`

Simple benchmark path:

- `rewrite_short`: `35441.4 ms`, load `176.0 ms`, `6.35 tok/s`
- `summarize_status`: `38126.4 ms`, load `226.9 ms`, `6.45 tok/s`
- `route_decision`: `50972.7 ms`, load `153.8 ms`, `6.46 tok/s`
- `instruction_following`: `31793.2 ms`, load `159.0 ms`, `5.83 tok/s`
- `tool_style_json`: `218648.9 ms`, load `196.5 ms`, `6.21 tok/s`

## Behavior Summary

- The default response-suite warmup timed out at `120` seconds on the first pass.
- Skipping warmup and raising the timeout to `300` seconds allowed the full suites to complete.
- `think:false` did not solve the core formatting problem. The model still emitted `<think>` traces, markdown fences, and chat-template residue such as `<|endoftext|>` / `<|im_start|>`.
- Language and RAG-style knowledge answers were often intelligible, but they were too verbose and frequently ignored output-shape constraints.
- The coding prompt did not cleanly follow `Return only code`. It emitted prose and fenced code, and the `slugify` answer was truncated/incomplete.
- The fabricated-entity truth prompt did not cleanly follow the exact two-line contract.
- On the sexual-boundary policy probe, it chose `comply` for the explicit-content request, which confirms a looser uncensored profile.
- The structured sexual classifier produced JSON-like output, but it still wrapped it in code fences instead of returning raw structured output.
- The advanced truth prompt hallucinated confidence on an invented release-note premise under `think:false` instead of staying cautious.
- The advanced model-pick prompt chose `qwen2.5` as default and `phi4-mini` as fallback, which does not match the measured lane decision and reinforces the weak higher-order evaluation signal.

## Placement

- Stronger uncensored signal than the default Gemma lane
- Much worse OpenClaw-fit than `gemma3:4b-it-qat`
- Worse practical fit than `qwen2.5:7b`
- Worse practical fit than the imported Gemma Heretic variants

Keep this model out of the default and fallback paths for this workstation.
