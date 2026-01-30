#!/usr/bin/env python3
"""Diagnostic script - no TUI, just prints info."""
import sys
import os

print("=== DIAGNOSTIC INFO ===")
print(f"Python: {sys.version}")
print(f"TERM: {os.environ.get('TERM', 'not set')}")
print(f"WSL: {os.environ.get('WSL_DISTRO_NAME', 'not WSL')}")

try:
    import textual
    print(f"Textual: {textual.__version__}")
except Exception as e:
    print(f"Textual import error: {e}")

try:
    import textual_autocomplete
    print(f"textual-autocomplete: {textual_autocomplete.__version__}")
except Exception as e:
    print(f"textual-autocomplete: {e}")

print("\n=== SIMPLE INPUT TEST ===")
print("Type something and press Enter:")
try:
    user_input = input("> ")
    print(f"You typed: {user_input}")
    print("Basic input works!")
except Exception as e:
    print(f"Input error: {e}")

print("\nDone.")
