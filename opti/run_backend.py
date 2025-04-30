"""
Compatibility wrapper for the original run_backend.py script

This module maintains backward compatibility with the original run_backend.py
by redirecting to the new modular implementation.
"""
import subprocess
import sys
import signal
from .runner import run_processes

def main():
    """
    Backward-compatible entry point that matches the original run_backend.py
    """
    # Just delegate to our new implementation
    run_processes()

if __name__ == "__main__":
    main() 