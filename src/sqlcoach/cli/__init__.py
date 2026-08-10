"""Command-line interface layer.

Responsible only for argument parsing, input validation, invoking
application services, and formatting output. Business logic must never
live in this layer (NFR-X.2). The Typer application and command
registration are introduced in US1.5.
"""
