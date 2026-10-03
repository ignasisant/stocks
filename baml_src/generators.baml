// The Python client is generated into src/stocks/baml_client and committed:
// `uv run baml-cli generate` after editing anything in baml_src, and CI fails
// when the two drift. The version must match the baml-py pin in pyproject.toml
// exactly — the generated client refuses to import under any other.
generator target {
  output_type "python/pydantic"
  output_dir "../src/stocks"
  version "0.226.2"
  default_client_mode sync
}
