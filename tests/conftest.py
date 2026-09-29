import os
import sys
import tempfile

os.environ.setdefault("CARDWIZARD_DATA", tempfile.mkdtemp())
os.environ["CARDWIZARD_EMBEDDER"] = "hash"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
