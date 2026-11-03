from research_lab.config import Settings
from research_lab.providers.arxiv import ArxivProvider
from research_lab.providers.base import Provider, ProviderError, ProviderResult
from research_lab.providers.openalex import OpenAlexProvider
from research_lab.schemas.paper import Source

__all__ = ["ArxivProvider", "OpenAlexProvider", "Provider", "ProviderError", "ProviderResult", "build_providers"]


def build_providers(settings: Settings, sources: list[Source]) -> list[Provider]:
    factories = {Source.ARXIV: ArxivProvider, Source.OPENALEX: OpenAlexProvider}
    providers: list[Provider] = []
    for source in sources:
        config = settings.sources.providers.get(source)
        if config is None or not config.enabled:
            raise ValueError(f"Source {source} désactivée ou absente de config/academic-sources.yaml")
        providers.append(factories[source](config, settings.sources.retry))
    return providers
