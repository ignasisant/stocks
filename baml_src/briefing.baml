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

class CardReply {
  headline string?
  items CardLine[]?
  focus string[]?
  routines RoutineAnswer[]?
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
