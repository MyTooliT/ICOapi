# generate_metadata.py
import argparse
import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict

HEADER = """# This file is auto-generated from metadata.yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict

"""

INTEGER_TYPES = {'int', 'integer'}
FLOAT_TYPES = {'float', 'double', 'decimal'}
BOOLEAN_TYPES = {'boolean', 'bool'}

@dataclass
class Quantity:
    value: float
    unit: str


def to_python_type(datatype: str) -> str:
    dt = datatype.lower()
    if dt in INTEGER_TYPES:
        return 'int'
    if dt in FLOAT_TYPES:
        return 'float'
    if dt in BOOLEAN_TYPES:
        return 'bool'
    # text_box, text, text_suggestions, dropdown fallback to str
    return 'str'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='metadata.yaml', help='Path to metadata.yaml')
    parser.add_argument('--output', default='metadata.py', help='Path to output Python file')
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    code = HEADER

    # Version and info
    version = config.get('info', {}).get('version', '')
    code += f"METADATA_VERSION = '{version}'\n\n"

    # Generate enums for lists
    enum_defs = []
    for list_id, values in config.get('lists', {}).items():
        enum_name = list_id.title().replace('_', '') + 'Enum'
        lines = [f'class {enum_name}(str, Enum):']
        for v in values:
            member = ''.join(c if c.isalnum() else '_' for c in str(v)).upper()
            if member and member[0].isdigit():
                member = '_' + member
            lines.append(f"    {member} = '{v}'")
        enum_defs.append('\n'.join(lines))
    if enum_defs:
        code += '\n\n'.join(enum_defs) + '\n\n'

    # Generate Profile classes
    for prof_key, prof in config.get('profiles', {}).items():
        class_name = prof_key.title().replace('_', '') + 'Profile'
        code += f'@dataclass\nclass {class_name}:\n'
        code += f"    id: str = '{prof.get('id', prof_key)}'\n"
        code += f"    name: str = '{prof.get('name', prof_key)}'\n"
        for phase in ('pre', 'post'):
            if phase in prof:
                code += f"    {phase}: Dict[str, Dict[str, Dict]] = field(default_factory=lambda: {{}})\n"
        code += '\n'
    code += '\n'

    # UnifiedMetadata dataclass
    code += '@dataclass\n'
    code += 'class UnifiedMetadata:\n'
    # Separate required and optional fields
    required_lines = []
    optional_lines = []
    for pid, pdef in config.get('parameters', {}).items():
        py_type = to_python_type(pdef.get('datatype', 'str'))
        if pdef.get('datatype') in ('dropdown', 'text_suggestions'):
            enum_name = pid.title().replace('_', '') + 'Enum|str'
            py_type = enum_name
        default_value = pdef.get('default', None)
        # Determine required across profiles
        is_required = False
        for prof in config.get('profiles', {}).values():
            for phase in ('pre', 'post'):
                phase_dict = prof.get(phase, {})
                for category_fields in phase_dict.values():
                    if pid in category_fields and category_fields[pid].get('required') == 'required':
                        is_required = True
                        break
                if is_required:
                    break
            if is_required:
                break
        if is_required and default_value is None:
            required_lines.append(f"    {pid}: {py_type}\n")
        else:
            default_repr = repr(default_value) if default_value is not None else 'None'
            optional_lines.append(f"    {pid}: Optional[{py_type}] = {default_repr}\n")

    # Write required fields first
    for line in required_lines:
        code += line
    # Then optional fields
    if optional_lines:
        code += '\n'
        for line in optional_lines:
            code += line

    # finalize writing
    os.makedirs(Path(args.output).parent, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as out:
        out.write(code)
    print(f"✅ UnifiedMetadata model written to {args.output}")


if __name__ == '__main__':
    main()
