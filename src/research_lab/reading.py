"""Couverture de lecture du texte intégral : quelles pages ont été affichées par `fulltext show`.

Leçon de l'agent researcher (2026-11-23) : contrôler que les extraits cités existent ne dit pas ce qui a été
lu. L'état de l'art du projet decentralized-ai-governance annonçait 53 publications « lues en texte
intégral » alors que seuls le résumé, l'introduction, la conclusion et les limites l'avaient été. Chaque page
affichée est donc enregistrée, et le texte principal (jusqu'au début des références) doit l'avoir été en
entier. Une page affichée n'est pas la preuve qu'elle a été comprise : c'est le minimum vérifiable.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# Titre de bibliographie seul sur sa ligne, éventuellement numéroté (« 7 References », « VIII. REFERENCES »).
_REFERENCES_RE = re.compile(
    r"^[ \t]*(?:[0-9]+\.?|[IVXL]+\.)?[ \t]*(references|bibliography|références|bibliographie|literature cited)"
    r"[ \t]*:?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def references_start(pages: list[str]) -> int | None:
    """Page (numérotée à partir de 1) où commence la bibliographie, ou None si elle n'est pas repérée.

    Le titre n'est cherché qu'à partir de la deuxième page et après le premier tiers du texte, pour ne pas
    prendre une table des matières pour la bibliographie.
    """
    first = max(2, len(pages) // 3 + 1)
    for number in range(first, len(pages) + 1):
        if _REFERENCES_RE.search(pages[number - 1]):
            return number
    return None


def format_ranges(numbers: Iterable[int]) -> str:
    """[1, 2, 3, 5, 7, 8] -> « 1-3, 5, 7-8 »."""
    ranges: list[str] = []
    ordered = sorted(set(numbers))
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1] == ordered[j] + 1:
            j += 1
        ranges.append(str(ordered[i]) if i == j else f"{ordered[i]}-{ordered[j]}")
        i = j + 1
    return ", ".join(ranges)


@dataclass
class Coverage:
    paper_id: str
    page_count: int
    # Dernière page du texte principal : la page où commencent les références (elle porte souvent la fin
    # de la conclusion), ou la dernière page si les références ne sont pas repérées.
    main_end: int
    references_from: int | None
    read: set[int] = field(default_factory=set)

    @property
    def unread_main(self) -> list[int]:
        return [n for n in range(1, self.main_end + 1) if n not in self.read]

    @property
    def complete(self) -> bool:
        return not self.unread_main

    def summary(self) -> str:
        main_read = self.main_end - len(self.unread_main)
        text = f"{main_read}/{self.main_end} pages du texte principal lues"
        if self.unread_main:
            text += f" (non lues : {format_ranges(self.unread_main)})"
        if self.references_from:
            text += f" ; références à partir de la page {self.references_from}"
        return text

    def as_dict(self) -> dict:
        return {
            "page_count": self.page_count,
            "main_pages": self.main_end,
            "references_from": self.references_from,
            "pages_read": sorted(self.read),
            "unread_main_pages": self.unread_main,
            "complete": self.complete,
        }


def coverage(paper_id: str, pages: list[str], read: set[int]) -> Coverage:
    start = references_start(pages)
    return Coverage(
        paper_id=paper_id,
        page_count=len(pages),
        main_end=start or len(pages),
        references_from=start,
        read={n for n in read if 1 <= n <= len(pages)},
    )


def check_reading(coverages: Iterable[Coverage], project_id: str) -> list[str]:
    """Erreurs : publications incluses dont le texte intégral est disponible mais pas lu en entier."""
    errors = []
    for c in coverages:
        if not c.complete:
            unread = c.unread_main
            errors.append(
                f"{c.paper_id} : texte intégral disponible, pages du texte principal jamais affichées : "
                f"{format_ranges(unread)} (`fulltext show {project_id} {c.paper_id} --pages {unread[0]}-{c.main_end}`)"
            )
    return errors


def outline(pages: list[str], read: set[int], width: int = 90) -> list[dict]:
    """Plan du texte : pour chaque page, sa taille, son statut de lecture et sa première ligne."""
    start = references_start(pages)
    rows = []
    for number, text in enumerate(pages, start=1):
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        rows.append({
            "page": number,
            "chars": len(text),
            "read": number in read,
            "references": start is not None and number >= start,
            "first_line": first_line[:width],
        })
    return rows


def select_pages(pages: list[str], first: int, last: int, max_chars: int) -> list[int]:
    """Pages de `first` à `last` à afficher sans dépasser `max_chars` ; la première est toujours affichée."""
    selected: list[int] = []
    total = 0
    for number in range(first, last + 1):
        size = len(pages[number - 1])
        if selected and total + size > max_chars:
            break
        selected.append(number)
        total += size
    return selected


def parse_page_range(value: str, page_count: int) -> tuple[int, int]:
    """« 3 » ou « 3-7 » -> (3, 7), borné au nombre de pages."""
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", value)
    if not match:
        raise ValueError(f"plage de pages invalide : {value!r} (attendu N ou N-M)")
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if not 1 <= first <= last:
        raise ValueError(f"plage de pages invalide : {value!r}")
    if first > page_count:
        raise ValueError(f"le texte a {page_count} pages")
    return first, min(last, page_count)
