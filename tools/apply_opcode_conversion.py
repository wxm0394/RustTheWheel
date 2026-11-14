#!/usr/bin/env python3
"""Apply opcode conversion to scripts.txt and verify results."""

import json
import hashlib
import sys
import os

# Add the project root to path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)


def compute_sha256(filepath):
    """Compute SHA-256 of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def load_identification_table(table_path):
    """Load identification table and extract changed mappings."""
    with open(table_path, 'r', encoding='utf-8') as f:
        table = json.load(f)
    
    mappings = {}
    for key, mapping in table.get('mappings', {}).items():
        if mapping['status'] == 'changed':
            old_val = mapping['old_value']
            new_val = mapping['new_value']
            mappings[old_val] = new_val
    
    return mappings


def parse_scripts_txt(filepath):
    """Parse scripts.txt into structured data.
    
    Returns:
        dict with:
        - 'header': first line (script count)
        - 'scripts': list of dicts with 'name', 'declared_count', 'tokens'
        - 'raw_lines': all lines for reconstruction
        - 'line_ending': the line ending used in the file ('\r\n' or '\n')
    """
    with open(filepath, 'rb') as f:
        content = f.read()
    
    # Detect line ending
    if b'\r\n' in content:
        line_ending = '\r\n'
    else:
        line_ending = '\n'
    
    # Decode and split preserving line endings
    text = content.decode('utf-8')
    lines = text.split(line_ending)
    # Remove empty last element if file ends with line ending
    if lines and lines[-1] == '':
        lines.pop()
    # Add line ending back to each line
    lines = [line + line_ending for line in lines]
    
    # Skip header line "scriptsfile version 1" if present
    i = 0
    if lines[i].strip().startswith('scriptsfile version'):
        i += 1
    
    # Next line is script count
    script_count = int(lines[i].strip())
    i += 1
    
    scripts = []
    while i < len(lines):
        line = lines[i].rstrip('\r\n')
        if not line.strip():
            i += 1
            continue
        
        # Script name line (no leading space)
        script_name = line.strip()
        i += 1
        
        # Script body (single line with space-separated tokens)
        # The first token is the declared statement count
        # IMPORTANT: Preserve the original line including leading space for round-trip
        if i >= len(lines):
            break
        body_line = lines[i].rstrip('\r\n')
        i += 1
        
        # Parse tokens from stripped version
        tokens = body_line.strip().split() if body_line.strip() else []
        declared_count = int(tokens[0]) if tokens else 0
        
        scripts.append({
            'name': script_name,
            'declared_count': declared_count,
            'tokens': tokens,
            'body_line': body_line,  # Preserve original with leading space
            'start_line': i - 3,  # 0-based line index of script name
        })
    
    return {
        'script_count': script_count,
        'scripts': scripts,
        'raw_lines': lines,
        'line_ending': line_ending
    }


def apply_conversion(parsed, mappings, modifier_mask):
    """Apply opcode conversion to parsed scripts.
    
    Only converts tokens in opcode position (first token of each statement).
    Does NOT convert parameter tokens.
    Does NOT do chained conversion - only looks up original base opcode once.
    
    Args:
        parsed: Parsed scripts data from parse_scripts_txt()
        mappings: Dict mapping old_base_opcode -> new_base_opcode
        modifier_mask: Bitmask for modifier bits (NEG | THIS_OR_NEXT)
    
    Returns:
        - modified parsed data
        - list of changes: (script_name, statement_index, old_opcode, new_opcode, old_raw, new_raw)
    """
    changes = []
    affected_scripts = set()
    
    for script in parsed['scripts']:
        tokens = script['tokens']
        if not tokens:
            continue
        
        # Process statements sequentially using the FILE'S OWN param_count (second token of each statement)
        # for boundary detection, NOT the header's param_counts.
        # Token structure: [declared_count, opcode1, param_count1, params..., opcode2, param_count2, params..., ...]
        token_idx = 1  # Skip declared_count at index 0
        stmt_idx = 0
        
        while token_idx < len(tokens) and stmt_idx < script['declared_count']:
            raw_opcode = int(tokens[token_idx])
            base_opcode = raw_opcode & ~modifier_mask
            
            # Get param_count from the FILE'S own data (second token of this statement)
            if token_idx + 1 < len(tokens):
                param_count = int(tokens[token_idx + 1])
            else:
                param_count = 0
            
            # Check if this base opcode needs conversion
            if base_opcode in mappings:
                new_base = mappings[base_opcode]
                # Preserve modifiers
                new_raw = (raw_opcode & modifier_mask) | new_base
                
                changes.append({
                    'script_name': script['name'],
                    'statement_index': stmt_idx,
                    'token_index': token_idx,
                    'old_raw': raw_opcode,
                    'old_base': base_opcode,
                    'new_raw': new_raw,
                    'new_base': new_base,
                    'modifiers': raw_opcode & modifier_mask
                })
                affected_scripts.add(script['name'])
                
                # Apply change
                tokens[token_idx] = str(new_raw)
            
            # Move to next statement using FILE'S param_count
            token_idx += 2 + param_count  # opcode + param_count + params
            stmt_idx += 1
        
        # Update body_line - preserve trailing space from original if present
        new_body = ' '.join(tokens)
        # Check if original body_line had trailing space
        if script['body_line'].endswith(' '):
            new_body += ' '
        script['body_line'] = new_body
        script['tokens'] = tokens
    
    return parsed, changes


def reconstruct_scripts_txt(parsed, output_path):
    """Reconstruct scripts.txt from parsed data.
    
    Preserves the original formatting: script body lines start with a leading
    space (matching the RTW original file format).
    """
    line_ending = parsed.get('line_ending', '\n')
    lines = []
    lines.append("scriptsfile version 1" + line_ending)
    lines.append(str(parsed['script_count']) + line_ending)
    
    for script in parsed['scripts']:
        lines.append(script['name'] + line_ending)
        # The body_line already contains the declared_count as first token.
        # Ensure it starts with a leading space to match the original format.
        body = script['body_line']
        if not body.startswith(' '):
            body = ' ' + body
        lines.append(body + line_ending)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def main():
    if len(sys.argv) != 5:
        print("Usage: python tools/apply_opcode_conversion.py <input_scripts.txt> <identification_table.json> <output_scripts.txt> <report.json>")
        sys.exit(1)
    
    input_path = sys.argv[1]
    table_path = sys.argv[2]
    output_path = sys.argv[3]
    report_path = sys.argv[4]
    
    # Verify input SHA-256
    input_sha256 = compute_sha256(input_path)
    expected_sha256 = "d667feb4c11fb45f838f436a068164ece76e3fb3c06d162c8174d8c3e20f2e88"
    
    print(f"Input SHA-256: {input_sha256}")
    print(f"Expected:      {expected_sha256}")
    print(f"Match: {input_sha256 == expected_sha256}")
    
    if input_sha256 != expected_sha256:
        print("ERROR: Input file SHA-256 mismatch!")
        sys.exit(1)
    
    # Load mappings
    mappings = load_identification_table(table_path)
    
    # Filter out mappings for opcodes not used in RTW (e.g., 713 has 0 occurrences)
    # Only keep mappings where the old opcode actually appears in the source
    # We'll check this after parsing
    
    print(f"\nAll changed mappings from table: {mappings}")
    
    # Parse input
    parsed = parse_scripts_txt(input_path)
    print(f"\nParsed {len(parsed['scripts'])} scripts")
    print(f"Declared script count: {parsed['script_count']}")
    
    # Count total operations
    total_ops = sum(s['declared_count'] for s in parsed['scripts'])
    print(f"Total declared operations: {total_ops}")
    
    # Apply conversion
    # We need the scanner's param count logic. Let's import it.
    from tools.scan_rtw_opcodes import _load_known_opcodes, _MODIFIER_MASK
    
    # Use the 1.174 header_operations.py since we're converting TO 1.174
    known_opcodes = _load_known_opcodes("Native_1174/module_system/header_operations.py")
    # Build param count dict
    param_counts = {}
    for name, (opcode, params) in known_opcodes.items():
        param_counts[opcode] = params
    
    # Determine which mappings are actually needed (old opcode appears in source)
    # Use the SAME boundary logic as apply_conversion(): file's own param_count from token_idx + 1
    used_base_opcodes = set()
    for script in parsed['scripts']:
        tokens = script['tokens']
        if not tokens:
            continue
        token_idx = 1  # Skip declared_count at index 0 (same as apply_conversion)
        stmt_idx = 0
        while token_idx < len(tokens) and stmt_idx < script['declared_count']:
            raw_opcode = int(tokens[token_idx])
            base_opcode = raw_opcode & ~_MODIFIER_MASK
            used_base_opcodes.add(base_opcode)
            # Get param_count from the FILE'S own data (second token of this statement)
            if token_idx + 1 < len(tokens):
                param_count = int(tokens[token_idx + 1])
            else:
                param_count = 0
            # Move to next statement using FILE'S param_count (opcode + param_count + params)
            token_idx += 2 + param_count
            stmt_idx += 1
    
    # Filter mappings to only those where old opcode is actually used
    filtered_mappings = {k: v for k, v in mappings.items() if k in used_base_opcodes}
    print(f"\nFiltered mappings (only used opcodes): {filtered_mappings}")
    print(f"Used base opcodes in source: {sorted(used_base_opcodes)}")
    
    # Apply conversion using the reusable function
    parsed, changes = apply_conversion(parsed, filtered_mappings, _MODIFIER_MASK)
    
    affected_scripts = set(c['script_name'] for c in changes)
    
    print(f"\nChanges made: {len(changes)}")
    print(f"Affected scripts: {len(affected_scripts)}")
    
    # Count by opcode
    from collections import Counter
    old_base_counter = Counter(c['old_base'] for c in changes)
    new_base_counter = Counter(c['new_base'] for c in changes)
    print(f"Old base opcode counts: {dict(old_base_counter)}")
    print(f"New base opcode counts: {dict(new_base_counter)}")
    
    # Write output
    reconstruct_scripts_txt(parsed, output_path)
    
    # Verify output SHA-256 after round-trip (re-parse and reconstruct)
    output_sha256 = compute_sha256(output_path)
    print(f"\nOutput SHA-256: {output_sha256}")
    
    # Round-trip test: parse output, apply reverse mappings, reconstruct, compare to original
    reverse_mappings = {v: k for k, v in filtered_mappings.items()}
    parsed_output = parse_scripts_txt(output_path)
    
    # Apply reverse conversion using the reusable function
    parsed_output, _ = apply_conversion(parsed_output, reverse_mappings, _MODIFIER_MASK)
    
    # Reconstruct round-trip
    roundtrip_path = output_path + ".roundtrip"
    reconstruct_scripts_txt(parsed_output, roundtrip_path)
    roundtrip_sha256 = compute_sha256(roundtrip_path)
    
    print(f"Round-trip SHA-256: {roundtrip_sha256}")
    print(f"Round-trip matches original: {roundtrip_sha256 == input_sha256}")
    
    # Clean up round-trip file
    os.remove(roundtrip_path)
    
    # Generate report
    report = {
        "input": {
            "path": input_path,
            "sha256": input_sha256,
            "script_count": parsed['script_count'],
            "total_operations": total_ops
        },
        "mappings_applied": filtered_mappings,
        "changes": changes,
        "summary": {
            "total_token_changes": len(changes),
            "affected_scripts_count": len(affected_scripts),
            "affected_scripts": sorted(list(affected_scripts)),
            "old_base_counts": dict(old_base_counter),
            "new_base_counts": dict(new_base_counter)
        },
        "output": {
            "path": output_path,
            "sha256": output_sha256
        },
        "roundtrip": {
            "sha256": roundtrip_sha256,
            "matches_original": roundtrip_sha256 == input_sha256
        }
    }
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\nReport saved to: {report_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())