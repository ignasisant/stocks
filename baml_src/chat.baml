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
