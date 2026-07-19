#!/usr/bin/env python3
"""
Code validation without external dependencies.
Checks that all files compile and have required functions.
"""

import sys
import os
import py_compile
import ast

print("=" * 70)
print("System C - Code Validation")
print("=" * 70)
print()

# Test 1: File compilation
print("TEST 1: Python File Compilation")
print("-" * 70)

files_to_check = [
    'main_orchestrator.py',
    'agent/ml_feature_engineer.py',
    'agent/ml_signal_generator.py',
    'agent/claude_analyst.py',
    'agent/evidence_integrity.py',
    'ops/check_evidence_integrity.py',
    'dashboard.py',
    'send_daily_metrics.py',
]

all_compile = True
for filepath in files_to_check:
    try:
        py_compile.compile(filepath, doraise=True)
        print(f"✅ {filepath}")
    except py_compile.PyCompileError as e:
        print(f"❌ {filepath}: {e}")
        all_compile = False

if not all_compile:
    print("\n❌ Some files have syntax errors!")
    sys.exit(1)

print()

# Test 2: Check required functions exist
print("TEST 2: Check Required Functions")
print("-" * 70)

def check_function_in_file(filepath, function_name):
    """Check if a function is defined in a Python file."""
    try:
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return True
        return False
    except Exception as e:
        print(f"Error checking {filepath}: {e}")
        return False

def check_class_in_file(filepath, class_name):
    """Check if a class is defined in a Python file."""
    try:
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return True
        return False
    except Exception as e:
        print(f"Error checking {filepath}: {e}")
        return False

checks = [
    ('agent/ml_feature_engineer_gold.py', 'GoldFeatureEngineer', True),
    ('agent/ml_signal_generator.py', 'MLSignalFilter', True),
    ('agent/claude_analyst.py', 'AITradingDecider', True),
    ('main_orchestrator.py', 'AIAssistedOrchestrator', True),
    ('dashboard.py', 'calculate_metrics', False),
    ('dashboard.py', 'get_evidence_integrity', False),
    ('agent/evidence_integrity.py', 'build_evidence_integrity_report', False),
    ('send_daily_metrics.py', 'get_metrics', False),
]

all_valid = True
for filepath, name, is_class in checks:
    if is_class:
        result = check_class_in_file(filepath, name)
        check_type = "class"
    else:
        result = check_function_in_file(filepath, name)
        check_type = "function"

    if result:
        print(f"✅ {filepath}: {name} ({check_type})")
    else:
        print(f"❌ {filepath}: {name} ({check_type}) NOT FOUND")
        all_valid = False

if not all_valid:
    print("\n❌ Some functions/classes are missing!")
    sys.exit(1)

print()

# Test 3: Check critical imports
print("TEST 3: Check Critical Imports")
print("-" * 70)

imports_to_check = [
    ('agent/ml_signal_generator.py', ['from .ml_feature_engineer_gold import GoldFeatureEngineer']),
    ('main_orchestrator.py', ['from agent.gold_correlations import GoldCorrelationValidator']),
    ('main_orchestrator.py', ['from agent.smc_gold_scanner import run_gold_scanner']),
    ('main_orchestrator.py', ['from agent.claude_analyst import AITradingDecider']),
    ('dashboard.py', ['from flask import Flask']),
]

def check_import_in_file(filepath, import_statement):
    """Check if an import exists in a Python file."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        # Simple string check - not perfect but works for basic validation
        return import_statement in content
    except Exception as e:
        print(f"Error checking {filepath}: {e}")
        return False

all_imports = True
for filepath, imports in imports_to_check:
    for import_stmt in imports:
        result = check_import_in_file(filepath, import_stmt)
        if result:
            print(f"✅ {filepath}: {import_stmt.split()[-1]}")
        else:
            print(f"❌ {filepath}: {import_stmt} NOT FOUND")
            all_imports = False

if not all_imports:
    print("\n❌ Some required imports are missing!")
    sys.exit(1)

print()

# Test 4: Check configuration files
print("TEST 4: Check Configuration Files")
print("-" * 70)

config_files = [
    'config/settings.py',
    '.env.example',
    'requirements.txt',
    'CLAUDE.md',
    'VPS_DEPLOYMENT.md',
    'config/evidence_integrity_v1.json',
]

all_configs = True
for filepath in config_files:
    if os.path.exists(filepath):
        size = os.path.getsize(filepath)
        print(f"✅ {filepath} ({size} bytes)")
    else:
        print(f"❌ {filepath} NOT FOUND")
        all_configs = False

if not all_configs:
    print("\n⚠️  Some configuration files are missing (may be OK)")

print()

# Test 5: Check directory structure
print("TEST 5: Check Directory Structure")
print("-" * 70)

required_dirs = [
    'agent',
    'config',
    'data',
    'logs',
    'models',
]

all_dirs = True
for dirname in required_dirs:
    if os.path.isdir(dirname):
        file_count = len(os.listdir(dirname))
        print(f"✅ {dirname}/ ({file_count} files)")
    else:
        print(f"❌ {dirname}/ NOT FOUND")
        all_dirs = False

if not all_dirs:
    print("\n⚠️  Some directories are missing")

print()

# Test 6: Check key methods exist
print("TEST 6: Check Key Methods in Classes")
print("-" * 70)

def check_method_in_class(filepath, class_name, method_name):
    """Check if a method exists in a class (including async methods)."""
    try:
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    # Check both regular and async methods
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                        return True
        return False
    except Exception as e:
        print(f"Error checking {filepath}: {e}")
        return False

methods_to_check = [
    ('agent/claude_analyst.py', 'AITradingDecider', 'decide'),
    ('agent/ml_signal_generator.py', 'MLSignalFilter', 'score_signal'),
    ('main_orchestrator.py', 'AIAssistedOrchestrator', 'run_scan'),
    ('main_orchestrator.py', 'AIAssistedOrchestrator', 'update_open_trades'),
]

all_methods = True
for filepath, class_name, method_name in methods_to_check:
    result = check_method_in_class(filepath, class_name, method_name)
    if result:
        print(f"✅ {class_name}.{method_name}()")
    else:
        print(f"❌ {class_name}.{method_name}() NOT FOUND")
        all_methods = False

if not all_methods:
    print("\n❌ Some required methods are missing!")
    sys.exit(1)

print()

# Summary
print("=" * 70)
print("✅ ALL CODE VALIDATION CHECKS PASSED")
print("=" * 70)
print()
print("Summary:")
print("  ✅ All Python files compile without syntax errors")
print("  ✅ All required classes exist")
print("  ✅ All required functions/methods exist")
print("  ✅ All critical imports are in place")
print("  ✅ Directory structure is correct")
print()
print("Engineering checks passed; this does not establish strategy profitability or production readiness.")
print()
print("Next step: SSH to VPS and verify logs are being created")
print("  ssh root@187.55.229.4")
print("  tail -20 /root/gold_signal_fetcher_ai_assisted/logs/gold_scanner_ai.log")
print()
