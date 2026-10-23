/**
 * "Type your positions instead": the way in for someone whose broker has no
 * importer. The chat already books trades told in plain words, so this only
 * opens it with the start of such a sentence in the field, never sent
 * (`fillAssistant`). One more way to add trades, not a feature of its own.
 */

import { fillAssistant } from "../shell/assistant";
import { useT } from "../shell/i18n";

export function TypeInstead({ className = "ag-btn" }: { className?: string }) {
  const t = useT();
  return (
    <button
      className={className}
      onClick={() => fillAssistant(t("import.type_prompt"))}
      type="button"
    >
      {t("import.type_button")}
    </button>
  );
}
