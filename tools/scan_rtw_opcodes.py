#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Precise read-only scanner for Mount & Blade Warband scripts.txt.

Parses a scripts.txt file statement-by-statement (not line-by-line), because
Warband writes the entire body of one script as a single line of space-separated
tokens. Each statement has the form:

    <opcode> <param_count> [param_1 ... param_N]

Special handling:
  * Opcode 713 is treated as a sentinel/parameter value and is never counted as
    an opcode usage when appearing in parameter position.
  * Modifier bits (neg=0x80000000, this_or_next=0x40000000) are extracted via
    bitwise masking; the base opcode is reported and counted.
  * The first token of each script body is the statement count and is skipped
    (RTW format convention).
  * Truncated bodies (statement claims more parameters than remain) are flagged.
  * Illegal/negative parameter counts are flagged.
  * Unknown opcodes (values not present in the loaded opcode tables) are flagged
    when a known-opcode table is supplied.
  * The scanner never modifies the input file.

Returns a structured result dict:
    {
        'file_success': bool,
        'structure_success': bool,
        'opcode_identification_status': 'ok' | 'unknown_opcode',
        'semantic_compatibility_status': 'ok' | 'changed' | 'removed' | 'unknown',
        'declared_script_count': int,
        'discovered_script_count': int,
        'successful_script_count': int,
        'failed_script_count': int,
        'declared_statement_total': int,
        'successful_statement_total': int,
        'base_usage': {base_opcode: count},
        'raw_usage': {raw_opcode: count},
        'modifier_usage': {'neg': count, 'this_or_next': count},
        'errors': [str],
        'warnings': [str],
        'scripts': [script_result],
        'sha256': str,
    }

Each script_result contains:
    {
        'script_id': str,
        'declared_statement_count': int,
        'parsed_statement_count': int,
        'success': bool,
        'structure_success': bool,
        'opcode_identification_status': 'ok' | 'unknown_opcode',
        'semantic_compatibility_status': 'ok' | 'changed' | 'removed' | 'unknown',
        'positioning': {'start_line': int, 'end_line': int},
        'errors': [str],
        'warnings': [str],
        'base_usage': {base_opcode: count},
        'raw_usage': {raw_opcode: count},
        'modifier_usage': {'neg': count, 'this_or_next': count},
        'statements': [statement_detail],  # optional, if capture_statement_details=True
    }

Design notes on structure vs. semantics:
  * **Structural failures** (truncation, negative/implausible parameter counts,
    declared-count mismatch, invalid tokens, script-count mismatch) break the
    parsing integrity of a script.  A script with a structural failure does NOT
    contribute its opcode usage stats to the file-level aggregates, and sets
    file-level ``structure_success`` to False.
  * **Opcode identification issues** (unknown opcodes - not found in header table)
    do not break parsing structure.  A script with only an identification issue
    still contributes its stats to the file-level aggregates, but sets
    file-level ``opcode_identification_status`` to ``'unknown_opcode'`` and
    ``file_success`` to False.
  * **Semantic compatibility issues** (opcode value changed, opcode removed,
    or unknown mapping) are tracked separately via ``semantic_compatibility_status``.
  * ``file_success`` is True only when ``structure_success`` is True AND
    ``opcode_identification_status`` is ``'ok'`` AND there are no errors.
