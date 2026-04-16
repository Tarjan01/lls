# MVP Tech Debt

- Runtime image assets currently keep a placeholder-render fallback in [reverse_detective/renderer.py](/d:/lls/reverse_detective/renderer.py) because the current `crs`/Codex-compatible provider used by `config.toml` exposes live scene text generation but does not expose a working OpenAI-compatible image generation route. Real image rendering works only when the configured provider supports either the Responses `image_generation` tool or the Images API.
