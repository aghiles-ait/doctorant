"""Vérification qu'un extrait cité figure réellement dans le texte d'une publication (Q2, spec §8).

Le texte extrait d'un PDF diffère de sa forme lue : coupures de mots en fin de ligne
(« Respon-\\nsible »), ligatures (« ﬁ »), accents décomposés (« J´er´emy »), espaces perdus.
La comparaison porte donc sur une clé réduite aux lettres et chiffres, sans casse ni accents.
"""

import unicodedata


def match_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if c.isalnum()).casefold()


def quote_length(quote: str) -> int:
    """Longueur significative d'un extrait : nombre de lettres et chiffres."""
    return len(match_key(quote))


def quote_in(quote: str, text: str) -> bool:
    key = match_key(quote)
    return bool(key) and key in match_key(text)


def find_quote_pages(quote: str, pages: list[str]) -> list[int]:
    """Numéros de page (à partir de 1) où figure l'extrait."""
    key = match_key(quote)
    if not key:
        return []
    return [number for number, text in enumerate(pages, start=1) if key in match_key(text)]
