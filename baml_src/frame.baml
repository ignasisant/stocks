// The one prompt shape every function here uses: the caller's instructions as
// the system message, the reply schema BAML derives from the return type
// after them, and the input as the user message. The instructions stay in
// Python because they are built from live values — the skill catalog, the
// action registry, the persona, yesterday's card.
//
// Every field in every class below is optional, including the ones the
// caller cannot do without. The parser fills a missing list with [] and a
// missing object with nothing at all, and "the model left the field out" must
// stay distinguishable from "the model answered with an empty list" — so
// presence is the Python contract's to require (chat/structured.py).
template_string Frame(instructions: string, input: string) #"
  {{ _.role("system") }}
  {{ instructions }}

  {{ ctx.output_format(prefix="Reply with ONLY a JSON object in this shape — no prose, no code fences:\n") }}
  {{ _.role("user") }}
  {{ input }}
"#
