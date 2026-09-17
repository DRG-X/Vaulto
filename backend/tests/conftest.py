import os
import sys

# Backend root on the path so `import money` etc. resolve the same way the
# app resolves them at runtime.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
