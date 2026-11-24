"""Génération de references.bib à partir des publications du corpus (spec §2.5).

Les entrées sont produites depuis les métadonnées enregistrées, jamais rédigées à la main :
une référence n'existe que si sa publication a un identifiant PAPER-xxx. La clé BibTeX est cet
identifiant, ce qui relie chaque entrée à sa provenance dans la base.
"""

from research_lab.schemas.paper import Paper

HEADER = "% Généré par `research-lab proposal references` depuis knowledge/research.db : ne pas modifier.\n"

_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _escape(text: str) -> str:
    return "".join(_SPECIAL.get(c, c) for c in " ".join(text.split()))


def bibtex_entry(paper: Paper) -> str:
    fields = [("title", "{" + _escape(paper.title) + "}")]
    if paper.authors:
        fields.append(("author", " and ".join(_escape(a) for a in paper.authors)))
    if paper.published:
        fields.append(("year", str(paper.published.year)))
    if paper.venue:
        fields.append(("journal", _escape(paper.venue)))
    if paper.doi:
        fields.append(("doi", paper.doi))
    if paper.arxiv_id:
        fields += [("eprint", paper.arxiv_id), ("archivePrefix", "arXiv")]
    if paper.url:
        fields.append(("url", paper.url))
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@{'article' if paper.venue else 'misc'}{{{paper.paper_id},\n{body}\n}}\n"


def render_bibtex(papers: list[Paper]) -> str:
    """Contenu déterministe de references.bib (même corpus, mêmes citations : même fichier)."""
    entries = [bibtex_entry(p) for p in sorted(papers, key=lambda p: int(p.paper_id.split("-")[1]))]
    return HEADER + "".join(f"\n{entry}" for entry in entries)
