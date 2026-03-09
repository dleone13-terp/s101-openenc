"""
injest/base.py

Abstract base classes for the three pipeline stages and null implementations
for dry-runs and testing.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterator, Optional, TypedDict

enum

class FeatureDict(TypedDict):
    code: str            # S-101 feature type name, e.g. 'DepthArea'
    id: str              # unique feature identifier
    geometry: str        # 'Point' | 'Curve' | 'Surface'
    attributes: dict[str, Any]
    wkt: str             # WGS-84 WKT

@dataclass
class DrawingInstructions:
    """Parsed output of one HostPortrayalEmit call."""
    viewing_group: Optional[int] = None
    drawing_priority: Optional[int] = None
    scale_min: Optional[int] = None
    scale_max: Optional[int] = None
    # Area
    color_fill: Optional[str] = None           # ColorFill token

    # line / boundary
    line_style: Optional[str] = None           # LineStyle name (e.g. '_simple_')
    line_width: Optional[float] = None         # line width mm
    line_color: Optional[str] = None           # line colour token

class FeatureReader(ABC):
    """Yield feature dicts from an ENC data source."""

    @abstractmethod
    def read(self, path) -> Iterator[FeatureDict]: ...


class FeaturePortrayer(ABC):
    """Convert a feature dict into drawing instructions."""

    @abstractmethod
    def portray(self, feature: FeatureDict) -> list[DrawingInstructions]: ...


class FeatureWriter(ABC):
    """Persist a portrayed feature to a backing store."""

    @abstractmethod
    def write(self, feature: FeatureDict, dis: list[DrawingInstructions], cell_file: str) -> None: ...


class NullPortrayer(FeaturePortrayer):
    """Always returns empty DIs — for dry-runs and testing readers."""

    def portray(self, feature: FeatureDict) -> list[DrawingInstructions]:
        return []


class NullWriter(FeatureWriter):
    """Discards all features — for dry-runs and testing portrayers."""

    def write(self, feature: FeatureDict, dis: list[DrawingInstructions], cell_file: str) -> None:
        pass
