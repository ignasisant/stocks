/**
 * "Import with the assistant": the same statement, read in the chat drawer.
 *
 * The drawer imports files too — the paperclip or a drop takes a statement,
 * reads it with this page's reader (parsers first, the model for a format no
 * parser knows) and shows the rows before anything is written. Nothing on
 * this page said so.
 *
 * A file already staged goes as it is and leaves the page (`onHanded`), so
 * the same rows are not waiting behind two import buttons; with none, the
 * button picks one. Drawn only where an assistant takes files (an account's
 * drawer, not a guest's).
 */

import { useRef } from "react";
import { attachAssistant, useAssistantTakesFiles } from "../../shell/assistant";
import { useT } from "../../shell/i18n";
import { acceptOf, type Staged } from "./api";
import { Way } from "./Way";

/** A staged statement back as the file it was. */
export function fileOf(staged: Staged): File {
  const binary = atob(staged.content);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new File([bytes], staged.filename);
}

export function ToAssistant({
  accepts,
  staged,
  onHanded,
}: {
  accepts: string[];
  staged: Staged | null;
  onHanded: () => void;
}) {
  const t = useT();
  const picker = useRef<HTMLInputElement>(null);
  if (!useAssistantTakesFiles()) return null;
  return (
    <>
      <Way
        accent
        icon="chat"
        onClick={() => {
          if (!staged) {
            picker.current?.click();
            return;
          }
          attachAssistant(fileOf(staged));
          onHanded();
        }}
        sub={t("import.assistant_help")}
        title={t("import.assistant_button")}
        trail="panel"
      />
      <input
        accept={acceptOf(accepts)}
        aria-hidden="true"
        className="ag-sr"
        onChange={(event) => {
          const picked = event.target.files?.[0];
          event.target.value = "";
          if (picked) attachAssistant(picked);
        }}
        ref={picker}
        tabIndex={-1}
        type="file"
      />
    </>
  );
}
