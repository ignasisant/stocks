// The Home briefing (chat/daily.py, chat/daily_analysis.py) and the sector
// screen's widening (chat/sector_ai.py). Every figure these print is audited
// in Python against the facts it was given; the parser only shapes them.

class CardLine {
  key string? @description("the key of the action the line is about, copied exactly")
  line string?
}

class RoutineAnswer {
  id string? @description("the `id` of the routine in the data, copied exactly")
  answer string?
}

// The reader's own brief: one section per thing it asks for, in its order.
class BriefSection {
  asks int[]? @description("the `n` of the brief lines this section answers")
  title string?
  lines CardLine[]?
}

// The Today page's computed sections (chat/today_sections.py): the rows are
// the app's, the model adds at most one remark per section.
class SectionNote {
  id string? @description("news, insiders or compare, copied exactly")
  note string?
}

class CardReply {
  headline string?
  items CardLine[]?
  focus string[]?
  routines RoutineAnswer[]?
  sections BriefSection[]?
  today SectionNote[]?
}

function WriteDailyCard(instructions: string, input: string) -> CardReply {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

class AnalysisPoint {
  title string?
  text string?
}

class AnalysisReply {
  verdict string?
  points AnalysisPoint[]?
}

function WriteAnalysis(instructions: string, input: string) -> AnalysisReply {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

class PeerPicks {
  symbols string[]? @description("Yahoo Finance symbols, exchange suffix included")
}

function ProposePeers(instructions: string, input: string) -> PeerPicks {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

// What each of the reader's daily routines needs fetched (chat/routine_plan.py).
// Planned once per wording; the vocabulary is checked in Python, and the
// symbols only ever become quote lookups.
class RoutinePlan {
  id string? @description("the `id` of the routine, copied exactly")
  markets string[]? @description("market groups to quote, from the listed ones; empty when the routine is not about markets")
  earnings string? @description("none, book, named or large")
  symbols string[]? @description("Yahoo Finance symbols of the instruments the routine names")
  topics string[]? @description("any of events, insiders, exits, news, filings, holders; empty when the routine asks for none")
}

class RoutinePlans {
  plans RoutinePlan[]?
}

function PlanRoutines(instructions: string, input: string) -> RoutinePlans {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

// The day's market read (chat/today_market.py): shared by every account,
// written once a morning by the cron from the market's own figures.
class MarketNote {
  topic string? @description("trend, sector, rates, macro or crypto")
  line string?
}

class MarketReply {
  headline string?
  lines MarketNote[]?
}

function WriteMarketDay(instructions: string, input: string) -> MarketReply {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}
