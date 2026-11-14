#!/usr/bin/env python3
"""Verification checks A and B for opcode conversion."""

import json
import hashlib
import sys
import os

# Add project root to path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from tools.scan_rtw_opcodes import _load_known_opcodes, _MODIFIER_MASK, scan_rtw_scripts


def compute_sha256(filepath):
    """Compute SHA-256 of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def parse_scripts_txt_structured(filepath):
    """Parse scripts.txt into structured data for verification."""
    with open(filepath, 'rb') as f:
        content = f.read()
    
    # Detect line ending
    if b'\r\n' in content:
        line_ending = '\r\n'
    else:
        line_ending = '\n'
    
    text = content.decode('utf-8')
    lines = text.split(line_ending)
    if lines and lines[-1] == '':
        lines.pop()
    lines = [line + line_ending for line in lines]
    
    i = 0
    if lines[i].strip().startswith('scriptsfile version'):
        i += 1
    
    script_count = int(lines[i].strip())
    i += 1
    
    scripts = []
    while i < len(lines):
        line = lines[i].rstrip('\r\n')
        if not line.strip():
            i += 1
            continue
        
        script_name = line.strip()
        i += 1
        
        if i >= len(lines):
            break
        body_line = lines[i].rstrip('\r\n')
        i += 1
        
        tokens = body_line.strip().split() if body_line.strip() else []
        declared_count = int(tokens[0]) if tokens else 0
        
        scripts.append({
            'name': script_name,
            'declared_count': declared_count,
            'tokens': tokens,
            'body_line': body_line,
        })
    
    return {
        'script_count': script_count,
        'scripts': scripts,
        'line_ending': line_ending
    }


def extract_base_opcodes_from_parsed(parsed):
    """Extract all base opcodes used in parsed scripts using file's own param_count."""
    used_base_opcodes = []
    for script in parsed['scripts']:
        tokens = script['tokens']
        if not tokens:
            continue
        token_idx = 1  # Skip declared_count
        stmt_idx = 0
        while token_idx < len(tokens) and stmt_idx < script['declared_count']:
            raw_opcode = int(tokens[token_idx])
            base_opcode = raw_opcode & ~_MODIFIER_MASK
            used_base_opcodes.append(base_opcode)
            
            # Get param_count from file's own data
            if token_idx + 1 < len(tokens):
                param_count = int(tokens[token_idx + 1])
            else:
                param_count = 0
            
            token_idx += 2 + param_count
            stmt_idx += 1
    return used_base_opcodes


