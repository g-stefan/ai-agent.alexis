#!/usr/bin/env python3
# Print the current local date/time.
# Optional first argument: a strftime format string (default: "%Y-%m-%d %H:%M:%S").
import sys
from datetime import datetime

fmt = sys.argv[1] if len(sys.argv) > 1 else "%Y-%m-%d %H:%M:%S"
try:
    print(datetime.now().strftime(fmt))
except Exception as e:
    print(f"Error: invalid format string: {e}")
    sys.exit(1)
