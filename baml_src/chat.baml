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

// One field per argument any tool in chat/tools.py TOOLS reads. A new tool
// with a new argument adds it here too (tests/test_baml_contracts.py checks).
class ActionCall {
  action string? @description("the action name, or null when the message asks for no change")
  ticker string? @description("the symbol the action targets")
  alerts AlertRule[]?
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