def check_A():
    """Check A: Target opcode full set identification."""
    print("=== Check A: Target opcode full set identification ===")
    
    # Load target header_operations.py
    header_path = "module_system_1174/module_system/header_operations.py"
    if not os.path.exists(header_path):
        header_path = "Native_1174/module_system/header_operations.py"
    
    target_header_sha256 = compute_sha256(header_path)
    print(f"Target header SHA-256: {target_header_sha256}")
    
    known_opcodes = _load_known_opcodes(header_path)
    valid_base_opcodes = set(opcode for _, (opcode, _) in known_opcodes.items())
    print(f"Valid base opcode count in target: {len(valid_base_opcodes)}")
    
    # Parse candidate
    candidate_path = "output_scripts.txt"
    parsed = parse_scripts_txt_structured(candidate_path)
    
    actual_scripts = len(parsed['scripts'])
    total_ops = sum(s['declared_count'] for s in parsed['scripts'])
    print(f"Candidate parsed scripts: {actual_scripts}")
    print(f"Candidate total operations: {total_ops}")
    
    # Extract used base opcodes from candidate
    used_base_opcodes = extract_base_opcodes_from_parsed(parsed)
    used_set = set(used_base_opcodes)
    
    # Compute unknown opcodes (used but not in target)
    unknown_opcodes = used_set - valid_base_opcodes
    unknown_counts = {}
    for op in unknown_opcodes:
        unknown_counts[op] = used_base_opcodes.count(op)
    
    print(f"Unknown opcodes (used but not in target): {unknown_counts}")
    
    # Structural validation using scanner
    scan_result = scan_rtw_scripts(candidate_path, known_opcodes=known_opcodes, capture_statement_details=False)
    structure_errors = 0
    for script in scan_result.get('scripts', []):
        if not script.get('structure_success', True):
            structure_errors += 1
    print(f"Structural errors: {structure_errors}")
    
    # Write results
    os.makedirs("verification_results", exist_ok=True)
    result = {
        "target_header_sha256": target_header_sha256,
        "valid_base_opcode_count": len(valid_base_opcodes),
        "candidate_scripts": actual_scripts,
        "candidate_operations": total_ops,
        "unknown_opcodes": unknown_counts,
        "structure_errors": structure_errors
    }
    with open("verification_results/check_A.json", 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    # Determine pass/fail
    if unknown_counts or structure_errors > 0:
        status = "FAIL"
    else:
        status = "PASS"
    
    print(f"Check A: {status}")
    return status, result


def check_B():
    """Check B: Per-change-list point restoration."""
    print("\n=== Check B: Per-change-list point restoration ===")
    
    # Load conversion report
    with open("conversion_report.json", 'r', encoding='utf-8') as f:
        report = json.load(f)
    
    changes = report['changes']
    print(f"Total changes in report: {len(changes)}")
    
    # Parse candidate
    candidate_path = "output_scripts.txt"
    parsed = parse_scripts_txt_structured(candidate_path)
    
    # Build script name -> script index map
    script_map = {s['name']: i for i, s in enumerate(parsed['scripts'])}
    
    # Apply each restoration individually
    restored_count = 0
    for change in changes:
        script_name = change['script_name']
        token_index = change['token_index']
        old_raw = change['old_raw']
        new_raw = change['new_raw']
        
        if script_name not in script_map:
            print(f"ERROR: Script {script_name} not found in candidate")
            return "FAIL", {}
        
        script_idx = script_map[script_name]
        script = parsed['scripts'][script_idx]
        tokens = script['tokens']
        
        # Verify the new opcode is at the expected position
        if token_index >= len(tokens):
            print(f"ERROR: token_index {token_index} out of bounds for {script_name}")
            return "FAIL", {}
        
        actual_raw = int(tokens[token_index])
        if actual_raw != new_raw:
            print(f"ERROR: Expected new_raw {new_raw} at token_index {token_index}, found {actual_raw}")
            return "FAIL", {}
        
        # Restore this single position
        tokens[token_index] = str(old_raw)
        restored_count += 1
        
        # Update body_line
        new_body = ' '.join(tokens)
        if script['body_line'].endswith(' '):
            new_body += ' '
        script['body_line'] = new_body
        script['tokens'] = tokens
    
    print(f"Restored {restored_count} positions")
    
    # Reconstruct to independent file
    output_path = "verification_results/restored_scripts.txt"
    os.makedirs("verification_results", exist_ok=True)
    
    line_ending = parsed.get('line_ending', '\n')
    lines = []
    lines.append("scriptsfile version 1" + line_ending)
    lines.append(str(parsed['script_count']) + line_ending)
    
    for script in parsed['scripts']:
        lines.append(script['name'] + line_ending)
        body = script['body_line']
        if not body.startswith(' '):
            body = ' ' + body
        lines.append(body + line_ending)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    # Verify SHA-256
    restored_sha256 = compute_sha256(output_path)
    expected_sha256 = "d667feb4c11fb45f838f436a068164ece76e3fb3c06d162c8174d8c3e20f2e88"
    
    print(f"Restored file SHA-256: {restored_sha256}")
    print(f"Expected SHA-256:      {expected_sha256}")
    print(f"Match: {restored_sha256 == expected_sha256}")
    
    result = {
        "restored_positions": restored_count,
        "restored_sha256": restored_sha256,
        "expected_sha256": expected_sha256,
        "matches": restored_sha256 == expected_sha256
    }
    with open("verification_results/check_B.json", 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    status = "PASS" if restored_sha256 == expected_sha256 else "FAIL"
    print(f"Check B: {status}")
    return status, result


def main():
    print("Running verification checks A and B...\n")
    
    status_A, result_A = check_A()
    status_B, result_B = check_B()
    
    print("\n=== SUMMARY ===")
    print(f"A: {status_A}")
    print(f"  Command: python tools/verify_checks.py (check A)")
    print(f"  Exit code: {0 if status_A == 'PASS' else 1}")
    print(f"  Target header SHA-256: {result_A.get('target_header_sha256', 'N/A')}")
    print(f"  Actual scripts/ops: {result_A.get('candidate_scripts', 'N/A')}/{result_A.get('candidate_operations', 'N/A')}")
    print(f"  Unknown opcodes: {result_A.get('unknown_opcodes', 'N/A')}")
    print(f"  Result file: verification_results/check_A.json")
    
    print(f"\nB: {status_B}")
    print(f"  Command: python tools/verify_checks.py (check B)")
    print(f"  Exit code: {0 if status_B == 'PASS' else 1}")
    print(f"  Actual restored positions: {result_B.get('restored_positions', 'N/A')}")
    print(f"  Restored file SHA-256: {result_B.get('restored_sha256', 'N/A')}")
    print(f"  Result file: verification_results/check_B.json")
    
    return 0 if (status_A == "PASS" and status_B == "PASS") else 1


if __name__ == "__main__":
    sys.exit(main())