"""Runner minimo (niente pytest nell'ambiente): esegue tutti i test_* del file."""
import importlib.util, sys, traceback, pathlib

def run(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    n = ok = 0
    for name in dir(mod):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            getattr(mod, name)()
            ok += 1
            print(f"  ok   {path.name}::{name}")
        except Exception:
            print(f"  FAIL {path.name}::{name}")
            traceback.print_exc()
    return n, ok

tot = passed = 0
for p in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
    n, o = run(p)
    tot += n; passed += o
print(f"\n{passed}/{tot} test passati")
sys.exit(0 if passed == tot else 1)
