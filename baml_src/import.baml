// Reading broker files nobody wrote a parser for (portfolio/llm_map.py) and
// naming the instruments in them (portfolio/instruments.py).

class Columns {
  date int?
  ticker int?
  action int?
  quantity int?
  price int?
  amount int?
  currency int?
  fee int?
  note int?
}

enum AssetClass {
  Crypto @alias("crypto")
  Securities @alias("securities")
}

class ColumnMap {
  header_row int? @description("index of the row holding the column headers")
  columns Columns? @description("0-based column index per field, or null for the whole object when the file cannot be mapped")
  date_format string? @description("strftime format of the date cells, e.g. %d/%m/%Y")
  decimal string? @description("the decimal separator, '.' or ','")
  thousands string? @description("the thousands separator, or an empty string")
  asset_class AssetClass?
  action_map map<string, string>? @description("the exact text in the action column -> buy, sell, dividend, fee, split or capital")
}

function MapColumns(instructions: string, input: string) -> ColumnMap {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

enum DocumentKind {
  Trades @alias("trades")
  Positions @alias("positions")
  Neither @alias("none")
}

// Optional all the way down, and no field the parser can fail to coerce, so
// one unreadable record reaches Python — which reports it as skipped —
// instead of taking the whole page's list with it. Figures are
// `float | string` because as plain `float` the parser reads a European
// "0,25" as 25; a string comes through untouched for llm_map to judge.
class StatementRow {
  date string? @description("YYYY-MM-DD")
  ticker string? @description("symbol or ISIN")
  action string? @description("buy, sell, dividend, fee, split or capital")
  quantity (float | string)? @description("a plain number")
  price (float | string)? @description("a plain number")
  currency string? @description("3-letter code")
  fee (float | string)? @description("a plain number")
  note string? @description("short label, optional")
}

class StatementPage {
  kind DocumentKind?
  transactions StatementRow[]?
}

function ExtractStatement(instructions: string, input: string) -> StatementPage {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

function ResolveSymbols(instructions: string, input: string) -> map<string, string?> {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}

// Crypto exchange and wallet exports (portfolio/crypto_map.py): the layout
// and the role of each column. Python groups, values and books the rows.

enum CryptoLayout {
  Rows @alias("rows")
  Swaps @alias("swaps")
  Ledger @alias("ledger")
}

class CryptoColumns {
  date int?
  type int?
  subtype int?
  asset int?
  pair int?
  quantity int?
  price int?
  total int?
  quote int?
  fee int?
  fee_asset int?
  sent_quantity int?
  sent_asset int?
  received_quantity int?
  received_asset int?
  value int?
  value_currency int?
  group int?
  direction int?
  asset_class int?
  note int?
}

class CryptoMap {
  exchange string? @description("the platform's name, when the file shows it")
  layout CryptoLayout? @description("null when the file is not a crypto transaction list")
  header_row int? @description("index of the row holding the column headers")
  columns CryptoColumns? @description("0-based column index per role, null when absent")
  date_format string? @description("strftime format of the date cells, e.g. %Y-%m-%d %H:%M:%S")
  decimal string? @description("the decimal separator, '.' or ','")
  thousands string? @description("the thousands separator, or an empty string")
  type_map map<string, string>? @description("the exact text in the type column -> buy, sell, trade, convert, reward, receive, send, move, fee or ignore")
}

function MapCrypto(instructions: string, input: string) -> CryptoMap {
  client Wire
  prompt #"{{ Frame(instructions, input) }}"#
}
