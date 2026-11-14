#!/usr/bin/env python3
"""Generate opcode migration plan from scan results and identification table."""

import json
import sys
import os

# Add the project root to path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

def generate_migration_plan(scan_results_path, identification_table_path, output_path):
    """Generate migration plan from scan results and identification table."""
    
    # Load scan results
    with open(scan_results_path, 'r', encoding='utf-8') as f:
        scan_results = json.load(f)
    
    # Load identification table
    with open(identification_table_path, 'r', encoding='utf-8') as f:
        identification_table = json.load(f)
    
    # Extract base usage from scan results
    base_usage = scan_results.get('base_usage', {})
    
    # Extract mappings from identification table
    mappings = identification_table.get('mappings', {})
    
    # Create migration plan
    migration_plan = {
        "total_rtw_used_opcodes": len(base_usage),
        "classification": {
            "unchanged": 0,
            "changed": 0,
            "removed": 0,
            "not_in_table": 0
        },
        "opcodes": {}
    }
    
    # Process each opcode in base usage
    for opcode_str, count in base_usage.items():
        opcode = int(opcode_str)
        
        # Find mapping in identification table
        if str(opcode) in mappings:
            mapping = mappings[str(opcode)]
            status = mapping['status']
            new_value = mapping['new_value']
            old_name = mapping['old_names'][0] if mapping['old_names'] else f"opcode_{opcode}"
            new_name = mapping['new_names'][0] if mapping['new_names'] else f"opcode_{new_value}"
        else:
            # Opcode not in identification table
            status = "not_in_table"
            new_value = None
            old_name = f"opcode_{opcode}"
            new_name = f"opcode_{opcode}"
        
        # Add to migration plan
        migration_plan['opcodes'][str(opcode)] = {
            "count": count,
            "status": status,
            "old_name": old_name,
            "new_name": new_name
        }
        
        # Update classification counts
        if status == "unchanged":
            migration_plan['classification']['unchanged'] += 1
        elif status == "changed":
            migration_plan['classification']['changed'] += 1
        elif status == "removed":
            migration_plan['classification']['removed'] += 1
        else:
            migration_plan['classification']['not_in_table'] += 1
    
    # Save migration plan
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(migration_plan, f, indent=2, ensure_ascii=False)
    
    print(f"Migration plan generated successfully with {len(base_usage)} opcodes")
    print(f"Classification: {migration_plan['classification']}")
    print(f"Output saved to: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python tools/generate_migration_plan.py <scan_results.json> <identification_table.json> <output_plan.json>")
        sys.exit(1)
    
    scan_results_path = sys.argv[1]
    identification_table_path = sys.argv[2]
    output_path = sys.argv[3]
    
    generate_migration_plan(scan_results_path, identification_table_path, output_path)