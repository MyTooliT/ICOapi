# This file is auto-generated from metadata.yaml
from dataclasses import dataclass
from enum import Enum
from typing import Optional

METADATA_VERSION = '0.0.1'

@dataclass
class Quantity:
    value: float
    unit: str

class InstitutionEnum(str, Enum):
    TU_WIEN = 'TU Wien'
    TU_MUENCHEN = 'TU München'
    ETH_ZUERICH = 'ETH Zürich'

class ProcessEnum(str, Enum):
    MILLING = 'Milling'
    DRILLING = 'Drilling'
    GRINDING = 'Grinding'
    TURNING = 'Turning'
    REAMING = 'Reaming'
    SHAPING = 'Shaping'
    THREAD_CUTTING = 'Thread Cutting'
    THREAD_MILLING = 'Thread Milling'
    THREAD_FORMING = 'Thread Forming'

class WorkpieceMaterialEnum(str, Enum):
    S235 = 'S235'
    _4140 = '4140'
    TIAL = 'TiAl'
    GRADE_5_TITANIUM = 'Grade 5 Titanium'

class ToolMaterialEnum(str, Enum):
    PCD = 'PCD'
    CARBIDE = 'Carbide'
    MCD = 'MCD'
    CERAMIC = 'Ceramic'

class CoolantEnum(str, Enum):
    FLOOD = 'Flood'
    MMQ = 'MMQ'
    _ = '…'

@dataclass
class UnifiedMetadata:
    person: str
    institution: InstitutionEnum
    machine: str
    experiment: str
    process: ProcessEnum
    workpiece_material: WorkpieceMaterialEnum
    cutting_speed: Quantity
    tool_material: ToolMaterialEnum
    coolant: CoolantEnum
    sth_mac: str
    stu_mac: str
    feed_per_tooth: Optional[Quantity] = None
    feed_per_rev: Optional[Quantity] = None
    doc_axial: Optional[Quantity] = None
    doc_radial: Optional[Quantity] = None
    doc: Optional[Quantity] = None
    workpiece_diameter: Optional[Quantity] = None
    tool_diameter: Optional[Quantity] = None
    tool_tooth_count: Optional[int] = None
    tool_offset: Optional[Quantity] = None
