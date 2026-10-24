// The chat's classifier calls (web/chat_skills.py, web/chat_web.py,
// chat/tools.py). Cheap model, one JSON object, degrade to "no answer".

class SkillPick {
  skills string[]? @description("skill ids from the catalog")
}

function PickSkills(instructions: string, input: string) -> SkillPick {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

class QueryPlan {
  queries string[]? @description("web search queries; empty when none is needed")
}

function PlanQueries(instructions: string, input: string) -> QueryPlan {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

// Nothing in here can fail to coerce, because one item that does takes its
// whole list down with it in the parser — an enum `type` lost every alert as
// soon as two rules had a bad one. So `type` is text, and figures are
// `float | string`: as plain `float`, "1,5" reads as 15 (the comma taken for
// a thousands separator). chat/tools.py drops the rules it cannot read.
class AlertRule {
  type string? @description("above or below")
  price (float | string)?
}

// The same rules for an exit rule (journal criteria): `rule` is text and
// `level` a figure or text; chat/journal.py clean_rules drops what it cannot
// read.
class CriterionRule {
  rule string? @description("below, drawdown_cost, drawdown_high, weight_above, revenue_growth_below, gross_margin_below, operating_margin_below, ceo_change, guidance_cut or dividend_cut")
  level (float | string)? @description("a price for below, a percent for the price and fundamental rules, null for ceo_change, guidance_cut and dividend_cut")
  quarters int? @description("fundamental rules only: how many quarters in a row, 1 to 4")
}

// One field per argument any tool in chat/tools.py TOOLS reads. A new tool
// with a new argument adds it here too (tests/test_baml_contracts.py checks).
class ActionCall {
  action string? @description("the action name, or null when the message asks for no change")
  ticker string? @description("the symbol the action targets")
  tickers string[]? @description("every symbol, when the action targets several")
  alerts AlertRule[]?
  criteria CriterionRule[]?
  thesis string? @description("why the user holds it, in their words")
  tags string[]?
  name string?
  shares (float | string)? @description("a plain number")
  cost (float | string)? @description("a plain number")
  // The recorded-trade actions (chat/tools.py BOOK): which rows, in words,
  // and for an edit or a new row its values.
  broker string? @description("one lowercase word: degiro, ibkr, revolut")
  to_broker string? @description("the broker the shares moved to")
  date string? @description("YYYY-MM-DD")
  since string? @description("YYYY-MM-DD")
  until string? @description("YYYY-MM-DD")
  trade string? @description("buy, sell, dividend, fee, split, transfer_in or transfer_out")
  quantity (float | string)? @description("a plain number")
  price (float | string)? @description("a plain number")
  fee (float | string)? @description("a plain number")
  currency string? @description("ISO code, like EUR")
  to string? @description("the symbol to book the rows under instead")
  ids (int | string)[]? @description("row numbers the user quoted")
  new_date string? @description("YYYY-MM-DD")
  new_quantity (float | string)? @description("a plain number")
  new_price (float | string)? @description("a plain number")
  new_fee (float | string)? @description("a plain number")
}

function DetectAction(instructions: string, input: string) -> ActionCall {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

// The memory extraction (chat/learnings.py). Everything it proposes is
// checked in Python against the user's own words and the saved list
// (`learnings.lessons`); the parser only shapes the reply.
class LessonOp {
  op string? @description("add, update or delete")
  id string? @description("the saved item's id, for update and delete")
  kind string? @description("preference, goal, decision, constraint, context or routine")
  text string?
}

class LessonOps {
  ops LessonOp[]?
}

function ExtractLessons(instructions: string, input: string) -> LessonOps {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

// The weekly tidy-up of saved memories (chat/memory_review.py): changes
// proposed to the user, never made.
class ReviewOp {
  action string? @description("merge, drop or reword")
  ids string[]? @description("the saved items' ids it is about")
  text string? @description("merge and reword: the new wording")
  reason string? @description("one short sentence: why")
}

class ReviewOps {
  ops ReviewOp[]?
}

function ReviewMemories(instructions: string, input: string) -> ReviewOps {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

// The chat's input guard (chat/guard.py): is this message something an
// investing assistant is for? Fail-open, so every field has a safe default.
class ScopeVerdict {
  in_scope bool? @description("false only when clearly not for this assistant")
  refusal string? @description("when out of scope: one short sentence in the message's language")
}

function CheckScope(instructions: string, input: string) -> ScopeVerdict {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

// The eval's judge (chat/agent_judge.py): one answer read against its case's
// goals and the score rubrics. Offline only, never on a reader's turn.
class GoalJudged {
  n int @description("the goal's number")
  verdict string @description("met, not_met or unclear")
  why string? @description("one short sentence")
}

class ScoreJudged {
  id string @description("the score's id")
  value int? @description("1 to 5; null when it does not apply")
  why string? @description("one short sentence")
}

class AnswerJudged {
  goals GoalJudged[]
  scores ScoreJudged[]
}

function JudgeAnswer(instructions: string, input: string) -> AnswerJudged {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}
