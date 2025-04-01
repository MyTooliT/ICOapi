# generate_metadata_model.py
import argparse
import os
import yaml
import re
from pathlib import Path
from collections import defaultdict

HEADER = """# This file is auto-generated from metadata.yaml
from dataclasses import dataclass
from enum import Enum
from typing import Optional

"""

def to_python_type(datatype: str, param_id: str, enums: dict, quantities: set) -> str:
    if param_id in enums:
        return param_id.title().replace('_', '') + "Enum"
    if param_id in quantities:
        return "Quantity"
    dt = datatype.lower()
    if dt in ["int", "integer"]:
        return "int"
    elif dt in ["float", "double", "decimal"]:
        return "float"
    elif dt in ["bool", "boolean"]:
        return "bool"
    else:
        return "str"

def determine_field_requirements(config: dict) -> dict:
    usage = defaultdict(list)
    for process in config.get("processes", {}).values():
        for param_id, state in process.get("parameters", {}).items():
            usage[param_id].append(state)

    decisions = {}
    for param_id, states in usage.items():
        if all(state == "required" for state in states):
            decisions[param_id] = "required"
        else:
            decisions[param_id] = "optional"

    return decisions

def generate_enums(config: dict) -> dict:
    enums = {}
    for param_id, param in config.get("parameters", {}).items():
        options = param.get("options")
        if options:
            enums[param_id] = options
    return enums

def get_quantity_fields(config: dict) -> set:
    return {k for k, v in config.get("parameters", {}).items() if "unit" in v}

def escape_enum_name(value: str) -> str:
    value = str(value)
    value = value.strip()
    value = value.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
    value = value.replace('Ä', 'Ae').replace('Ö', 'Oe').replace('Ü', 'Ue')
    value = re.sub(r'[^a-zA-Z0-9_]', '_', value)
    if re.match(r'^\d', value):
        value = '_' + value
    return value.upper()

def format_enum_class(name: str, values: list[str]) -> str:
    enum_name = name.title().replace('_', '') + "Enum"
    lines = [f"class {enum_name}(str, Enum):"]
    for val in values:
        val_str = str(val)
        safe = escape_enum_name(val_str)
        lines.append(f"    {safe} = '{val_str}'")
    return "\n".join(lines)

def generate_unified_dataclass(config: dict, enums: dict, quantities: set) -> str:
    requiredness = determine_field_requirements(config)
    parameters = config.get("parameters", {})

    required_fields = []
    optional_fields = []

    for key, meta in parameters.items():
        field_type = to_python_type(meta.get("datatype", "str"), key, enums, quantities)
        if requiredness.get(key) == "required":
            required_fields.append(f"    {key}: {field_type}")
        else:
            optional_fields.append(f"    {key}: Optional[{field_type}] = None")

    fields = "\n".join(required_fields + optional_fields)
    return f"@dataclass\nclass UnifiedMetadata:\n{fields}\n"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(Path(__file__).resolve().parent.parent.parent / "icoclient" / "public" / "config" / "metadata.yaml"),
        help="Path to metadata.yaml"
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent.parent / "models" / "autogen" / "metadata.py"),
        help="Path to output metadata.py file"
    )

    args = parser.parse_args()
    os.makedirs(Path(args.output).parent, exist_ok=True)

    with open(args.input, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    enums = generate_enums(config)
    quantities = get_quantity_fields(config)

    version_line = f"METADATA_VERSION = '{config.get('info', {}).get('version', 'unknown')}'\n\n"
    quantity_class = """@dataclass
class Quantity:
    value: float
    unit: str
"""

    enum_defs = [format_enum_class(name, values) for name, values in enums.items()]
    enum_section = "\n\n".join(enum_defs) + "\n\n" if enum_defs else ""
    class_def = generate_unified_dataclass(config, enums, quantities)

    with open(args.output, "w", encoding="utf-8") as out:
        out.write(HEADER + version_line + quantity_class + "\n" + enum_section + class_def)

    print(f"✅ UnifiedMetadata model written to {args.output}")

if __name__ == "__main__":
    main()
