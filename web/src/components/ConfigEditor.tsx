import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";

// Formulaire d'un fichier de config/, pré-rempli avec ses valeurs actuelles. Seules les valeurs existantes
// changent ; le serveur valide le fichier avant de l'écrire et conserve ses commentaires.

type Data = Record<string, unknown>;
const isObject = (v: unknown): v is Data => typeof v === "object" && v !== null && !Array.isArray(v);

function setAt(data: Data, path: string[], value: unknown): Data {
  const [head, ...rest] = path;
  return { ...data, [head]: rest.length ? setAt(data[head] as Data, rest, value) : value };
}

interface Props {
  file: string; data: Data; informative: Record<string, string>; onSaved: (message: string) => void; onClose: () => void;
}

export function ConfigEditor({ file, data, informative, onSaved, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [form, setForm] = useState<Data>(data);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => { ref.current?.showModal(); }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const values = Object.fromEntries(Object.entries(form).filter(([k]) => k !== "version" && !(k in informative)));
      const r = await api.updateConfig(file, values);
      onSaved([
        `config/${file} enregistré.`,
        r.values_changed && "Pondération modifiée : les évaluations des gaps sur les valeurs sont périmées, à refaire "
          + "(skill values-alignment) avant la Gate 1.",
        r.config_changed && "Nouvelle empreinte de configuration : les prochaines recherches l'enregistreront.",
      ].filter(Boolean).join(" "));
      ref.current?.close();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const field = (path: string[], value: unknown): ReactNode => {
    const key = path.join(".");
    const name = path.at(-1)!;
    const set = (v: unknown) => setForm((f) => setAt(f, path, v));
    if (isObject(value)) {
      return (
        <fieldset key={key}>
          <legend>{name}</legend>
          {Object.entries(value).map(([k, v]) => field([...path, k], v))}
        </fieldset>
      );
    }
    if (typeof value === "boolean") {
      return <label key={key} className="check"><input type="checkbox" checked={value}
        onChange={(e) => set(e.target.checked)} /> {name}</label>;
    }
    if (typeof value === "number") {
      return <label key={key}>{name}<input type="number" step="any" value={value} required
        onChange={(e) => set(e.target.value === "" ? 0 : Number(e.target.value))} /></label>;
    }
    if (Array.isArray(value)) {
      return <ListField key={key} name={name} value={value} onChange={set} />;
    }
    const text = String(value ?? "");
    return (
      <label key={key}>{name}
        {text.length > 60 || text.includes("\n")
          ? <textarea rows={3} value={text.trim()} onChange={(e) => set(e.target.value)} />
          : <input value={text} onChange={(e) => set(e.target.value)} />}
      </label>
    );
  };

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dh"><b>Modifier config/{file}</b><button onClick={() => ref.current?.close()}>Fermer</button></div>
      <form className="form config-form" onSubmit={submit}>
        <p className="sub">Pré-rempli avec les valeurs actuelles. Le fichier est validé avant d'être écrit ; ses
          commentaires sont conservés.</p>
        {Object.entries(form).filter(([k]) => k !== "version").map(([k, v]) => k in informative ? (
          <fieldset key={k} className="readonly">
            <legend>{k} <span className="sub">— informatif, non lu par le code</span></legend>
            <p className="sub">{informative[k]}</p>
            <pre className="raw">{Object.entries(v as Data).map(([n, x]) => `${n}: ${String(x)}`).join("\n")}</pre>
          </fieldset>
        ) : field([k], v))}
        {error && <p className="err-msg">✗ {error}</p>}
        <button className="act" type="submit" disabled={busy}>{busy ? "Enregistrement…" : "Enregistrer"}</button>
      </form>
    </dialog>
  );
}

// Liste de valeurs simples, saisie séparée par des virgules ; nombres si la liste d'origine en contient.
function ListField({ name, value, onChange }: { name: string; value: unknown[]; onChange: (v: unknown[]) => void }) {
  const numeric = value.length > 0 && value.every((v) => typeof v === "number");
  const [text, setText] = useState(value.join(", "));
  const parse = (t: string) => t.split(",").map((s) => s.trim()).filter(Boolean).map((s) => (numeric ? Number(s) : s));
  return (
    <label>{name} <span className="sub">(séparés par des virgules)</span>
      <input value={text} onChange={(e) => { setText(e.target.value); onChange(parse(e.target.value)); }} />
    </label>
  );
}
