import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props { title: string; text: string | null; onClose: () => void; raw?: boolean }

export function DocumentDialog({ title, text, onClose, raw = false }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dh"><b>{title}</b><button onClick={() => ref.current?.close()}>Fermer</button></div>
      <div className="doc">
        {text === null ? <p className="empty">Chargement…</p>
          : raw ? <pre className="raw">{text}</pre> : <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>}
      </div>
    </dialog>
  );
}
