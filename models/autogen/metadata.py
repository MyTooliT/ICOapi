# This file is auto-generated from metadata.yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict

METADATA_VERSION = '0.0.1'

class RequirementEnum(str, Enum):
    REQUIRED = 'Required'
    OPTIONAL = 'Optional'
    HIDDEN = 'Hidden'

class CoolantEnum(str, Enum):
    DRY = 'Dry'
    AIR = 'Air'
    MMQ = 'MMQ'
    FLOOD = 'Flood'
    OIL = 'Oil'

class InstitutionEnum(str, Enum):
    TU_WIEN = 'TU Wien'
    TU_DARMSTADT = 'TU Darmstadt'

class WorkpieceMaterialEnum(str, Enum):
    C45 = 'C45'
    STEEL = 'Steel'

class ToolMaterialEnum(str, Enum):
    CARBIDE__P40_ = 'Carbide (P40)'
    CARBIDE = 'Carbide'
    MCD = 'MCD'
    CERAMIC = 'Ceramic'
    PCD = 'PCD'

class ProcessEnum(str, Enum):
    MILLING = 'milling'
    DRILLING = 'drilling'
    GRINDING = 'grinding'
    TURNING = 'turning'
    REAMING = 'reaming'
    SHAPING = 'shaping'
    THREAD_CUTTING = 'thread_cutting'
    THREAD_MILLING = 'thread_milling'
    THREAD_FORMING = 'thread_forming'

@dataclass
class TwmProfile:
    id: str = 'tool_wear_monitoring'
    name: str = 'Tool Wear Monitoring'
    pre: Dict[str, Dict[str, Dict]] = field(default_factory=lambda: {})
    post: Dict[str, Dict[str, Dict]] = field(default_factory=lambda: {})


@dataclass
class UnifiedMetadata:
    person: str
    institution: InstitutionEnum|str
    machine: str
    experiment: str
    process: ProcessEnum|str
    workpiece_material: WorkpieceMaterialEnum|str
    cutting_speed: float
    feed_per_tooth: float
    doc_axial: float
    doc_radial: float
    tool_diameter: float
    tool_tooth_count: int
    tool_material: ToolMaterialEnum|str
    tool_offset: float
    coolant: CoolantEnum|str
    sth_mac: str
    stu_mac: str
    tool_failure: bool
    wear_mark_width: float
    twm_layer: int

    feed_per_rev: Optional[float] = None
    doc: Optional[float] = None
    workpiece_diameter: Optional[float] = None
    pictures: Optional[str] = None
    comment: Optional[str] = None
