// The ticker page's "Analyse with AI" brief (src/stocks/chat/brief.py): the
// notes a cheap model drafts once per company from its Yahoo profile, kept a
// month and read into every analysis of it. Questions, never figures — the
// Python contract drops any item that carries a number.

class Dossier {
  business string? @description("what it sells, to whom and how it earns, one sentence")
  lens string? @description("one industry skill id from the catalog, or empty")
  debates string[]? @description("two or three questions bulls and bears disagree on for this company")
  watch string[]? @description("two or three company-specific metrics or events to watch")
}

function DraftDossier(instructions: string, input: string) -> Dossier {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}
