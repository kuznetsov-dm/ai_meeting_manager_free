import sys
import os

print("Checking ML Environment...")
try:
    import sentence_transformers
    print(f"sentence_transformers: INSTALLED (v{sentence_transformers.__version__})")
except ImportError:
    print("sentence_transformers: MISSING")

try:
    import numpy
    print(f"numpy: INSTALLED (v{numpy.__version__})")
except ImportError:
    print("numpy: MISSING")

# Check utils path
sys.path.append(os.getcwd())
try:
    from plugins.text_processing import utils
    print(f"Models Dir: {utils.get_models_dir()}")
except ImportError as e:
    print(f"utils load failed: {e}")
except Exception as e:
    print(f"utils error: {e}")
