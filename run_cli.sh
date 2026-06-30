#!/bin/bash
# Menjalankan Interactive CLI dengan environment project 'src' yang benar
uv run --project ../src python cli.py "$@"
