# Script style guide (guion.md)

## Structure
1. **Gancho** (3–5 s, `title` card): what changes and for whom. One sentence.
2. **One scene per feature** (3–4 max): what it is → where it is → what it gives the user.
3. **Además** (`card` with items): everything else worth a mention, one line each.
4. **Cierre** (`outro`): where to find it / next step.

## Word budget — the script rules the duration
- Spanish narration ≈ 2.3–2.5 words/s → **60 s ≈ 135–140 words in total**, cards included.
- `release.py check` counts words against `max_duration × words_per_second × 0.92` (room for the lead,
  tail and crossfades). Over budget → cut words, never speed up the voice.
- A feature scene is usually 18–28 words (7–11 s).

## Language
- User language, not developer language: "mi cartera", "la ficha de la acción", not component, library,
  ticket, branch or class names.
- Short sentences, present tense, active voice. One idea per sentence.
- Name the UI exactly as the user sees it ("pestaña Envíos", "botón Exportar").
- Numbers and acronyms are written normally; pronunciation fixes go in `pronunciacion.yaml`, so the
  subtitles keep the written form.
- Audience is always the public: benefit first, no internal names, no backend detail. Never promise returns or tell anyone what to buy.

## What goes in
Classify every change from the PRs / feature description:
| class | in the video? |
|---|---|
| funcionalidad visible | own scene (top 3–4 by user impact) |
| mejora visible | own scene if strong, else "además" |
| corrección de error | "además" only if users noticed the bug |
| cambio interno (refactor, deps, tests, infra) | never, unless asked |
A backend change with no UI that users still benefit from → a `diagram` scene (plan B).

## guion.md template (shown to the user for approval)
```markdown
# <title> — guion (<N> palabras ≈ <S> s)

Fuentes: PR <links>. Entorno: <env> (guest, libro de ejemplo).

| # | Escena | Narración | En pantalla |
|---|---|---|---|
| 1 | Gancho | … | Tarjeta de título |
| 2 | <feature> | … | <page>, clic en …, zoom a … |
…
Fuera del vídeo: <internal changes left out and why>.
```

## notas_release.md template (post copy)
```markdown
# <title> — notas

Instagram / TikTok (≤40 palabras): <hook + benefit>. mybrainstock.com
Hashtags: #inversión #bolsa #cartera #finanzaspersonales
X (≤280): <one line + link>
LinkedIn (≤80 palabras): <what shipped and why it matters>

PRs: <owner/repo#n>, …
```
