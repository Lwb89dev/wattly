"""Provider parser registry.

Adding support for a new provider means subclassing
:class:`ProviderParser`, implementing ``fingerprint`` and ``parse``,
and appending the class to ``PARSERS`` — the pipeline picks the best
fingerprint automatically and falls back to the generic parser.
"""

from wattly.parsing.provider_parsers.base import ProviderParser, detect_parser
from wattly.parsing.provider_parsers.enel import EnelEnergiaParser
from wattly.parsing.provider_parsers.generic import GenericProviderParser
from wattly.parsing.provider_parsers.octopus import OctopusParser

PARSERS: list[type[ProviderParser]] = [
    EnelEnergiaParser,
    OctopusParser,
    GenericProviderParser,
]

__all__ = [
    "ProviderParser", "detect_parser", "GenericProviderParser",
    "EnelEnergiaParser", "OctopusParser", "PARSERS",
]