"""

import sys
import os
import hashlib
import json
import csv
import ast


def _load_known_opcodes(header_operations_path):
    """
    Parse header_operations.py using AST to extract opcode definitions.
    
    Returns a dict mapping opcode_name -> (opcode_value, param_count).
    Param count is extracted from inline comments in the format:
    # (opcode_name,param1,param2),  -> count commas + 1
    """
    known_constants = {
        "neg": 0x80000000,
        "this_or_next": 0x40000000,
    }
    
    result = {}
    
    with open(header_operations_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    tree = ast.parse(content, filename=header_operations_path)
    
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                var_name = node.targets[0].id
                
                # Skip list groupings
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    continue
                
                # Evaluate the expression to get the opcode value
                try:
                    evaluator = ExpressionEvaluator(known_constants)
                    value = evaluator.evaluate(node.value)
                    
                    if isinstance(value, (int, float)):
                        # Extract param count from inline comment
                        param_count = 0
                        if hasattr(node, 'lineno'):
                            # Get the source line for this assignment
                            lines = content.splitlines()
                            if node.lineno <= len(lines):
                                line = lines[node.lineno - 1]
                                # Find inline comment
                                comment_start = line.find('#')
                                if comment_start != -1:
                                    comment = line[comment_start:]
                                    # Look for pattern: # (name,param1,param2),
                                    import re
                                    match = re.search(r'\(([^)]+)\)', comment)
                                    if match:
                                        params_str = match.group(1)
                                        # Count commas + 1 for param count
                                        # But exclude the opcode name itself (first item before comma)
                                        parts = [p.strip() for p in params_str.split(',')]
                                        if len(parts) > 1:
                                            param_count = len(parts) - 1  # exclude opcode name
                                        elif len(parts) == 1 and parts[0]:
                                            # Only opcode name, no params
                                            param_count = 0
                        
                        known_constants[var_name] = value
                        result[var_name] = (int(value), param_count)
                        
                except (ValueError, TypeError, NameError):
                    # Skip unparseable expressions
                    pass
                except Exception:
                    # Skip any other errors
                    pass
    
    return result


class ExpressionEvaluator(ast.NodeVisitor):
    """
    Evaluates a Python abstract syntax tree (AST) node to a constant value.
    Supports constants, names (variables), binary operations, and unary operations.
    Rejects unsupported node types with explicit errors.
    """
    def __init__(self, constants):
        self.constants = constants
        self.evaluated_value = None

    def evaluate(self, node):
        self.visit(node)
        return self.evaluated_value

    def _require_value(self, value, message):
        if value is None:
            raise ValueError(message)
        return value

    def visit_Constant(self, node):
        self.evaluated_value = node.value

    def visit_Name(self, node):
        if node.id in self.constants:
            self.evaluated_value = self.constants[node.id]
        else:
            raise NameError(f"Undefined constant: {node.id}")

    # Reject unsupported AST node types
    def visit_Call(self, node):
        raise TypeError(f"Unsupported AST node: function call ({node.func.id if hasattr(node.func, 'id') else node.func})")

    def visit_Attribute(self, node):
        raise TypeError(f"Unsupported AST node: attribute access ({node.attr})")

    def visit_Subscript(self, node):
        raise TypeError(f"Unsupported AST node: subscript ({node.slice})")

    def visit_IfExp(self, node):  # Ternary expression
        raise TypeError("Unsupported AST node: ternary expression")

    def generic_visit(self, node):
        raise TypeError(f"Unsupported AST node: {type(node).__name__}")

    def visit_BinOp(self, node):
        left_evaluator = ExpressionEvaluator(self.constants)
        left_value = left_evaluator.evaluate(node.left)
        left_value = self._require_value(left_value, "Left operand could not be evaluated")

        right_evaluator = ExpressionEvaluator(self.constants)
        right_value = right_evaluator.evaluate(node.right)
        right_value = self._require_value(right_value, "Right operand could not be evaluated")

        if isinstance(node.op, ast.Add):
            self.evaluated_value = left_value + right_value
        elif isinstance(node.op, ast.Sub):
            self.evaluated_value = left_value - right_value
        elif isinstance(node.op, ast.Mult):
            self.evaluated_value = left_value * right_value
        elif isinstance(node.op, ast.Div):
            self.evaluated_value = left_value / right_value
        elif isinstance(node.op, ast.Mod):
            self.evaluated_value = left_value % right_value
        elif isinstance(node.op, ast.LShift):
            self.evaluated_value = left_value << right_value
        elif isinstance(node.op, ast.RShift):
            self.evaluated_value = left_value >> right_value
        elif isinstance(node.op, ast.BitOr):
            self.evaluated_value = left_value | right_value
        elif isinstance(node.op, ast.BitAnd):
            self.evaluated_value = left_value & right_value
        elif isinstance(node.op, ast.BitXor):
            self.evaluated_value = left_value ^ right_value
        else:
            raise TypeError(f"Unsupported binary operator: {type(node.op).__name__}")

    def visit_UnaryOp(self, node):
        operand_evaluator = ExpressionEvaluator(self.constants)
        operand_value = operand_evaluator.evaluate(node.operand)
        operand_value = self._require_value(operand_value, "Operand could not be evaluated")

        if isinstance(node.op, ast.USub):
            self.evaluated_value = -operand_value
        elif isinstance(node.op, ast.UAdd):
            self.evaluated_value = +operand_value
        elif isinstance(node.op, ast.Invert): # Bitwise NOT (~)
            self.evaluated_value = ~operand_value
        else:
            raise TypeError(f"Unsupported unary operator: {type(node.op).__name__}")


# Modifier bit definitions from rtw_port/header_operations.py
# These Warband Module System definitions decode modifier bits in opcodes.
NEG = 0x80000000       # negation modifier (e.g., lt = neg | ge)
THIS_OR_NEXT = 0x40000000  # this_or_next modifier

# Combined modifier mask: both neg and this_or_next bits
_MODIFIER_MASK = NEG | THIS_OR_NEXT


def _extract_base_opcode(raw_opcode):
    """
    Extract the base opcode from a raw opcode that may have modifier bits set.

    Returns (base_opcode, has_neg, has_this_or_next).
    """
    flags = raw_opcode & _MODIFIER_MASK
    has_neg = bool(flags & NEG)
    has_this_or_next = bool(flags & THIS_OR_NEXT)
    base_opcode = raw_opcode & ~_MODIFIER_MASK
    return base_opcode, has_neg, has_this_or_next


# All integers in opcode position are preserved and recorded.
# 713 in opcode position IS counted; 713 in parameter position is naturally excluded
# because parameter tokens are skipped by the advancement logic.
# 0 in opcode position is also preserved (not filtered).

# Maximum plausible parameter count for a single operation.
# Values above this are likely due to desynchronization.
_MAX_EXPECTED_PARAM_COUNT = 100


def _strip_inline_comment(line):
    """
    Strip an inline comment (everything from '#' onward) from a line.

    Warband scripts.txt files occasionally contain inline comments or
    trailing annotations. These must be removed before tokenizing so
    that comment text is not mistaken for opcode/parameter tokens.
    """
    hash_pos = line.find('#')
    if hash_pos != -1:
        return line[:hash_pos]
    return line


def _make_result(file_success=False, structure_success=True, opcode_identification_status='ok',
                 semantic_compatibility_status='ok',
                 declared_script_count=0, discovered_script_count=0,
                 successful_script_count=0, failed_script_count=0,
                 declared_statement_total=0, successful_statement_total=0,
                 base_usage=None, raw_usage=None, modifier_usage=None,
                 errors=None, warnings=None, scripts=None,
                 sha256=None):
    """Build a structured result dictionary with stable defaults."""
    return {
        'file_success': file_success,
        'structure_success': structure_success,
        'opcode_identification_status': opcode_identification_status,
        'semantic_compatibility_status': semantic_compatibility_status,
        'declared_script_count': declared_script_count,
        'discovered_script_count': discovered_script_count,
        'successful_script_count': successful_script_count,
        'failed_script_count': failed_script_count,
        'declared_statement_total': declared_statement_total,
        'successful_statement_total': successful_statement_total,
        'base_usage': base_usage if base_usage is not None else {},
        'raw_usage': raw_usage if raw_usage is not None else {},
        'modifier_usage': modifier_usage if modifier_usage is not None else {'neg': 0, 'this_or_next': 0},
        'errors': errors if errors is not None else [],
        'warnings': warnings if warnings is not None else [],
        'scripts': scripts if scripts is not None else [],
        'sha256': sha256,
    }


def scan_rtw_scripts(scripts_filepath, known_opcodes=None, capture_statement_details=False):
    """
    Scan a scripts.txt file and return opcode usage statistics.
    
    Args:
        scripts_filepath: path to scripts.txt.
        known_opcodes: optional set of opcode values considered valid.
            None = no filtering (backward compatible, all opcodes counted).
            set() = no opcodes known (all flagged as unknown but still counted).
            {101, 102} = only these opcodes are valid.
    
    Returns:
        dict: structured result with file-level and script-level statistics
        None: on fatal error (file not found, empty, unreadable).
    """
    # known_opcodes=None means no filtering (backward compatible).
    # known_opcodes=set() means no opcodes are known (all flagged as unknown).
    # Do NOT convert None to set() here - the distinction matters.

    # File-level statistics
    file_structure_success = True  # track if any structural failure occurred at file level
    file_opcode_identification_status = 'ok'    # 'ok' or 'unknown_opcode'
    file_semantic_compatibility_status = 'ok'   # 'ok', 'changed', 'removed', or 'unknown'
    declared_script_count = 0
    discovered_script_count = 0
    successful_script_count = 0
    failed_script_count = 0
    declared_statement_total = 0
    successful_statement_total = 0
    base_usage = {}
    raw_usage = {}
    modifier_usage = {'neg': 0, 'this_or_next': 0}
    errors = []
    warnings = []
    script_results = []

    # SHA-256 of the file contents (hex digest)
    sha256_hex = None

    try:
        with open(scripts_filepath, 'rb') as fb:
            raw_bytes = fb.read()
        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
        
        # Reopen for text processing
        with open(scripts_filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: File not found at {scripts_filepath}")
        return None
    except Exception as e:
        print(f"Error reading file: {e}")
        return None

    if not lines:
        print("Error: scripts.txt is empty.")
        return None

    # Header: "scriptsfile version 1"
    if lines[0].strip() != "scriptsfile version 1":
        warnings.append(f"Unexpected scriptsfile version: {lines[0].strip()!r}")

    # Script count line
    try:
        declared_script_count = int(lines[1].strip())
    except (IndexError, ValueError) as e:
        print(f"Error: Could not read script count from line 2: {e}")
        return None

    line_idx = 2  # 0-based index
    while line_idx < len(lines):
        line = lines[line_idx].strip()
        if not line:
            line_idx += 1
            continue

        # Header line: "script_name -1" (second token is script flags)
        first_token = line.split(maxsplit=1)[0]
        is_header = not first_token.lstrip('-').replace('.', '', 1).isdigit()

        if not is_header:
            # A statement token appearing where a header was expected.
            warnings.append(
                f"Line {line_idx + 1}: expected script header, found statement token {first_token!r}"
            )
            line_idx += 1
            continue

        # Script header
        discovered_script_count += 1
        script_name = first_token
        script_start_line = line_idx + 1
        
        script_success = True
        script_structure_success = True # Track structural integrity of this specific script
        script_opcode_identification_status = 'ok'   # 'ok' or 'unknown_opcode'
        script_semantic_compatibility_status = 'ok'   # 'ok' or 'changed'/'removed'/'unknown'
        
        script_errors = []
        script_warnings = []
        script_base_usage = {}
        script_raw_usage = {}
        script_modifier_usage = {'neg': 0, 'this_or_next': 0}
        script_statements = [] # To store detailed statement info if capture_statement_details is True
        declared_statement_count = 0
        parsed_statement_count = 0
        line_idx += 1

        # Skip any blank lines between header and body (defensive)
        while line_idx < len(lines):
            body_line = lines[line_idx].strip()
            if body_line:
                break
            line_idx += 1
        else:
            script_errors.append(
                f"Script {script_name!r} at line {line_idx}: no body line found (EOF)"
            )
            script_success = False
            script_structure_success = False
            # Don't break file-level loop, just mark this script as failed
            # break # This was breaking the outer loop, now it just fails the script

        if not script_success: # If script already failed due to EOF, skip parsing body
            script_results.append({
                'script_id': script_name,
                'declared_statement_count': declared_statement_count,
                'parsed_statement_count': parsed_statement_count,
                'success': script_success,
                'structure_success': script_structure_success,
                'opcode_identification_status': script_opcode_identification_status,
                'semantic_compatibility_status': script_semantic_compatibility_status,
                'positioning': {
                    'start_line': script_start_line,
                    'end_line': line_idx
                },
                'errors': script_errors,
                'warnings': script_warnings,
                'base_usage': script_base_usage,
                'raw_usage': script_raw_usage,
                'modifier_usage': script_modifier_usage
            })
            failed_script_count += 1
            file_structure_success = False # A structural failure in any script makes file_structure_success False
            line_idx += 1 # Advance to next line to avoid infinite loop if body_line was empty
            continue


        tokens = _strip_inline_comment(body_line).split()
        t = 0
        n_tokens = len(tokens)
        statement_index = 0

        # First token of the body is the declared statement count
        if t < n_tokens:
            try:
                declared_statement_count = int(tokens[t])
                t += 1
            except ValueError:
                # Not a statement count, treat as opcode
                pass

        # Script body processing
        while t < n_tokens:
            statement_index += 1
            parsed_statement_count += 1

            # Parse opcode
            try:
                opcode = int(tokens[t])
            except ValueError:
                script_errors.append(
                    f"Script {script_name!r}, line {line_idx + 1}, statement {statement_index}: "
                    f"invalid opcode token {tokens[t]!r} (expected integer opcode)"
                )
                script_success = False
                script_structure_success = False
                break

            # Extract base opcode and modifier bits using bitwise masking
            base_opcode, has_neg, has_this_or_next = _extract_base_opcode(opcode)

            # Count usage for this script. All integers in opcode position are
            # preserved, including 0 and 713.
            if opcode & _MODIFIER_MASK:
                script_raw_usage[opcode] = script_raw_usage.get(opcode, 0) + 1
                script_base_usage[base_opcode] = script_base_usage.get(base_opcode, 0) + 1
                if has_neg:
                    script_modifier_usage['neg'] = script_modifier_usage.get('neg', 0) + 1
                if has_this_or_next:
                    script_modifier_usage['this_or_next'] = script_modifier_usage.get('this_or_next', 0) + 1
            else:
                script_base_usage[base_opcode] = script_base_usage.get(base_opcode, 0) + 1

            current_statement_details = {
                'statement_index': statement_index,
                'raw_opcode': opcode,
                'base_opcode': base_opcode,
                'modifier_neg': has_neg,
                'modifier_this_or_next': has_this_or_next,
                'param_count': 0, # Will be updated
                'parameters': []
            }

            # Advance past opcode token
            current_statement_details['param_count'] = 0  # Will be updated after param_count parsing
            current_statement_details['parameters'] = []
            if capture_statement_details:
                script_statements.append(current_statement_details)
            t += 1

            # Parse parameter count
            if t >= n_tokens:
                script_errors.append(
                    f"Script {script_name!r}, line {line_idx + 1}, statement {statement_index}: "
                    f"truncated statement after opcode {opcode} (missing parameter count)"
                )
                script_success = False
                script_structure_success = False
                break

            try:
                param_count = int(tokens[t])
            except ValueError:
                script_errors.append(
                    f"Script {script_name!r}, line {line_idx + 1}, statement {statement_index}: "
                    f"invalid parameter count token {tokens[t]!r} after opcode {opcode}"
                )
                script_success = False
                script_structure_success = False
                break

            # Validate parameter count
            if param_count < 0:
                script_errors.append(
                    f"Script {script_name!r}, line {line_idx + 1}, statement {statement_index}: "
                    f"illegal negative parameter count {param_count} for opcode {opcode}"
                )
                script_success = False
                script_structure_success = False
                break

            # Validate parameter count is plausible
            if param_count > _MAX_EXPECTED_PARAM_COUNT:
                script_errors.append(
                    f"Script {script_name!r}, line {line_idx + 1}, statement {statement_index}: "
                    f"implausible parameter count {param_count} for opcode {opcode} "
                    f"(max expected {_MAX_EXPECTED_PARAM_COUNT})"
                )
                script_success = False
                script_structure_success = False
                break

            # After advancing past the opcode, t points at the param_count token.
            # The statement occupies: opcode (t-1), param_count (t), and
            # param_count params (t+1 .. t+param_count). So the last param is at
            # index t + param_count, which must be < n_tokens.
            if t + 1 + max(0, param_count) > n_tokens:
                script_errors.append(
                    f"Script {script_name!r}, line {line_idx + 1}, statement {statement_index}: "
                    f"truncated block for opcode {opcode} (claims {param_count} params, "
                    f"only {n_tokens - t - 1} available)"
                )
                script_success = False
                script_structure_success = False
                break

            # Update statement details with parsed parameter count and values
            current_statement_details['param_count'] = param_count
            current_statement_details['parameters'] = tokens[t+1:t+1+param_count]

            # Check for unknown opcodes when a known-opcode table is supplied.
            # Unknown opcodes are flagged as errors but still counted.
            # known_opcodes=None means no filtering (backward compatible);
            # known_opcodes=set() means no opcodes are known (all flagged as unknown).
            if known_opcodes is not None and base_opcode not in known_opcodes:
                script_errors.append(
                    f"Script {script_name!r}, line {line_idx + 1}, statement {statement_index}: "
                    f"unknown opcode {base_opcode} (raw {opcode})"
                )
                script_opcode_identification_status = 'unknown_opcode'
                script_semantic_compatibility_status = 'unknown'
                script_success = False
            elif known_opcodes is None:
                # No filtering - backward compatible behavior
                pass

            # Advance past param_count + param values
            t += 1 + max(0, param_count)

        # Validate declared statement count matches actual parsed statements
        if declared_statement_count != statement_index:
            script_errors.append(
                f"Script {script_name!r}, line {line_idx + 1}: "
                f"declared statement count {declared_statement_count} does not match "
                f"actual parsed statements {statement_index}"
            )
            script_success = False
            script_structure_success = False

        # Record script result
        script_results.append({
            'script_id': script_name,
            'declared_statement_count': declared_statement_count,
            'parsed_statement_count': statement_index,
            'success': script_success,
            'structure_success': script_structure_success,
            'opcode_identification_status': script_opcode_identification_status,
            'semantic_compatibility_status': script_semantic_compatibility_status,
            'positioning': {
                'start_line': script_start_line,
                'end_line': line_idx
            },
            'errors': script_errors,
            'warnings': script_warnings,
            'base_usage': script_base_usage,
            'raw_usage': script_raw_usage,
            'modifier_usage': script_modifier_usage,
            'statements': script_statements # Add detailed statements if captured
        })
        
        # Aggregate file-level stats based on script_structure_success
        if script_structure_success:
            for op, cnt in script_base_usage.items():
                base_usage[op] = base_usage.get(op, 0) + cnt
            for op, cnt in script_raw_usage.items():
                raw_usage[op] = raw_usage.get(op, 0) + cnt
            modifier_usage['neg'] = modifier_usage.get('neg', 0) + script_modifier_usage['neg']
            modifier_usage['this_or_next'] = modifier_usage.get('this_or_next', 0) + script_modifier_usage['this_or_next']

        # Count scripts and aggregate stats based on structure_success.
        # A script with only an identification issue (unknown opcode) still has
        # structure_success=True, so it counts as successful and its stats
        # enter the success aggregates. Only structural failures break
        # parsing integrity and exclude stats.
        if script_structure_success:
            successful_script_count += 1
            declared_statement_total += declared_statement_count
            successful_statement_total += statement_index
        else:
            failed_script_count += 1
            file_structure_success = False
        # Track identification and compatibility status independently
        if script_opcode_identification_status == 'unknown_opcode':
            file_opcode_identification_status = 'unknown_opcode'
        if script_semantic_compatibility_status != 'ok':
            file_semantic_compatibility_status = script_semantic_compatibility_status
        
        line_idx += 1

    # Validate script count
    if discovered_script_count != declared_script_count:
        errors.append(
            f"Declared script count {declared_script_count} does not match "
            f"discovered script count {discovered_script_count}"
        )
        file_structure_success = False # Script count mismatch is a structural failure

    # Aggregate script-level errors into file-level errors
    for script in script_results:
        if script['errors']:
            errors.extend(script['errors'])
        if script['warnings']:
            warnings.extend(script['warnings'])

    # Determine final file_success
    final_file_success = file_structure_success and file_opcode_identification_status == 'ok' and not bool(errors)

    return _make_result(
        file_success=final_file_success,
        structure_success=file_structure_success,
        opcode_identification_status=file_opcode_identification_status,
        semantic_compatibility_status=file_semantic_compatibility_status,
        declared_script_count=declared_script_count,
        discovered_script_count=discovered_script_count,
        successful_script_count=successful_script_count,
        failed_script_count=failed_script_count,
        declared_statement_total=declared_statement_total,
        successful_statement_total=successful_statement_total,
        base_usage=base_usage,
        raw_usage=raw_usage,
        modifier_usage=modifier_usage,
        errors=errors,
        warnings=warnings,
        scripts=script_results,
        sha256=sha256_hex
    )

def _calculate_sha256(filepath):
    """Calculates the SHA256 hash of a file."""
    try:
        with open(filepath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error calculating SHA256 for {filepath}: {e}")
        return None

def _generate_json_report(data, output_path):
    """Generates a JSON report."""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"JSON report generated at {output_path}")
    except Exception as e:
        print(f"Error generating JSON report: {e}")

def _generate_csv_report(data, output_path):
    """Generates a CSV report for script-level data."""
    if not data or 'scripts' not in data or not data['scripts']:
        print("No script data to generate CSV report.")
        return

    try:
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'script_id', 'declared_statement_count', 'parsed_statement_count',
                'success', 'structure_success', 'opcode_identification_status',
                'semantic_compatibility_status',
                'start_line', 'end_line', 'errors', 'warnings',
                'base_usage', 'raw_usage', 'modifier_usage'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for script in data['scripts']:
                row = {
                    'script_id': script['script_id'],
                    'declared_statement_count': script['declared_statement_count'],
                    'parsed_statement_count': script['parsed_statement_count'],
                    'success': script['success'],
                    'structure_success': script['structure_success'],
                    'opcode_identification_status': script['opcode_identification_status'],
                    'semantic_compatibility_status': script['semantic_compatibility_status'],
                    'start_line': script['positioning']['start_line'],
                    'end_line': script['positioning']['end_line'],
                    'errors': '; '.join(script['errors']),
                    'warnings': '; '.join(script['warnings']),
                    'base_usage': json.dumps(script['base_usage']),
                    'raw_usage': json.dumps(script['raw_usage']),
                    'modifier_usage': json.dumps(script['modifier_usage'])
                }
                writer.writerow(row)
        print(f"CSV report generated at {output_path}")
    except Exception as e:
        print(f"Error generating CSV report: {e}")

# Example usage (for testing purposes)
if __name__ == '__main__':
    # This part would typically be called by another script or a test runner
    # For now, it's a placeholder.
    print("This script is intended to be imported and used, not run directly.")
    print("To run tests, execute tools/test_scanner.py")
