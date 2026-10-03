// Every function needs a client, and this one is never called. BAML here only
// renders prompts (`b.request`) and parses replies (`b.parse`); the request
// itself goes out through stocks.web.llm.Provider, which owns the free chain,
// BYOK keys, quotas and prompt caching. The address is deliberately
// unroutable, so a call that bypassed Provider would fail rather than leak.
client<llm> Wire {
  provider "openai-generic"
  options {
    base_url "http://render.invalid/v1"
    model "render-only"
  }
}
